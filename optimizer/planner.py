
import copy
import math
from dataclasses import dataclass

from parser import parse_condition_text
from ra_tree import (
    Attr,
    Literal,
    Comparison,
    Logical,
    Not,
)

from storage.catalog import Catalog

from optimizer.rewrite import (
    LogicalPlanRewriter,
)

from optimizer.join_order import (
    RelationInfo,
    JoinPredicateInfo,
    enumerate_left_deep,
)

from optimizer.cost import (
    distinct_cost,
    group_by_cost,
    sort_cost,
    nested_loop_join_cost,
    join_algorithm_costs,
)

from optimizer.selectivity import (
    attr_name,
    estimate_rows,
    estimate_join_rows,
    estimate_pages,
    _linear_fraction,
)


DEFAULT_EQUALITY_SELECTIVITY = 0.1
DEFAULT_RANGE_SELECTIVITY = 1.0 / 3.0
DEFAULT_JOIN_SELECTIVITY = 0.1


@dataclass
class ColumnEstimate:
    name: str
    type_name: str
    width: float


@dataclass
class PlanEstimate:
    plan: dict

    rows: int
    pages: int
    width: float

    columns: list
    relations: frozenset
    bindings: dict

    cost: int = 0


class PhysicalPlanner:
    """
    Module 4 logical -> physical planner.

    Responsibilities:

        1. Apply logical rewrite rules.
        2. Read statistics from the Module 1 catalog.
        3. Estimate cardinalities and page counts.
        4. Use dynamic programming for connected joins.
        5. Choose physical algorithms.
        6. Produce Module 2-compatible physical JSON.
    """

    def __init__(
        self,
        db_dir,
        frames=32,
        catalog=None,
    ):
        if frames < 4:
            raise ValueError(
                "Physical planning requires "
                "at least 4 frames."
            )

        self.db_dir = db_dir
        self.frames = frames

        if catalog is None:
            catalog = Catalog(
                db_dir,
                frames=max(
                    2,
                    frames,
                ),
            )

        self.catalog = catalog

    # ========================================================
    # Public interface
    # ========================================================

    def plan(
        self,
        logical_plan,
        disabled_rules=None,
    ):
        """
        Return only the physical JSON plan.
        """

        result = (
            self.plan_with_estimates(
                logical_plan,
                disabled_rules=
                    disabled_rules,
            )
        )

        return result.plan

    def plan_with_estimates(
        self,
        logical_plan,
        disabled_rules=None,
    ):
        """
        Rewrite and physically plan a logical tree.

        Returns PlanEstimate so EXPLAIN can later use the
        estimated rows/pages/cost.
        """

        rewriter = LogicalPlanRewriter(
            self.catalog
        )

        rewritten = rewriter.rewrite(
            copy.deepcopy(
                logical_plan
            ),
            disabled_rules=
                disabled_rules,
        )

        return self._plan_node(
            rewritten
        )

    def rewritten_plan(
        self,
        logical_plan,
        disabled_rules=None,
    ):
        """
        Useful later for opt explain.
        """

        rewriter = LogicalPlanRewriter(
            self.catalog
        )

        return rewriter.rewrite(
            copy.deepcopy(
                logical_plan
            ),
            disabled_rules=
                disabled_rules,
        )

    # ========================================================
    # Generic node dispatcher
    # ========================================================

    def _plan_node(
        self,
        node,
    ):
        if not isinstance(
            node,
            dict,
        ):
            raise ValueError(
                "Logical plan node must "
                "be a dictionary."
            )

        op = node.get(
            "op"
        )

        if op == "scan":
            return self._plan_scan(
                node
            )

        if op == "rename":
            return self._plan_rename(
                node
            )

        if op == "select":
            return self._plan_select(
                node
            )

        if op == "project":
            return self._plan_project(
                node
            )

        if op == "group_by":
            return self._plan_group_by(
                node
            )

        if op == "distinct":
            return self._plan_distinct(
                node
            )

        if op == "sort":
            return self._plan_sort(
                node
            )

        if op == "limit":
            return self._plan_limit(
                node
            )

        if op == "join":
            return self._plan_join_component(
                node
            )

        if op == "cross":
            return self._plan_cross(
                node
            )

        if op in (
            "union",
            "union_all",
            "intersect",
            "except",
        ):
            return self._plan_set_operator(
                node
            )

        raise ValueError(
            "Unsupported logical "
            f"operator: {op}"
        )

    # ========================================================
    # Catalog/statistics helpers
    # ========================================================

    def _metadata(
        self,
        table_name,
    ):
        return self.catalog.get_table(
            table_name
        )

    def _statistics(
        self,
        metadata,
    ):
        statistics = metadata.get(
            "statistics"
        )

        if not isinstance(
            statistics,
            dict,
        ):
            return {}

        return statistics

    def _declared_column_width(
        self,
        column,
    ):
        type_name = column[1]

        if type_name == "INT":
            return 4.0

        if type_name == "REAL":
            return 8.0

        if type_name == "VARCHAR":
            if len(column) >= 3:
                return float(
                    2 + column[2]
                )

            return 10.0

        return 8.0

    def _base_columns(
        self,
        metadata,
        qualifier,
        total_width,
    ):
        schema = metadata[
            "schema"
        ]

        declared = [
            self._declared_column_width(
                column
            )
            for column in schema
        ]

        declared_total = sum(
            declared
        )

        if (
            total_width > 0
            and declared_total > 0
        ):
            scale = (
                total_width
                / declared_total
            )
        else:
            scale = 1.0

        columns = []

        for (
            column,
            declared_width,
        ) in zip(
            schema,
            declared,
        ):
            columns.append(
                ColumnEstimate(
                    name=(
                        f"{qualifier}."
                        f"{column[0]}"
                    ),
                    type_name=
                        column[1],
                    width=(
                        declared_width
                        * scale
                    ),
                )
            )

        return columns

    def _fallback_width(
        self,
        metadata,
    ):
        return sum(
            self._declared_column_width(
                column
            )
            for column
            in metadata[
                "schema"
            ]
        )

    # ========================================================
    # SCAN
    # ========================================================

    def _plan_scan(
        self,
        node,
    ):
        table_name = node[
            "table"
        ]

        metadata = self._metadata(
            table_name
        )

        statistics = self._statistics(
            metadata
        )

        rows = int(
            statistics.get(
                "n_tuples",
                metadata.get(
                    "num_tuples",
                    1,
                ),
            )
        )

        pages = int(
            statistics.get(
                "n_pages",
                metadata.get(
                    "num_pages",
                    1,
                ),
            )
        )

        width = float(
            statistics.get(
                "width",
                self._fallback_width(
                    metadata
                ),
            )
        )

        rows = max(
            0,
            rows,
        )

        pages = max(
            0,
            pages,
        )

        columns = (
            self._base_columns(
                metadata,
                table_name,
                width,
            )
        )

        return PlanEstimate(
            plan={
                "op":
                    "seqscan",
                "table":
                    table_name,
            },
            rows=rows,
            pages=pages,
            width=width,
            columns=columns,
            relations=frozenset(
                {
                    table_name,
                }
            ),
            bindings={
                table_name:
                    table_name,
            },
            cost=pages,
        )

    # ========================================================
    # RENAME
    # ========================================================

    def _plan_rename(
        self,
        node,
    ):
        alias = node[
            "to"
        ]

        child_node = node[
            "child"
        ]

        # ----------------------------------------------------
        # Base-table alias.
        #
        # Module 2 SeqScan now supports:
        #
        # {"op":"seqscan",
        #  "table":"Emp",
        #  "alias":"e"}
        # ----------------------------------------------------

        if (
            child_node.get(
                "op"
            )
            == "scan"
        ):
            table_name = (
                child_node[
                    "table"
                ]
            )

            base = self._plan_scan(
                child_node
            )

            columns = []

            for column in base.columns:

                suffix = (
                    column.name
                    .split(
                        ".",
                        1,
                    )[1]
                )

                columns.append(
                    ColumnEstimate(
                        name=(
                            f"{alias}."
                            f"{suffix}"
                        ),
                        type_name=
                            column.type_name,
                        width=
                            column.width,
                    )
                )

            return PlanEstimate(
                plan={
                    "op":
                        "seqscan",
                    "table":
                        table_name,
                    "alias":
                        alias,
                },
                rows=
                    base.rows,
                pages=
                    base.pages,
                width=
                    base.width,
                columns=
                    columns,
                relations=
                    frozenset(
                        {
                            alias,
                        }
                    ),
                bindings={
                    alias:
                        table_name,
                },
                cost=
                    base.cost,
            )

                # ----------------------------------------------------
        # Renamed subquery.
        #
        # Unlike a base-table alias, this cannot be folded
        # directly into SeqScan because the child may contain
        # project/filter/group/join/etc.
        #
        # Use the zero-I/O physical Rename operator.
        # ----------------------------------------------------

        child = self._plan_node(
            child_node
        )

        columns = []

        for column in child.columns:

            original_name = (
                column.name
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

            columns.append(
                ColumnEstimate(
                    name=(
                        f"{alias}."
                        f"{suffix}"
                    ),
                    type_name=
                        column.type_name,
                    width=
                        column.width,
                )
            )

        return PlanEstimate(
            plan={
                "op":
                    "rename",
                "to":
                    alias,
                "child":
                    child.plan,
            },
            rows=
                child.rows,
            pages=
                child.pages,
            width=
                child.width,
            columns=
                columns,

            # To the outer query the entire derived table
            # is one scope identified by its alias.
            relations=
                frozenset(
                    {
                        alias,
                    }
                ),

            # A derived relation does not correspond to one
            # base table, so base-table NDV lookup is not
            # available. Join estimation therefore uses the
            # documented fallback when needed.
            bindings={
                alias:
                    None,
            },

            # Rename is pipelined and performs no own I/O.
            cost=
                child.cost,
        )

    # ========================================================
    # Column helpers
    # ========================================================

    def _find_column(
        self,
        estimate,
        name,
    ):
        matches = [
            column
            for column
            in estimate.columns
            if column.name == name
        ]

        if len(matches) == 1:
            return matches[0]

        # Allow an unqualified aggregate output such as:
        #
        # total
        #
        if "." not in name:

            matches = [
                column
                for column
                in estimate.columns
                if (
                    column.name
                    .split(
                        "."
                    )[-1]
                    == name
                )
            ]

            if len(matches) == 1:
                return matches[0]

        raise ValueError(
            f"Planner cannot resolve "
            f"column {name}."
        )

    # ========================================================
    # Condition helpers
    # ========================================================

    def _parse_condition(
        self,
        text,
    ):
        return parse_condition_text(
            text
        )

    def _attribute_parts(
        self,
        attr,
    ):
        name = attr_name(
            attr
        )

        if "." in name:

            relation, column = (
                name.split(
                    ".",
                    1,
                )
            )

            return (
                relation,
                column,
                name,
            )

        return (
            None,
            name,
            name,
        )

    def _literal_text(
        self,
        value,
    ):
        if isinstance(
            value,
            str,
        ):
            escaped = (
                value.replace(
                    "'",
                    "''",
                )
            )

            return (
                "'"
                + escaped
                + "'"
            )

        return str(
            value
        )

    def _condition_text(
        self,
        condition,
    ):
        if isinstance(
            condition,
            Attr,
        ):
            return attr_name(
                condition
            )

        if isinstance(
            condition,
            Literal,
        ):
            return self._literal_text(
                condition.value
            )

        if isinstance(
            condition,
            Comparison,
        ):
            return (
                self._condition_text(
                    condition.left
                )
                + " "
                + condition.op
                + " "
                + self._condition_text(
                    condition.right
                )
            )

        if isinstance(
            condition,
            Logical,
        ):
            return (
                "("
                + self._condition_text(
                    condition.left
                )
                + " "
                + condition.op.upper()
                + " "
                + self._condition_text(
                    condition.right
                )
                + ")"
            )

        if isinstance(
            condition,
            Not,
        ):
            child = getattr(
                condition,
                "condition",
                None,
            )

            if child is None:
                child = getattr(
                    condition,
                    "child",
                )

            return (
                "NOT ("
                + self._condition_text(
                    child
                )
                + ")"
            )

        raise ValueError(
            "Unsupported condition "
            f"node: {type(condition).__name__}"
        )

    def _condition_relations(
        self,
        condition,
    ):
        if isinstance(
            condition,
            Attr,
        ):
            relation, _, _ = (
                self._attribute_parts(
                    condition
                )
            )

            if relation is None:
                return set()

            return {
                relation,
            }

        if isinstance(
            condition,
            Literal,
        ):
            return set()

        if isinstance(
            condition,
            Comparison,
        ):
            return (
                self._condition_relations(
                    condition.left
                )
                |
                self._condition_relations(
                    condition.right
                )
            )

        if isinstance(
            condition,
            Logical,
        ):
            return (
                self._condition_relations(
                    condition.left
                )
                |
                self._condition_relations(
                    condition.right
                )
            )

        if isinstance(
            condition,
            Not,
        ):
            child = getattr(
                condition,
                "condition",
                None,
            )

            if child is None:
                child = getattr(
                    condition,
                    "child",
                )

            return (
                self._condition_relations(
                    child
                )
            )

        return set()

    def _split_and(
        self,
        condition,
    ):
        if (
            isinstance(
                condition,
                Logical,
            )
            and condition.op.lower()
            == "and"
        ):
            return (
                self._split_and(
                    condition.left
                )
                +
                self._split_and(
                    condition.right
                )
            )

        return [
            condition,
        ]

    # ========================================================
    # Statistics for one attribute
    # ========================================================

    def _column_statistics(
        self,
        estimate,
        attr,
    ):
        relation, column, _ = (
            self._attribute_parts(
                attr
            )
        )

        if relation is None:
            return (
                {},
                None,
            )

        table_name = (
            estimate.bindings.get(
                relation
            )
        )

        if table_name is None:
            return (
                {},
                None,
            )

        metadata = self._metadata(
            table_name
        )

        statistics = self._statistics(
            metadata
        )

        column_statistics = (
            statistics.get(
                "columns",
                {},
            ).get(
                column,
                {},
            )
        )

        try:
            column_info = (
                self._find_column(
                    estimate,
                    attr_name(
                        attr
                    ),
                )
            )

            type_name = (
                column_info.type_name
            )

        except ValueError:
            type_name = None

        return (
            column_statistics,
            type_name,
        )

    # ========================================================
    # Selection selectivity
    # ========================================================

    def _equality_selectivity(
        self,
        estimate,
        attr,
        value,
    ):
        column_stats, type_name = (
            self._column_statistics(
                estimate,
                attr,
            )
        )

        relation, _, _ = (
            self._attribute_parts(
                attr
            )
        )

        if relation is None:
            return (
                DEFAULT_EQUALITY_SELECTIVITY
            )

        table_name = (
            estimate.bindings.get(
                relation
            )
        )

        if table_name is None:
            return (
                DEFAULT_EQUALITY_SELECTIVITY
            )

        metadata = self._metadata(
            table_name
        )

        table_stats = (
            self._statistics(
                metadata
            )
        )

        n_tuples = max(
            1,
            int(
                table_stats.get(
                    "n_tuples",
                    estimate.rows,
                )
            ),
        )

        histogram = (
            column_stats.get(
                "hist",
                [],
            )
        )

        for bucket in histogram:

            low = bucket.get(
                "min"
            )

            high = bucket.get(
                "max"
            )

            if (
                low is None
                or high is None
            ):
                continue

            try:
                inside = (
                    low <= value <= high
                )

            except TypeError:
                inside = False

            if not inside:
                continue

            count = max(
                0,
                bucket.get(
                    "count",
                    0,
                ),
            )

            ndv = max(
                1,
                bucket.get(
                    "ndv",
                    1,
                ),
            )

            return max(
                0.0,
                min(
                    1.0,
                    count
                    /
                    (
                        n_tuples
                        * ndv
                    ),
                ),
            )

        ndv = column_stats.get(
            "ndv"
        )

        if (
            isinstance(
                ndv,
                int,
            )
            and ndv > 0
        ):
            return (
                1.0
                / ndv
            )

        return (
            DEFAULT_EQUALITY_SELECTIVITY
        )

    def _less_than_selectivity(
        self,
        estimate,
        attr,
        value,
    ):
        column_stats, type_name = (
            self._column_statistics(
                estimate,
                attr,
            )
        )

        relation, _, _ = (
            self._attribute_parts(
                attr
            )
        )

        if relation is None:
            return (
                DEFAULT_RANGE_SELECTIVITY
            )

        table_name = (
            estimate.bindings.get(
                relation
            )
        )

        if table_name is None:
            return (
                DEFAULT_RANGE_SELECTIVITY
            )

        metadata = self._metadata(
            table_name
        )

        table_stats = (
            self._statistics(
                metadata
            )
        )

        n_tuples = max(
            1,
            int(
                table_stats.get(
                    "n_tuples",
                    estimate.rows,
                )
            ),
        )

        histogram = (
            column_stats.get(
                "hist",
                [],
            )
        )

        if histogram:

            selected = 0.0

            for bucket in histogram:

                low = bucket.get(
                    "min"
                )

                high = bucket.get(
                    "max"
                )

                count = float(
                    bucket.get(
                        "count",
                        0,
                    )
                )

                if (
                    low is None
                    or high is None
                ):
                    continue

                try:

                    if value <= low:
                        fraction = 0.0

                    elif value > high:
                        fraction = 1.0

                    else:
                        fraction = (
                            _linear_fraction(
                                low,
                                high,
                                value,
                                type_name,
                            )
                        )

                except (
                    TypeError,
                    ValueError,
                ):
                    fraction = 0.0

                selected += (
                    count
                    * max(
                        0.0,
                        min(
                            1.0,
                            fraction,
                        ),
                    )
                )

            return max(
                0.0,
                min(
                    1.0,
                    selected
                    / n_tuples,
                ),
            )

        low = column_stats.get(
            "min"
        )

        high = column_stats.get(
            "max"
        )

        if (
            low is not None
            and high is not None
        ):
            try:
                return max(
                    0.0,
                    min(
                        1.0,
                        _linear_fraction(
                            low,
                            high,
                            value,
                            type_name,
                        ),
                    ),
                )

            except (
                TypeError,
                ValueError,
            ):
                pass

        return (
            DEFAULT_RANGE_SELECTIVITY
        )

    def _comparison_selectivity(
        self,
        estimate,
        condition,
    ):
        left = condition.left
        right = condition.right
        op = condition.op

        # Attribute compared with literal.
        if (
            isinstance(
                left,
                Attr,
            )
            and
            isinstance(
                right,
                Literal,
            )
        ):
            attr = left
            value = right.value

        elif (
            isinstance(
                right,
                Attr,
            )
            and
            isinstance(
                left,
                Literal,
            )
        ):
            attr = right
            value = left.value

            reverse = {
                "<": ">",
                "<=": ">=",
                ">": "<",
                ">=": "<=",
                "=": "=",
                "!=": "!=",
                "<>": "<>",
            }

            op = reverse.get(
                op,
                op,
            )

        else:
            # Attribute-attribute comparisons inside FILTER
            # are uncommon after rewrite. Use a conservative
            # default.
            if op == "=":
                return (
                    DEFAULT_EQUALITY_SELECTIVITY
                )

            if op in (
                "!=",
                "<>",
            ):
                return (
                    1.0
                    -
                    DEFAULT_EQUALITY_SELECTIVITY
                )

            return (
                DEFAULT_RANGE_SELECTIVITY
            )

        if op == "=":

            return (
                self._equality_selectivity(
                    estimate,
                    attr,
                    value,
                )
            )

        if op in (
            "!=",
            "<>",
        ):
            return (
                1.0
                -
                self._equality_selectivity(
                    estimate,
                    attr,
                    value,
                )
            )

        if op in (
            "<",
            "<=",
        ):
            return (
                self._less_than_selectivity(
                    estimate,
                    attr,
                    value,
                )
            )

        if op in (
            ">",
            ">=",
        ):
            return (
                1.0
                -
                self._less_than_selectivity(
                    estimate,
                    attr,
                    value,
                )
            )

        return (
            DEFAULT_EQUALITY_SELECTIVITY
        )

    def _filter_selectivity(
        self,
        estimate,
        condition,
    ):
        if isinstance(
            condition,
            Comparison,
        ):
            result = (
                self._comparison_selectivity(
                    estimate,
                    condition,
                )
            )

        elif isinstance(
            condition,
            Logical,
        ):
            left = (
                self._filter_selectivity(
                    estimate,
                    condition.left,
                )
            )

            right = (
                self._filter_selectivity(
                    estimate,
                    condition.right,
                )
            )

            if (
                condition.op.lower()
                == "and"
            ):
                result = (
                    left
                    * right
                )

            else:
                result = (
                    left
                    + right
                    -
                    left
                    * right
                )

        elif isinstance(
            condition,
            Not,
        ):
            child = getattr(
                condition,
                "condition",
                None,
            )

            if child is None:
                child = getattr(
                    condition,
                    "child",
                )

            result = (
                1.0
                -
                self._filter_selectivity(
                    estimate,
                    child,
                )
            )

        else:
            result = (
                DEFAULT_EQUALITY_SELECTIVITY
            )

        return max(
            0.0,
            min(
                1.0,
                result,
            ),
        )

    # ========================================================
    # SELECT / FILTER
    # ========================================================

    def _plan_select(
        self,
        node,
    ):
        child = self._plan_node(
            node[
                "child"
            ]
        )

        condition_text = node[
            "condition"
        ]

        condition = (
            self._parse_condition(
                condition_text
            )
        )

        selectivity = (
            self._filter_selectivity(
                child,
                condition,
            )
        )

        rows = estimate_rows(
            child.rows,
            selectivity,
        )

        pages = estimate_pages(
            rows,
            child.width,
        )

        return PlanEstimate(
            plan={
                "op":
                    "filter",
                "condition":
                    condition_text,
                "child":
                    child.plan,
            },
            rows=
                rows,
            pages=
                pages,
            width=
                child.width,
            columns=
                list(
                    child.columns
                ),
            relations=
                child.relations,
            bindings=
                dict(
                    child.bindings
                ),
            cost=
                child.cost,
        )

    # ========================================================
    # PROJECT
    # ========================================================

    def _plan_project(
        self,
        node,
    ):
        child = self._plan_node(
            node[
                "child"
            ]
        )

        requested = list(
            node[
                "columns"
            ]
        )

        columns = [
            self._find_column(
                child,
                name,
            )
            for name in requested
        ]

        width = sum(
            column.width
            for column in columns
        )

        pages = estimate_pages(
            child.rows,
            width,
        )

        return PlanEstimate(
            plan={
                "op":
                    "project",
                "columns":
                    requested,
                "child":
                    child.plan,
            },
            rows=
                child.rows,
            pages=
                pages,
            width=
                width,
            columns=
                columns,
            relations=
                child.relations,
            bindings=
                dict(
                    child.bindings
                ),
            cost=
                child.cost,
        )

    # ========================================================
    # GROUP BY
    # ========================================================

    def _default_aggregate_name(
        self,
        function,
        argument,
    ):
        if argument == "*":
            suffix = "star"
        else:
            suffix = argument.replace(
                ".",
                "_",
            )

        return (
            f"{function}_{suffix}"
        )

    def _aggregate_column(
        self,
        child,
        aggregate,
    ):
        function = (
            aggregate[0].lower()
        )

        argument = aggregate[1]

        if len(
            aggregate
        ) == 3:
            output_name = (
                aggregate[2]
            )
        else:
            output_name = (
                self._default_aggregate_name(
                    function,
                    argument,
                )
            )

        if function in (
            "count",
            "sum",
        ):
            type_name = "INT"
            width = 4.0

        elif function == "avg":
            type_name = "REAL"
            width = 8.0

        else:
            source = self._find_column(
                child,
                argument,
            )

            type_name = (
                source.type_name
            )

            width = (
                source.width
            )

        return ColumnEstimate(
            name=
                output_name,
            type_name=
                type_name,
            width=
                width,
        )

    def _estimate_groups(
        self,
        child,
        keys,
    ):
        if not keys:
            return 1

        estimate = 1

        for key in keys:

            relation = None
            column = key

            if "." in key:
                relation, column = (
                    key.split(
                        ".",
                        1,
                    )
                )

            ndv = None

            if relation is not None:

                table_name = (
                    child.bindings.get(
                        relation
                    )
                )

                if table_name is not None:

                    metadata = self._metadata(
                        table_name
                    )

                    statistics = (
                        self._statistics(
                            metadata
                        )
                    )

                    ndv = (
                        statistics
                        .get(
                            "columns",
                            {},
                        )
                        .get(
                            column,
                            {},
                        )
                        .get(
                            "ndv"
                        )
                    )

            if (
                not isinstance(
                    ndv,
                    int,
                )
                or ndv < 1
            ):
                ndv = max(
                    1,
                    int(
                        math.sqrt(
                            max(
                                1,
                                child.rows,
                            )
                        )
                    ),
                )

            estimate *= ndv

            if estimate >= child.rows:
                return max(
                    1,
                    child.rows,
                )

        return max(
            1,
            min(
                child.rows,
                estimate,
            ),
        )

    def _plan_group_by(
        self,
        node,
    ):
        child = self._plan_node(
            node[
                "child"
            ]
        )

        sort_group_cost = (
            group_by_cost(
                child.pages,
                self.frames,
                "sort",
            )
        )

        hash_group_cost = (
            group_by_cost(
                child.pages,
                self.frames,
                "hash",
            )
        )

        if hash_group_cost < sort_group_cost:
            mode = "hash"
            own_cost = (
                hash_group_cost
            )
        else:
            mode = "sort"
            own_cost = (
                sort_group_cost
            )

        keys = list(
            node.get(
                "keys",
                [],
            )
        )

        aggregates = [
            list(
                aggregate
            )
            for aggregate
            in node.get(
                "aggregates",
                [],
            )
        ]

        key_columns = [
            self._find_column(
                child,
                key,
            )
            for key in keys
        ]

        aggregate_columns = [
            self._aggregate_column(
                child,
                aggregate,
            )
            for aggregate
            in aggregates
        ]

        columns = (
            key_columns
            +
            aggregate_columns
        )

        rows = (
            self._estimate_groups(
                child,
                keys,
            )
        )

        width = sum(
            column.width
            for column
            in columns
        )

        pages = estimate_pages(
            rows,
            width,
        )

        return PlanEstimate(
            plan={
                "op":
                    "group_by",
                "mode":
                    mode,
                "keys":
                    keys,
                "aggregates":
                    aggregates,
                "child":
                    child.plan,
            },
            rows=
                rows,
            pages=
                pages,
            width=
                width,
            columns=
                columns,
            relations=
                child.relations,
            bindings=
                dict(
                    child.bindings
                ),
            cost=(
                child.cost
                +
                own_cost
            ),
        )

    # ========================================================
    # DISTINCT
    # ========================================================

    def _plan_distinct(
        self,
        node,
    ):
        child = self._plan_node(
            node[
                "child"
            ]
        )

        sort_distinct = (
            distinct_cost(
                child.pages,
                self.frames,
                "sort",
            )
        )

        hash_distinct = (
            distinct_cost(
                child.pages,
                self.frames,
                "hash",
            )
        )

        if hash_distinct < sort_distinct:
            mode = "hash"
            own_cost = hash_distinct
        else:
            mode = "sort"
            own_cost = sort_distinct

        if child.rows <= 1:
            rows = child.rows
        else:
            rows = max(
                1,
                math.ceil(
                    child.rows
                    * 0.5
                ),
            )

        pages = estimate_pages(
            rows,
            child.width,
        )

        return PlanEstimate(
            plan={
                "op":
                    "distinct",
                "mode":
                    mode,
                "child":
                    child.plan,
            },
            rows=
                rows,
            pages=
                pages,
            width=
                child.width,
            columns=
                list(
                    child.columns
                ),
            relations=
                child.relations,
            bindings=
                dict(
                    child.bindings
                ),
            cost=(
                child.cost
                +
                own_cost
            ),
        )

    # ========================================================
    # SORT
    # ========================================================

    def _plan_sort(
        self,
        node,
    ):
        child = self._plan_node(
            node[
                "child"
            ]
        )

        own_cost = sort_cost(
            child.pages,
            self.frames,
        )

        return PlanEstimate(
            plan={
                "op":
                    "sort",
                "keys":
                    copy.deepcopy(
                        node[
                            "keys"
                        ]
                    ),
                "child":
                    child.plan,
            },
            rows=
                child.rows,
            pages=
                child.pages,
            width=
                child.width,
            columns=
                list(
                    child.columns
                ),
            relations=
                child.relations,
            bindings=
                dict(
                    child.bindings
                ),
            cost=(
                child.cost
                +
                own_cost
            ),
        )

    # ========================================================
    # LIMIT
    # ========================================================

    def _plan_limit(
        self,
        node,
    ):
        child = self._plan_node(
            node[
                "child"
            ]
        )

        n = int(
            node[
                "n"
            ]
        )

        rows = min(
            child.rows,
            n,
        )

        pages = estimate_pages(
            rows,
            child.width,
        )

        return PlanEstimate(
            plan={
                "op":
                    "limit",
                "n":
                    n,
                "child":
                    child.plan,
            },
            rows=
                rows,
            pages=
                pages,
            width=
                child.width,
            columns=
                list(
                    child.columns
                ),
            relations=
                child.relations,
            bindings=
                dict(
                    child.bindings
                ),
            cost=
                child.cost,
        )

    # ========================================================
    # Join selectivity
    # ========================================================

    def _attribute_ndv(
        self,
        bindings,
        attr,
    ):
        relation, column, _ = (
            self._attribute_parts(
                attr
            )
        )

        if relation is None:
            return None

        table_name = (
            bindings.get(
                relation
            )
        )

        if table_name is None:
            return None

        metadata = self._metadata(
            table_name
        )

        statistics = self._statistics(
            metadata
        )

        ndv = (
            statistics
            .get(
                "columns",
                {},
            )
            .get(
                column,
                {},
            )
            .get(
                "ndv"
            )
        )

        if (
            isinstance(
                ndv,
                int,
            )
            and ndv > 0
        ):
            return ndv

        return None

    def _join_selectivity(
        self,
        condition,
        bindings,
    ):
        if isinstance(
            condition,
            Logical,
        ):
            left = (
                self._join_selectivity(
                    condition.left,
                    bindings,
                )
            )

            right = (
                self._join_selectivity(
                    condition.right,
                    bindings,
                )
            )

            if (
                condition.op.lower()
                == "and"
            ):
                return (
                    left
                    * right
                )

            return (
                left
                + right
                -
                left
                * right
            )

        if isinstance(
            condition,
            Not,
        ):
            child = getattr(
                condition,
                "condition",
                None,
            )

            if child is None:
                child = getattr(
                    condition,
                    "child",
                )

            return (
                1.0
                -
                self._join_selectivity(
                    child,
                    bindings,
                )
            )

        if not isinstance(
            condition,
            Comparison,
        ):
            return (
                DEFAULT_JOIN_SELECTIVITY
            )

        if (
            condition.op == "="
            and
            isinstance(
                condition.left,
                Attr,
            )
            and
            isinstance(
                condition.right,
                Attr,
            )
        ):
            left_ndv = (
                self._attribute_ndv(
                    bindings,
                    condition.left,
                )
            )

            right_ndv = (
                self._attribute_ndv(
                    bindings,
                    condition.right,
                )
            )

            if (
                left_ndv is not None
                and right_ndv is not None
            ):
                return (
                    1.0
                    /
                    max(
                        left_ndv,
                        right_ndv,
                    )
                )

        return (
            DEFAULT_JOIN_SELECTIVITY
        )

    def _simple_equality_join(
        self,
        condition,
    ):
        return (
            isinstance(
                condition,
                Comparison,
            )
            and
            condition.op == "="
            and
            isinstance(
                condition.left,
                Attr,
            )
            and
            isinstance(
                condition.right,
                Attr,
            )
            and
            len(
                self._condition_relations(
                    condition
                )
            )
            == 2
        )

    # ========================================================
    # DP join component
    # ========================================================

    def _collect_join_component(
        self,
        node,
        leaves,
        predicates,
    ):
        if node.get(
            "op"
        ) != "join":

            leaves.append(
                self._plan_node(
                    node
                )
            )

            return

        self._collect_join_component(
            node[
                "left"
            ],
            leaves,
            predicates,
        )

        self._collect_join_component(
            node[
                "right"
            ],
            leaves,
            predicates,
        )

        parsed = (
            self._parse_condition(
                node[
                    "condition"
                ]
            )
        )

        predicates.extend(
            self._split_and(
                parsed
            )
        )

    def _dp_columns(
        self,
        plan,
        leaf_lookup,
    ):
        if (
            plan.get(
                "op"
            )
            == "seqscan"
        ):
            return list(
                leaf_lookup[
                    plan[
                        "table"
                    ]
                ].columns
            )

        if plan.get(
            "op"
        ) in (
            "nested_loop_join",
            "sort_merge_join",
            "hash_join",
        ):
            return (
                self._dp_columns(
                    plan[
                        "left"
                    ],
                    leaf_lookup,
                )
                +
                self._dp_columns(
                    plan[
                        "right"
                    ],
                    leaf_lookup,
                )
            )

        return []

    def _hydrate_dp_plan(
        self,
        plan,
        leaf_lookup,
    ):
        if (
            plan.get(
                "op"
            )
            == "seqscan"
        ):
            name = plan[
                "table"
            ]

            return copy.deepcopy(
                leaf_lookup[
                    name
                ].plan
            )

        result = copy.deepcopy(
            plan
        )

        if "left" in result:
            result["left"] = (
                self._hydrate_dp_plan(
                    result[
                        "left"
                    ],
                    leaf_lookup,
                )
            )

        if "right" in result:
            result["right"] = (
                self._hydrate_dp_plan(
                    result[
                        "right"
                    ],
                    leaf_lookup,
                )
            )

        return result

    def _plan_join_component(
        self,
        node,
    ):
        leaves = []
        predicate_nodes = []

        self._collect_join_component(
            node,
            leaves,
            predicate_nodes,
        )

        # Every DP leaf must represent exactly one visible
        # relation.
        if any(
            len(
                leaf.relations
            )
            != 1
            for leaf in leaves
        ):
            return (
                self._plan_binary_join(
                    node
                )
            )

        leaf_lookup = {}

        relations = []

        bindings = {}

        for leaf in leaves:

            relation_name = next(
                iter(
                    leaf.relations
                )
            )

            if relation_name in leaf_lookup:
                return (
                    self._plan_binary_join(
                        node
                    )
                )

            leaf_lookup[
                relation_name
            ] = leaf

            relations.append(
                RelationInfo(
                    name=
                        relation_name,
                    pages=
                        leaf.pages,
                    rows=
                        leaf.rows,
                    width=
                        leaf.width,
                )
            )

            bindings.update(
                leaf.bindings
            )

        join_predicates = []

        for predicate_node in (
            predicate_nodes
        ):
            referenced = (
                self._condition_relations(
                    predicate_node
                )
            )

            if len(
                referenced
            ) != 2:
                return (
                    self._plan_binary_join(
                        node
                    )
                )

            left_name, right_name = (
                sorted(
                    referenced
                )
            )

            join_predicates.append(
                JoinPredicateInfo(
                    left=
                        left_name,
                    right=
                        right_name,
                    condition=
                        self._condition_text(
                            predicate_node
                        ),
                    equality=
                        self._simple_equality_join(
                            predicate_node
                        ),
                    selectivity=
                        self._join_selectivity(
                            predicate_node,
                            bindings,
                        ),
                )
            )

        if not join_predicates:
            return (
                self._plan_binary_join(
                    node
                )
            )

        dp = enumerate_left_deep(
            relations,
            join_predicates,
            self.frames,
        )

        all_relations = frozenset(
            leaf_lookup.keys()
        )

        if all_relations not in dp.best:
            return (
                self._plan_binary_join(
                    node
                )
            )

        winner = dp.best[
            all_relations
        ]

        columns = self._dp_columns(
            winner.plan,
            leaf_lookup,
        )

        hydrated = (
            self._hydrate_dp_plan(
                winner.plan,
                leaf_lookup,
            )
        )

        leaf_extra_cost = sum(
            max(
                0,
                leaf.cost
                - leaf.pages,
            )
            for leaf in leaves
        )

        return PlanEstimate(
            plan=
                hydrated,
            rows=
                winner.rows,
            pages=
                winner.pages,
            width=
                winner.width,
            columns=
                columns,
            relations=
                all_relations,
            bindings=
                bindings,
            cost=(
                winner.cost
                +
                leaf_extra_cost
            ),
        )

    # ========================================================
    # Binary join fallback
    # ========================================================

    def _plan_binary_join(
        self,
        node,
    ):
        left = self._plan_node(
            node[
                "left"
            ]
        )

        right = self._plan_node(
            node[
                "right"
            ]
        )

        condition_text = node[
            "condition"
        ]

        condition = (
            self._parse_condition(
                condition_text
            )
        )

        bindings = {
            **left.bindings,
            **right.bindings,
        }

        equality = (
            self._simple_equality_join(
                condition
            )
        )

        algorithms = (
            join_algorithm_costs(
                left.pages,
                right.pages,
                self.frames,
                equality=
                    equality,
            )
        )

        algorithm, own_cost = min(
            algorithms.items(),
            key=lambda item: (
                item[1],
                item[0],
            ),
        )

        selectivity = (
            self._join_selectivity(
                condition,
                bindings,
            )
        )

        rows = estimate_join_rows(
            left.rows,
            right.rows,
            selectivity,
        )

        width = (
            left.width
            +
            right.width
        )

        pages = estimate_pages(
            rows,
            width,
        )

        return PlanEstimate(
            plan={
                "op":
                    algorithm,
                "condition":
                    condition_text,
                "left":
                    left.plan,
                "right":
                    right.plan,
            },
            rows=
                rows,
            pages=
                pages,
            width=
                width,
            columns=(
                list(
                    left.columns
                )
                +
                list(
                    right.columns
                )
            ),
            relations=(
                left.relations
                |
                right.relations
            ),
            bindings=
                bindings,
            cost=(
                left.cost
                +
                right.cost
                +
                own_cost
            ),
        )

    # ========================================================
    # CROSS
    # ========================================================

    def _plan_cross(
        self,
        node,
    ):
        left = self._plan_node(
            node[
                "left"
            ]
        )

        right = self._plan_node(
            node[
                "right"
            ]
        )

        if not left.columns:
            raise ValueError(
                "Cross product requires "
                "a left-side column."
            )

        # Module 2 does not define a separate physical cross
        # operator. A block nested loop with the tautology
        #
        #     left_column = left_column
        #
        # produces the Cartesian product.
        column_name = (
            left.columns[
                0
            ].name
        )

        condition = (
            f"{column_name} = "
            f"{column_name}"
        )

        rows = (
            left.rows
            * right.rows
        )

        width = (
            left.width
            +
            right.width
        )

        pages = estimate_pages(
            rows,
            width,
        )

        own_cost = (
            nested_loop_join_cost(
                left.pages,
                right.pages,
                self.frames,
            )
        )

        return PlanEstimate(
            plan={
                "op":
                    "nested_loop_join",
                "condition":
                    condition,
                "left":
                    left.plan,
                "right":
                    right.plan,
            },
            rows=
                rows,
            pages=
                pages,
            width=
                width,
            columns=(
                list(
                    left.columns
                )
                +
                list(
                    right.columns
                )
            ),
            relations=(
                left.relations
                |
                right.relations
            ),
            bindings={
                **left.bindings,
                **right.bindings,
            },
            cost=(
                left.cost
                +
                right.cost
                +
                own_cost
            ),
        )

    # ========================================================
    # Set operators
    # ========================================================

    def _plan_set_operator(
        self,
        node,
    ):
        left = self._plan_node(
            node[
                "left"
            ]
        )

        right = self._plan_node(
            node[
                "right"
            ]
        )

        op = node[
            "op"
        ]

        if op == "union_all":
            rows = (
                left.rows
                +
                right.rows
            )

        elif op == "intersect":
            rows = min(
                left.rows,
                right.rows,
            )

        elif op == "except":
            rows = left.rows

        else:
            rows = max(
                left.rows,
                right.rows,
            )

        width = left.width

        pages = estimate_pages(
            rows,
            width,
        )

        return PlanEstimate(
            plan={
                "op":
                    op,
                "left":
                    left.plan,
                "right":
                    right.plan,
            },
            rows=
                rows,
            pages=
                pages,
            width=
                width,
            columns=
                list(
                    left.columns
                ),
            relations=(
                left.relations
                |
                right.relations
            ),
            bindings={
                **left.bindings,
                **right.bindings,
            },
            cost=(
                left.cost
                +
                right.cost
            ),
        )


def plan_logical(
    db_dir,
    logical_plan,
    frames=32,
    disabled_rules=None,
):
    """
    Convenience function used by CLI/tests.
    """

    planner = PhysicalPlanner(
        db_dir,
        frames=frames,
    )

    return planner.plan(
        logical_plan,
        disabled_rules=
            disabled_rules,
    )