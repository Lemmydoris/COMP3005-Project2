from execution.base import (
    END,
    Operator,
    column_index,
    validate_schema,
)
from execution.conditions import resolve_column_name

class Project(Operator):
    """
    Pipelined Module 2 projection.

    Projection preserves duplicate tuples.
    """

    def __init__(self, child, columns):
        super().__init__()

        self.child = child
        self.columns = list(columns)

        self._indices = []
        self._exhausted = False

    def open(self):
        if self.is_open:
            raise RuntimeError(
                "Project is already open."
            )

        self._reset_counters()
        self._exhausted = False

        self.child.open()

        try:
            input_schema = self.child.schema

            self._indices = []
            self.schema = []

            for requested in self.columns:
                resolved = resolve_column_name(
                    input_schema,
                    requested,
                )

                index = column_index(
                    input_schema,
                    resolved,
                )

                self._indices.append(index)

                self.schema.append(
                    list(input_schema[index])
                )

            # Duplicate projected qualified names are invalid because a Module 2 schema may not contain the same qualified name twice.
            validate_schema(self.schema)

        except Exception:
            self.child.close()
            raise

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "Project.next() called before open()."
            )

        if self._exhausted:
            return END

        row = self.child.next()

        if row is END:
            self._exhausted = True
            return END

        projected = tuple(
            row[index]
            for index in self._indices
        )

        self._count_output()

        return projected

    def close(self):
        if not self.is_open:
            return

        self.child.close()

        self._indices = []
        self.is_open = False