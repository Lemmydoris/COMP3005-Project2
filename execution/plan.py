import json

from execution.distinct import Distinct
from execution.filter import Filter
from execution.group_by import GroupBy
from execution.hash_join import HashJoin
from execution.limit import Limit
from execution.nested_loop_join import NestedLoopJoin
from execution.project import Project
from execution.rename import Rename
from execution.seqscan import SeqScan
from execution.set_ops import (
    Except,
    Intersect,
    Union,
)
from execution.sort import Sort
from execution.sort_merge_join import SortMergeJoin
from execution.union_all import UnionAll


class PlanError(ValueError):
    pass


def load_plan_file(path):
    try:
        with open(
            path,
            "r",
            encoding="utf-8",
        ) as handle:
            plan = json.load(handle)

    except json.JSONDecodeError as exc:
        raise PlanError(
            "Invalid plan JSON: "
            f"{exc.msg} at line "
            f"{exc.lineno}, column "
            f"{exc.colno}"
        ) from exc

    return plan


def _fail(path, message):
    raise PlanError(
        f"{path}: {message}"
    )


def _require_dict(
    value,
    path,
):
    if not isinstance(
        value,
        dict,
    ):
        _fail(
            path,
            "node must be a JSON object",
        )


def _require_string(
    node,
    field,
    path,
):
    if field not in node:
        _fail(
            path,
            f"missing required field "
            f"'{field}'",
        )

    value = node[field]

    if not isinstance(
        value,
        str,
    ):
        _fail(
            path,
            f"field '{field}' must "
            f"be a string",
        )

    if value == "":
        _fail(
            path,
            f"field '{field}' cannot "
            f"be empty",
        )

    return value


def _require_list(
    node,
    field,
    path,
):
    if field not in node:
        _fail(
            path,
            f"missing required field "
            f"'{field}'",
        )

    value = node[field]

    if not isinstance(
        value,
        list,
    ):
        _fail(
            path,
            f"field '{field}' must "
            f"be a list",
        )

    return value


def _require_int(
    node,
    field,
    path,
):
    if field not in node:
        _fail(
            path,
            f"missing required field "
            f"'{field}'",
        )

    value = node[field]

    if (
        not isinstance(
            value,
            int,
        )
        or isinstance(
            value,
            bool,
        )
    ):
        _fail(
            path,
            f"field '{field}' must "
            f"be an integer",
        )

    return value


def _check_fields(
    node,
    allowed,
    path,
):
    extras = (
        set(node)
        - set(allowed)
    )

    if extras:
        extra = sorted(
            extras
        )[0]

        _fail(
            path,
            f"unexpected field "
            f"'{extra}'",
        )


def _child(
    node,
    db_dir,
    frames,
    temp_dir,
    path,
):
    if "child" not in node:
        _fail(
            path,
            "missing required field "
            "'child'",
        )

    return build_operator(
        node["child"],
        db_dir=db_dir,
        frames=frames,
        temp_dir=temp_dir,
        path=f"{path}.child",
    )


def _binary_children(
    node,
    db_dir,
    frames,
    temp_dir,
    path,
):
    if "left" not in node:
        _fail(
            path,
            "missing required field "
            "'left'",
        )

    if "right" not in node:
        _fail(
            path,
            "missing required field "
            "'right'",
        )

    left = build_operator(
        node["left"],
        db_dir=db_dir,
        frames=frames,
        temp_dir=temp_dir,
        path=f"{path}.left",
    )

    right = build_operator(
        node["right"],
        db_dir=db_dir,
        frames=frames,
        temp_dir=temp_dir,
        path=f"{path}.right",
    )

    return left, right


