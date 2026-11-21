import unittest

from optimizer.rewrite import (
    LogicalPlanRewriter,
)


class OptimizerRewriteTests(
    unittest.TestCase
):

    def setUp(self):

        self.catalog = {
            "Emp": {
                "schema": [
                    [
                        "name",
                        "VARCHAR",
                        20,
                    ],
                    [
                        "did",
                        "INT",
                    ],
                    [
                        "age",
                        "INT",
                    ],
                ]
            },
            "Dept": {
                "schema": [
                    [
                        "did",
                        "INT",
                    ],
                    [
                        "budget",
                        "INT",
                    ],
                ]
            },
            "A": {
                "schema": [
                    [
                        "x",
                        "INT",
                    ],
                    [
                        "y",
                        "INT",
                    ],
                ]
            },
            "B": {
                "schema": [
                    [
                        "x",
                        "INT",
                    ],
                    [
                        "y",
                        "INT",
                    ],
                ]
            },
        }

        self.rewriter = (
            LogicalPlanRewriter(
                self.catalog
            )
        )

    def test_rule_1_splits_conjunction(
        self,
    ):

        plan = {
            "op": "select",
            "condition":
                "A.x = 1 AND A.y = 2",
            "child": {
                "op": "scan",
                "table": "A",
            },
        }

        result = self.rewriter.rewrite(
            plan,
            disabled_rules={
                2,
                3,
                4,
                5,
                6,
                7,
            },
        )

        self.assertEqual(
            result,
            {
                "op": "select",
                "condition":
                    "A.x = 1",
                "child": {
                    "op": "select",
                    "condition":
                        "A.y = 2",
                    "child": {
                        "op":
                            "scan",
                        "table":
                            "A",
                    },
                },
            },
        )

    def test_rule_2_pushes_one_sided_select(
        self,
    ):

        plan = {
            "op": "select",
            "condition":
                "A.x > 10",
            "child": {
                "op": "join",
                "condition":
                    "A.x = B.x",
                "left": {
                    "op":
                        "scan",
                    "table":
                        "A",
                },
                "right": {
                    "op":
                        "scan",
                    "table":
                        "B",
                },
            },
        }

        result = self.rewriter.rewrite(
            plan,
            disabled_rules={
                1,
                3,
                4,
                5,
                6,
                7,
            },
        )

        self.assertEqual(
            result[
                "op"
            ],
            "join",
        )

        self.assertEqual(
            result[
                "left"
            ][
                "op"
            ],
            "select",
        )

        self.assertEqual(
            result[
                "left"
            ][
                "condition"
            ],
            "A.x > 10",
        )

    def test_rule_3_turns_cross_equality_into_join(
        self,
    ):

        plan = {
            "op": "select",
            "condition":
                "A.x = B.x",
            "child": {
                "op": "cross",
                "left": {
                    "op":
                        "scan",
                    "table":
                        "A",
                },
                "right": {
                    "op":
                        "scan",
                    "table":
                        "B",
                },
            },
        }

        result = self.rewriter.rewrite(
            plan,
            disabled_rules={
                1,
                2,
                4,
                5,
                6,
                7,
            },
        )

        self.assertEqual(
            result,
            {
                "op": "join",
                "condition":
                    "A.x = B.x",
                "left": {
                    "op":
                        "scan",
                    "table":
                        "A",
                },
                "right": {
                    "op":
                        "scan",
                    "table":
                        "B",
                },
            },
        )

    def test_rule_4_pushes_through_rename_and_rewrites_name(
        self,
    ):

        plan = {
            "op": "select",
            "condition":
                "e.age > 60",
            "child": {
                "op": "rename",
                "to": "e",
                "child": {
                    "op":
                        "scan",
                    "table":
                        "Emp",
                },
            },
        }

        result = self.rewriter.rewrite(
            plan,
            disabled_rules={
                1,
                2,
                3,
                5,
                6,
                7,
            },
        )

        self.assertEqual(
            result[
                "op"
            ],
            "rename",
        )

        self.assertEqual(
            result[
                "child"
            ][
                "op"
            ],
            "select",
        )

        self.assertEqual(
            result[
                "child"
            ][
                "condition"
            ],
            "Emp.age > 60",
        )

    def test_rule_4_pushes_union_predicate_into_both_branches(
        self,
    ):

        plan = {
            "op": "select",
            "condition":
                "A.x > 5",
            "child": {
                "op": "union_all",
                "left": {
                    "op":
                        "scan",
                    "table":
                        "A",
                },
                "right": {
                    "op":
                        "scan",
                    "table":
                        "B",
                },
            },
        }

        result = self.rewriter.rewrite(
            plan,
            disabled_rules={
                1,
                2,
                3,
                5,
                6,
                7,
            },
        )

        self.assertEqual(
            result[
                "left"
            ][
                "condition"
            ],
            "A.x > 5",
        )

        self.assertEqual(
            result[
                "right"
            ][
                "condition"
            ],
            "B.x > 5",
        )

    def test_rule_5_pushes_only_grouping_predicate(
        self,
    ):

        group = {
            "op": "group_by",
            "keys": [
                "A.x",
            ],
            "aggregates": [
                [
                    "COUNT",
                    "*",
                    "n",
                ]
            ],
            "child": {
                "op": "scan",
                "table": "A",
            },
        }

        grouping_plan = {
            "op": "select",
            "condition":
                "A.x > 5",
            "child":
                group,
        }

        grouping_result = (
            self.rewriter.rewrite(
                grouping_plan,
                disabled_rules={
                    1,
                    2,
                    3,
                    4,
                    6,
                    7,
                },
            )
        )

        self.assertEqual(
            grouping_result[
                "op"
            ],
            "group_by",
        )

        self.assertEqual(
            grouping_result[
                "child"
            ][
                "op"
            ],
            "select",
        )

        aggregate_plan = {
            "op": "select",
            "condition":
                "n > 5",
            "child":
                group,
        }

        aggregate_result = (
            self.rewriter.rewrite(
                aggregate_plan,
                disabled_rules={
                    1,
                    2,
                    3,
                    4,
                    6,
                    7,
                },
            )
        )

        self.assertEqual(
            aggregate_result[
                "op"
            ],
            "select",
        )

        self.assertEqual(
            aggregate_result[
                "child"
            ][
                "op"
            ],
            "group_by",
        )

    def test_rule_7_removes_noop_project_and_collapses_selects(
        self,
    ):

        plan = {
            "op": "project",
            "columns": [
                "A.x",
                "A.y",
            ],
            "child": {
                "op": "select",
                "condition":
                    "A.x > 1",
                "child": {
                    "op": "select",
                    "condition":
                        "A.y < 9",
                    "child": {
                        "op":
                            "scan",
                        "table":
                            "A",
                    },
                },
            },
        }

        result = self.rewriter.rewrite(
            plan,
            disabled_rules={
                1,
                2,
                3,
                4,
                5,
                6,
            },
        )

        self.assertEqual(
            result[
                "op"
            ],
            "select",
        )

        self.assertIn(
            "A.x > 1",
            result[
                "condition"
            ],
        )

        self.assertIn(
            "A.y < 9",
            result[
                "condition"
            ],
        )

        self.assertEqual(
            result[
                "child"
            ][
                "op"
            ],
            "scan",
        )

    def test_professor_comma_join_worked_example(
        self,
    ):

        # Logical plan emitted by Module 3 for:
        #
        # SELECT e.name
        # FROM Emp e, Dept d
        # WHERE e.did = d.did
        #   AND e.age > 60
        #   AND d.budget > 1000;

        before = {
            "op": "project",
            "columns": [
                "e.name",
            ],
            "child": {
                "op": "select",
                "condition": (
                    "e.did = d.did "
                    "AND e.age > 60 "
                    "AND d.budget > 1000"
                ),
                "child": {
                    "op": "cross",
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
                },
            },
        }

        after = (
            self.rewriter.rewrite(
                before
            )
        )

        expected = {
            "op":
                "project",
            "columns": [
                "e.name",
            ],
            "child": {
                "op":
                    "join",
                "condition":
                    "e.did = d.did",
                "left": {
                    "op":
                        "project",
                    "columns": [
                        "e.name",
                        "e.did",
                    ],
                    "child": {
                        "op":
                            "select",
                        "condition":
                            "e.age > 60",
                        "child": {
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
                    },
                },
                "right": {
                    "op":
                        "project",
                    "columns": [
                        "d.did",
                    ],
                    "child": {
                        "op":
                            "select",
                        "condition":
                            "d.budget > 1000",
                        "child": {
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
                    },
                },
            },
        }

        self.assertEqual(
            after,
            expected,
        )

    def test_disabling_rule_3_keeps_cross(
        self,
    ):

        plan = {
            "op": "select",
            "condition":
                "A.x = B.x",
            "child": {
                "op": "cross",
                "left": {
                    "op":
                        "scan",
                    "table":
                        "A",
                },
                "right": {
                    "op":
                        "scan",
                    "table":
                        "B",
                },
            },
        }

        result = self.rewriter.rewrite(
            plan,
            disabled_rules={
                3,
                6,
                7,
            },
        )

        self.assertEqual(
            result[
                "op"
            ],
            "select",
        )

        self.assertEqual(
            result[
                "child"
            ][
                "op"
            ],
            "cross",
        )


if __name__ == "__main__":
    unittest.main()