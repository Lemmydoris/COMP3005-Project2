from execution.base import (
    END,
    Operator,
    validate_schema,
)


class UnionAll(Operator):
    """
    Bag union / concatenation.

    Returns every tuple from the left child followed by
    every tuple from the right child. Duplicates remain.
    """

    def __init__(self, left, right):
        super().__init__()

        self.left = left
        self.right = right

        self._using_left = True
        self._right_open = False
        self._exhausted = False

    def _validate_compatibility(
        self,
        left_schema,
        right_schema,
    ):
        if len(left_schema) != len(
            right_schema
        ):
            raise ValueError(
                "union_all inputs must have "
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
                    "union_all column type "
                    f"mismatch at position "
                    f"{index}: "
                    f"{left_type} vs "
                    f"{right_type}"
                )

    def open(self):
        if self.is_open:
            raise RuntimeError(
                "UnionAll is already open."
            )

        self._reset_counters()

        self._using_left = True
        self._right_open = False
        self._exhausted = False

        self.left.open()

        try:
            left_schema = [
                list(column)
                for column
                in self.left.schema
            ]

            validate_schema(
                left_schema
            )

            # Open the right child only long enough
            # to validate its schema at open().
            self.right.open()

            try:
                right_schema = [
                    list(column)
                    for column
                    in self.right.schema
                ]

                validate_schema(
                    right_schema
                )

                self._validate_compatibility(
                    left_schema,
                    right_schema,
                )

            finally:
                self.right.close()

            # Set operators use the LEFT names.
            self.schema = left_schema

        except Exception:
            self.left.close()
            raise

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "UnionAll.next() called before open()."
            )

        if self._exhausted:
            return END

        if self._using_left:
            row = self.left.next()

            if row is not END:
                self._count_output()
                return row

            self.left.close()
            self._using_left = False

            self.right.open()
            self._right_open = True

        row = self.right.next()

        if row is END:
            self._exhausted = True
            return END

        self._count_output()

        return row

    def close(self):
        if not self.is_open:
            return

        self.left.close()

        if self._right_open:
            self.right.close()

        self._right_open = False
        self.is_open = False