import argparse
import json
import sys

from execution.base import END
from execution.distinct import Distinct
from execution.filter import Filter
from execution.group_by import GroupBy
from execution.hash_join import HashJoin
from execution.limit import Limit
from execution.nested_loop_join import NestedLoopJoin
from execution.plan import (
    PlanError,
    build_operator,
    load_plan_file,
)
from execution.project import Project
from execution.seqscan import SeqScan
from execution.set_ops import (
    Except,
    Intersect,
    Union,
)
from execution.sort import Sort
from execution.sort_merge_join import SortMergeJoin
from execution.union_all import UnionAll


# =============================================================
# Plan-tree traversal
# =============================================================


def operator_children(operator):
    """
    Return only children that correspond to nodes in the
    submitted physical plan.

    Internal implementation operators such as the Sort
    hidden inside Distinct are intentionally not shown
    as separate plan nodes.
    """

    if hasattr(operator, "left") and hasattr(
        operator,
        "right",
    ):
        return [
            operator.left,
            operator.right,
        ]

    if hasattr(operator, "child"):
        return [
            operator.child,
        ]

    return []


def walk_plan(
    operator,
    depth=0,
):
    """
    Preorder traversal:
        parent
          left / child
          right
    """

    yield operator, depth

    for child in operator_children(
        operator
    ):
        yield from walk_plan(
            child,
            depth + 1,
        )


# =============================================================
# Names used by trace
# =============================================================


def operator_name(operator):

    if isinstance(
        operator,
        SeqScan,
    ):
        return (
            f"seqscan "
            f"{operator.table_name}"
        )

    if isinstance(
        operator,
        Filter,
    ):
        return (
            f"filter "
            f"({operator.condition})"
        )

    if isinstance(
        operator,
        Project,
    ):
        return "project"

    if isinstance(
        operator,
        Distinct,
    ):
        return (
            f"distinct "
            f"{operator.mode}"
        )

    if isinstance(
        operator,
        Sort,
    ):
        return "sort"

    if isinstance(
        operator,
        GroupBy,
    ):
        return (
            f"group_by "
            f"{operator.mode}"
        )

    if isinstance(
        operator,
        NestedLoopJoin,
    ):
        return (
            f"nested_loop_join "
            f"({operator.condition})"
        )

    if isinstance(
        operator,
        SortMergeJoin,
    ):
        return (
            f"sort_merge_join "
            f"({operator.condition})"
        )

    if isinstance(
        operator,
        HashJoin,
    ):
        return (
            f"hash_join "
            f"({operator.condition})"
        )

    if isinstance(
        operator,
        UnionAll,
    ):
        return "union_all"

    if isinstance(
        operator,
        Union,
    ):
        return "union"

    if isinstance(
        operator,
        Intersect,
    ):
        return "intersect"

    if isinstance(
        operator,
        Except,
    ):
        return "except"

    if isinstance(
        operator,
        Limit,
    ):
        return (
            f"limit "
            f"{operator.limit}"
        )

    return (
        operator.__class__.__name__
    )


# =============================================================
# Execution
# =============================================================


def execute_operator(root):
    """
    Open and fully consume an operator tree.

    Returns:
        {
            "schema": ...,
            "rows": ...
        }

    close() is always attempted so temporary files and
    pinned pages are released even if execution fails.
    """

    opened = False

    try:
        root.open()
        opened = True

        schema = [
            list(column)
            for column
            in root.schema
        ]

        rows = []

        while True:
            row = root.next()

            if row is END:
                break

            rows.append(
                list(row)
            )

        return {
            "schema": schema,
            "rows": rows,
        }

    finally:
        if opened or getattr(
            root,
            "is_open",
            False,
        ):
            root.close()


# =============================================================
# Counters
# =============================================================


def plan_totals(root):
    """
    Whole-plan totals.

    tuples_out:
        number of result tuples returned by the ROOT.

    comparisons/page_reads/page_writes:
        sum of counters owned by every physical plan node.

    This avoids summing tuples_out from intermediate nodes,
    which would not represent the query result size.
    """

    root_counters = (
        root.counters()
    )

    totals = {
        "tuples_out":
            root_counters[
                "tuples_out"
            ],
        "comparisons": 0,
        "page_reads": 0,
        "page_writes": 0,
    }

    for operator, _ in walk_plan(
        root
    ):
        counters = (
            operator.counters()
        )

        totals[
            "comparisons"
        ] += counters[
            "comparisons"
        ]

        totals[
            "page_reads"
        ] += counters[
            "page_reads"
        ]

        totals[
            "page_writes"
        ] += counters[
            "page_writes"
        ]

    return totals


