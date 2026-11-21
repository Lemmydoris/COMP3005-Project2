import unittest

from execution.base import END, Operator
from execution.nested_loop_join import (
    NestedLoopJoin,
)


class ListSource(Operator):

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

        self.position = 0

    def open(self):
        self.position = 0
        self._reset_counters()
        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "ListSource is not open."
            )

        if self.position >= len(
            self.rows
        ):
            return END

        row = self.rows[
            self.position
        ]

        self.position += 1

        self._count_output()

        return row

    def close(self):
        self.is_open = False

class CountingListSource(ListSource):
    """
    Test source that behaves like ListSource but records
    one page read every time it is opened.

    Because open() resets counters, this lets us verify
    that NestedLoopJoin preserves counters across
    repeated inner rescans.
    """

    def open(self):
        super().open()
        self._count_read()

class NestedLoopJoinTests(unittest.TestCase):

    def setUp(self):

        self.left_schema = [
            ["R.id", "INT"],
            ["R.value", "INT"],
        ]

        self.right_schema = [
            ["S.id", "INT"],
            ["S.value", "INT"],
        ]

    def collect(self, operator):

        result = []

        while True:

            row = operator.next()

            if row is END:
                break

            result.append(row)

        return result

    def test_equality_join(self):

        operator = NestedLoopJoin(
            ListSource(
                self.left_schema,
                [
                    (1, 10),
                    (2, 20),
                    (3, 30),
                ],
            ),
            ListSource(
                self.right_schema,
                [
                    (2, 200),
                    (3, 300),
                    (4, 400),
                ],
            ),
            "R.id = S.id",
            frames=4,
        )

        operator.open()

        result = self.collect(
            operator
        )

        operator.close()

        self.assertEqual(
            result,
            [
                (
                    2, 20,
                    2, 200,
                ),
                (
                    3, 30,
                    3, 300,
                ),
            ],
        )

    def test_duplicate_matches_are_preserved(self):

        operator = NestedLoopJoin(
            ListSource(
                self.left_schema,
                [
                    (2, 10),
                    (2, 20),
                ],
            ),
            ListSource(
                self.right_schema,
                [
                    (2, 100),
                    (2, 200),
                ],
            ),
            "R.id = S.id",
            frames=4,
        )

        operator.open()

        result = self.collect(
            operator
        )

        operator.close()

        self.assertEqual(
            len(result),
            4,
        )

        self.assertEqual(
            set(result),
            {
                (2, 10, 2, 100),
                (2, 20, 2, 100),
                (2, 10, 2, 200),
                (2, 20, 2, 200),
            },
        )

    def test_inequality_condition(self):

        operator = NestedLoopJoin(
            ListSource(
                self.left_schema,
                [
                    (1, 10),
                    (3, 30),
                ],
            ),
            ListSource(
                self.right_schema,
                [
                    (2, 200),
                    (4, 400),
                ],
            ),
            "R.id < S.id",
            frames=4,
        )

        operator.open()

        result = self.collect(
            operator
        )

        operator.close()

        self.assertEqual(
            result,
            [
                (1, 10, 2, 200),
                (1, 10, 4, 400),
                (3, 30, 4, 400),
            ],
        )

    def test_comparisons_are_exact_cartesian_product(self):

        operator = NestedLoopJoin(
            ListSource(
                self.left_schema,
                [
                    (1, 10),
                    (2, 20),
                    (3, 30),
                ],
            ),
            ListSource(
                self.right_schema,
                [
                    (100, 1),
                    (200, 2),
                ],
            ),
            "R.id = S.id",
            frames=4,
        )

        operator.open()

        self.collect(operator)

        self.assertEqual(
            operator.counters()[
                "comparisons"
            ],
            6,
        )

        operator.close()

    def test_comparison_count_independent_of_matches(self):

        operator = NestedLoopJoin(
            ListSource(
                self.left_schema,
                [
                    (1, 1),
                    (1, 2),
                    (1, 3),
                ],
            ),
            ListSource(
                self.right_schema,
                [
                    (1, 4),
                    (1, 5),
                ],
            ),
            "R.id = S.id",
            frames=4,
        )

        operator.open()

        result = self.collect(
            operator
        )

        self.assertEqual(
            len(result),
            6,
        )

        self.assertEqual(
            operator.counters()[
                "comparisons"
            ],
            6,
        )

        operator.close()

    def test_output_schema_is_left_then_right(self):

        operator = NestedLoopJoin(
            ListSource(
                self.left_schema,
                [],
            ),
            ListSource(
                self.right_schema,
                [],
            ),
            "R.id = S.id",
            frames=4,
        )

        operator.open()

        self.assertEqual(
            operator.schema,
            (
                self.left_schema
                + self.right_schema
            ),
        )

        operator.close()

    def test_empty_input_returns_cleanly(self):

        operator = NestedLoopJoin(
            ListSource(
                self.left_schema,
                [],
            ),
            ListSource(
                self.right_schema,
                [
                    (1, 100),
                ],
            ),
            "R.id = S.id",
            frames=4,
        )

        operator.open()

        self.assertIs(
            operator.next(),
            END,
        )

        self.assertEqual(
            operator.counters()[
                "comparisons"
            ],
            0,
        )

        operator.close()

    def test_unknown_condition_column_fails_at_open(self):

        operator = NestedLoopJoin(
            ListSource(
                self.left_schema,
                [],
            ),
            ListSource(
                self.right_schema,
                [],
            ),
            "R.missing = S.id",
            frames=4,
        )

        with self.assertRaisesRegex(
            ValueError,
            "Unknown column",
        ):
            operator.open()

    def test_duplicate_qualified_names_fail_at_open(self):

        operator = NestedLoopJoin(
            ListSource(
                self.left_schema,
                [],
            ),
            ListSource(
                [
                    ["R.id", "INT"],
                    ["S.value", "INT"],
                ],
                [],
            ),
            "R.id = S.value",
            frames=4,
        )

        with self.assertRaisesRegex(
            ValueError,
            "Duplicate qualified",
        ):
            operator.open()

    def test_large_outer_uses_multiple_blocks_at_B4(self):

        left_schema = [
            ["R.id", "INT"],
            ["R.payload", "VARCHAR", 1900],
        ]

        right_schema = [
            ["S.id", "INT"],
        ]

        left_rows = [
            (
                value,
                "x" * 1900,
            )
            for value in range(1, 9)
        ]

        right_rows = [
            (1,),
            (8,),
        ]

        operator = NestedLoopJoin(
            ListSource(
                left_schema,
                left_rows,
            ),
            ListSource(
                right_schema,
                right_rows,
            ),
            "R.id = S.id",
            frames=4,
        )

        operator.open()

        result = self.collect(
            operator
        )

        self.assertEqual(
            [
                row[0]
                for row in result
            ],
            [
                1,
                8,
            ],
        )

        # 8 left x 2 right.
        self.assertEqual(
            operator.counters()[
                "comparisons"
            ],
            16,
        )

        self.assertGreater(
            operator.outer_blocks,
            1,
        )

        self.assertLessEqual(
            operator.max_frames_held,
            4,
        )

        operator.close()

    def test_inner_rescan_counters_accumulate(self):

        left_schema = [
            ["R.id", "INT"],
            ["R.payload", "VARCHAR", 1900],
        ]

        right_schema = [
            ["S.id", "INT"],
        ]

        left_rows = [
            (
                value,
                "x" * 1900,
            )
            for value in range(1, 9)
        ]

        right_rows = [
            (1,),
            (8,),
        ]

        left = ListSource(
            left_schema,
            left_rows,
        )

        right = CountingListSource(
            right_schema,
            right_rows,
        )

        operator = NestedLoopJoin(
            left,
            right,
            "R.id = S.id",
            frames=4,
        )

        operator.open()

        result = self.collect(
            operator
        )

        self.assertEqual(
            [
                row[0]
                for row in result
            ],
            [
                1,
                8,
            ],
        )

        # At B=4 these 8 large outer tuples
        # require exactly two outer blocks.
        self.assertEqual(
            operator.outer_blocks,
            2,
        )

        # The inner source is scanned once per
        # outer block. Each open represents one
        # page read in CountingListSource.
        self.assertEqual(
            right.counters()[
                "page_reads"
            ],
            2,
        )

        # Two inner tuples are returned during
        # each of the two scans.
        self.assertEqual(
            right.counters()[
                "tuples_out"
            ],
            4,
        )

        # 8 left tuples x 2 right tuples.
        self.assertEqual(
            operator.counters()[
                "comparisons"
            ],
            16,
        )

        operator.close()
if __name__ == "__main__":
    unittest.main()