import json
import os
import tempfile
import unittest

from execution.distinct import Distinct
from execution.filter import Filter
from execution.group_by import GroupBy
from execution.hash_join import HashJoin
from execution.limit import Limit
from execution.plan import (
    PlanError,
    build_operator,
    load_plan_file,
)
from execution.project import Project
from execution.seqscan import SeqScan
from execution.set_ops import (
    Intersect,
    Union,
)
from execution.sort import Sort
from execution.union_all import UnionAll


class PlanBuilderTests(unittest.TestCase):

    def test_seqscan_builds(self):

        operator = build_operator(
            {
                "op": "seqscan",
                "table": "R",
            },
            db_dir="fake-db",
            frames=4,
        )

        self.assertIsInstance(
            operator,
            SeqScan,
        )

        self.assertEqual(
            operator.frames,
            1,
        )

    def test_filter_project_pipeline_builds(self):

        operator = build_operator(
            {
                "op": "project",
                "columns": [
                    "R.a",
                ],
                "child": {
                    "op": "filter",
                    "condition": "R.a > 10",
                    "child": {
                        "op": "seqscan",
                        "table": "R",
                    },
                },
            },
            db_dir="fake-db",
            frames=4,
        )

        self.assertIsInstance(
            operator,
            Project,
        )

        self.assertIsInstance(
            operator.child,
            Filter,
        )

        self.assertIsInstance(
            operator.child.child,
            SeqScan,
        )

    def test_sort_builds_with_plan_frames(self):

        operator = build_operator(
            {
                "op": "sort",
                "keys": [
                    [
                        "R.a",
                        "asc",
                    ],
                ],
                "child": {
                    "op": "seqscan",
                    "table": "R",
                },
            },
            db_dir="db",
            frames=16,
        )

        self.assertIsInstance(
            operator,
            Sort,
        )

        self.assertEqual(
            operator.frames,
            16,
        )

    def test_distinct_hash_builds(self):

        operator = build_operator(
            {
                "op": "distinct",
                "mode": "hash",
                "child": {
                    "op": "seqscan",
                    "table": "R",
                },
            },
            db_dir="db",
            frames=8,
        )

        self.assertIsInstance(
            operator,
            Distinct,
        )

        self.assertEqual(
            operator.mode,
            "hash",
        )

    def test_group_by_builds(self):

        operator = build_operator(
            {
                "op": "group_by",
                "mode": "sort",
                "keys": [
                    "R.dept",
                ],
                "aggregates": [
                    [
                        "count",
                        "*",
                    ],
                    [
                        "avg",
                        "R.salary",
                    ],
                ],
                "child": {
                    "op": "seqscan",
                    "table": "R",
                },
            },
            db_dir="db",
            frames=4,
        )

        self.assertIsInstance(
            operator,
            GroupBy,
        )

    def test_hash_join_builds(self):

        operator = build_operator(
            {
                "op": "hash_join",
                "condition":
                    "R.id = S.id",
                "left": {
                    "op": "seqscan",
                    "table": "R",
                },
                "right": {
                    "op": "seqscan",
                    "table": "S",
                },
            },
            db_dir="db",
            frames=4,
        )

        self.assertIsInstance(
            operator,
            HashJoin,
        )

    def test_union_all_builds(self):

        operator = build_operator(
            {
                "op": "union_all",
                "left": {
                    "op": "seqscan",
                    "table": "R",
                },
                "right": {
                    "op": "seqscan",
                    "table": "S",
                },
            },
            db_dir="db",
            frames=4,
        )

        self.assertIsInstance(
            operator,
            UnionAll,
        )

    def test_union_and_intersect_build(self):

        union = build_operator(
            {
                "op": "union",
                "left": {
                    "op": "seqscan",
                    "table": "R",
                },
                "right": {
                    "op": "seqscan",
                    "table": "S",
                },
            },
            db_dir="db",
            frames=4,
        )

        intersect = build_operator(
            {
                "op": "intersect",
                "left": {
                    "op": "seqscan",
                    "table": "R",
                },
                "right": {
                    "op": "seqscan",
                    "table": "S",
                },
            },
            db_dir="db",
            frames=4,
        )

        self.assertIsInstance(
            union,
            Union,
        )

        self.assertIsInstance(
            intersect,
            Intersect,
        )

    def test_limit_builds(self):

        operator = build_operator(
            {
                "op": "limit",
                "n": 5,
                "child": {
                    "op": "seqscan",
                    "table": "R",
                },
            },
            db_dir="db",
            frames=4,
        )

        self.assertIsInstance(
            operator,
            Limit,
        )

        self.assertEqual(
            operator.limit,
            5,
        )

    def test_unknown_operator_rejected(self):

        with self.assertRaisesRegex(
            PlanError,
            "root.*unknown physical",
        ):
            build_operator(
                {
                    "op": "magic_join",
                },
                db_dir="db",
                frames=4,
            )

    def test_missing_child_names_node(self):

        with self.assertRaisesRegex(
            PlanError,
            "root.*missing required field 'child'",
        ):
            build_operator(
                {
                    "op": "filter",
                    "condition": "R.a = 1",
                },
                db_dir="db",
                frames=4,
            )

    def test_nested_error_has_path(self):

        with self.assertRaisesRegex(
            PlanError,
            "root.child.*missing required field 'table'",
        ):
            build_operator(
                {
                    "op": "project",
                    "columns": [
                        "R.a",
                    ],
                    "child": {
                        "op": "seqscan",
                    },
                },
                db_dir="db",
                frames=4,
            )

    def test_unexpected_field_rejected(self):

        with self.assertRaisesRegex(
            PlanError,
            "unexpected field 'banana'",
        ):
            build_operator(
                {
                    "op": "seqscan",
                    "table": "R",
                    "banana": 7,
                },
                db_dir="db",
                frames=4,
            )

    def test_bad_sort_direction_rejected(self):

        with self.assertRaisesRegex(
            PlanError,
            "sort direction",
        ):
            build_operator(
                {
                    "op": "sort",
                    "keys": [
                        [
                            "R.a",
                            "sideways",
                        ],
                    ],
                    "child": {
                        "op": "seqscan",
                        "table": "R",
                    },
                },
                db_dir="db",
                frames=4,
            )

    def test_load_plan_file(self):

        with tempfile.TemporaryDirectory() as temp_dir:

            path = os.path.join(
                temp_dir,
                "plan.json",
            )

            plan = {
                "op": "seqscan",
                "table": "R",
            }

            with open(
                path,
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    plan,
                    handle,
                )

            self.assertEqual(
                load_plan_file(path),
                plan,
            )

    def test_invalid_json_rejected(self):

        with tempfile.TemporaryDirectory() as temp_dir:

            path = os.path.join(
                temp_dir,
                "bad.json",
            )

            with open(
                path,
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    '{"op": "seqscan",'
                )

            with self.assertRaisesRegex(
                PlanError,
                "Invalid plan JSON",
            ):
                load_plan_file(
                    path
                )


if __name__ == "__main__":
    unittest.main()