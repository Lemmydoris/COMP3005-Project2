from sql_frontend.ast import (
    Comparison,
    Literal,
    LogicalCondition,
    NotCondition,
)
from sql_frontend.semantic import (
    AnalyzedCross,
    AnalyzedJoin,
    AnalyzedSelect,
    AnalyzedSet,
    AnalyzedTable,
    ResolvedColumn,
)


class SQLTranslationError(ValueError):
    pass


class LogicalPlanTranslator:

    # ========================================================
    # Public entry point
    # ========================================================

    def translate_query(
        self,
        query,
    ):

        if isinstance(
            query,
            AnalyzedSelect,
        ):
            return (
                self._translate_select(
                    query
                )
            )

        if isinstance(
            query,
            AnalyzedSet,
        ):
            return (
                self._translate_set(
                    query
                )
            )

        raise SQLTranslationError(
            "Expected analyzed query."
        )

    # ========================================================
    # SELECT
    # ========================================================

    def _translate_select(
        self,
        query,
    ):

        # ----------------------------------------------------
        # 1. FROM
        # ----------------------------------------------------

        plan = self._translate_from(
            query.from_source
        )

        # ----------------------------------------------------
        # 2. WHERE
        #
        # Keep the whole condition in one select node.
        # Do not push it toward a scan here.
        # ----------------------------------------------------

        if query.where is not None:

            plan = {
                "op": "select",
                "condition":
                    self.condition_to_string(
                        query.where
                    ),
                "child": plan,
            }

        # ----------------------------------------------------
        # 3. GROUP BY
        #
        # A global aggregate has keys=[].
        # ----------------------------------------------------

        if query.aggregating:

            aggregates = [
                [
                    aggregate.function,
                    aggregate.argument,
                    aggregate.output_name,
                ]
                for aggregate
                in query.aggregates
            ]

            plan = {
                "op": "group_by",
                "keys": [
                    column.plan_name
                    for column
                    in query.group_by
                ],
                "aggregates":
                    aggregates,
                "child": plan,
            }

        # ----------------------------------------------------
        # 4. HAVING
        # ----------------------------------------------------

        if query.having is not None:

            plan = {
                "op": "select",
                "condition":
                    self.condition_to_string(
                        query.having
                    ),
                "child": plan,
            }

        # ----------------------------------------------------
        # 5. SELECT / PROJECT
        #
        # In the published examples project.columns contains
        # the resolved source names and aggregate output names.
        #
        # Aggregate aliases already exist as group_by outputs.
        #
        # Ordinary column alias metadata stays in the semantic
        # result until the companion logical-plan schema gives
        # us an explicit column-alias representation.
        # ----------------------------------------------------

        columns = [
            item.source_name
            for item
            in query.projection
        ]

        plan = {
            "op": "project",
            "columns": columns,
            "child": plan,
        }

        # GROUP BY already produces one row per group.
        # The handout explicitly says DISTINCT above GROUP BY
        # is redundant and must not be emitted.
        if (
            query.distinct
            and not query.group_by
        ):

            plan = {
                "op": "distinct",
                "child": plan,
            }

        # ----------------------------------------------------
        # 6. ORDER BY
        # ----------------------------------------------------

        if query.order_by:

            plan = {
                "op": "sort",
                "keys": [
                    [
                        item.name,
                        item.direction,
                    ]
                    for item
                    in query.order_by
                ],
                "child": plan,
            }

        # ----------------------------------------------------
        # 7. LIMIT
        # ----------------------------------------------------

        if query.limit is not None:

            plan = {
                "op": "limit",
                "n": query.limit,
                "child": plan,
            }

        return plan

    # ========================================================
    # FROM
    # ========================================================

    def _translate_from(
        self,
        source,
    ):

        # ----------------------------------------------------
        # Base table or FROM subquery
        # ----------------------------------------------------

        if isinstance(
            source,
            AnalyzedTable,
        ):

            # Base table.
            if source.table_name is not None:

                plan = {
                    "op": "scan",
                    "table":
                        source.table_name,
                }

                if source.alias is not None:

                    plan = {
                        "op": "rename",
                        "to": source.alias,
                        "child": plan,
                    }

                return plan

            # FROM subquery.
            if source.subquery is None:

                raise SQLTranslationError(
                    "Analyzed subquery "
                    "source is missing query."
                )

            plan = self.translate_query(
                source.subquery
            )

            return {
                "op": "rename",
                "to": source.alias,
                "child": plan,
            }

        # ----------------------------------------------------
        # Comma FROM
        #
        # A comma remains a cross product.
        # Its WHERE predicate is not moved into the cross.
        # ----------------------------------------------------

        if isinstance(
            source,
            AnalyzedCross,
        ):

            return {
                "op": "cross",
                "left":
                    self._translate_from(
                        source.left
                    ),
                "right":
                    self._translate_from(
                        source.right
                    ),
            }

        # ----------------------------------------------------
        # Explicit JOIN ... ON
        # ----------------------------------------------------

        if isinstance(
            source,
            AnalyzedJoin,
        ):

            return {
                "op": "join",
                "condition":
                    self.condition_to_string(
                        source.condition
                    ),
                "left":
                    self._translate_from(
                        source.left
                    ),
                "right":
                    self._translate_from(
                        source.right
                    ),
            }

        raise SQLTranslationError(
            "Unsupported analyzed "
            "FROM source: "
            f"{type(source).__name__}"
        )

    # ========================================================
    # Set operations
    # ========================================================

    def _translate_set(
        self,
        query,
    ):

        if query.operator not in {
            "union",
            "union_all",
            "intersect",
            "except",
        }:

            raise SQLTranslationError(
                "Unknown set operator: "
                f"{query.operator}"
            )

        return {
            "op": query.operator,
            "left":
                self.translate_query(
                    query.left
                ),
            "right":
                self.translate_query(
                    query.right
                ),
        }

    # ========================================================
    # Conditions
    # ========================================================

    def condition_to_string(
        self,
        condition,
    ):

        return self._condition_text(
            condition,
            parent_precedence=0,
        )

    def _condition_text(
        self,
        condition,
        parent_precedence,
    ):

        # OR
        if isinstance(
            condition,
            LogicalCondition,
        ) and condition.operator == "or":

            precedence = 1

            text = (
                self._condition_text(
                    condition.left,
                    precedence,
                )
                + " OR "
                + self._condition_text(
                    condition.right,
                    precedence,
                )
            )

            return self._maybe_parenthesize(
                text,
                precedence,
                parent_precedence,
            )

        # AND
        if isinstance(
            condition,
            LogicalCondition,
        ) and condition.operator == "and":

            precedence = 2

            text = (
                self._condition_text(
                    condition.left,
                    precedence,
                )
                + " AND "
                + self._condition_text(
                    condition.right,
                    precedence,
                )
            )

            return self._maybe_parenthesize(
                text,
                precedence,
                parent_precedence,
            )

        # NOT
        if isinstance(
            condition,
            NotCondition,
        ):

            precedence = 3

            child = self._condition_text(
                condition.child,
                precedence,
            )

            text = (
                "NOT "
                + child
            )

            return self._maybe_parenthesize(
                text,
                precedence,
                parent_precedence,
            )

        # Comparison
        if isinstance(
            condition,
            Comparison,
        ):

            precedence = 4

            text = (
                self._operand_text(
                    condition.left
                )
                + " "
                + condition.operator
                + " "
                + self._operand_text(
                    condition.right
                )
            )

            return self._maybe_parenthesize(
                text,
                precedence,
                parent_precedence,
            )

        raise SQLTranslationError(
            "Unsupported condition node: "
            f"{type(condition).__name__}"
        )

    def _maybe_parenthesize(
        self,
        text,
        precedence,
        parent_precedence,
    ):

        if precedence < parent_precedence:
            return f"({text})"

        return text

    def _operand_text(
        self,
        operand,
    ):

        if isinstance(
            operand,
            ResolvedColumn,
        ):

            return operand.plan_name

        if isinstance(
            operand,
            Literal,
        ):

            if operand.kind == "INT":
                return str(
                    operand.value
                )

            if operand.kind == "VARCHAR":

                escaped = (
                    str(operand.value)
                    .replace(
                        "'",
                        "''",
                    )
                )

                return (
                    "'"
                    + escaped
                    + "'"
                )

        raise SQLTranslationError(
            "Unsupported resolved "
            "condition operand: "
            f"{type(operand).__name__}"
        )


def translate_query(
    analyzed_query,
):
    return LogicalPlanTranslator(
    ).translate_query(
        analyzed_query
    )