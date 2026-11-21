import re

from execution.base import (
    END,
    Operator,
    column_index,
    validate_schema,
)
from execution.conditions import resolve_column_name
from execution.sort import Sort
from execution.temp_run import TempRun


_COLUMN = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?"

_EQUALITY_RE = re.compile(
    rf"^\s*({_COLUMN})\s*=\s*({_COLUMN})\s*$"
)


class SortMergeJoin(Operator):
    """
    Equality sort-merge join.

    Both inputs are sorted on their join keys.

    When equal keys are found, the entire matching run
    from the RIGHT side is spilled to a TempRun. That
    temporary run is replayed for every matching LEFT
    tuple.

    This preserves the full duplicate cross-product
    without assuming the equal-key run fits in memory.
    """

    def __init__(
        self,
        left,
        right,
        condition,
        frames,
        temp_dir=None,
    ):
        super().__init__()

        self.left = left
        self.right = right

        self.condition = condition
        self.frames = frames
        self.temp_dir = temp_dir

        self._left_schema = []
        self._right_schema = []

        self._left_key_name = None
        self._right_key_name = None

        self._left_key_index = None
        self._right_key_index = None
        self._key_type = None

        self._left_sort = None
        self._right_sort = None

        self._left_row = END
        self._right_row = END

        # Duplicate-run state.
        self._match_run = None
        self._match_key = None
        self._match_left_row = None
        self._match_iterator = None
        self._in_match = False

        self._exhausted = False

        self._last_left = {
            "comparisons": 0,
            "page_reads": 0,
            "page_writes": 0,
        }

        self._last_right = {
            "comparisons": 0,
            "page_reads": 0,
            "page_writes": 0,
        }

        self.max_frames_held = 0

    # ---------------------------------------------------------
    # Counter helpers
    # ---------------------------------------------------------

    def _sync_one_sort(
        self,
        sort_operator,
        previous,
    ):
        if sort_operator is None:
            return

        counters = sort_operator.counters()

        self._count_comparison(
            counters["comparisons"]
            - previous["comparisons"]
        )

        self._count_read(
            counters["page_reads"]
            - previous["page_reads"]
        )

        self._count_write(
            counters["page_writes"]
            - previous["page_writes"]
        )

        previous["comparisons"] = (
            counters["comparisons"]
        )

        previous["page_reads"] = (
            counters["page_reads"]
        )

        previous["page_writes"] = (
            counters["page_writes"]
        )

    def _sync_sorts(self):
        self._sync_one_sort(
            self._left_sort,
            self._last_left,
        )

        self._sync_one_sort(
            self._right_sort,
            self._last_right,
        )

        held = 3

        if self._left_sort is not None:
            held = max(
                held,
                self._left_sort.max_frames_held,
            )

        if self._right_sort is not None:
            held = max(
                held,
                self._right_sort.max_frames_held,
            )

        self.max_frames_held = max(
            self.max_frames_held,
            min(
                self.frames,
                held,
            ),
        )

    def _temp_read(self):
        self._count_read()

    def _temp_write(self):
        self._count_write()

    # ---------------------------------------------------------
    # Schema and condition
    # ---------------------------------------------------------

    def _inspect_schemas(self):
        self.left.open()

        try:
            self._left_schema = [
                list(column)
                for column
                in self.left.schema
            ]

            validate_schema(
                self._left_schema
            )

        finally:
            self.left.close()

        self.right.open()

        try:
            self._right_schema = [
                list(column)
                for column
                in self.right.schema
            ]

            validate_schema(
                self._right_schema
            )

        finally:
            self.right.close()

        self.schema = (
            self._left_schema
            + self._right_schema
        )

        validate_schema(
            self.schema
        )

    def _prepare_join_condition(self):
        if not isinstance(
            self.condition,
            str,
        ):
            raise TypeError(
                "sort_merge_join condition "
                "must be a string."
            )

        match = _EQUALITY_RE.match(
            self.condition
        )

        if match is None:
            raise ValueError(
                "sort_merge_join requires "
                "one equality condition between "
                "two columns."
            )

        first_requested = match.group(1)
        second_requested = match.group(2)

        first = resolve_column_name(
            self.schema,
            first_requested,
        )

        second = resolve_column_name(
            self.schema,
            second_requested,
        )

        left_names = {
            column[0]
            for column
            in self._left_schema
        }

        right_names = {
            column[0]
            for column
            in self._right_schema
        }

        first_on_left = first in left_names
        first_on_right = first in right_names

        second_on_left = second in left_names
        second_on_right = second in right_names

        if (
            first_on_left
            and second_on_right
        ):
            left_name = first
            right_name = second

        elif (
            first_on_right
            and second_on_left
        ):
            left_name = second
            right_name = first

        else:
            raise ValueError(
                "sort_merge_join equality "
                "must compare one left column "
                "with one right column."
            )

        left_index = column_index(
            self._left_schema,
            left_name,
        )

        right_index = column_index(
            self._right_schema,
            right_name,
        )

        left_type = (
            self._left_schema[
                left_index
            ][1]
        )

        right_type = (
            self._right_schema[
                right_index
            ][1]
        )

        if left_type != right_type:
            raise TypeError(
                "sort_merge_join key types "
                f"must match: "
                f"{left_type} vs "
                f"{right_type}"
            )

        self._left_key_name = left_name
        self._right_key_name = right_name

        self._left_key_index = left_index
        self._right_key_index = right_index

        self._key_type = left_type

    # ---------------------------------------------------------
    # Key comparisons
    # ---------------------------------------------------------

    def _normalize_value(self, value):
        if self._key_type == "VARCHAR":
            return value.encode(
                "utf-8"
            )

        return value

    def _compare_values(
        self,
        left_value,
        right_value,
    ):
        self._count_comparison()

        left_value = self._normalize_value(
            left_value
        )

        right_value = self._normalize_value(
            right_value
        )

        if left_value < right_value:
            return -1

        if left_value > right_value:
            return 1

        return 0

    def _left_key(self, row):
        return row[
            self._left_key_index
        ]

    def _right_key(self, row):
        return row[
            self._right_key_index
        ]

    def _compare_current_rows(self):
        return self._compare_values(
            self._left_key(
                self._left_row
            ),
            self._right_key(
                self._right_row
            ),
        )

    # ---------------------------------------------------------
    # Sorted input movement
    # ---------------------------------------------------------

    def _advance_left(self):
        self._left_row = (
            self._left_sort.next()
        )

        self._sync_sorts()

    def _advance_right(self):
        self._right_row = (
            self._right_sort.next()
        )

        self._sync_sorts()

    # ---------------------------------------------------------
    # Duplicate-run handling
    # ---------------------------------------------------------

    def _make_match_run(self):
        return TempRun(
            self._right_schema,
            temp_dir=self.temp_dir,
            read_callback=self._temp_read,
            write_callback=self._temp_write,
        )

    def _cleanup_match_run(self):
        if self._match_run is not None:
            self._match_run.delete()

        self._match_run = None
        self._match_key = None
        self._match_left_row = None
        self._match_iterator = None
        self._in_match = False

    def _start_matching_group(self):
        """
        Current left and right rows have equal keys.

        Spill the whole matching RIGHT run so it can be
        replayed once for every matching LEFT row.
        """

        self._match_key = (
            self._left_key(
                self._left_row
            )
        )

        self._match_run = (
            self._make_match_run()
        )

        try:
            # Current right row is already known to match.
            self._match_run.append(
                self._right_row
            )

            while True:
                self._advance_right()

                if self._right_row is END:
                    break

                comparison = (
                    self._compare_values(
                        self._right_key(
                            self._right_row
                        ),
                        self._match_key,
                    )
                )

                if comparison != 0:
                    break

                self._match_run.append(
                    self._right_row
                )

            self._match_run.finish()

        except Exception:
            self._cleanup_match_run()
            raise

        self._match_left_row = (
            self._left_row
        )

        self._match_iterator = iter(
            self._match_run.rows()
        )

        self._in_match = True

        self.max_frames_held = max(
            self.max_frames_held,
            min(
                self.frames,
                3,
            ),
        )

    def _next_matching_output(self):
        """
        Return the next tuple from the duplicate
        cross-product.

        Returns None only when this equal-key group has
        completely finished.
        """

        while self._in_match:

            try:
                right_row = next(
                    self._match_iterator
                )

                result = tuple(
                    self._match_left_row
                ) + tuple(
                    right_row
                )

                self._count_output()

                return result

            except StopIteration:
                pass

            # Finished replaying the right run for this
            # left tuple. Move to the next left tuple.
            self._advance_left()

            if self._left_row is END:
                self._cleanup_match_run()
                return None

            comparison = (
                self._compare_values(
                    self._left_key(
                        self._left_row
                    ),
                    self._match_key,
                )
            )

            if comparison != 0:
                # First row after the matching left run.
                # Keep it for the normal merge loop.
                self._cleanup_match_run()
                return None

            # Another left duplicate: replay the entire
            # right matching run from disk.
            self._match_left_row = (
                self._left_row
            )

            self._match_iterator = iter(
                self._match_run.rows()
            )

        return None

    # ---------------------------------------------------------
    # Operator interface
    # ---------------------------------------------------------

    def open(self):
        if self.is_open:
            raise RuntimeError(
                "SortMergeJoin is already open."
            )

        if self.frames < 4:
            raise ValueError(
                "sort_merge_join requires "
                "at least 4 frames."
            )

        self._reset_counters()

        self._last_left = {
            "comparisons": 0,
            "page_reads": 0,
            "page_writes": 0,
        }

        self._last_right = {
            "comparisons": 0,
            "page_reads": 0,
            "page_writes": 0,
        }

        self._left_row = END
        self._right_row = END

        self._cleanup_match_run()

        self._exhausted = False
        self.max_frames_held = 0

        self._inspect_schemas()
        self._prepare_join_condition()

        self._left_sort = Sort(
            self.left,
            [
                [
                    self._left_key_name,
                    "asc",
                ]
            ],
            frames=self.frames,
            temp_dir=self.temp_dir,
        )

        self._right_sort = Sort(
            self.right,
            [
                [
                    self._right_key_name,
                    "asc",
                ]
            ],
            frames=self.frames,
            temp_dir=self.temp_dir,
        )

        try:
            self._left_sort.open()
            self._sync_sorts()

            self._right_sort.open()
            self._sync_sorts()

            self._advance_left()
            self._advance_right()

        except Exception:
            if self._left_sort is not None:
                self._left_sort.close()

            if self._right_sort is not None:
                self._right_sort.close()

            self._cleanup_match_run()

            raise

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "SortMergeJoin.next() "
                "called before open()."
            )

        if self._exhausted:
            return END

        while True:

            if self._in_match:
                result = (
                    self._next_matching_output()
                )

                if result is not None:
                    return result

            if (
                self._left_row is END
                or
                self._right_row is END
            ):
                self._exhausted = True
                return END

            comparison = (
                self._compare_current_rows()
            )

            if comparison < 0:
                self._advance_left()
                continue

            if comparison > 0:
                self._advance_right()
                continue

            # Equal join keys.
            self._start_matching_group()

    def close(self):
        if not self.is_open:
            return

        self._cleanup_match_run()

        if self._left_sort is not None:
            self._left_sort.close()

        if self._right_sort is not None:
            self._right_sort.close()

        self._sync_sorts()

        self._left_sort = None
        self._right_sort = None

        self.is_open = False