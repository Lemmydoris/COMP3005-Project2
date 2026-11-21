import argparse
import json
import sys

from optimizer.cost import (
    join_algorithm_costs,
)

from optimizer.join_order import (
    JoinPredicateInfo,
    RelationInfo,
    enumerate_left_deep,
)
from optimizer.planner import PhysicalPlanner
from optimizer.statistics import analyze_table


# ============================================================
# Helpers
# ============================================================


def _load_logical_plan(path):

    try:

        with open(
            path,
            "r",
            encoding="utf-8",
        ) as handle:

            logical_plan = json.load(
                handle
            )

    except json.JSONDecodeError as exc:

        raise ValueError(
            "Invalid logical-plan JSON: "
            f"{exc.msg} at line "
            f"{exc.lineno}, column "
            f"{exc.colno}"
        ) from exc

    if not isinstance(
        logical_plan,
        dict,
    ):

        raise ValueError(
            "Logical plan must be a JSON object."
        )

    return logical_plan


def _format_plan_node(plan):

    op = plan.get(
        "op",
        "unknown",
    )

    if op == "seqscan":

        table = plan.get(
            "table",
            "?"
        )

        return (
            f"seqscan {table}"
        )

    if op == "rename":

        alias = plan.get(
            "to",
            "?"
        )

        return (
            f"rename {alias}"
        )

    if op == "filter":

        condition = plan.get(
            "condition",
            "?"
        )

        return (
            f"filter ({condition})"
        )

    if op == "project":

        columns = plan.get(
            "columns",
            [],
        )

        return (
            "project ["
            + ", ".join(
                str(column)
                for column
                in columns
            )
            + "]"
        )

    if op == "group_by":

        keys = plan.get(
            "keys",
            [],
        )

        return (
            "group_by ["
            + ", ".join(
                str(key)
                for key
                in keys
            )
            + "]"
        )

    if op == "distinct":

        mode = plan.get(
            "mode",
            "?"
        )

        return (
            f"distinct {mode}"
        )

    if op == "sort":

        keys = plan.get(
            "keys",
            [],
        )

        return (
            f"sort {keys}"
        )

    if op == "limit":

        return (
            f"limit {plan.get('n', '?')}"
        )

    if op in (
        "nested_loop_join",
        "sort_merge_join",
        "hash_join",
    ):

        condition = plan.get(
            "condition",
            "?"
        )

        return (
            f"{op} ({condition})"
        )

    if op in (
        "union_all",
        "union",
        "intersect",
        "except",
    ):

        return op

    return str(
        op
    )

def _format_logical_node(node):

    op = node.get(
        "op",
        "unknown",
    )

    if op == "scan":

        return (
            f"scan {node.get('table', '?')}"
        )

    if op == "select":

        return (
            f"select ({node.get('condition', '?')})"
        )

    if op == "project":

        columns = node.get(
            "columns",
            [],
        )

        return (
            "project ["
            + ", ".join(
                str(column)
                for column
                in columns
            )
            + "]"
        )

    if op == "join":

        return (
            f"join ({node.get('condition', '?')})"
        )

    if op == "cross":

        return "cross"

    if op == "rename":

        return (
            f"rename {node.get('to', '?')}"
        )

    if op == "group_by":

        keys = node.get(
            "keys",
            [],
        )

        aggregates = node.get(
            "aggregates",
            [],
        )

        result = (
            "group_by ["
            + ", ".join(
                str(key)
                for key
                in keys
            )
            + "]"
        )

        if aggregates:

            result += (
                " aggregates="
                + str(
                    aggregates
                )
            )

        return result

    if op == "distinct":

        return "distinct"

    if op == "sort":

        return (
            f"sort {node.get('keys', [])}"
        )

    if op == "limit":

        return (
            f"limit {node.get('n', '?')}"
        )

    if op in (
        "union",
        "union_all",
        "intersect",
        "except",
    ):

        return op

    return str(
        op
    )


