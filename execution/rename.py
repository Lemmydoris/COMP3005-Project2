from execution.base import (
    END,
    Operator,
    validate_schema,
)


class Rename(Operator):
    """
    Schema-only physical rename.

    Tuples are returned unchanged. Only the visible
    qualifier of every output column changes.

    Example:

        Emp.did
        Emp.name

    renamed to x becomes:

        x.did
        x.name

    This operator has no page I/O or comparisons of
    its own.
    """

    def __init__(
        self,
        child,
        alias,
    ):
        super().__init__()

        self.child = child
        self.alias = alias

        self._exhausted = False

    def open(self):

        if self.is_open:
            raise RuntimeError(
                "Rename is already open."
            )

        if (
            not isinstance(
                self.alias,
                str,
            )
            or self.alias == ""
        ):
            raise ValueError(
                "Rename alias must be "
                "a non-empty string."
            )

        self._reset_counters()
        self._exhausted = False

        self.child.open()

        try:

            self.schema = []

            for column in self.child.schema:

                original_name = (
                    column[0]
                )

                if "." in original_name:

                    suffix = (
                        original_name.split(
                            ".",
                            1,
                        )[1]
                    )

                else:

                    suffix = (
                        original_name
                    )

                renamed = [
                    (
                        f"{self.alias}."
                        f"{suffix}"
                    ),
                    *column[1:],
                ]

                self.schema.append(
                    renamed
                )

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
                "Rename.next() called "
                "before open()."
            )

        if self._exhausted:
            return END

        row = self.child.next()

        if row is END:

            self._exhausted = True

            return END

        self._count_output()

        return row

    def close(self):

        if not self.is_open:
            return

        self.child.close()

        self._exhausted = False
        self.is_open = False