# =============================================================
# Trace formatting
# =============================================================


def trace_lines(root):

    lines = []

    for operator, depth in walk_plan(
        root
    ):
        counters = (
            operator.counters()
        )

        name = operator_name(
            operator
        )

        indent = (
            "  " * depth
        )

        line = (
            f"{indent}"
            f"{name:<28}"
            f" tuples_out="
            f"{counters['tuples_out']:<6}"
            f" comparisons="
            f"{counters['comparisons']:<8}"
            f" reads="
            f"{counters['page_reads']:<6}"
            f" writes="
            f"{counters['page_writes']}"
        )

        lines.append(line)

    return lines


# =============================================================
# Commands
# =============================================================


def run_command(args):

    plan = load_plan_file(
        args.plan
    )

    root = build_operator(
        plan,
        db_dir=args.db,
        frames=args.frames,
    )

    result = execute_operator(
        root
    )

    result["totals"] = (
        plan_totals(
            root
        )
    )

    if args.json:
        print(
            json.dumps(
                result,
                ensure_ascii=False,
            )
        )

    else:
        print(
            "schema:",
            result["schema"],
        )

        for row in result["rows"]:
            print(row)

        print(
            "totals:",
            result["totals"],
        )

    return 0


def trace_command(args):

    plan = load_plan_file(
        args.plan
    )

    root = build_operator(
        plan,
        db_dir=args.db,
        frames=args.frames,
    )

    # Trace is a measurement of an EXECUTED plan,
    # so consume the entire result first.
    execute_operator(
        root
    )

    for line in trace_lines(
        root
    ):
        print(line)

    return 0


# =============================================================
# Argument parser
# =============================================================


def build_parser():

    parser = argparse.ArgumentParser(
        prog="exec",
        description=(
            "COMP 3005 Module 2 "
            "physical-plan executor"
        ),
    )

    subparsers = (
        parser.add_subparsers(
            dest="command",
            required=True,
        )
    )

    # ---------------------------------------------------------
    # exec run
    # ---------------------------------------------------------

    run_parser = (
        subparsers.add_parser(
            "run",
            help=(
                "Execute a physical "
                "plan."
            ),
        )
    )

    run_parser.add_argument(
        "--db",
        required=True,
        help="Database directory.",
    )

    run_parser.add_argument(
        "--plan",
        required=True,
        help="Physical plan JSON file.",
    )

    run_parser.add_argument(
        "--frames",
        required=True,
        type=int,
        help=(
            "Whole-plan buffer "
            "budget B."
        ),
    )

    run_parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Print machine-readable "
            "JSON output."
        ),
    )

    run_parser.set_defaults(
        handler=run_command,
    )

    # ---------------------------------------------------------
    # exec trace
    # ---------------------------------------------------------

    trace_parser = (
        subparsers.add_parser(
            "trace",
            help=(
                "Execute a plan and print "
                "per-node counters."
            ),
        )
    )

    trace_parser.add_argument(
        "--db",
        required=True,
        help="Database directory.",
    )

    trace_parser.add_argument(
        "--plan",
        required=True,
        help="Physical plan JSON file.",
    )

    trace_parser.add_argument(
        "--frames",
        required=True,
        type=int,
        help=(
            "Whole-plan buffer "
            "budget B."
        ),
    )

    trace_parser.set_defaults(
        handler=trace_command,
    )

    return parser


# =============================================================
# Main
# =============================================================


def main(argv=None):

    parser = build_parser()

    args = parser.parse_args(
        argv
    )

    if args.frames < 4:
        print(
            "error: frames must "
            "be at least 4",
            file=sys.stderr,
        )

        return 1

    try:
        return args.handler(
            args
        )

    except (
        PlanError,
        ValueError,
        TypeError,
        RuntimeError,
        OSError,
    ) as exc:

        # Required behavior:
        # reject cleanly rather than dumping
        # a Python stack trace.
        print(
            f"error: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )