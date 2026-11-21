import hashlib
import re

from execution.base import (
    END,
    Operator,
    column_index,
    validate_schema,
)
from execution.conditions import resolve_column_name
from execution.nested_loop_join import NestedLoopJoin
from execution.temp_run import TempRun
from storage.record import encode_record


PAGE_BYTES = 4088
SLOT_BYTES = 4

_COLUMN = (
    r"[A-Za-z_][A-Za-z0-9_]*"
    r"(?:\.[A-Za-z_][A-Za-z0-9_]*)?"
)

_EQUALITY_RE = re.compile(
    rf"^\s*({_COLUMN})\s*=\s*({_COLUMN})\s*$"
)


class _TempRunSource(Operator):
    """
    Re-openable operator wrapper around a TempRun.

    TempRun itself owns the physical reads through the
    HashJoin callbacks, so this wrapper has no I/O of
    its own.
    """

    def __init__(self, run, schema):
        super().__init__()

        self.run = run

        self.schema = [
            list(column)
            for column in schema
        ]

        self._iterator = None

    def open(self):
        self._reset_counters()

        self._iterator = iter(
            self.run.rows()
        )

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "_TempRunSource.next() "
                "called before open()."
            )

        try:
            row = next(
                self._iterator
            )

        except StopIteration:
            return END

        self._count_output()

        return row

    def close(self):
        self._iterator = None
        self.is_open = False


