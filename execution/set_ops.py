from execution.base import (
    END,
    Operator,
    validate_schema,
)
from execution.distinct import Distinct
from execution.union_all import UnionAll


def validate_set_schemas(
    left_schema,
    right_schema,
):
    if len(left_schema) != len(
        right_schema
    ):
        raise ValueError(
            "Set operator inputs must have "
            "the same number of columns."
        )

    for index, (
        left_column,
        right_column,
    ) in enumerate(
        zip(
            left_schema,
            right_schema,
        )
    ):
        left_type = left_column[1]
        right_type = right_column[1]

        if left_type != right_type:
            raise TypeError(
                "Set operator column type "
                f"mismatch at position "
                f"{index}: "
                f"{left_type} vs "
                f"{right_type}"
            )


class Union(Operator):
    """
    Set UNION.

    Concatenate both inputs, then remove duplicates.
    """

    def __init__(
        self,
        left,
        right,
        frames,
        temp_dir=None,
    ):
        super().__init__()

        self.left = left
        self.right = right
        self.frames = frames
        self.temp_dir = temp_dir

        self._pipeline = None
        self._exhausted = False

        self._last_comparisons = 0
        self._last_reads = 0
        self._last_writes = 0

    def _sync_counters(self):
        if self._pipeline is None:
            return

        counters = (
            self._pipeline.counters()
        )

        self._count_comparison(
            counters["comparisons"]
            - self._last_comparisons
        )

        self._count_read(
            counters["page_reads"]
            - self._last_reads
        )

        self._count_write(
            counters["page_writes"]
            - self._last_writes
        )

        self._last_comparisons = (
            counters["comparisons"]
        )

        self._last_reads = (
            counters["page_reads"]
        )

        self._last_writes = (
            counters["page_writes"]
        )

    def open(self):
        if self.is_open:
            raise RuntimeError(
                "Union is already open."
            )

        self._reset_counters()

        self._exhausted = False

        self._last_comparisons = 0
        self._last_reads = 0
        self._last_writes = 0

        concatenated = UnionAll(
            self.left,
            self.right,
        )

        self._pipeline = Distinct(
            concatenated,
            mode="sort",
            frames=self.frames,
            temp_dir=self.temp_dir,
        )

        self._pipeline.open()

        self.schema = [
            list(column)
            for column
            in self._pipeline.schema
        ]

        self._sync_counters()

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "Union.next() called before open()."
            )

        if self._exhausted:
            return END

        row = self._pipeline.next()

        self._sync_counters()

        if row is END:
            self._exhausted = True
            return END

        self._count_output()

        return row

    def close(self):
        if not self.is_open:
            return

        if self._pipeline is not None:
            self._pipeline.close()
            self._sync_counters()

        self._pipeline = None
        self.is_open = False


class _SortedBinarySetOperator(Operator):
    """
    Shared external-sort machinery for INTERSECT and EXCEPT.
    """

    def __init__(
        self,
        left,
        right,
        frames,
        temp_dir=None,
    ):
        super().__init__()

        self.left = left
        self.right = right
        self.frames = frames
        self.temp_dir = temp_dir

        self._left_distinct = None
        self._right_distinct = None

        self._left_row = END
        self._right_row = END

        self._left_schema = []
        self._right_schema = []

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

        self._exhausted = False

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

                validate_set_schemas(
                    self._left_schema,
                    self._right_schema,
                )

            finally:
                self.right.close()

        finally:
            self.left.close()

        self.schema = [
            list(column)
            for column
            in self._left_schema
        ]

    def _sync_one(
        self,
        operator,
        previous,
    ):
        if operator is None:
            return

        counters = operator.counters()

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

    def _sync_children(self):
        self._sync_one(
            self._left_distinct,
            self._last_left,
        )

        self._sync_one(
            self._right_distinct,
            self._last_right,
        )

    def _compare_rows(
        self,
        left,
        right,
    ):
        for index, column in enumerate(
            self._left_schema
        ):
            self._count_comparison()

            left_value = left[index]
            right_value = right[index]

            type_name = column[1]

            if type_name == "VARCHAR":
                left_value = (
                    left_value.encode(
                        "utf-8"
                    )
                )

                right_value = (
                    right_value.encode(
                        "utf-8"
                    )
                )

            if left_value < right_value:
                return -1

            if left_value > right_value:
                return 1

        return 0

    def _advance_left(self):
        self._left_row = (
            self._left_distinct.next()
        )

        self._sync_children()

    def _advance_right(self):
        self._right_row = (
            self._right_distinct.next()
        )

        self._sync_children()

    def open(self):
        if self.is_open:
            raise RuntimeError(
                f"{self.__class__.__name__} "
                f"is already open."
            )

        self._reset_counters()

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

        self._inspect_schemas()

        self._left_distinct = Distinct(
            self.left,
            mode="sort",
            frames=self.frames,
            temp_dir=self.temp_dir,
        )

        self._right_distinct = Distinct(
            self.right,
            mode="sort",
            frames=self.frames,
            temp_dir=self.temp_dir,
        )

        try:
            self._left_distinct.open()
            self._right_distinct.open()

            self._sync_children()

            self._left_row = (
                self._left_distinct.next()
            )

            self._right_row = (
                self._right_distinct.next()
            )

            self._sync_children()

        except Exception:
            if self._left_distinct is not None:
                self._left_distinct.close()

            if self._right_distinct is not None:
                self._right_distinct.close()

            raise

        self.is_open = True

    def close(self):
        if not self.is_open:
            return

        if self._left_distinct is not None:
            self._left_distinct.close()

        if self._right_distinct is not None:
            self._right_distinct.close()

        self._sync_children()

        self._left_distinct = None
        self._right_distinct = None

        self.is_open = False


class Intersect(_SortedBinarySetOperator):
    """
    Set INTERSECT.

    Each matching tuple appears exactly once.
    """

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "Intersect.next() called "
                "before open()."
            )

        if self._exhausted:
            return END

        while (
            self._left_row is not END
            and self._right_row is not END
        ):
            comparison = self._compare_rows(
                self._left_row,
                self._right_row,
            )

            if comparison < 0:
                self._advance_left()
                continue

            if comparison > 0:
                self._advance_right()
                continue

            result = self._left_row

            self._advance_left()
            self._advance_right()

            self._count_output()

            return result

        self._exhausted = True

        return END


class Except(_SortedBinarySetOperator):
    """
    Set EXCEPT.

    Each left-side tuple appears once only if it does not
    occur on the right.
    """

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "Except.next() called "
                "before open()."
            )

        if self._exhausted:
            return END

        while self._left_row is not END:

            if self._right_row is END:

                result = self._left_row

                self._advance_left()

                self._count_output()

                return result

            comparison = self._compare_rows(
                self._left_row,
                self._right_row,
            )

            if comparison < 0:

                result = self._left_row

                self._advance_left()

                self._count_output()

                return result

            if comparison > 0:
                self._advance_right()
                continue

            # Equal: remove this value from EXCEPT.
            self._advance_left()
            self._advance_right()

        self._exhausted = True

        return END