def _logical_children(node):

    if not isinstance(
        node,
        dict,
    ):

        return []

    if "child" in node:

        return [
            node["child"]
        ]

    children = []

    if "left" in node:

        children.append(
            node["left"]
        )

    if "right" in node:

        children.append(
            node["right"]
        )

    return children


def _print_logical_tree(
    node,
    depth=0,
):

    indent = (
        "  " * depth
    )

    print(
        indent
        + _format_logical_node(
            node
        )
    )

    for child in (
        _logical_children(
            node
        )
    ):

        _print_logical_tree(
            child,
            depth + 1,
        )
def _physical_children(node):

    if not isinstance(
        node,
        dict,
    ):

        return []

    if "child" in node:

        return [
            node["child"]
        ]

    children = []

    if "left" in node:

        children.append(
            node["left"]
        )

    if "right" in node:

        children.append(
            node["right"]
        )

    return children


def _physical_to_logical(node):
    """
    Convert one physical-plan subtree back into the equivalent
    logical shape so the existing planner can estimate its
    rows/pages/width.

    The displayed tree still remains the physical tree.
    """

    if not isinstance(
        node,
        dict,
    ):

        return node

    result = {}

    for key, value in node.items():

        if key in (
            "child",
            "left",
            "right",
        ):

            result[key] = (
                _physical_to_logical(
                    value
                )
            )

        else:

            result[key] = value

    op = node.get(
        "op"
    )

    if op == "seqscan":

        result["op"] = "scan"

    elif op == "filter":

        result["op"] = "select"

    elif op in (
        "nested_loop_join",
        "sort_merge_join",
        "hash_join",
    ):

        result["op"] = "join"

    return result


def _estimate_physical_tree(
    planner,
    node,
):
    """
    Estimate the chosen physical tree while preserving its
    actual child order and physical algorithms.
    """

    logical_equivalent = (
        _physical_to_logical(
            node
        )
    )

    estimate = (
        planner._plan_node(
            logical_equivalent
        )
    )

    child_trees = [
        _estimate_physical_tree(
            planner,
            child,
        )
        for child
        in _physical_children(
            node
        )
    ]

    op = node.get(
        "op"
    )

    # --------------------------------------------------------
    # Sequential scan
    # --------------------------------------------------------

    if op == "seqscan":

        own_cost = (
            estimate.cost
        )

    # --------------------------------------------------------
    # Physical joins
    # --------------------------------------------------------

    elif op in (
        "nested_loop_join",
        "sort_merge_join",
        "hash_join",
    ):

        if len(
            child_trees
        ) != 2:

            raise ValueError(
                "Physical join must have "
                "two children."
            )

        left_estimate = (
            child_trees[0][
                "estimate"
            ]
        )

        right_estimate = (
            child_trees[1][
                "estimate"
            ]
        )

        parsed_condition = (
            planner._parse_condition(
                node[
                    "condition"
                ]
            )
        )

        equality = (
            planner._simple_equality_join(
                parsed_condition
            )
        )

        costs = (
            join_algorithm_costs(
                left_estimate.pages,
                right_estimate.pages,
                planner.frames,
                equality=equality,
            )
        )

        if op not in costs:

            raise ValueError(
                f"Cost model does not support "
                f"physical operator {op}."
            )

        own_cost = costs[
            op
        ]

    # --------------------------------------------------------
    # Unary operators
    # --------------------------------------------------------

    elif len(
        child_trees
    ) == 1:

        child_cost = (
            child_trees[0][
                "estimate"
            ].cost
        )

        own_cost = max(
            0,
            estimate.cost
            - child_cost,
        )

    # --------------------------------------------------------
    # Binary non-join operators
    # --------------------------------------------------------

    elif len(
        child_trees
    ) == 2:

        left_cost = (
            child_trees[0][
                "estimate"
            ].cost
        )

        right_cost = (
            child_trees[1][
                "estimate"
            ].cost
        )

        own_cost = max(
            0,
            estimate.cost
            - left_cost
            - right_cost,
        )

    else:

        own_cost = (
            estimate.cost
        )

    return {
        "node":
            node,
        "estimate":
            estimate,
        "own_cost":
            own_cost,
        "children":
            child_trees,
    }