class HashJoin(Operator):
    """
    Grace hash join.

    Phase 1:
        partition both relations into P = B - 1
        temporary partitions using h1.

    Phase 2:
        for each pair:
            build an in-memory hash table on LEFT using h2
            stream RIGHT and probe.

    Overflow:
        if a left partition cannot safely fit in the
        B - 1 build frames, use block nested-loop join
        for that partition pair.

    Left is always the build side.
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

        self._partition_pairs = []

        self._current_left_run = None
        self._current_right_run = None

        self._build_table = None
        self._right_iterator = None

        self._candidate_rows = []
        self._candidate_index = 0
        self._current_right_row = None

        self._fallback = None
        self._fallback_last_comparisons = 0

        self._exhausted = False

        # Useful later for the required report.
        self.partition_count = 0
        self.partition_sizes = []

        self.overflow_fallbacks = 0
        self.max_frames_held = 0

    # =========================================================
    # Temporary file counters
    # =========================================================

    def _temp_read(self):
        self._count_read()

    def _temp_write(self):
        self._count_write()

    def _make_run(self, schema):
        return TempRun(
            schema,
            temp_dir=self.temp_dir,
            read_callback=self._temp_read,
            write_callback=self._temp_write,
        )

    # =========================================================
    # Schema / condition validation
    # =========================================================

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

    def _prepare_condition(self):
        if not isinstance(
            self.condition,
            str,
        ):
            raise TypeError(
                "hash_join condition "
                "must be a string."
            )

        match = _EQUALITY_RE.match(
            self.condition
        )

        if match is None:
            raise ValueError(
                "hash_join requires one "
                "equality condition between "
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

        first_left = first in left_names
        first_right = first in right_names

        second_left = second in left_names
        second_right = second in right_names

        if (
            first_left
            and second_right
        ):
            left_name = first
            right_name = second

        elif (
            first_right
            and second_left
        ):
            left_name = second
            right_name = first

        else:
            raise ValueError(
                "hash_join equality must "
                "compare one left column "
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
                "hash_join key types "
                f"must match: "
                f"{left_type} vs "
                f"{right_type}"
            )

        self._left_key_name = left_name
        self._right_key_name = right_name

        self._left_key_index = (
            left_index
        )

        self._right_key_index = (
            right_index
        )

        self._key_type = left_type

    # =========================================================
    # Hash functions
    # =========================================================

    def _key_bytes(self, value):
        if self._key_type == "INT":
            return (
                b"I|"
                + str(value).encode(
                    "ascii"
                )
            )

        if self._key_type == "VARCHAR":
            return (
                b"V|"
                + value.encode(
                    "utf-8"
                )
            )

        return repr(
            value
        ).encode(
            "utf-8"
        )

    def _hash_value(
        self,
        value,
        purpose,
    ):
        raw = (
            purpose.encode("ascii")
            + b"|"
            + self._key_bytes(value)
        )

        digest = hashlib.blake2b(
            raw,
            digest_size=8,
        ).digest()

        return int.from_bytes(
            digest,
            byteorder="little",
            signed=False,
        )

    def _h1(self, value):
        return self._hash_value(
            value,
            "h1",
        )

    def _h2(self, value):
        return self._hash_value(
            value,
            "h2",
        )

    # =========================================================
    # Join-key helpers
    # =========================================================

    def _left_key(self, row):
        return row[
            self._left_key_index
        ]

    def _right_key(self, row):
        return row[
            self._right_key_index
        ]

    def _keys_equal(
        self,
        left_key,
        right_key,
    ):
        self._count_comparison()

        if self._key_type == "VARCHAR":
            return (
                left_key.encode(
                    "utf-8"
                )
                ==
                right_key.encode(
                    "utf-8"
                )
            )

        return left_key == right_key

    # =========================================================
    # Initial Grace partition phase
    # =========================================================

    def _partition_child(
        self,
        child,
        schema,
        key_index,
    ):
        partition_total = (
            self.frames - 1
        )

        partitions = [
            self._make_run(
                schema
            )
            for _ in range(
                partition_total
            )
        ]

        # B-1 output buffers + 1 input frame.
        self.max_frames_held = max(
            self.max_frames_held,
            self.frames,
        )

        child.open()

        try:
            while True:
                row = child.next()

                if row is END:
                    break

                key = row[
                    key_index
                ]

                partition_no = (
                    self._h1(key)
                    % partition_total
                )

                partitions[
                    partition_no
                ].append(row)

            for run in partitions:
                run.finish()

        except Exception:
            for run in partitions:
                run.delete()

            raise

        finally:
            child.close()

        return partitions

    def _partition_inputs(self):
        left_partitions = (
            self._partition_child(
                self.left,
                self._left_schema,
                self._left_key_index,
            )
        )

        try:
            right_partitions = (
                self._partition_child(
                    self.right,
                    self._right_schema,
                    self._right_key_index,
                )
            )

        except Exception:
            for run in left_partitions:
                run.delete()

            raise

        self.partition_count = len(
            left_partitions
        )

        self.partition_sizes = []

        self._partition_pairs = []

        for index, (
            left_run,
            right_run,
        ) in enumerate(
            zip(
                left_partitions,
                right_partitions,
            )
        ):
            self.partition_sizes.append(
                {
                    "partition": index,
                    "left_tuples":
                        left_run.tuple_count,
                    "right_tuples":
                        right_run.tuple_count,
                    "left_pages":
                        left_run.disk.num_pages(),
                    "right_pages":
                        right_run.disk.num_pages(),
                }
            )

            self._partition_pairs.append(
                (
                    left_run,
                    right_run,
                )
            )

    # =========================================================
    # Build-side hash table
    # =========================================================

    def _left_row_memory_cost(
        self,
        row,
    ):
        """
        Conceptual charge for one stored build tuple.

        Encoded tuple + slot + small hash-table charge.
        """

        return (
            len(
                encode_record(
                    self._left_schema,
                    row,
                )
            )
            + SLOT_BYTES
            + 64
        )

    def _build_left_partition(
        self,
        run,
    ):
        # Physical early overflow check.
        if (
            run.disk.num_pages()
            > self.frames - 1
        ):
            return None

        memory_budget = (
            self.frames - 1
        ) * PAGE_BYTES

        memory_used = 0
        table = {}

        for row in run.rows():
            required = (
                self._left_row_memory_cost(
                    row
                )
            )

            if (
                memory_used + required
                > memory_budget
            ):
                return None

            key = self._left_key(
                row
            )

            bucket = self._h2(
                key
            )

            table.setdefault(
                bucket,
                [],
            ).append(
                (
                    key,
                    row,
                )
            )

            memory_used += required

        # B-1 build frames + one probe frame.
        self.max_frames_held = max(
            self.max_frames_held,
            self.frames,
        )

        return table

    # =========================================================
    # Overflow fallback
    # =========================================================

    def _start_fallback(self):
        left_source = _TempRunSource(
            self._current_left_run,
            self._left_schema,
        )

        right_source = _TempRunSource(
            self._current_right_run,
            self._right_schema,
        )

        self._fallback = NestedLoopJoin(
            left_source,
            right_source,
            self.condition,
            frames=self.frames,
        )

        self._fallback_last_comparisons = 0

        self._fallback.open()

        self.overflow_fallbacks += 1

        self.max_frames_held = max(
            self.max_frames_held,
            self._fallback.max_frames_held,
        )

    def _sync_fallback(self):
        if self._fallback is None:
            return

        counters = (
            self._fallback.counters()
        )

        comparisons = counters[
            "comparisons"
        ]

        self._count_comparison(
            comparisons
            - self._fallback_last_comparisons
        )

        self._fallback_last_comparisons = (
            comparisons
        )

        self.max_frames_held = max(
            self.max_frames_held,
            self._fallback.max_frames_held,
        )

    # =========================================================
    # Partition-pair state
    # =========================================================

    def _clear_probe_state(self):
        self._build_table = None
        self._right_iterator = None

        self._candidate_rows = []
        self._candidate_index = 0

        self._current_right_row = None

    def _delete_current_pair(self):
        if self._current_left_run is not None:
            self._current_left_run.delete()

        if self._current_right_run is not None:
            self._current_right_run.delete()

        self._current_left_run = None
        self._current_right_run = None

        self._clear_probe_state()

    def _finish_fallback(self):
        if self._fallback is not None:
            self._fallback.close()
            self._sync_fallback()

        self._fallback = None
        self._fallback_last_comparisons = 0

        self._delete_current_pair()

    def _start_next_pair(self):
        while self._partition_pairs:
            (
                self._current_left_run,
                self._current_right_run,
            ) = self._partition_pairs.pop(
                0
            )

            # No match is possible if either side is empty.
            if (
                self._current_left_run.tuple_count
                == 0
                or
                self._current_right_run.tuple_count
                == 0
            ):
                self._delete_current_pair()
                continue

            table = (
                self._build_left_partition(
                    self._current_left_run
                )
            )

            if table is None:
                # Professor-approved overflow strategy:
                # BNL only this partition pair.
                self._start_fallback()
                return True

            self._build_table = table

            self._right_iterator = iter(
                self._current_right_run.rows()
            )

            self._candidate_rows = []
            self._candidate_index = 0

            return True

        return False

    # =========================================================
    # Normal hash-probe output
    # =========================================================

    def _next_hash_output(self):
        while True:

            while (
                self._candidate_index
                < len(
                    self._candidate_rows
                )
            ):
                (
                    left_key,
                    left_row,
                ) = self._candidate_rows[
                    self._candidate_index
                ]

                self._candidate_index += 1

                if self._keys_equal(
                    left_key,
                    self._right_key(
                        self._current_right_row
                    ),
                ):
                    result = tuple(
                        left_row
                    ) + tuple(
                        self._current_right_row
                    )

                    self._count_output()

                    return result

            try:
                right_row = next(
                    self._right_iterator
                )

            except StopIteration:
                self._delete_current_pair()
                return None

            self._current_right_row = (
                right_row
            )

            bucket = self._h2(
                self._right_key(
                    right_row
                )
            )

            self._candidate_rows = (
                self._build_table.get(
                    bucket,
                    [],
                )
            )

            self._candidate_index = 0

    # =========================================================
    # Operator API
    # =========================================================

    def open(self):
        if self.is_open:
            raise RuntimeError(
                "HashJoin is already open."
            )

        if self.frames < 4:
            raise ValueError(
                "hash_join requires "
                "at least 4 frames."
            )

        self._reset_counters()

        self._partition_pairs = []

        self._current_left_run = None
        self._current_right_run = None

        self._clear_probe_state()

        self._fallback = None
        self._fallback_last_comparisons = 0

        self._exhausted = False

        self.partition_count = 0
        self.partition_sizes = []

        self.overflow_fallbacks = 0
        self.max_frames_held = 0

        # Important: validate schemas and condition BEFORE
        # doing partition work.
        self._inspect_schemas()
        self._prepare_condition()

        self._partition_inputs()

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "HashJoin.next() called "
                "before open()."
            )

        if self._exhausted:
            return END

        while True:

            # Overflow partition currently handled by BNL.
            if self._fallback is not None:

                row = self._fallback.next()

                self._sync_fallback()

                if row is not END:
                    self._count_output()
                    return row

                self._finish_fallback()
                continue

            # Normal Grace hash probe.
            if self._build_table is not None:

                row = self._next_hash_output()

                if row is not None:
                    return row

                continue

            # Need another partition pair.
            if not self._start_next_pair():
                self._exhausted = True
                return END

    def close(self):
        if not self.is_open:
            return

        if self._fallback is not None:
            self._fallback.close()
            self._sync_fallback()

        self._fallback = None

        self._delete_current_pair()

        for (
            left_run,
            right_run,
        ) in self._partition_pairs:
            left_run.delete()
            right_run.delete()

        self._partition_pairs = []

        self.left.close()
        self.right.close()

        self.is_open = False