def build_operator(
    node,
    db_dir,
    frames,
    temp_dir=None,
    path="root",
):
    """
    Build a physical Module 2 operator tree
    from one JSON plan node.

    This validates plan SHAPE here.

    Table names, columns, types and condition
    semantics are validated by operator.open().
    """

    _require_dict(
        node,
        path,
    )

    op = _require_string(
        node,
        "op",
        path,
    )

    # -------------------------------------------------
    # seqscan
    # -------------------------------------------------

    if op == "seqscan":
        _check_fields(
            node,
            {
                "op",
                "table",
                "alias",
            },
            path,
        )

        table = _require_string(
            node,
            "table",
            path,
        )

        alias = None

        if "alias" in node:

            alias = _require_string(
                node,
                "alias",
                path,
            )   

        return SeqScan(
            db_dir,
            table,
            frames=1,
            alias=alias,
        )

        # -------------------------------------------------
    # rename
    # -------------------------------------------------

    if op == "rename":

        _check_fields(
            node,
            {
                "op",
                "to",
                "child",
            },
            path,
        )

        alias = _require_string(
            node,
            "to",
            path,
        )

        child = _child(
            node,
            db_dir,
            frames,
            temp_dir,
            path,
        )

        return Rename(
            child,
            alias,
        )

    # -------------------------------------------------
    # filter
    # -------------------------------------------------

    if op == "filter":
        _check_fields(
            node,
            {
                "op",
                "condition",
                "child",
            },
            path,
        )

        condition = _require_string(
            node,
            "condition",
            path,
        )

        child = _child(
            node,
            db_dir,
            frames,
            temp_dir,
            path,
        )

        return Filter(
            child,
            condition,
        )

    # -------------------------------------------------
    # project
    # -------------------------------------------------

    if op == "project":
        _check_fields(
            node,
            {
                "op",
                "columns",
                "child",
            },
            path,
        )

        columns = _require_list(
            node,
            "columns",
            path,
        )

        for index, column in enumerate(
            columns
        ):
            if not isinstance(
                column,
                str,
            ):
                _fail(
                    path,
                    "project column at "
                    f"index {index} must "
                    f"be a string",
                )

        child = _child(
            node,
            db_dir,
            frames,
            temp_dir,
            path,
        )

        return Project(
            child,
            columns,
        )

    # -------------------------------------------------
    # distinct
    # -------------------------------------------------

    if op == "distinct":
        _check_fields(
            node,
            {
                "op",
                "mode",
                "child",
            },
            path,
        )

        mode = _require_string(
            node,
            "mode",
            path,
        )

        if mode not in (
            "sort",
            "hash",
        ):
            _fail(
                path,
                "distinct mode must be "
                "'sort' or 'hash'",
            )

        child = _child(
            node,
            db_dir,
            frames,
            temp_dir,
            path,
        )

        return Distinct(
            child,
            mode=mode,
            frames=frames,
            temp_dir=temp_dir,
        )

    # -------------------------------------------------
    # sort
    # -------------------------------------------------

    if op == "sort":
        _check_fields(
            node,
            {
                "op",
                "keys",
                "child",
            },
            path,
        )

        keys = _require_list(
            node,
            "keys",
            path,
        )

        for index, key in enumerate(
            keys
        ):
            if (
                not isinstance(
                    key,
                    list,
                )
                or len(key) != 2
            ):
                _fail(
                    path,
                    "sort key at index "
                    f"{index} must be "
                    "[column, direction]",
                )

            if not isinstance(
                key[0],
                str,
            ):
                _fail(
                    path,
                    "sort key column at "
                    f"index {index} must "
                    f"be a string",
                )

            if key[1] not in (
                "asc",
                "desc",
            ):
                _fail(
                    path,
                    "sort direction at "
                    f"index {index} must "
                    f"be 'asc' or 'desc'",
                )

        child = _child(
            node,
            db_dir,
            frames,
            temp_dir,
            path,
        )

        return Sort(
            child,
            keys,
            frames=frames,
            temp_dir=temp_dir,
        )

    # -------------------------------------------------
    # group_by
    # -------------------------------------------------

    if op == "group_by":
        _check_fields(
            node,
            {
                "op",
                "mode",
                "keys",
                "aggregates",
                "child",
            },
            path,
        )

        mode = _require_string(
            node,
            "mode",
            path,
        )

        if mode not in (
            "sort",
            "hash",
        ):
            _fail(
                path,
                "group_by mode must be "
                "'sort' or 'hash'",
            )

        keys = _require_list(
            node,
            "keys",
            path,
        )

        aggregates = _require_list(
            node,
            "aggregates",
            path,
        )

        for index, key in enumerate(
            keys
        ):
            if not isinstance(
                key,
                str,
            ):
                _fail(
                    path,
                    "group_by key at "
                    f"index {index} must "
                    f"be a string",
                )

        for index, aggregate in enumerate(
            aggregates
        ):
            
            if (
                not isinstance(
                    aggregate,
                    list,
                )
                or len(aggregate)
                not in (
                    2,
                    3,
                )
            ):

                _fail(
                path,
                "aggregate at index "
                f"{index} must be "
                "[function, column] or "
                "[function, column, output_name]",
            )

            if (
                not isinstance(
                    aggregate[0],
                    str,
                )
                or
                not isinstance(
                    aggregate[1],
                    str,
                )
            ):
                _fail(
                    path,
                    "aggregate at index "
                    f"{index} must contain "
                    f"strings",
                )
            if len(aggregate) == 3:

                if (
                    not isinstance(
                        aggregate[2],
                        str,
                    )
                    or aggregate[2] == ""
                ):

                    _fail(
                        path,
                        "aggregate output name at "
                        f"index {index} must be "
                        "a non-empty string",
                    )

        child = _child(
            node,
            db_dir,
            frames,
            temp_dir,
            path,
        )

        return GroupBy(
            child,
            mode=mode,
            keys=keys,
            aggregates=aggregates,
            frames=frames,
            temp_dir=temp_dir,
        )

    # -------------------------------------------------
    # joins
    # -------------------------------------------------

    if op in (
        "nested_loop_join",
        "sort_merge_join",
        "hash_join",
    ):
        _check_fields(
            node,
            {
                "op",
                "condition",
                "left",
                "right",
            },
            path,
        )

        condition = _require_string(
            node,
            "condition",
            path,
        )

        left, right = _binary_children(
            node,
            db_dir,
            frames,
            temp_dir,
            path,
        )

        if op == "nested_loop_join":
            return NestedLoopJoin(
                left,
                right,
                condition,
                frames=frames,
            )

        if op == "sort_merge_join":
            return SortMergeJoin(
                left,
                right,
                condition,
                frames=frames,
                temp_dir=temp_dir,
            )

        return HashJoin(
            left,
            right,
            condition,
            frames=frames,
            temp_dir=temp_dir,
        )

    # -------------------------------------------------
    # binary set operators
    # -------------------------------------------------

    if op in (
        "union_all",
        "union",
        "intersect",
        "except",
    ):
        _check_fields(
            node,
            {
                "op",
                "left",
                "right",
            },
            path,
        )

        left, right = _binary_children(
            node,
            db_dir,
            frames,
            temp_dir,
            path,
        )

        if op == "union_all":
            return UnionAll(
                left,
                right,
            )

        if op == "union":
            return Union(
                left,
                right,
                frames=frames,
                temp_dir=temp_dir,
            )

        if op == "intersect":
            return Intersect(
                left,
                right,
                frames=frames,
                temp_dir=temp_dir,
            )

        return Except(
            left,
            right,
            frames=frames,
            temp_dir=temp_dir,
        )

    # -------------------------------------------------
    # limit
    # -------------------------------------------------

    if op == "limit":
        _check_fields(
            node,
            {
                "op",
                "n",
                "child",
            },
            path,
        )

        n = _require_int(
            node,
            "n",
            path,
        )

        if n < 0:
            _fail(
                path,
                "limit n cannot be negative",
            )

        child = _child(
            node,
            db_dir,
            frames,
            temp_dir,
            path,
        )

        return Limit(
            child,
            n,
        )

    _fail(
        path,
        f"unknown physical operator "
        f"'{op}'",
    )
    