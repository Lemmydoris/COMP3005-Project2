import math

from execution.conditions import (
    attr_name,
    compare_values,
    literal_type,
    prepare_condition,
    resolve_column_name,
)

from ra_tree import (
    Attr,
    Comparison,
    Literal,
    Logical,
    Not,
)


DEFAULT_JOIN_SELECTIVITY = 0.1
PAGE_SIZE = 4096


def _clamp(value):
    return max(
        0.0,
        min(
            1.0,
            float(value),
        ),
    )


def _statistics_payload(value):
    """
    Accept either:

        table_entry["statistics"]

    or a complete catalog table entry.
    """

    if (
        isinstance(value, dict)
        and "statistics" in value
        and "columns" not in value
    ):
        return value["statistics"]

    return value


def _compare(left, right, type_name):
    """
    Return -1, 0, or 1 using the same ordering rules
    as Module 2.
    """

    if compare_values(
        left,
        right,
        type_name,
        "<",
    ):
        return -1

    if compare_values(
        left,
        right,
        type_name,
        ">",
    ):
        return 1

    return 0


def _string_position(value, width):
    """
    Convert UTF-8 bytes into an order-preserving integer.

    This is our documented interpolation assumption for
    VARCHAR histogram ranges.

    Module 2 compares VARCHAR values byte-wise, so this keeps
    Module 4 interpolation consistent with that ordering.
    """

    raw = value.encode(
        "utf-8"
    )

    padded = raw.ljust(
        width,
        b"\x00",
    )

    return int.from_bytes(
        padded,
        byteorder="big",
        signed=False,
    )


def _linear_fraction(
    low,
    high,
    value,
    type_name,
):
    """
    Fraction of [low, high] lying below value.

    Result is always between 0 and 1.
    """

    if _compare(
        value,
        low,
        type_name,
    ) <= 0:
        return 0.0

    if _compare(
        value,
        high,
        type_name,
    ) >= 0:
        return 1.0

    if type_name == "INT":

        denominator = (
            high - low
        )

        if denominator == 0:
            return 0.0

        return _clamp(
            (
                value - low
            )
            / denominator
        )

    if type_name == "VARCHAR":

        width = max(
            len(
                low.encode(
                    "utf-8"
                )
            ),
            len(
                high.encode(
                    "utf-8"
                )
            ),
            len(
                value.encode(
                    "utf-8"
                )
            ),
        )

        low_number = (
            _string_position(
                low,
                width,
            )
        )

        high_number = (
            _string_position(
                high,
                width,
            )
        )

        value_number = (
            _string_position(
                value,
                width,
            )
        )

        denominator = (
            high_number
            - low_number
        )

        if denominator == 0:
            return 0.0

        return _clamp(
            (
                value_number
                - low_number
            )
            / denominator
        )

    raise ValueError(
        "Unsupported histogram "
        f"type: {type_name}"
    )


