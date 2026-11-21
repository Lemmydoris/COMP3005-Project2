from dataclasses import dataclass

from sql_frontend.ast import (
    AggregateCall,
    ColumnRef,
    Comparison,
    CreateTable,
    FromCross,
    FromJoin,
    InsertStatement,
    Literal,
    LogicalCondition,
    NotCondition,
    Program,
    SelectQuery,
    SetQuery,
    TableRef,
)


# ============================================================
# Errors
# ============================================================


class SQLSemanticError(ValueError):

    def __init__(
        self,
        category,
        message,
        line,
        column,
    ):
        super().__init__(message)

        self.category = category
        self.message = message
        self.line = line
        self.column = column

    def __str__(self):
        return (
            f"error: {self.category}: "
            f"{self.message} "
            f"at line {self.line}, "
            f"column {self.column}"
        )


# ============================================================
# Resolved semantic structures
# ============================================================


@dataclass(frozen=True)
class ResolvedColumn:
    """
    A column reference after semantic resolution.

    plan_name is the exact name that later belongs
    in the logical plan.

    Examples:
        Emp.age
        e.name
        t.n
        n              (generated aggregate/output alias)
    """

    plan_name: str
    column_name: str
    type_name: str
    length: int | None = None

    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class OutputColumn:
    """
    One column exposed by a completed query.

    name is the name visible to an outer query.
    """

    name: str
    type_name: str
    length: int | None = None


@dataclass(frozen=True)
class ScopeColumn:
    """
    Column stored inside one FROM-scope entry.
    """

    name: str
    plan_name: str
    type_name: str
    length: int | None = None


@dataclass(frozen=True)
class ScopeEntry:
    name: str
    columns: tuple


@dataclass(frozen=True)
class AggregateSpec:
    function: str

    # "*" or a fully resolved column name.
    argument: str

    output_name: str

    type_name: str
    length: int | None = None


@dataclass(frozen=True)
class ProjectionSpec:
    """
    source_name is the name available below the
    project node.

    output_name is the SQL-visible output name.
    """

    source_name: str
    output_name: str

    type_name: str
    length: int | None = None

    explicit_alias: bool = False


@dataclass(frozen=True)
class ResolvedSortItem:
    name: str
    direction: str

    type_name: str
    length: int | None = None


@dataclass(frozen=True)
class AnalyzedTable:
    table_name: str | None
    alias: str | None

    # An analyzed subquery when table_name is None.
    subquery: object | None

    scope_entry: ScopeEntry


@dataclass(frozen=True)
class AnalyzedCross:
    left: object
    right: object


@dataclass(frozen=True)
class AnalyzedJoin:
    left: object
    right: object
    condition: object


@dataclass(frozen=True)
class AnalyzedSelect:
    distinct: bool

    from_source: object

    where: object | None

    group_by: tuple

    aggregates: tuple

    having: object | None

    projection: tuple

    order_by: tuple

    limit: int | None

    aggregating: bool

    output_schema: tuple

    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class AnalyzedSet:
    left: object
    operator: str
    right: object
    output_schema: tuple

    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class AnalyzedCreate:
    statement: CreateTable


@dataclass(frozen=True)
class AnalyzedInsert:
    statement: InsertStatement


@dataclass(frozen=True)
class AnalyzedProgram:
    statements: tuple


# ============================================================
# Analyzer
# ============================================================


