import tempfile
import unittest

from execution.plan import build_operator

from optimizer.planner import (
    PhysicalPlanner,
)

from storage.catalog import Catalog


class OptimizerPlannerTests(
    unittest.TestCase
):

    def setUp(self):

        self.temp = (
            tempfile.TemporaryDirectory()
        )

        self.db_dir = (
            self.temp.name
        )

        self.catalog = Catalog(
            self.db_dir
        )

        self.catalog.create_table(
            "R",
            [
                [
                    "a",
                    "INT",
                ],
                [
                    "b",
                    "INT",
                ],
            ],
        )

        self.catalog.create_table(
            "S",
            [
                [
                    "b",
                    "INT",
                ],
                [
                    "c",
                    "INT",
                ],
            ],
        )

        self.catalog.create_table(
            "Emp",
            [
                [
                    "id",
                    "INT",
                ],
                [
                    "did",
                    "INT",
                ],
                [
                    "salary",
                    "INT",
                ],
            ],
        )

        self.catalog.create_table(
            "Dept",
            [
                [
                    "did",
                    "INT",
                ],
                [
                    "budget",
                    "INT",
                ],
            ],
        )

        self.catalog.update_statistics(
            "R",
            {
                "n_tuples":
                    1000,
                "n_pages":
                    20,
                "width":
                    8,
                "columns": {
                    "a": {
                        "ndv":
                            100,
                        "min":
                            1,
                        "max":
                            100,
                        "hist":
                            [],
                    },
                    "b": {
                        "ndv":
                            50,
                        "min":
                            1,
                        "max":
                            50,
                        "hist":
                            [],
                    },
                },
            },
        )

        self.catalog.update_statistics(
            "S",
            {
                "n_tuples":
                    500,
                "n_pages":
                    10,
                "width":
                    8,
                "columns": {
                    "b": {
                        "ndv":
                            50,
                        "min":
                            1,
                        "max":
                            50,
                        "hist":
                            [],
                    },
                    "c": {
                        "ndv":
                            200,
                        "min":
                            1,
                        "max":
                            200,
                        "hist":
                            [],
                    },
                },
            },
        )

        self.catalog.update_statistics(
            "Emp",
            {
                "n_tuples":
                    10000,
                "n_pages":
                    200,
                "width":
                    12,
                "columns": {
                    "id": {
                        "ndv":
                            10000,
                        "hist":
                            [],
                    },
                    "did": {
                        "ndv":
                            50,
                        "hist":
                            [],
                    },
                    "salary": {
                        "ndv":
                            5000,
                        "min":
                            20000,
                        "max":
                            120000,
                        "hist":
                            [],
                    },
                },
            },
        )

        self.catalog.update_statistics(
            "Dept",
            {
                "n_tuples":
                    50,
                "n_pages":
                    1,
                "width":
                    8,
                "columns": {
                    "did": {
                        "ndv":
                            50,
                        "hist":
                            [],
                    },
                    "budget": {
                        "ndv":
                            40,
                        "min":
                            100,
                        "max":
                            10000,
                        "hist":
                            [],
                    },
                },
            },
        )

        self.catalog.flush()

        self.planner = (
            PhysicalPlanner(
                self.db_dir,
                frames=32,
                catalog=
                    self.catalog,
            )
        )

    def tearDown(self):

        self.temp.cleanup()

    def _seqscans(
        self,
        plan,
    ):
        result = []

        if (
            isinstance(
                plan,
                dict,
            )
            and plan.get(
                "op"
            )
            == "seqscan"
        ):
            result.append(
                plan
            )

        if isinstance(
            plan,
            dict,
        ):

            for key in (
                "child",
                "left",
                "right",
            ):

                if key in plan:
                    result.extend(
                        self._seqscans(
                            plan[
                                key
                            ]
                        )
                    )

        return result

    def test_single_table_filter_project_is_physical(
        self,
    ):

        logical = {
            "op":
                "project",
            "columns": [
                "R.a",
            ],
            "child": {
                "op":
                    "select",
                "condition":
                    "R.a > 50",
                "child": {
                    "op":
                        "scan",
                    "table":
                        "R",
                },
            },
        }

        physical = (
            self.planner.plan(
                logical
            )
        )

        # Rewrite rule 6 pushes the projection below
        # the filter. Rule 7 then removes the redundant
        # outer projection.
        self.assertEqual(
            physical[
                "op"
            ],
            "filter",
        )

        self.assertEqual(
            physical[
                "child"
            ][
                "op"
            ],
            "project",
        )

        self.assertEqual(
            physical[
                "child"
            ][
                "child"
            ][
                "op"
            ],
            "seqscan",
        )

        self.assertEqual(
            physical[
                "child"
            ][
                "columns"
            ],
            [
                "R.a",
            ],
        )

        build_operator(
            physical,
            db_dir=
                self.db_dir,
            frames=32,
        )

    def test_base_table_alias_becomes_seqscan_alias(
        self,
    ):

        logical = {
            "op":
                "rename",
            "to":
                "e",
            "child": {
                "op":
                    "scan",
                "table":
                    "Emp",
            },
        }

        physical = (
            self.planner.plan(
                logical
            )
        )

        self.assertEqual(
            physical,
            {
                "op":
                    "seqscan",
                "table":
                    "Emp",
                "alias":
                    "e",
            },
        )

        build_operator(
            physical,
            db_dir=
                self.db_dir,
            frames=32,
        )

    def test_alias_join_emits_module2_join_plan(
        self,
    ):

        logical = {
            "op":
                "join",
            "condition":
                "e.did = d.did",
            "left": {
                "op":
                    "rename",
                "to":
                    "e",
                "child": {
                    "op":
                        "scan",
                    "table":
                        "Emp",
                },
            },
            "right": {
                "op":
                    "rename",
                "to":
                    "d",
                "child": {
                    "op":
                        "scan",
                    "table":
                        "Dept",
                },
            },
        }

        physical = (
            self.planner.plan(
                logical
            )
        )

        self.assertIn(
            physical[
                "op"
            ],
            {
                "nested_loop_join",
                "sort_merge_join",
                "hash_join",
            },
        )

        scans = (
            self._seqscans(
                physical
            )
        )

        aliases = {
            scan.get(
                "alias"
            )
            for scan in scans
        }

        self.assertEqual(
            aliases,
            {
                "e",
                "d",
            },
        )

        build_operator(
            physical,
            db_dir=
                self.db_dir,
            frames=32,
        )

    def test_comma_and_join_forms_produce_same_physical_plan(
        self,
    ):

        comma = {
            "op":
                "select",
            "condition":
                "R.b = S.b",
            "child": {
                "op":
                    "cross",
                "left": {
                    "op":
                        "scan",
                    "table":
                        "R",
                },
                "right": {
                    "op":
                        "scan",
                    "table":
                        "S",
                },
            },
        }

        explicit = {
            "op":
                "join",
            "condition":
                "R.b = S.b",
            "left": {
                "op":
                    "scan",
                "table":
                    "R",
            },
            "right": {
                "op":
                    "scan",
                "table":
                    "S",
            },
        }

        comma_physical = (
            self.planner.plan(
                comma
            )
        )

        explicit_physical = (
            self.planner.plan(
                explicit
            )
        )

        self.assertEqual(
            comma_physical,
            explicit_physical,
        )

    def test_group_by_adds_physical_mode_and_keeps_alias(
        self,
    ):

        logical = {
            "op":
                "group_by",
            "keys": [],
            "aggregates": [
                [
                    "count",
                    "*",
                    "total",
                ],
            ],
            "child": {
                "op":
                    "scan",
                "table":
                    "R",
            },
        }

        physical = (
            self.planner.plan(
                logical
            )
        )

        self.assertEqual(
            physical[
                "op"
            ],
            "group_by",
        )

        self.assertIn(
            physical[
                "mode"
            ],
            {
                "sort",
                "hash",
            },
        )

        self.assertEqual(
            physical[
                "aggregates"
            ],
            [
                [
                    "count",
                    "*",
                    "total",
                ],
            ],
        )

        build_operator(
            physical,
            db_dir=
                self.db_dir,
            frames=32,
        )

    def test_no_statistics_still_produces_valid_plan(
        self,
    ):

        self.catalog.create_table(
            "NoStats",
            [
                [
                    "x",
                    "INT",
                ],
            ],
        )

        logical = {
            "op":
                "project",
            "columns": [
                "NoStats.x",
            ],
            "child": {
                "op":
                    "scan",
                "table":
                    "NoStats",
            },
        }

        physical = (
            self.planner.plan(
                logical
            )
        )

        # The table has only one column, and the project
        # asks for that same one column. Rewrite rule 7
        # correctly removes the no-op projection.
        self.assertEqual(
            physical[
                "op"
            ],
            "seqscan",
        )

        self.assertEqual(
            physical[
                "table"
            ],
            "NoStats",
        )

        build_operator(
            physical,
            db_dir=
                self.db_dir,
            frames=32,
        )

    def test_subquery_alias_executes_with_physical_rename(
        self,
    ):

        logical = {
            "op":
                "rename",
            "to":
                "x",
            "child": {
                "op":
                    "project",
                "columns": [
                    "Emp.did",
                ],
                "child": {
                    "op":
                        "scan",
                    "table":
                        "Emp",
                },
            },
        }

        physical = (
            self.planner.plan(
                logical
            )
        )

        self.assertEqual(
            physical[
                "op"
            ],
            "rename",
        )

        self.assertEqual(
            physical[
                "to"
            ],
            "x",
        )

        operator = build_operator(
            physical,
            db_dir=
                self.db_dir,
            frames=32,
        )

        operator.open()

        try:

            self.assertEqual(
                operator.schema,
                [
                    [
                        "x.did",
                        "INT",
                    ],
                ],
            )

        finally:

            operator.close()

if __name__ == "__main__":
    unittest.main()