class SelectivityEstimator:
    """
    Module 4 selectivity estimator.

    statistics_by_relation maps the qualifier appearing in
    the condition to statistics.

    Example:

        {
            "R": R_statistics,
            "S": S_statistics,
        }

    For aliases:

        {
            "e": Emp_statistics,
            "m": Emp_statistics,
        }

    so self joins work naturally.
    """

    def __init__(
        self,
        schema,
        statistics_by_relation,
    ):

        self.schema = [
            list(column)
            for column in schema
        ]

        self.statistics = {
            relation:
                _statistics_payload(
                    statistics
                )
            for (
                relation,
                statistics,
            )
            in (
                statistics_by_relation
                .items()
            )
        }

    # ========================================================
    # Column lookup
    # ========================================================

    def _attribute_info(
        self,
        attribute,
    ):

        requested = attr_name(
            attribute
        )

        qualified = (
            resolve_column_name(
                self.schema,
                requested,
            )
        )

        if "." not in qualified:

            raise ValueError(
                "Optimizer requires "
                "qualified columns."
            )

        relation, column = (
            qualified.split(
                ".",
                1,
            )
        )

        if relation not in self.statistics:

            raise ValueError(
                "No statistics for "
                f"relation: {relation}"
            )

        table_statistics = (
            self.statistics[
                relation
            ]
        )

        try:

            column_statistics = (
                table_statistics[
                    "columns"
                ][
                    column
                ]
            )

        except KeyError as exc:

            raise ValueError(
                "No statistics for "
                f"column: {qualified}"
            ) from exc

        type_name = None

        for schema_column in (
            self.schema
        ):

            if (
                schema_column[0]
                == qualified
            ):

                type_name = (
                    schema_column[1]
                )

                break

        if type_name is None:

            raise ValueError(
                f"Unknown column: "
                f"{qualified}"
            )

        return (
            relation,
            column,
            type_name,
            table_statistics,
            column_statistics,
        )

    # ========================================================
    # Equality
    # ========================================================

    def _equality_selectivity(
        self,
        attribute,
        value,
    ):

        (
            _relation,
            _column,
            type_name,
            table_statistics,
            column_statistics,
        ) = self._attribute_info(
            attribute
        )

        n_tuples = (
            table_statistics.get(
                "n_tuples",
                0,
            )
        )

        if n_tuples <= 0:
            return 0.0

        histogram = (
            column_statistics.get(
                "hist",
                [],
            )
        )

        # Required Module 4 histogram formula.
        if histogram:

            for bucket in histogram:

                low = bucket[
                    "min"
                ]

                high = bucket[
                    "max"
                ]

                if (
                    _compare(
                        value,
                        low,
                        type_name,
                    )
                    >= 0
                    and
                    _compare(
                        value,
                        high,
                        type_name,
                    )
                    <= 0
                ):

                    bucket_ndv = (
                        bucket[
                            "ndv"
                        ]
                    )

                    if bucket_ndv <= 0:
                        return 0.0

                    return _clamp(
                        bucket[
                            "count"
                        ]
                        /
                        (
                            n_tuples
                            * bucket_ndv
                        )
                    )

            # Value lies outside all bucket ranges.
            return 0.0

        # Required no-histogram fallback.
        ndv = column_statistics.get(
            "ndv",
            0,
        )

        if ndv <= 0:
            return 0.0

        return _clamp(
            1.0 / ndv
        )

    # ========================================================
    # Range predicates
    # ========================================================

    def _less_than_selectivity(
        self,
        attribute,
        value,
    ):

        (
            _relation,
            _column,
            type_name,
            table_statistics,
            column_statistics,
        ) = self._attribute_info(
            attribute
        )

        n_tuples = (
            table_statistics.get(
                "n_tuples",
                0,
            )
        )

        if n_tuples <= 0:
            return 0.0

        histogram = (
            column_statistics.get(
                "hist",
                [],
            )
        )

        if histogram:

            estimated_rows = 0.0

            for bucket in histogram:

                low = bucket[
                    "min"
                ]

                high = bucket[
                    "max"
                ]

                count = bucket[
                    "count"
                ]

                # Whole bucket lies below v.
                if (
                    _compare(
                        high,
                        value,
                        type_name,
                    )
                    < 0
                ):

                    estimated_rows += (
                        count
                    )

                    continue

                # Whole bucket is on or above v.
                if (
                    _compare(
                        value,
                        low,
                        type_name,
                    )
                    <= 0
                ):

                    continue

                # v lies inside this bucket.
                fraction = (
                    _linear_fraction(
                        low,
                        high,
                        value,
                        type_name,
                    )
                )

                estimated_rows += (
                    count
                    * fraction
                )

            return _clamp(
                estimated_rows
                / n_tuples
            )

        # ANALYZE normally creates a histogram.
        # If one is unavailable, use the recorded global
        # min/max with the same uniformity assumption.
        low = column_statistics.get(
            "min"
        )

        high = column_statistics.get(
            "max"
        )

        if (
            low is None
            or high is None
        ):
            return 0.0

        return _linear_fraction(
            low,
            high,
            value,
            type_name,
        )

    def _greater_than_selectivity(
        self,
        attribute,
        value,
    ):

        (
            _relation,
            _column,
            type_name,
            table_statistics,
            column_statistics,
        ) = self._attribute_info(
            attribute
        )

        n_tuples = (
            table_statistics.get(
                "n_tuples",
                0,
            )
        )

        if n_tuples <= 0:
            return 0.0

        histogram = (
            column_statistics.get(
                "hist",
                [],
            )
        )

        if histogram:

            estimated_rows = 0.0

            for bucket in histogram:

                low = bucket[
                    "min"
                ]

                high = bucket[
                    "max"
                ]

                count = bucket[
                    "count"
                ]

                # Whole bucket is greater than v.
                if (
                    _compare(
                        value,
                        low,
                        type_name,
                    )
                    < 0
                ):

                    estimated_rows += (
                        count
                    )

                    continue

                # Whole bucket is on or below v.
                if (
                    _compare(
                        value,
                        high,
                        type_name,
                    )
                    >= 0
                ):

                    continue

                fraction_below = (
                    _linear_fraction(
                        low,
                        high,
                        value,
                        type_name,
                    )
                )

                estimated_rows += (
                    count
                    * (
                        1.0
                        - fraction_below
                    )
                )

            return _clamp(
                estimated_rows
                / n_tuples
            )

        low = column_statistics.get(
            "min"
        )

        high = column_statistics.get(
            "max"
        )

        if (
            low is None
            or high is None
        ):
            return 0.0

        return _clamp(
            1.0
            - _linear_fraction(
                low,
                high,
                value,
                type_name,
            )
        )

    # ========================================================
    # Attribute / literal comparisons
    # ========================================================

    def _attribute_literal(
        self,
        attribute,
        literal,
        op,
    ):

        value = literal.value

        if op == "=":

            return (
                self
                ._equality_selectivity(
                    attribute,
                    value,
                )
            )

        if op in {
            "!=",
            "<>",
        }:

            return _clamp(
                1.0
                -
                self
                ._equality_selectivity(
                    attribute,
                    value,
                )
            )

        if op == "<":

            return (
                self
                ._less_than_selectivity(
                    attribute,
                    value,
                )
            )

        if op == ">":

            return (
                self
                ._greater_than_selectivity(
                    attribute,
                    value,
                )
            )

        if op == "<=":

            return _clamp(
                1.0
                -
                self
                ._greater_than_selectivity(
                    attribute,
                    value,
                )
            )

        if op == ">=":

            return _clamp(
                1.0
                -
                self
                ._less_than_selectivity(
                    attribute,
                    value,
                )
            )

        raise ValueError(
            "Unknown comparison "
            f"operator: {op}"
        )

    # ========================================================
    # Join comparison
    # ========================================================

    def _attribute_attribute(
        self,
        left,
        right,
        op,
    ):

        (
            left_relation,
            _left_column,
            _left_type,
            _left_table,
            left_statistics,
        ) = self._attribute_info(
            left
        )

        (
            right_relation,
            _right_column,
            _right_type,
            _right_table,
            right_statistics,
        ) = self._attribute_info(
            right
        )

        # Required equality-join formula.
        if (
            op == "="
            and left_relation
            != right_relation
        ):

            left_ndv = (
                left_statistics.get(
                    "ndv",
                    0,
                )
            )

            right_ndv = (
                right_statistics.get(
                    "ndv",
                    0,
                )
            )

            denominator = max(
                left_ndv,
                right_ndv,
            )

            if denominator <= 0:
                return 0.0

            return _clamp(
                1.0
                / denominator
            )

        # Required fallback for any other join predicate.
        return (
            DEFAULT_JOIN_SELECTIVITY
        )

    # ========================================================
    # Literal / literal
    # ========================================================

    def _literal_literal(
        self,
        left,
        right,
        op,
    ):

        left_type = literal_type(
            left
        )

        right_type = literal_type(
            right
        )

        if left_type != right_type:

            raise TypeError(
                f"Cannot compare "
                f"{left_type} with "
                f"{right_type}"
            )

        normalized_op = (
            "!="
            if op == "<>"
            else op
        )

        result = compare_values(
            left.value,
            right.value,
            left_type,
            normalized_op,
        )

        if result:
            return 1.0

        return 0.0

    # ========================================================
    # Comparison dispatch
    # ========================================================

    def _comparison(
        self,
        node,
    ):

        left = node.left
        right = node.right
        op = node.op

        # column OP literal
        if (
            isinstance(
                left,
                Attr,
            )
            and isinstance(
                right,
                Literal,
            )
        ):

            return (
                self
                ._attribute_literal(
                    left,
                    right,
                    op,
                )
            )

        # literal OP column
        if (
            isinstance(
                left,
                Literal,
            )
            and isinstance(
                right,
                Attr,
            )
        ):

            flipped = {
                "=": "=",
                "!=": "!=",
                "<>": "<>",
                "<": ">",
                ">": "<",
                "<=": ">=",
                ">=": "<=",
            }

            return (
                self
                ._attribute_literal(
                    right,
                    left,
                    flipped[op],
                )
            )

        # column OP column
        if (
            isinstance(
                left,
                Attr,
            )
            and isinstance(
                right,
                Attr,
            )
        ):

            return (
                self
                ._attribute_attribute(
                    left,
                    right,
                    op,
                )
            )

        # literal OP literal
        if (
            isinstance(
                left,
                Literal,
            )
            and isinstance(
                right,
                Literal,
            )
        ):

            return (
                self
                ._literal_literal(
                    left,
                    right,
                    op,
                )
            )

        raise ValueError(
            "Unsupported comparison."
        )

    # ========================================================
    # Recursive estimator
    # ========================================================

    def _estimate_node(
        self,
        node,
    ):

        if isinstance(
            node,
            Not,
        ):

            return _clamp(
                1.0
                -
                self._estimate_node(
                    node.condition
                )
            )

        if isinstance(
            node,
            Logical,
        ):

            left = (
                self._estimate_node(
                    node.left
                )
            )

            right = (
                self._estimate_node(
                    node.right
                )
            )

            operation = (
                node.op.lower()
            )

            if operation == "and":

                # Independence assumption required by
                # the Module 4 handout.
                return _clamp(
                    left * right
                )

            if operation == "or":

                return _clamp(
                    left
                    + right
                    - (
                        left
                        * right
                    )
                )

            raise ValueError(
                "Unknown logical "
                f"operator: {node.op}"
            )

        if isinstance(
            node,
            Comparison,
        ):

            return self._comparison(
                node
            )

        raise ValueError(
            "Invalid condition node: "
            f"{type(node).__name__}"
        )

    def estimate(
        self,
        condition,
    ):
        """
        Estimate selectivity in [0, 1].

        condition may be condition text or an already parsed
        condition tree.
        """

        prepared = prepare_condition(
            condition,
            self.schema,
        )

        return _clamp(
            self._estimate_node(
                prepared
            )
        )


def estimate_rows(
    input_rows,
    selectivity,
):
    """
    Required Module 4 cardinality rule:

        ceil(input_rows * selectivity)

    never below 1.
    """

    return max(
        1,
        math.ceil(
            input_rows
            * _clamp(
                selectivity
            )
        ),
    )


def estimate_join_rows(
    left_rows,
    right_rows,
    selectivity,
):
    return max(
        1,
        math.ceil(
            left_rows
            * right_rows
            * _clamp(
                selectivity
            )
        ),
    )


def estimate_pages(
    rows,
    width,
):
    """
    Module 4 page estimate:

        ceil(rows * width / 4096)
    """

    if rows <= 0:
        return 0

    if width <= 0:
        return 0

    return math.ceil(
        rows
        * width
        / PAGE_SIZE
    )