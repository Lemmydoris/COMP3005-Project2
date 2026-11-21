from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnRef:
    name: str
    qualifier: str | None = None
    line: int = 1
    column: int = 1

    def text(self):
        if self.qualifier is None:
            return self.name

        return (
            f"{self.qualifier}."
            f"{self.name}"
        )


@dataclass(frozen=True)
class Literal:
    value: object
    kind: str
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class AggregateCall:
    function: str

    # None means "*".
    argument: ColumnRef | None

    line: int = 1
    column: int = 1

    def text(self):

        argument = (
            "*"
            if self.argument is None
            else self.argument.text()
        )

        return (
            f"{self.function.upper()}"
            f"({argument})"
        )


@dataclass(frozen=True)
class Comparison:
    left: object
    operator: str
    right: object
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class LogicalCondition:
    operator: str
    left: object
    right: object
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class NotCondition:
    child: object
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class SelectItem:
    expression: object
    alias: str | None = None
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class SortItem:
    column_ref: ColumnRef
    direction: str = "asc"
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class TableRef:
    # Base table when not None.
    name: str | None = None

    alias: str | None = None

    # Query object for a FROM subquery.
    subquery: object | None = None

    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class FromCross:
    left: object
    right: object
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class FromJoin:
    left: object
    right: object
    condition: object
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class SelectQuery:
    distinct: bool

    # True for SELECT *.
    select_all: bool

    items: list

    from_source: object

    where: object | None = None

    group_by: list = field(
        default_factory=list
    )

    having: object | None = None

    order_by: list = field(
        default_factory=list
    )

    limit: int | None = None

    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class SetQuery:
    left: object

    # union, union_all,
    # intersect, except
    operator: str

    right: object

    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class ColumnDef:
    name: str
    type_name: str
    length: int | None = None
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class CreateTable:
    name: str
    columns: list
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class InsertStatement:
    table: str
    values: list
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class Program:
    statements: list