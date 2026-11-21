from execution.base import (
    END,
    Operator,
    validate_schema,
)


class Limit(Operator):
    """
    Return at most n tuples and then stop pulling
    from the child.
    """

    def __init__(self, child, limit):
        super().__init__()

        self.child = child
        self.limit = limit

        self._returned = 0
        self._exhausted = False

    def open(self):
        if self.is_open:
            raise RuntimeError(
                "Limit is already open."
            )

        if (
            not isinstance(
                self.limit,
                int,
            )
            or isinstance(
                self.limit,
                bool,
            )
        ):
            raise TypeError(
                "Limit must be an integer."
            )

        if self.limit < 0:
            raise ValueError(
                "Limit cannot be negative."
            )

        self._reset_counters()

        self._returned = 0
        self._exhausted = False

        self.child.open()

        try:
            self.schema = [
                list(column)
                for column
                in self.child.schema
            ]

            validate_schema(
                self.schema
            )

        except Exception:
            self.child.close()
            raise

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "Limit.next() called before open()."
            )

        if self._exhausted:
            return END

        # Crucial: do not call child.next()
        # once the limit has been reached.
        if self._returned >= self.limit:
            self._exhausted = True
            return END

        row = self.child.next()

        if row is END:
            self._exhausted = True
            return END

        self._returned += 1
        self._count_output()

        return row

    def close(self):
        if not self.is_open:
            return

        self.child.close()

        self.is_open = False