def _print_explain_tree(
    tree,
    depth=0,
):

    node = tree[
        "node"
    ]

    estimate = tree[
        "estimate"
    ]

    label = (
        _format_plan_node(
            node
        )
    )

    indent = (
        "  " * depth
    )

    print(
        f"{indent}{label}"
        f"  est_rows={estimate.rows}"
        f"  est_cost={tree['own_cost']}"
    )

    for child in tree[
        "children"
    ]:

        _print_explain_tree(
            child,
            depth + 1,
        )

def _collect_top_join_components(
    node,
    components,
):

    if not isinstance(
        node,
        dict,
    ):

        return

    if node.get(
        "op"
    ) == "join":

        components.append(
            node
        )

        # Nested joins belong to this same component.
        return

    if "child" in node:

        _collect_top_join_components(
            node["child"],
            components,
        )

    if "left" in node:

        _collect_top_join_components(
            node["left"],
            components,
        )

    if "right" in node:

        _collect_top_join_components(
            node["right"],
            components,
        )


def _build_dp_result(
    planner,
    join_node,
):

    leaves = []
    predicate_nodes = []

    planner._collect_join_component(
        join_node,
        leaves,
        predicate_nodes,
    )

    if not leaves:

        raise ValueError(
            "No relations found in join component."
        )

    leaf_lookup = {}
    relations = []
    bindings = {}

    for leaf in leaves:

        if len(
            leaf.relations
        ) != 1:

            raise ValueError(
                "DP table requires each join leaf "
                "to represent one relation."
            )

        relation_name = next(
            iter(
                leaf.relations
            )
        )

        if relation_name in leaf_lookup:

            raise ValueError(
                "DP table requires unique "
                "relation names or aliases."
            )

        leaf_lookup[
            relation_name
        ] = leaf

        relations.append(
            RelationInfo(
                name=relation_name,
                pages=leaf.pages,
                rows=leaf.rows,
                width=leaf.width,
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
            planner._condition_relations(
                predicate_node
            )
        )

        if len(
            referenced
        ) != 2:

            raise ValueError(
                "DP table requires join predicates "
                "that connect exactly two relations."
            )

        left_name, right_name = (
            sorted(
                referenced
            )
        )

        join_predicates.append(
            JoinPredicateInfo(
                left=left_name,
                right=right_name,
                condition=(
                    planner._condition_text(
                        predicate_node
                    )
                ),
                equality=(
                    planner._simple_equality_join(
                        predicate_node
                    )
                ),
                selectivity=(
                    planner._join_selectivity(
                        predicate_node,
                        bindings,
                    )
                ),
            )
        )

    if not join_predicates:

        raise ValueError(
            "No join predicates available "
            "for DP enumeration."
        )

    return enumerate_left_deep(
        relations,
        join_predicates,
        planner.frames,
    )


def _subset_text(
    subset,
):

    return (
        "{"
        + ",".join(
            sorted(
                subset
            )
        )
        + "}"
    )


def _candidate_description(
    candidate,
):

    left = (
        _subset_text(
            candidate.left_relations
        )
    )

    return (
        f"{left} outer, "
        f"{candidate.algorithm} with "
        f"{candidate.added_relation} inner, "
        f"condition {candidate.condition}"
    )

def _print_dp_result(
    dp,
):

    subsets = sorted(
        dp.candidates.keys(),
        key=lambda subset: (
            len(subset),
            tuple(
                sorted(
                    subset
                )
            ),
        ),
    )
    full_size = max(
        len(subset)
        for subset in subsets
    )

    print(
        f"{'Subset':<24}"
        f"{'Best plan considered':<70}"
        f"Cost"
    )

    print(
        "-" * 104
    )

    for subset in subsets:

        subset_label = (
            _subset_text(
                subset
            )
        )

        # ----------------------------------------------------
        # Singleton relation
        # ----------------------------------------------------

        if len(
            subset
        ) == 1:

            entry = (
                dp.best[
                    subset
                ]
            )

            relation_name = next(
                iter(
                    subset
                )
            )

            print(
                f"{subset_label:<24}"
                f"{('scan ' + relation_name):<70}"
                f"{entry.cost}"
            )

            continue

        candidates = (
            dp.candidates.get(
                subset,
                [],
            )
        )

        # ----------------------------------------------------
        # Disconnected subset
        # ----------------------------------------------------

        if not candidates:

            print(
                f"{subset_label:<24}"
                f"{'no predicate, skipped':<70}"
                "-"
            )

            continue

        winner = (
            dp.best.get(
                subset
            )
        )

        ordered = sorted(
            candidates,
            key=lambda candidate: (
                candidate.total_cost,
                candidate.algorithm,
                candidate.added_relation,
            ),
        )

        # Find the candidate corresponding to dp.best.
        winner_candidate = None

        for candidate in ordered:

            if (
                winner is not None
                and
                candidate.total_cost
                == winner.cost
                and
                candidate.algorithm
                == winner.algorithm
                and
                candidate.added_relation
                == winner.added_relation
            ):

                winner_candidate = (
                    candidate
                )

                break

        if winner_candidate is None:

            winner_candidate = (
                ordered[0]
            )

        description = (
            _candidate_description(
                winner_candidate
            )
        )

        print(
            f"{subset_label:<24}"
            f"{description:<70}"
            f"{winner_candidate.total_cost}"
        )

        # ----------------------------------------------------
        # For the complete relation set, also show the best
        # alternative join order, as in Section 5.1.
        # ----------------------------------------------------

        if (
            len(subset)
            == full_size
            and len(subset) > 2
        ):

            alternatives = [
                candidate
                for candidate in ordered
                if (
                    candidate.left_relations
                    != winner_candidate.left_relations
                    or
                    candidate.added_relation
                    != winner_candidate.added_relation
                )
            ]

            if alternatives:

                alternative = (
                    alternatives[0]
                )

                alternative_description = (
                    "alternative, "
                    + _candidate_description(
                        alternative
                    )
                )

                print(
                    f"{'':<24}"
                    f"{alternative_description:<70}"
                    f"{alternative.total_cost}"
                )   


# ============================================================
# Commands
# ============================================================


def analyze_command(args):

    analyze_table(
        db_dir=args.db,
        table_name=args.table,
        buckets=args.buckets,
    )

    # Successful ANALYZE is intentionally silent.
    return 0


def plan_command(args):

    logical_plan = (
        _load_logical_plan(
            args.logical
        )
    )

    planner = PhysicalPlanner(
        args.db,
        frames=args.frames,
    )

    physical_plan = (
        planner.plan(
            logical_plan
        )
    )

    print(
        json.dumps(
            physical_plan,
            indent=2,
        )
    )

    return 0


def explain_command(args):

    logical_plan = (
        _load_logical_plan(
            args.logical
        )
    )

    planner = PhysicalPlanner(
        args.db,
        frames=args.frames,
    )

    # --------------------------------------------------------
    # Optional before/after rewrite view
    # --------------------------------------------------------

    if args.rewrite:

        print(
            "BEFORE REWRITE"
        )

        _print_logical_tree(
            logical_plan
        )

        print()

        rewritten = (
            planner.rewritten_plan(
                logical_plan
            )
        )

        print(
            "AFTER REWRITE"
        )

        _print_logical_tree(
            rewritten
        )

        print()
        print(
            "PHYSICAL PLAN"
        )

    # --------------------------------------------------------
    # Physical EXPLAIN with estimates
    # --------------------------------------------------------

    result = (
        planner.plan_with_estimates(
            logical_plan
        )
    )

    explain_tree = (
        _estimate_physical_tree(
            planner,
            result.plan,
        )
    )

    _print_explain_tree(
        explain_tree
    )

    return 0
def dp_table_command(args):

    logical_plan = (
        _load_logical_plan(
            args.logical
        )
    )

    planner = PhysicalPlanner(
        args.db,
        frames=args.frames,
    )

    rewritten = (
        planner.rewritten_plan(
            logical_plan
        )
    )

    components = []

    _collect_top_join_components(
        rewritten,
        components,
    )

    if not components:

        raise ValueError(
            "Logical plan contains no "
            "join component."
        )

    for index, component in enumerate(
        components
    ):

        if len(
            components
        ) > 1:

            if index > 0:
                print()

            print(
                f"Join component {index + 1}"
            )

        dp = (
            _build_dp_result(
                planner,
                component,
            )
        )

        _print_dp_result(
            dp
        )

    return 0


# ============================================================
# Argument parser
# ============================================================


def _add_planning_arguments(
    parser,
):

    parser.add_argument(
        "--db",
        required=True,
        help="Database directory",
    )

    parser.add_argument(
        "--logical",
        required=True,
        help="Logical plan JSON file",
    )

    parser.add_argument(
        "--frames",
        type=int,
        default=32,
        help=(
            "Memory budget in frames "
            "(default: 32)"
        ),
    )


def build_argument_parser():

    parser = argparse.ArgumentParser(
        prog="opt",
        description=(
            "COMP 3005 Module 4 "
            "query optimizer"
        ),
    )

    subparsers = (
        parser.add_subparsers(
            dest="command",
            required=True,
        )
    )

    # --------------------------------------------------------
    # opt analyze
    # --------------------------------------------------------

    analyze_parser = (
        subparsers.add_parser(
            "analyze",
            help=(
                "Compute exact table "
                "statistics."
            ),
        )
    )

    analyze_parser.add_argument(
        "--db",
        required=True,
        help="Database directory",
    )

    analyze_parser.add_argument(
        "--table",
        required=True,
        help="Table to analyze",
    )

    analyze_parser.add_argument(
        "--buckets",
        type=int,
        default=20,
        help=(
            "Number of equi-depth "
            "histogram buckets "
            "(default: 20)"
        ),
    )

    analyze_parser.set_defaults(
        handler=analyze_command
    )

    # --------------------------------------------------------
    # opt plan
    # --------------------------------------------------------

    plan_parser = (
        subparsers.add_parser(
            "plan",
            help=(
                "Generate an optimized "
                "physical plan."
            ),
        )
    )

    _add_planning_arguments(
        plan_parser
    )

    plan_parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit the physical plan "
            "as JSON."
        ),
    )

    plan_parser.set_defaults(
        handler=plan_command
    )

    # --------------------------------------------------------
    # opt explain
    # --------------------------------------------------------

    explain_parser = (
        subparsers.add_parser(
            "explain",
            help=(
                "Show estimated rows and "
                "cost for the optimized plan."
            ),
        )
    )

    _add_planning_arguments(
        explain_parser
    )

    explain_parser.add_argument(
    "--rewrite",
    action="store_true",
    help=(
        "Show logical plan before and "
        "after rewrite before the "
        "physical EXPLAIN."
    ),
)

    explain_parser.set_defaults(
        handler=explain_command
    )

    # --------------------------------------------------------
    # opt dp-table
    # --------------------------------------------------------

    dp_parser = (
        subparsers.add_parser(
            "dp-table",
            help=(
                "Print dynamic-programming "
                "join enumeration."
            ),
        )
    )

    _add_planning_arguments(
        dp_parser
    )

    dp_parser.set_defaults(
        handler=dp_table_command
    )

    return parser


# ============================================================
# Main
# ============================================================


def main(argv=None):

    parser = (
        build_argument_parser()
    )

    args = parser.parse_args(
        argv
    )

    try:

        return args.handler(
            args
        )

    except (
        ValueError,
        OSError,
    ) as exc:

        print(
            f"error: optimizer: {exc}",
            file=sys.stderr,
        )

        return 1

    except KeyError as exc:

        print(
            f"error: optimizer: "
            f"missing or unknown value: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":

    raise SystemExit(
        main()
    )