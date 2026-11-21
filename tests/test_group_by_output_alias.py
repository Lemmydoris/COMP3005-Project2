import unittest

from execution.base import (
    END,
    Operator,
)
from execution.group_by import GroupBy
from execution.plan import build_operator


class RowSource(Operator):

    def __init__(
        self,
        schema,
        rows,
    ):
        super().__init__()

        self.schema = [
            list(column)
            for column in schema
        ]

        self.rows = [
            tuple(row)
            for row in rows
        ]

        self.index = 0

    def open(self):

        self._reset_counters()
        self.index = 0
        self.is_open = True

    def next(self):

        if not self.is_open:

            raise RuntimeError(
                "RowSource is not open."
            )

        if self.index >= len(
            self.rows
        ):
            return END

        row = self.rows[
            self.index
        ]

        self.index += 1

        self._count_output()

        return row

    def close(self):

        self.is_open = False


class GroupByOutputAliasTests(
    unittest.TestCase
):

    def test_legacy_two_item_aggregate_keeps_default_name(
        self,
    ):

        child = RowSource(
            [
                [
                    "R.a",
                    "INT",
                ],
            ],
            [
                [1],
                [2],
                [3],
            ],
        )

        operator = GroupBy(
            child,
            mode="sort",
            keys=[],
            aggregates=[
                [
                    "count",
                    "*",
                ],
            ],
            frames=4,
        )

        operator.open()

        try:

            self.assertEqual(
                operator.schema,
                [
                    [
                        "count_star",
                        "INT",
                    ],
                ],
            )

            self.assertEqual(
                operator.next(),
                (3,),
            )

        finally:

            operator.close()

    def test_three_item_aggregate_uses_explicit_output_name(
        self,
    ):

        child = RowSource(
            [
                [
                    "R.a",
                    "INT",
                ],
            ],
            [
                [1],
                [2],
                [3],
            ],
        )

        operator = GroupBy(
            child,
            mode="sort",
            keys=[],
            aggregates=[
                [
                    "count",
                    "*",
                    "total",
                ],
            ],
            frames=4,
        )

        operator.open()

        try:

            self.assertEqual(
                operator.schema,
                [
                    [
                        "total",
                        "INT",
                    ],
                ],
            )

            self.assertEqual(
                operator.next(),
                (3,),
            )

        finally:

            operator.close()

    def test_plan_builder_accepts_three_item_aggregate(
        self,
    ):

        plan = {
            "op":
                "group_by",
            "mode":
                "sort",
            "keys":
                [],
            "aggregates": [
                [
                    "count",
                    "*",
                    "total",
                ],
            ],
            "child": {
                "op":
                    "seqscan",
                "table":
                    "R",
            },
        }

        operator = build_operator(
            plan,
            db_dir=".",
            frames=4,
        )

        self.assertIsInstance(
            operator,
            GroupBy,
        )

        self.assertEqual(
            operator.aggregates,
            [
                [
                    "count",
                    "*",
                    "total",
                ],
            ],
        )


if __name__ == "__main__":
    unittest.main()