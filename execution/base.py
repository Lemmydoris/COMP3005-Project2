from dataclasses import dataclass


# One shared sentinel used by every physical operator.
# It is different from None because None could theoretically be a legitimate value in a future extension.
END = object()


@dataclass
class OperatorCounters:
    """
    Counters required by the Module 2 specification.
    """

    tuples_out: int = 0
    comparisons: int = 0
    page_reads: int = 0
    page_writes: int = 0

    def as_dict(self):
        return {
            "tuples_out": self.tuples_out,
            "comparisons": self.comparisons,
            "page_reads": self.page_reads,
            "page_writes": self.page_writes,
        }

class Operator:
    """
    Base class for every Module 2 physical operator.

    Every operator must implement:

        open()
        next()
        close()

    and expose the required counters.
    """

    def __init__(self):
        self._counters = OperatorCounters()
        self.schema = []
        self.is_open = False

    def open(self):
        raise NotImplementedError

    def next(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError

    def counters(self):
        return self._counters.as_dict()

    def _count_output(self):
        self._counters.tuples_out += 1

    def _count_comparison(self, amount=1):
        self._counters.comparisons += amount

    def _count_read(self, amount=1):
        self._counters.page_reads += amount

    def _count_write(self, amount=1):
        self._counters.page_writes += amount

    def _reset_counters(self):
        self._counters = OperatorCounters()


def validate_schema(schema):
    """
    Reject duplicate qualified column names.

    A schema is expected to be an ordered sequence where
    each entry begins with its qualified name, for example:

        ("R.a", "INT")
        ("R.name", "VARCHAR", 20)

    or the same values represented as lists.
    """

    seen = set()

    for column in schema:
        if not column:
            raise ValueError("Schema contains an empty column definition.")

        name = column[0]

        if name in seen:
            raise ValueError(
                f"Duplicate qualified column name in schema: {name}"
            )

        seen.add(name)


def column_index(schema, column_name):
    """
    Return the position of a qualified column name.

    Unknown columns are errors.
    """

    matches = [
        index
        for index, column in enumerate(schema)
        if column[0] == column_name
    ]

    if not matches:
        raise ValueError(
            f"Unknown column: {column_name}"
        )

    if len(matches) > 1:
        raise ValueError(
            f"Duplicate qualified column name in schema: {column_name}"
        )

    return matches[0]