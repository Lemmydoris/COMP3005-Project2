from execution.base import END, Operator, validate_schema
from execution.conditions import (
    evaluate_condition,
    prepare_condition,
)

class Filter(Operator):
    """
    Pipelined Module 2 filter operator.
    """

    def __init__(self, child, condition):
        super().__init__()

        self.child = child
        self.condition = condition
        self._condition_tree = None
        self._exhausted = False

    def open(self):
        if self.is_open:
            raise RuntimeError(
                "Filter is already open."
            )

        self._reset_counters()
        self._exhausted = False

        self.child.open()

        try:
            self.schema = [
                list(column)
                for column in self.child.schema
            ]

            validate_schema(self.schema)

            self._condition_tree = prepare_condition(
                self.condition,
                self.schema,
            )

        except Exception:
            self.child.close()
            raise

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "Filter.next() called before open()."
            )

        if self._exhausted:
            return END

        while True:
            row = self.child.next()

            if row is END:
                self._exhausted = True
                return END

            # Professor's rule: one comparison per tuple examined, even for a compound condition.
            self._count_comparison()

            if evaluate_condition(
                self._condition_tree,
                self.schema,
                row,
            ):
                self._count_output()
                return row

    def close(self):
        if not self.is_open:
            return

        self.child.close()

        self._condition_tree = None
        self.is_open = False