import copy

from parser import parse_condition_text
from ra_tree import (
    Attr,
    Comparison,
    Literal,
    Logical,
    Not,
)


ALL_REWRITE_RULES = {
    1,
    2,
    3,
    4,
    5,
    6,
    7,
}


# ============================================================
# Condition helpers
# ============================================================


def _attribute_text(node):

    if node.relation:
        return (
            f"{node.relation}."
            f"{node.name}"
        )

    return node.name


def _condition_references(
    node,
):

    references = set()

    def visit(current):

        if isinstance(
            current,
            Attr,
        ):

            references.add(
                _attribute_text(
                    current
                )
            )

            return

        if isinstance(
            current,
            Literal,
        ):
            return

        if isinstance(
            current,
            Comparison,
        ):

            visit(
                current.left
            )

            visit(
                current.right
            )

            return

        if isinstance(
            current,
            Logical,
        ):

            visit(
                current.left
            )

            visit(
                current.right
            )

            return

        if isinstance(
            current,
            Not,
        ):

            visit(
                current.condition
            )

            return

        raise ValueError(
            "Unsupported condition "
            f"node: "
            f"{type(current).__name__}"
        )

    visit(
        node
    )

    return references


def _operand_text(
    node,
    name_map=None,
):

    if name_map is None:
        name_map = {}

    if isinstance(
        node,
        Attr,
    ):

        name = _attribute_text(
            node
        )

        return name_map.get(
            name,
            name,
        )

    if isinstance(
        node,
        Literal,
    ):

        if isinstance(
            node.value,
            str,
        ):

            escaped = (
                node.value.replace(
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
            node.value
        )

    raise ValueError(
        "Unsupported condition "
        "operand."
    )


def _condition_text(
    node,
    parent_precedence=0,
    name_map=None,
):

    if name_map is None:
        name_map = {}

    # OR
    if (
        isinstance(
            node,
            Logical,
        )
        and node.op.lower()
        == "or"
    ):

        precedence = 1

        text = (
            _condition_text(
                node.left,
                precedence,
                name_map,
            )
            + " OR "
            + _condition_text(
                node.right,
                precedence,
                name_map,
            )
        )

    # AND
    elif (
        isinstance(
            node,
            Logical,
        )
        and node.op.lower()
        == "and"
    ):

        precedence = 2

        text = (
            _condition_text(
                node.left,
                precedence,
                name_map,
            )
            + " AND "
            + _condition_text(
                node.right,
                precedence,
                name_map,
            )
        )

    # NOT
    elif isinstance(
        node,
        Not,
    ):

        precedence = 3

        text = (
            "NOT "
            + _condition_text(
                node.condition,
                precedence,
                name_map,
            )
        )

    # Comparison
    elif isinstance(
        node,
        Comparison,
    ):

        precedence = 4

        text = (
            _operand_text(
                node.left,
                name_map,
            )
            + " "
            + node.op
            + " "
            + _operand_text(
                node.right,
                name_map,
            )
        )

    else:

        raise ValueError(
            "Unsupported condition "
            f"node: "
            f"{type(node).__name__}"
        )

    if (
        precedence
        < parent_precedence
    ):

        return (
            "("
            + text
            + ")"
        )

    return text


def _rewrite_condition_names(
    condition,
    mapping,
):

    parsed = (
        parse_condition_text(
            condition
        )
    )

    return _condition_text(
        parsed,
        name_map=mapping,
    )


def _flatten_and(
    node,
):

    if (
        isinstance(
            node,
            Logical,
        )
        and node.op.lower()
        == "and"
    ):

        return (
            _flatten_and(
                node.left
            )
            +
            _flatten_and(
                node.right
            )
        )

    return [
        node
    ]


# ============================================================
# Catalog/schema helpers
# ============================================================


class LogicalPlanRewriter:

    def __init__(
        self,
        catalog,
    ):

        self.catalog = catalog

    def _table_schema(
        self,
        table,
    ):

        if hasattr(
            self.catalog,
            "get_table",
        ):

            metadata = (
                self.catalog.get_table(
                    table
                )
            )

        else:

            metadata = (
                self.catalog[
                    table
                ]
            )

        if isinstance(
            metadata,
            dict,
        ):

            schema = metadata[
                "schema"
            ]

        else:

            schema = metadata

        return [
            list(column)
            for column in schema
        ]

    def output_columns(
        self,
        plan,
    ):

        op = plan[
            "op"
        ]

        # ----------------------------------------------------
        # scan
        # ----------------------------------------------------

        if op == "scan":

            table = plan[
                "table"
            ]

            return [
                (
                    f"{table}."
                    f"{column[0]}"
                )
                for column
                in self._table_schema(
                    table
                )
            ]

        # ----------------------------------------------------
        # rename
        # ----------------------------------------------------

        if op == "rename":

            child_columns = (
                self.output_columns(
                    plan[
                        "child"
                    ]
                )
            )

            alias = plan[
                "to"
            ]

            return [
                (
                    f"{alias}."
                    + column.split(
                        "."
                    )[-1]
                )
                for column
                in child_columns
            ]

        # ----------------------------------------------------
        # project
        # ----------------------------------------------------

        if op == "project":

            return list(
                plan[
                    "columns"
                ]
            )

        # ----------------------------------------------------
        # operators preserving schema
        # ----------------------------------------------------

        if op in {
            "select",
            "distinct",
            "sort",
            "limit",
        }:

            return (
                self.output_columns(
                    plan[
                        "child"
                    ]
                )
            )

        # ----------------------------------------------------
        # join / cross
        # ----------------------------------------------------

        if op in {
            "join",
            "cross",
        }:

            return (
                self.output_columns(
                    plan[
                        "left"
                    ]
                )
                +
                self.output_columns(
                    plan[
                        "right"
                    ]
                )
            )

        # ----------------------------------------------------
        # group_by
        # ----------------------------------------------------

        if op == "group_by":

            result = list(
                plan.get(
                    "keys",
                    [],
                )
            )

            for aggregate in (
                plan.get(
                    "aggregates",
                    [],
                )
            ):

                if len(
                    aggregate
                ) >= 3:

                    result.append(
                        aggregate[2]
                    )

            return result

        # ----------------------------------------------------
        # set operations
        # ----------------------------------------------------

        if op in {
            "union",
            "union_all",
            "intersect",
            "except",
        }:

            return (
                self.output_columns(
                    plan[
                        "left"
                    ]
                )
            )

        raise ValueError(
            "Unknown logical operator: "
            f"{op}"
        )

    # ========================================================
    # General column helpers
    # ========================================================

    def _column_belongs(
        self,
        requested,
        columns,
    ):

        if requested in columns:
            return True

        if "." in requested:
            return False

        matches = [
            column
            for column in columns
            if (
                column.split(
                    "."
                )[-1]
                == requested
            )
        ]

        return len(
            matches
        ) == 1

    def _refs_belong(
        self,
        references,
        columns,
    ):

        if not references:
            return False

        return all(
            self._column_belongs(
                reference,
                columns,
            )
            for reference
            in references
        )

    def _position_mapping(
        self,
        source_columns,
        target_columns,
    ):

        if len(
            source_columns
        ) != len(
            target_columns
        ):

            raise ValueError(
                "Cannot rewrite columns "
                "between schemas with "
                "different widths."
            )

        return {
            source:
                target
            for (
                source,
                target,
            )
            in zip(
                source_columns,
                target_columns,
            )
        }

    def _condition_refs_text(
        self,
        condition,
    ):

        parsed = (
            parse_condition_text(
                condition
            )
        )

        return (
            _condition_references(
                parsed
            )
        )

    # ========================================================
    # Rule 1
    # Split conjunctions
    # ========================================================

    def _rule_1(
        self,
        plan,
    ):

        op = plan[
            "op"
        ]

        result = copy.deepcopy(
            plan
        )

        if "child" in result:

            result[
                "child"
            ] = self._rule_1(
                result[
                    "child"
                ]
            )

        if "left" in result:

            result[
                "left"
            ] = self._rule_1(
                result[
                    "left"
                ]
            )

        if "right" in result:

            result[
                "right"
            ] = self._rule_1(
                result[
                    "right"
                ]
            )

        if op != "select":
            return result

        parsed = (
            parse_condition_text(
                result[
                    "condition"
                ]
            )
        )

        pieces = (
            _flatten_and(
                parsed
            )
        )

        if len(
            pieces
        ) <= 1:

            return result

        child = result[
            "child"
        ]

        # Reverse construction preserves textual left-to-right
        # order at the top of the tree.
        for piece in reversed(
            pieces
        ):

            child = {
                "op":
                    "select",
                "condition":
                    _condition_text(
                        piece
                    ),
                "child":
                    child,
            }

        return child

    # ========================================================
    # Rule 2
    # Push select below join/cross when one-sided
    # ========================================================

    def _rule_2(
        self,
        plan,
    ):

        result = copy.deepcopy(
            plan
        )

        if "child" in result:

            result[
                "child"
            ] = self._rule_2(
                result[
                    "child"
                ]
            )

        if "left" in result:

            result[
                "left"
            ] = self._rule_2(
                result[
                    "left"
                ]
            )

        if "right" in result:

            result[
                "right"
            ] = self._rule_2(
                result[
                    "right"
                ]
            )

        if (
            result[
                "op"
            ]
            != "select"
        ):

            return result

        child = result[
            "child"
        ]

        if child[
            "op"
        ] not in {
            "join",
            "cross",
        }:

            return result

        references = (
            self._condition_refs_text(
                result[
                    "condition"
                ]
            )
        )

        left_columns = (
            self.output_columns(
                child[
                    "left"
                ]
            )
        )

        right_columns = (
            self.output_columns(
                child[
                    "right"
                ]
            )
        )

        left_only = (
            self._refs_belong(
                references,
                left_columns,
            )
            and not
            self._refs_belong(
                references,
                right_columns,
            )
        )

        right_only = (
            self._refs_belong(
                references,
                right_columns,
            )
            and not
            self._refs_belong(
                references,
                left_columns,
            )
        )

        if left_only:

            child[
                "left"
            ] = {
                "op":
                    "select",
                "condition":
                    result[
                        "condition"
                    ],
                "child":
                    child[
                        "left"
                    ],
            }

            return child

        if right_only:

            child[
                "right"
            ] = {
                "op":
                    "select",
                "condition":
                    result[
                        "condition"
                    ],
                "child":
                    child[
                        "right"
                    ],
            }

            return child

        return result

    # ========================================================
    # Rule 3
    # cross + two-sided equality select -> join
    # ========================================================

    def _rule_3(
        self,
        plan,
    ):

        result = copy.deepcopy(
            plan
        )

        if "child" in result:

            result[
                "child"
            ] = self._rule_3(
                result[
                    "child"
                ]
            )

        if "left" in result:

            result[
                "left"
            ] = self._rule_3(
                result[
                    "left"
                ]
            )

        if "right" in result:

            result[
                "right"
            ] = self._rule_3(
                result[
                    "right"
                ]
            )

        if (
            result[
                "op"
            ]
            != "select"
        ):

            return result

        child = result[
            "child"
        ]

        if child[
            "op"
        ] != "cross":

            return result

        parsed = (
            parse_condition_text(
                result[
                    "condition"
                ]
            )
        )

        if not isinstance(
            parsed,
            Comparison,
        ):

            return result

        if parsed.op != "=":

            return result

        if not (
            isinstance(
                parsed.left,
                Attr,
            )
            and isinstance(
                parsed.right,
                Attr,
            )
        ):

            return result

        left_columns = (
            self.output_columns(
                child[
                    "left"
                ]
            )
        )

        right_columns = (
            self.output_columns(
                child[
                    "right"
                ]
            )
        )

        left_name = (
            _attribute_text(
                parsed.left
            )
        )

        right_name = (
            _attribute_text(
                parsed.right
            )
        )

        forward = (
            self._column_belongs(
                left_name,
                left_columns,
            )
            and
            self._column_belongs(
                right_name,
                right_columns,
            )
        )

        reverse = (
            self._column_belongs(
                left_name,
                right_columns,
            )
            and
            self._column_belongs(
                right_name,
                left_columns,
            )
        )

        if not (
            forward
            or reverse
        ):

            return result

        return {
            "op":
                "join",
            "condition":
                result[
                    "condition"
                ],
            "left":
                child[
                    "left"
                ],
            "right":
                child[
                    "right"
                ],
        }

    # ========================================================
    # Rule 4
    # Push select through rename / union / union_all
    # ========================================================

    def _rule_4(
        self,
        plan,
    ):

        result = copy.deepcopy(
            plan
        )

        if "child" in result:

            result[
                "child"
            ] = self._rule_4(
                result[
                    "child"
                ]
            )

        if "left" in result:

            result[
                "left"
            ] = self._rule_4(
                result[
                    "left"
                ]
            )

        if "right" in result:

            result[
                "right"
            ] = self._rule_4(
                result[
                    "right"
                ]
            )

        if (
            result[
                "op"
            ]
            != "select"
        ):

            return result

        child = result[
            "child"
        ]

        # ----------------------------------------------------
        # rename
        # ----------------------------------------------------

        if child[
            "op"
        ] == "rename":

            renamed_columns = (
                self.output_columns(
                    child
                )
            )

            original_columns = (
                self.output_columns(
                    child[
                        "child"
                    ]
                )
            )

            mapping = (
                self._position_mapping(
                    renamed_columns,
                    original_columns,
                )
            )

            rewritten = (
                _rewrite_condition_names(
                    result[
                        "condition"
                    ],
                    mapping,
                )
            )

            return {
                "op":
                    "rename",
                "to":
                    child[
                        "to"
                    ],
                "child": {
                    "op":
                        "select",
                    "condition":
                        rewritten,
                    "child":
                        child[
                            "child"
                        ],
                },
            }

        # ----------------------------------------------------
        # union / union_all
        # ----------------------------------------------------

        if child[
            "op"
        ] in {
            "union",
            "union_all",
        }:

            output_columns = (
                self.output_columns(
                    child
                )
            )

            left_columns = (
                self.output_columns(
                    child[
                        "left"
                    ]
                )
            )

            right_columns = (
                self.output_columns(
                    child[
                        "right"
                    ]
                )
            )

            left_mapping = (
                self._position_mapping(
                    output_columns,
                    left_columns,
                )
            )

            right_mapping = (
                self._position_mapping(
                    output_columns,
                    right_columns,
                )
            )

            left_condition = (
                _rewrite_condition_names(
                    result[
                        "condition"
                    ],
                    left_mapping,
                )
            )

            right_condition = (
                _rewrite_condition_names(
                    result[
                        "condition"
                    ],
                    right_mapping,
                )
            )

            return {
                "op":
                    child[
                        "op"
                    ],
                "left": {
                    "op":
                        "select",
                    "condition":
                        left_condition,
                    "child":
                        child[
                            "left"
                        ],
                },
                "right": {
                    "op":
                        "select",
                    "condition":
                        right_condition,
                    "child":
                        child[
                            "right"
                        ],
                },
            }

        return result

    # ========================================================
    # Rule 5
    # Push select below group_by when only grouping columns
    # ========================================================

    def _rule_5(
        self,
        plan,
    ):

        result = copy.deepcopy(
            plan
        )

        if "child" in result:

            result[
                "child"
            ] = self._rule_5(
                result[
                    "child"
                ]
            )

        if "left" in result:

            result[
                "left"
            ] = self._rule_5(
                result[
                    "left"
                ]
            )

        if "right" in result:

            result[
                "right"
            ] = self._rule_5(
                result[
                    "right"
                ]
            )

        if (
            result[
                "op"
            ]
            != "select"
        ):

            return result

        child = result[
            "child"
        ]

        if child[
            "op"
        ] != "group_by":

            return result

        references = (
            self._condition_refs_text(
                result[
                    "condition"
                ]
            )
        )

        grouping_columns = (
            child.get(
                "keys",
                [],
            )
        )

        if not references:

            return result

        if not all(
            self._column_belongs(
                reference,
                grouping_columns,
            )
            for reference
            in references
        ):

            return result

        moved_group = (
            copy.deepcopy(
                child
            )
        )

        moved_group[
            "child"
        ] = {
            "op":
                "select",
            "condition":
                result[
                    "condition"
                ],
            "child":
                child[
                    "child"
                ],
        }

        return moved_group

    # ========================================================
    # Rule 6
    # Projection pushdown
    # ========================================================

    def _ordered_required(
        self,
        columns,
        required,
    ):

        if required is None:

            return list(
                columns
            )

        return [
            column
            for column in columns
            if column in required
        ]

    def _maybe_project(
        self,
        plan,
        required,
    ):

        if required is None:
            return plan

        output = (
            self.output_columns(
                plan
            )
        )

        wanted = (
            self._ordered_required(
                output,
                required,
            )
        )

        # Empty internal projections are deliberately avoided:
        # keeping the relation is conservative and preserves
        # multiplicity without relying on zero-column schemas.
        if not wanted:
            return plan

        if wanted == output:
            return plan

        return {
            "op":
                "project",
            "columns":
                wanted,
            "child":
                plan,
        }

    def _rule_6(
        self,
        plan,
        required=None,
    ):

        op = plan[
            "op"
        ]

        original_output = (
            self.output_columns(
                plan
            )
        )

        if required is None:

            required = set(
                original_output
            )

        else:

            required = set(
                required
            )

        # ----------------------------------------------------
        # scan
        # ----------------------------------------------------

        if op == "scan":

            return (
                self._maybe_project(
                    copy.deepcopy(
                        plan
                    ),
                    required,
                )
            )

        # ----------------------------------------------------
        # rename
        # ----------------------------------------------------

        if op == "rename":

            child = plan[
                "child"
            ]

            child_columns = (
                self.output_columns(
                    child
                )
            )

            renamed_columns = (
                self.output_columns(
                    plan
                )
            )

            mapping = (
                self._position_mapping(
                    renamed_columns,
                    child_columns,
                )
            )

            child_required = {
                mapping[column]
                for column
                in renamed_columns
                if column in required
            }

            rewritten = {
                "op":
                    "rename",
                "to":
                    plan[
                        "to"
                    ],
                "child":
                    self._rule_6(
                        child,
                        child_required,
                    ),
            }

            return (
                self._maybe_project(
                    rewritten,
                    required,
                )
            )

        # ----------------------------------------------------
        # select
        # ----------------------------------------------------

        if op == "select":

            references = (
                self._condition_refs_text(
                    plan[
                        "condition"
                    ]
                )
            )

            child_required = (
                required
                |
                references
            )

            rewritten = {
                "op":
                    "select",
                "condition":
                    plan[
                        "condition"
                    ],
                "child":
                    self._rule_6(
                        plan[
                            "child"
                        ],
                        child_required,
                    ),
            }

            return (
                self._maybe_project(
                    rewritten,
                    required,
                )
            )

        # ----------------------------------------------------
        # existing project
        # ----------------------------------------------------

        if op == "project":

            columns = list(
                plan[
                    "columns"
                ]
            )

            wanted = [
                column
                for column
                in columns
                if column in required
            ]

            if not wanted:
                wanted = columns

            return {
                "op":
                    "project",
                "columns":
                    wanted,
                "child":
                    self._rule_6(
                        plan[
                            "child"
                        ],
                        set(
                            wanted
                        ),
                    ),
            }

        # ----------------------------------------------------
        # join
        # ----------------------------------------------------

        if op == "join":

            left_columns = (
                self.output_columns(
                    plan[
                        "left"
                    ]
                )
            )

            right_columns = (
                self.output_columns(
                    plan[
                        "right"
                    ]
                )
            )

            join_refs = (
                self._condition_refs_text(
                    plan[
                        "condition"
                    ]
                )
            )

            all_needed = (
                required
                |
                join_refs
            )

            left_required = {
                column
                for column
                in left_columns
                if column in all_needed
            }

            right_required = {
                column
                for column
                in right_columns
                if column in all_needed
            }

            rewritten = {
                "op":
                    "join",
                "condition":
                    plan[
                        "condition"
                    ],
                "left":
                    self._rule_6(
                        plan[
                            "left"
                        ],
                        left_required,
                    ),
                "right":
                    self._rule_6(
                        plan[
                            "right"
                        ],
                        right_required,
                    ),
            }

            return (
                self._maybe_project(
                    rewritten,
                    required,
                )
            )

        # ----------------------------------------------------
        # cross
        # ----------------------------------------------------

        if op == "cross":

            left_columns = (
                self.output_columns(
                    plan[
                        "left"
                    ]
                )
            )

            right_columns = (
                self.output_columns(
                    plan[
                        "right"
                    ]
                )
            )

            left_required = {
                column
                for column
                in left_columns
                if column in required
            }

            right_required = {
                column
                for column
                in right_columns
                if column in required
            }

            rewritten = {
                "op":
                    "cross",
                "left":
                    self._rule_6(
                        plan[
                            "left"
                        ],
                        left_required,
                    ),
                "right":
                    self._rule_6(
                        plan[
                            "right"
                        ],
                        right_required,
                    ),
            }

            return (
                self._maybe_project(
                    rewritten,
                    required,
                )
            )

        # ----------------------------------------------------
        # group_by
        # ----------------------------------------------------

        if op == "group_by":

            child_required = set(
                plan.get(
                    "keys",
                    [],
                )
            )

            # Conservatively retain every aggregate argument
            # because rule 6 inserts projections; it does not
            # delete aggregate computations.
            for aggregate in (
                plan.get(
                    "aggregates",
                    [],
                )
            ):

                if len(
                    aggregate
                ) < 2:
                    continue

                argument = (
                    aggregate[1]
                )

                if argument != "*":

                    child_required.add(
                        argument
                    )

            rewritten = {
                "op":
                    "group_by",
                "keys":
                    list(
                        plan.get(
                            "keys",
                            [],
                        )
                    ),
                "aggregates":
                    copy.deepcopy(
                        plan.get(
                            "aggregates",
                            [],
                        )
                    ),
                "child":
                    self._rule_6(
                        plan[
                            "child"
                        ],
                        child_required,
                    ),
            }

            return (
                self._maybe_project(
                    rewritten,
                    required,
                )
            )

        # ----------------------------------------------------
        # sort
        # ----------------------------------------------------

        if op == "sort":

            sort_columns = {
                key[0]
                for key
                in plan.get(
                    "keys",
                    [],
                )
            }

            child_required = (
                required
                |
                sort_columns
            )

            rewritten = {
                "op":
                    "sort",
                "keys":
                    copy.deepcopy(
                        plan[
                            "keys"
                        ]
                    ),
                "child":
                    self._rule_6(
                        plan[
                            "child"
                        ],
                        child_required,
                    ),
            }

            return (
                self._maybe_project(
                    rewritten,
                    required,
                )
            )

        # ----------------------------------------------------
        # limit
        # ----------------------------------------------------

        if op == "limit":

            rewritten = {
                "op":
                    "limit",
                "n":
                    plan[
                        "n"
                    ],
                "child":
                    self._rule_6(
                        plan[
                            "child"
                        ],
                        required,
                    ),
            }

            return (
                self._maybe_project(
                    rewritten,
                    required,
                )
            )

        # ----------------------------------------------------
        # distinct
        #
        # DISTINCT needs every existing input column to decide
        # which tuples are duplicates.
        # ----------------------------------------------------

        if op == "distinct":

            rewritten = {
                "op":
                    "distinct",
                "child":
                    self._rule_6(
                        plan[
                            "child"
                        ],
                        set(
                            original_output
                        ),
                    ),
            }

            return (
                self._maybe_project(
                    rewritten,
                    required,
                )
            )

        # ----------------------------------------------------
        # union_all
        #
        # Safe to project both branches positionally.
        # ----------------------------------------------------

        if op == "union_all":

            left_columns = (
                self.output_columns(
                    plan[
                        "left"
                    ]
                )
            )

            right_columns = (
                self.output_columns(
                    plan[
                        "right"
                    ]
                )
            )

            output_columns = (
                self.output_columns(
                    plan
                )
            )

            right_map = (
                self._position_mapping(
                    output_columns,
                    right_columns,
                )
            )

            left_required = {
                column
                for column
                in left_columns
                if column in required
            }

            right_required = {
                right_map[column]
                for column
                in output_columns
                if column in required
            }

            rewritten = {
                "op":
                    "union_all",
                "left":
                    self._rule_6(
                        plan[
                            "left"
                        ],
                        left_required,
                    ),
                "right":
                    self._rule_6(
                        plan[
                            "right"
                        ],
                        right_required,
                    ),
            }

            return (
                self._maybe_project(
                    rewritten,
                    required,
                )
            )

        # ----------------------------------------------------
        # UNION / INTERSECT / EXCEPT
        #
        # They need every full tuple to preserve set semantics.
        # Dropping columns before them can change duplicate
        # elimination or membership.
        # ----------------------------------------------------

        if op in {
            "union",
            "intersect",
            "except",
        }:

            left_output = (
                self.output_columns(
                    plan[
                        "left"
                    ]
                )
            )

            right_output = (
                self.output_columns(
                    plan[
                        "right"
                    ]
                )
            )

            rewritten = {
                "op":
                    op,
                "left":
                    self._rule_6(
                        plan[
                            "left"
                        ],
                        set(
                            left_output
                        ),
                    ),
                "right":
                    self._rule_6(
                        plan[
                            "right"
                        ],
                        set(
                            right_output
                        ),
                    ),
            }

            return (
                self._maybe_project(
                    rewritten,
                    required,
                )
            )

        raise ValueError(
            "Unknown logical operator: "
            f"{op}"
        )

    # ========================================================
    # Rule 7
    # Remove no-op project / collapse adjacent selects
    # ========================================================

    def _rule_7(
        self,
        plan,
    ):

        result = copy.deepcopy(
            plan
        )

        if "child" in result:

            result[
                "child"
            ] = self._rule_7(
                result[
                    "child"
                ]
            )

        if "left" in result:

            result[
                "left"
            ] = self._rule_7(
                result[
                    "left"
                ]
            )

        if "right" in result:

            result[
                "right"
            ] = self._rule_7(
                result[
                    "right"
                ]
            )

        # ----------------------------------------------------
        # Remove projection that drops nothing.
        # ----------------------------------------------------

        if (
            result[
                "op"
            ]
            == "project"
        ):

            child_columns = (
                self.output_columns(
                    result[
                        "child"
                    ]
                )
            )

            if (
                list(
                    result[
                        "columns"
                    ]
                )
                == child_columns
            ):

                return result[
                    "child"
                ]

        # ----------------------------------------------------
        # Collapse adjacent selections.
        # ----------------------------------------------------

        if (
            result[
                "op"
            ]
            == "select"
            and
            result[
                "child"
            ][
                "op"
            ]
            == "select"
        ):

            child = result[
                "child"
            ]

            return {
                "op":
                    "select",
                "condition": (
                    "("
                    + result[
                        "condition"
                    ]
                    + ") AND ("
                    + child[
                        "condition"
                    ]
                    + ")"
                ),
                "child":
                    child[
                        "child"
                    ],
            }

        return result

    # ========================================================
    # Public rewrite entry point
    # ========================================================

    def rewrite(
        self,
        plan,
        disabled_rules=None,
    ):

        disabled = set(
            disabled_rules
            or []
        )

        unknown = (
            disabled
            -
            ALL_REWRITE_RULES
        )

        if unknown:

            raise ValueError(
                "Unknown rewrite rule(s): "
                + ", ".join(
                    str(rule)
                    for rule
                    in sorted(
                        unknown
                    )
                )
            )

        current = copy.deepcopy(
            plan
        )

        # ----------------------------------------------------
        # Rewrite scheduling
        # ----------------------------------------------------
        #
        # Order is deliberate.
        #
        # Rules 4 and 5 act on selects that already appear
        # above rename/group_by in the original logical tree.
        #
        # Rule 2 then pushes one-sided predicates below
        # join/cross.
        #
        # We do NOT cycle rules 2-5 repeatedly, because that
        # would make a select newly moved by Rule 2 immediately
        # pass through a rename via Rule 4. That over-rewrites
        # the professor's required Section 3 example.
        # ----------------------------------------------------

        # Rule 1:
        # Split conjunctions.
        if 1 not in disabled:

            current = (
                self._rule_1(
                    current
                )
            )

        # Rule 4:
        # Push selects that already sit above
        # rename / union / union_all.
        if 4 not in disabled:

            current = (
                self._rule_4(
                    current
                )
            )

        # Rule 5:
        # Push grouping-column predicates below group_by.
        if 5 not in disabled:

            current = (
                self._rule_5(
                    current
                )
            )

        # Rule 2:
        # Push one-sided predicates below join/cross.
        if 2 not in disabled:

            current = (
                self._rule_2(
                    current
                )
            )

        # Rule 3:
        # Convert cross plus two-sided equality to join.
        if 3 not in disabled:

            current = (
                self._rule_3(
                    current
                )
            )

        # Rule 6:
        # Add narrow projections after predicate placement.
        if 6 not in disabled:

            current = (
                self._rule_6(
                    current
                )
            )

        # Rule 7:
        # Cosmetic cleanup last.
        if 7 not in disabled:

            current = (
                self._rule_7(
                    current
                )
            )

        return current


def rewrite_plan(
    plan,
    catalog,
    disabled_rules=None,
):

    return LogicalPlanRewriter(
        catalog
    ).rewrite(
        plan,
        disabled_rules=(
            disabled_rules
        ),
    )