class SQLSemanticAnalyzer:

    def __init__(self, catalog):
        self.catalog = catalog

    # --------------------------------------------------------
    # Public entry points
    # --------------------------------------------------------

    def analyze_program(
        self,
        program,
    ):

        results = []

        for statement in program.statements:
            results.append(
                self.analyze_statement(
                    statement
                )
            )

        return AnalyzedProgram(
            statements=tuple(results)
        )

    def analyze_statement(
        self,
        statement,
    ):

        if isinstance(
            statement,
            CreateTable,
        ):
            return (
                self.analyze_create(
                    statement
                )
            )

        if isinstance(
            statement,
            InsertStatement,
        ):
            return (
                self.analyze_insert(
                    statement
                )
            )

        if isinstance(
            statement,
            (
                SelectQuery,
                SetQuery,
            ),
        ):
            return self.analyze_query(
                statement
            )

        raise TypeError(
            "Unsupported SQL AST node: "
            f"{type(statement).__name__}"
        )

    # --------------------------------------------------------
    # CREATE TABLE
    # --------------------------------------------------------

    def analyze_create(
        self,
        statement,
    ):

        try:
            self.catalog.get_table(
                statement.name
            )

        except KeyError:
            pass

        else:
            raise SQLSemanticError(
                "schema",
                (
                    "Table already exists: "
                    f"{statement.name}"
                ),
                statement.line,
                statement.column,
            )

        names = set()

        for column in statement.columns:

            if column.name in names:
                raise SQLSemanticError(
                    "schema",
                    (
                        "Duplicate column: "
                        f"{column.name}"
                    ),
                    column.line,
                    column.column,
                )

            names.add(
                column.name
            )

            if (
                column.type_name
                == "VARCHAR"
            ):

                if (
                    column.length is None
                    or column.length < 1
                    or column.length > 255
                ):
                    raise SQLSemanticError(
                        "schema",
                        (
                            f"{column.name}: "
                            "VARCHAR length must "
                            "be between 1 and 255."
                        ),
                        column.line,
                        column.column,
                    )

        return AnalyzedCreate(
            statement=statement
        )

    # --------------------------------------------------------
    # INSERT
    # --------------------------------------------------------

    def analyze_insert(
        self,
        statement,
    ):

        table = self._get_table(
            statement.table,
            statement.line,
            statement.column,
        )

        schema = table[
            "schema"
        ]

        if (
            len(statement.values)
            != len(schema)
        ):
            raise SQLSemanticError(
                "schema",
                (
                    "INSERT value count does "
                    f"not match table "
                    f"{statement.table}: "
                    f"expected {len(schema)}, "
                    f"got "
                    f"{len(statement.values)}."
                ),
                statement.line,
                statement.column,
            )

        for (
            value,
            column,
        ) in zip(
            statement.values,
            schema,
        ):

            expected = (
                column[1]
            )

            if value.kind != expected:
                raise SQLSemanticError(
                    "type",
                    (
                        "INSERT type mismatch "
                        f"for {statement.table}."
                        f"{column[0]}: "
                        f"expected {expected}, "
                        f"got {value.kind}."
                    ),
                    value.line,
                    value.column,
                )

            if (
                expected == "VARCHAR"
                and len(value.value)
                > column[2]
            ):
                raise SQLSemanticError(
                    "type",
                    (
                        f"Value for "
                        f"{statement.table}."
                        f"{column[0]} exceeds "
                        f"VARCHAR({column[2]})."
                    ),
                    value.line,
                    value.column,
                )

        return AnalyzedInsert(
            statement=statement
        )

    # --------------------------------------------------------
    # Queries
    # --------------------------------------------------------

    def analyze_query(
        self,
        query,
    ):

        if isinstance(
            query,
            SetQuery,
        ):
            return (
                self._analyze_set_query(
                    query
                )
            )

        if isinstance(
            query,
            SelectQuery,
        ):
            return (
                self._analyze_select_query(
                    query
                )
            )

        raise TypeError(
            "Expected query AST node."
        )

    # --------------------------------------------------------
    # Set operations
    # --------------------------------------------------------

    def _analyze_set_query(
        self,
        query,
    ):

        left = self.analyze_query(
            query.left
        )

        right = self.analyze_query(
            query.right
        )

        left_schema = (
            left.output_schema
        )

        right_schema = (
            right.output_schema
        )

        if (
            len(left_schema)
            != len(right_schema)
        ):
            raise SQLSemanticError(
                "schema",
                (
                    "Set-operation inputs "
                    "have different column "
                    "counts."
                ),
                query.line,
                query.column,
            )

        for index, (
            left_column,
            right_column,
        ) in enumerate(
            zip(
                left_schema,
                right_schema,
            ),
            start=1,
        ):

            if (
                left_column.type_name
                != right_column.type_name
            ):
                raise SQLSemanticError(
                    "schema",
                    (
                        "Set-operation type "
                        f"mismatch at column "
                        f"{index}: "
                        f"{left_column.type_name} "
                        f"vs "
                        f"{right_column.type_name}."
                    ),
                    query.line,
                    query.column,
                )

        # Set-operation output names come
        # from the left input.
        return AnalyzedSet(
            left=left,
            operator=query.operator,
            right=right,
            output_schema=left_schema,
            line=query.line,
            column=query.column,
        )

    # --------------------------------------------------------
    # SELECT query
    # --------------------------------------------------------

    def _analyze_select_query(
        self,
        query,
    ):

        (
            analyzed_from,
            scope,
        ) = self._analyze_from(
            query.from_source
        )

        # WHERE is evaluated before grouping,
        # so aggregates are illegal here.
        where = None

        if query.where is not None:

            where = (
                self._resolve_condition(
                    query.where,
                    scope,
                    allow_aggregate=False,
                    grouping_names=None,
                    aggregate_specs=None,
                )
            )

        # GROUP BY columns.
        group_by = []

        for column in query.group_by:

            group_by.append(
                self._resolve_column(
                    column,
                    scope,
                )
            )

        grouping_names = {
            column.plan_name
            for column in group_by
        }

        has_select_aggregate = any(
            isinstance(
                item.expression,
                AggregateCall,
            )
            for item in query.items
        )

        aggregating = (
            bool(group_by)
            or has_select_aggregate
        )

        # SELECT * is expanded before the
        # projection is checked.
        expanded_items = []

        if query.select_all:

            for entry in scope:

                for column in entry.columns:

                    expanded_items.append(
                        (
                            ResolvedColumn(
                                plan_name=(
                                    column.plan_name
                                ),
                                column_name=(
                                    column.name
                                ),
                                type_name=(
                                    column.type_name
                                ),
                                length=(
                                    column.length
                                ),
                                line=query.line,
                                column=query.column,
                            ),
                            None,
                            False,
                        )
                    )

        else:

            for item in query.items:

                expanded_items.append(
                    (
                        item.expression,
                        item.alias,
                        (
                            item.alias
                            is not None
                        ),
                    )
                )

        aggregate_specs = []
        aggregate_by_key = {}

        projection = []

        # Keep explicit aliases here so
        # ORDER BY can resolve them first.
        explicit_aliases = {}

        for (
            expression,
            alias,
            explicit_alias,
        ) in expanded_items:

            # ------------------------------
            # Aggregate SELECT item
            # ------------------------------

            if isinstance(
                expression,
                AggregateCall,
            ):

                (
                    resolved_aggregate,
                    aggregate_key,
                ) = self._resolve_aggregate(
                    expression,
                    scope,
                    preferred_name=alias,
                )

                if (
                    aggregate_key
                    not in aggregate_by_key
                ):
                    aggregate_by_key[
                        aggregate_key
                    ] = (
                        resolved_aggregate
                    )

                    aggregate_specs.append(
                        resolved_aggregate
                    )

                else:
                    # Reuse the already
                    # computed grouped result.
                    resolved_aggregate = (
                        aggregate_by_key[
                            aggregate_key
                        ]
                    )

                output_name = (
                    alias
                    if alias is not None
                    else
                    resolved_aggregate.output_name
                )

                projection.append(
                    ProjectionSpec(
                        source_name=(
                            resolved_aggregate
                            .output_name
                        ),
                        output_name=(
                            output_name
                        ),
                        type_name=(
                            resolved_aggregate
                            .type_name
                        ),
                        length=(
                            resolved_aggregate
                            .length
                        ),
                        explicit_alias=(
                            explicit_alias
                        ),
                    )
                )

                if explicit_alias:

                    explicit_aliases[
                        alias
                    ] = ResolvedColumn(
                        plan_name=alias,
                        column_name=alias,
                        type_name=(
                            resolved_aggregate
                            .type_name
                        ),
                        length=(
                            resolved_aggregate
                            .length
                        ),
                        line=(
                            expression.line
                        ),
                        column=(
                            expression.column
                        ),
                    )

                continue

            # ------------------------------
            # SELECT * expansion already
            # produced ResolvedColumn.
            # ------------------------------

            if isinstance(
                expression,
                ResolvedColumn,
            ):
                resolved_column = expression

            else:
                resolved_column = (
                    self._resolve_column(
                        expression,
                        scope,
                    )
                )

            if (
                aggregating
                and resolved_column.plan_name
                not in grouping_names
            ):
                raise SQLSemanticError(
                    "aggregate",
                    (
                        "Column "
                        f"{resolved_column.plan_name} "
                        "must appear in GROUP BY "
                        "or be aggregated."
                    ),
                    resolved_column.line,
                    resolved_column.column,
                )

            output_name = (
                alias
                if alias is not None
                else resolved_column.column_name
            )

            projection.append(
                ProjectionSpec(
                    source_name=(
                        resolved_column.plan_name
                    ),
                    output_name=output_name,
                    type_name=(
                        resolved_column.type_name
                    ),
                    length=(
                        resolved_column.length
                    ),
                    explicit_alias=(
                        explicit_alias
                    ),
                )
            )

            if explicit_alias:

                explicit_aliases[
                    alias
                ] = ResolvedColumn(
                    plan_name=alias,
                    column_name=alias,
                    type_name=(
                        resolved_column.type_name
                    ),
                    length=(
                        resolved_column.length
                    ),
                    line=(
                        resolved_column.line
                    ),
                    column=(
                        resolved_column.column
                    ),
                )

        # HAVING is evaluated after grouping.
        having = None

        if query.having is not None:

            if not aggregating:
                raise SQLSemanticError(
                    "aggregate",
                    (
                        "HAVING requires an "
                        "aggregating query."
                    ),
                    query.having.line,
                    query.having.column,
                )

            having = (
                self._resolve_condition(
                    query.having,
                    scope,
                    allow_aggregate=True,
                    grouping_names=(
                        grouping_names
                    ),
                    aggregate_specs=(
                        (
                            aggregate_specs,
                            aggregate_by_key,
                        )
                    ),
                )
            )

        # ORDER BY:
        # 1. explicit SELECT aliases
        # 2. FROM scope
        order_by = []

        for item in query.order_by:

            column_ref = (
                item.column_ref
            )

            if (
                column_ref.qualifier
                is None
                and column_ref.name
                in explicit_aliases
            ):

                resolved = (
                    explicit_aliases[
                        column_ref.name
                    ]
                )

            else:

                resolved = (
                    self._resolve_column(
                        column_ref,
                        scope,
                    )
                )

                if (
                    aggregating
                    and resolved.plan_name
                    not in grouping_names
                ):
                    raise SQLSemanticError(
                        "aggregate",
                        (
                            "ORDER BY column "
                            f"{resolved.plan_name} "
                            "must be grouped or "
                            "refer to a SELECT "
                            "output alias."
                        ),
                        column_ref.line,
                        column_ref.column,
                    )

            order_by.append(
                ResolvedSortItem(
                    name=(
                        resolved.plan_name
                    ),
                    direction=(
                        item.direction
                    ),
                    type_name=(
                        resolved.type_name
                    ),
                    length=(
                        resolved.length
                    ),
                )
            )

        if (
            query.limit is not None
            and query.limit < 0
        ):
            raise SQLSemanticError(
                "type",
                "LIMIT cannot be negative.",
                query.line,
                query.column,
            )

        output_schema = tuple(
            OutputColumn(
                name=item.output_name,
                type_name=item.type_name,
                length=item.length,
            )
            for item in projection
        )

        return AnalyzedSelect(
            distinct=query.distinct,
            from_source=analyzed_from,
            where=where,
            group_by=tuple(group_by),
            aggregates=tuple(
                aggregate_specs
            ),
            having=having,
            projection=tuple(
                projection
            ),
            order_by=tuple(
                order_by
            ),
            limit=query.limit,
            aggregating=aggregating,
            output_schema=(
                output_schema
            ),
            line=query.line,
            column=query.column,
        )

    # --------------------------------------------------------
    # FROM / scope construction
    # --------------------------------------------------------

    def _analyze_from(
        self,
        source,
    ):

        if isinstance(
            source,
            TableRef,
        ):

            return (
                self._analyze_table_ref(
                    source
                )
            )

        if isinstance(
            source,
            FromCross,
        ):

            (
                left,
                left_scope,
            ) = self._analyze_from(
                source.left
            )

            (
                right,
                right_scope,
            ) = self._analyze_from(
                source.right
            )

            scope = (
                self._combine_scopes(
                    left_scope,
                    right_scope,
                    source.line,
                    source.column,
                )
            )

            return (
                AnalyzedCross(
                    left=left,
                    right=right,
                ),
                scope,
            )

        if isinstance(
            source,
            FromJoin,
        ):

            (
                left,
                left_scope,
            ) = self._analyze_from(
                source.left
            )

            (
                right,
                right_scope,
            ) = self._analyze_from(
                source.right
            )

            scope = (
                self._combine_scopes(
                    left_scope,
                    right_scope,
                    source.line,
                    source.column,
                )
            )

            condition = (
                self._resolve_condition(
                    source.condition,
                    scope,
                    allow_aggregate=False,
                    grouping_names=None,
                    aggregate_specs=None,
                )
            )

            return (
                AnalyzedJoin(
                    left=left,
                    right=right,
                    condition=condition,
                ),
                scope,
            )

        raise TypeError(
            "Unsupported FROM node: "
            f"{type(source).__name__}"
        )

    def _analyze_table_ref(
        self,
        source,
    ):

        # ------------------------------
        # Subquery in FROM
        # ------------------------------

        if source.subquery is not None:

            analyzed_subquery = (
                self.analyze_query(
                    source.subquery
                )
            )

            alias = source.alias

            columns = tuple(
                ScopeColumn(
                    name=column.name,
                    plan_name=(
                        f"{alias}."
                        f"{column.name}"
                    ),
                    type_name=(
                        column.type_name
                    ),
                    length=(
                        column.length
                    ),
                )
                for column
                in analyzed_subquery.output_schema
            )

            entry = ScopeEntry(
                name=alias,
                columns=columns,
            )

            return (
                AnalyzedTable(
                    table_name=None,
                    alias=alias,
                    subquery=(
                        analyzed_subquery
                    ),
                    scope_entry=entry,
                ),
                (entry,),
            )

        # ------------------------------
        # Base table
        # ------------------------------

        table = self._get_table(
            source.name,
            source.line,
            source.column,
        )

        visible_name = (
            source.alias
            if source.alias is not None
            else source.name
        )

        columns = []

        for column in table[
            "schema"
        ]:

            name = column[0]
            type_name = column[1]

            length = (
                column[2]
                if (
                    type_name
                    == "VARCHAR"
                )
                else None
            )

            columns.append(
                ScopeColumn(
                    name=name,
                    plan_name=(
                        f"{visible_name}."
                        f"{name}"
                    ),
                    type_name=(
                        type_name
                    ),
                    length=length,
                )
            )

        entry = ScopeEntry(
            name=visible_name,
            columns=tuple(columns),
        )

        return (
            AnalyzedTable(
                table_name=source.name,
                alias=source.alias,
                subquery=None,
                scope_entry=entry,
            ),
            (entry,),
        )

    def _combine_scopes(
        self,
        left_scope,
        right_scope,
        line,
        column,
    ):

        names = {
            entry.name
            for entry in left_scope
        }

        for entry in right_scope:

            if entry.name in names:
                raise SQLSemanticError(
                    "name",
                    (
                        "Duplicate table alias "
                        f"or scope name: "
                        f"{entry.name}"
                    ),
                    line,
                    column,
                )

            names.add(
                entry.name
            )

        return (
            tuple(left_scope)
            + tuple(right_scope)
        )

    # --------------------------------------------------------
    # Column resolution
    # --------------------------------------------------------

    def _resolve_column(
        self,
        column_ref,
        scope,
    ):

        # Qualified reference: t.c
        if (
            column_ref.qualifier
            is not None
        ):

            entry = None

            for candidate in scope:

                if (
                    candidate.name
                    == column_ref.qualifier
                ):
                    entry = candidate
                    break

            if entry is None:
                raise SQLSemanticError(
                    "name",
                    (
                        "Unknown table or alias: "
                        f"{column_ref.qualifier}"
                    ),
                    column_ref.line,
                    column_ref.column,
                )

            for column in entry.columns:

                if (
                    column.name
                    == column_ref.name
                ):

                    return ResolvedColumn(
                        plan_name=(
                            column.plan_name
                        ),
                        column_name=(
                            column.name
                        ),
                        type_name=(
                            column.type_name
                        ),
                        length=(
                            column.length
                        ),
                        line=(
                            column_ref.line
                        ),
                        column=(
                            column_ref.column
                        ),
                    )

            raise SQLSemanticError(
                "name",
                (
                    "Unknown column "
                    f"{column_ref.name} "
                    f"in {entry.name}."
                ),
                column_ref.line,
                column_ref.column,
            )

        # Unqualified reference: c
        matches = []

        for entry in scope:

            for column in entry.columns:

                if (
                    column.name
                    == column_ref.name
                ):
                    matches.append(
                        (
                            entry,
                            column,
                        )
                    )

        if not matches:
            raise SQLSemanticError(
                "name",
                (
                    "Unknown column: "
                    f"{column_ref.name}"
                ),
                column_ref.line,
                column_ref.column,
            )

        if len(matches) > 1:

            candidates = ", ".join(
                (
                    f"{entry.name}."
                    f"{column.name}"
                )
                for (
                    entry,
                    column,
                )
                in matches
            )

            raise SQLSemanticError(
                "ambiguity",
                (
                    "Ambiguous column "
                    f"{column_ref.name}; "
                    f"candidates: "
                    f"{candidates}"
                ),
                column_ref.line,
                column_ref.column,
            )

        (
            _,
            column,
        ) = matches[0]

        return ResolvedColumn(
            plan_name=column.plan_name,
            column_name=column.name,
            type_name=column.type_name,
            length=column.length,
            line=column_ref.line,
            column=column_ref.column,
        )

    # --------------------------------------------------------
    # Conditions
    # --------------------------------------------------------

    def _resolve_condition(
        self,
        condition,
        scope,
        *,
        allow_aggregate,
        grouping_names,
        aggregate_specs,
    ):

        if isinstance(
            condition,
            Comparison,
        ):

            left = self._resolve_operand(
                condition.left,
                scope,
                allow_aggregate=(
                    allow_aggregate
                ),
                grouping_names=(
                    grouping_names
                ),
                aggregate_specs=(
                    aggregate_specs
                ),
            )

            right = self._resolve_operand(
                condition.right,
                scope,
                allow_aggregate=(
                    allow_aggregate
                ),
                grouping_names=(
                    grouping_names
                ),
                aggregate_specs=(
                    aggregate_specs
                ),
            )

            left_type = (
                self._expression_type(
                    left
                )
            )

            right_type = (
                self._expression_type(
                    right
                )
            )

            if left_type != right_type:

                raise SQLSemanticError(
                    "type",
                    (
                        "Cannot compare "
                        f"{left_type} to "
                        f"{right_type}."
                    ),
                    condition.line,
                    condition.column,
                )

            return Comparison(
                left=left,
                operator=(
                    condition.operator
                ),
                right=right,
                line=condition.line,
                column=condition.column,
            )

        if isinstance(
            condition,
            LogicalCondition,
        ):

            return LogicalCondition(
                operator=(
                    condition.operator
                ),
                left=(
                    self._resolve_condition(
                        condition.left,
                        scope,
                        allow_aggregate=(
                            allow_aggregate
                        ),
                        grouping_names=(
                            grouping_names
                        ),
                        aggregate_specs=(
                            aggregate_specs
                        ),
                    )
                ),
                right=(
                    self._resolve_condition(
                        condition.right,
                        scope,
                        allow_aggregate=(
                            allow_aggregate
                        ),
                        grouping_names=(
                            grouping_names
                        ),
                        aggregate_specs=(
                            aggregate_specs
                        ),
                    )
                ),
                line=condition.line,
                column=condition.column,
            )

        if isinstance(
            condition,
            NotCondition,
        ):

            return NotCondition(
                child=(
                    self._resolve_condition(
                        condition.child,
                        scope,
                        allow_aggregate=(
                            allow_aggregate
                        ),
                        grouping_names=(
                            grouping_names
                        ),
                        aggregate_specs=(
                            aggregate_specs
                        ),
                    )
                ),
                line=condition.line,
                column=condition.column,
            )

        raise TypeError(
            "Unsupported condition node: "
            f"{type(condition).__name__}"
        )

    def _resolve_operand(
        self,
        operand,
        scope,
        *,
        allow_aggregate,
        grouping_names,
        aggregate_specs,
    ):

        if isinstance(
            operand,
            Literal,
        ):
            return operand

        if isinstance(
            operand,
            ColumnRef,
        ):

            resolved = (
                self._resolve_column(
                    operand,
                    scope,
                )
            )

            if (
                grouping_names
                is not None
                and resolved.plan_name
                not in grouping_names
            ):
                raise SQLSemanticError(
                    "aggregate",
                    (
                        "HAVING column "
                        f"{resolved.plan_name} "
                        "must appear in "
                        "GROUP BY."
                    ),
                    operand.line,
                    operand.column,
                )

            return resolved

        if isinstance(
            operand,
            AggregateCall,
        ):

            if not allow_aggregate:

                raise SQLSemanticError(
                    "aggregate",
                    (
                        "Aggregate "
                        f"{operand.function.upper()}"
                        " is not allowed "
                        "before grouping."
                    ),
                    operand.line,
                    operand.column,
                )

            (
                aggregate_list,
                aggregate_by_key,
            ) = aggregate_specs

            (
                aggregate,
                key,
            ) = self._resolve_aggregate(
                operand,
                scope,
                preferred_name=None,
            )

            if key not in aggregate_by_key:

                aggregate_by_key[
                    key
                ] = aggregate

                aggregate_list.append(
                    aggregate
                )

            else:
                aggregate = (
                    aggregate_by_key[
                        key
                    ]
                )

            # HAVING operates on the
            # generated group-by output.
            return ResolvedColumn(
                plan_name=(
                    aggregate.output_name
                ),
                column_name=(
                    aggregate.output_name
                ),
                type_name=(
                    aggregate.type_name
                ),
                length=(
                    aggregate.length
                ),
                line=operand.line,
                column=operand.column,
            )

        raise TypeError(
            "Unsupported operand: "
            f"{type(operand).__name__}"
        )

    # --------------------------------------------------------
    # Aggregates
    # --------------------------------------------------------

    def _resolve_aggregate(
        self,
        aggregate,
        scope,
        *,
        preferred_name,
    ):

        function = (
            aggregate.function.lower()
        )

        argument_name = "*"
        argument_type = None
        argument_length = None

        if aggregate.argument is not None:

            resolved_argument = (
                self._resolve_column(
                    aggregate.argument,
                    scope,
                )
            )

            argument_name = (
                resolved_argument.plan_name
            )

            argument_type = (
                resolved_argument.type_name
            )

            argument_length = (
                resolved_argument.length
            )

        if function == "count":

            output_type = "INT"
            output_length = None

        elif function in {
            "sum",
            "avg",
        }:

            if argument_name == "*":
                raise SQLSemanticError(
                    "aggregate",
                    (
                        f"{function.upper()}(*) "
                        "is not allowed."
                    ),
                    aggregate.line,
                    aggregate.column,
                )

            if argument_type != "INT":
                raise SQLSemanticError(
                    "aggregate",
                    (
                        f"{function.upper()} "
                        "requires an INT "
                        "column."
                    ),
                    aggregate.line,
                    aggregate.column,
                )

            if function == "avg":
                output_type = "REAL"
            else:
                output_type = "INT"

            output_length = None

        elif function in {
            "min",
            "max",
        }:

            if argument_name == "*":
                raise SQLSemanticError(
                    "aggregate",
                    (
                        f"{function.upper()}(*) "
                        "is not allowed."
                    ),
                    aggregate.line,
                    aggregate.column,
                )

            output_type = (
                argument_type
            )

            output_length = (
                argument_length
            )

        else:

            raise SQLSemanticError(
                "aggregate",
                (
                    "Unknown aggregate: "
                    f"{function}"
                ),
                aggregate.line,
                aggregate.column,
            )

        if preferred_name is not None:

            output_name = (
                preferred_name
            )

        else:

            output_name = (
                self._default_aggregate_name(
                    function,
                    argument_name,
                )
            )

        key = (
            function,
            argument_name,
        )

        return (
            AggregateSpec(
                function=function,
                argument=argument_name,
                output_name=output_name,
                type_name=output_type,
                length=output_length,
            ),
            key,
        )

    def _default_aggregate_name(
        self,
        function,
        argument_name,
    ):

        if argument_name == "*":
            suffix = "star"

        else:
            suffix = (
                argument_name.replace(
                    ".",
                    "_",
                )
            )

        return (
            f"{function}_{suffix}"
        )

    # --------------------------------------------------------
    # Types
    # --------------------------------------------------------

    def _expression_type(
        self,
        expression,
    ):

        if isinstance(
            expression,
            Literal,
        ):
            return expression.kind

        if isinstance(
            expression,
            ResolvedColumn,
        ):
            return (
                expression.type_name
            )

        raise TypeError(
            "Cannot determine type of "
            f"{type(expression).__name__}"
        )

    # --------------------------------------------------------
    # Catalog
    # --------------------------------------------------------

    def _get_table(
        self,
        name,
        line,
        column,
    ):

        try:
            return self.catalog.get_table(
                name
            )

        except KeyError:
            raise SQLSemanticError(
                "name",
                f"Unknown table: {name}",
                line,
                column,
            )


def analyze_sql(
    program,
    catalog,
):
    return SQLSemanticAnalyzer(
        catalog
    ).analyze_program(
        program
    )