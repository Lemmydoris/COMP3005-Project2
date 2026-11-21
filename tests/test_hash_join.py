import os
import tempfile
import unittest
from collections import Counter

from execution.base import END, Operator
from execution.hash_join import HashJoin
from execution.nested_loop_join import NestedLoopJoin
from execution.sort_merge_join import SortMergeJoin


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


class HashJoinTests(unittest.TestCase):

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
        rows = []

        while True:
            row = operator.next()

            if row is END:
                break

            rows.append(row)

        return rows

    def test_basic_equality_join(self):

        operator = HashJoin(
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
            set(result),
            {
                (2, 20, 2, 200),
                (3, 30, 3, 300),
            },
        )

    def test_duplicate_matches_preserve_cross_product(self):

        operator = HashJoin(
            ListSource(
                self.left_schema,
                [
                    (2, 20),
                    (2, 21),
                ],
            ),
            ListSource(
                self.right_schema,
                [
                    (2, 200),
                    (2, 201),
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
                (2, 20, 2, 200),
                (2, 20, 2, 201),
                (2, 21, 2, 200),
                (2, 21, 2, 201),
            },
        )

    def test_reversed_condition(self):

        operator = HashJoin(
            ListSource(
                self.left_schema,
                [
                    (1, 10),
                    (2, 20),
                ],
            ),
            ListSource(
                self.right_schema,
                [
                    (2, 200),
                ],
            ),
            "S.id = R.id",
            frames=4,
        )

        operator.open()

        self.assertEqual(
            self.collect(operator),
            [
                (2, 20, 2, 200),
            ],
        )

        operator.close()

    def test_inequality_rejected(self):

        operator = HashJoin(
            ListSource(
                self.left_schema,
                [],
            ),
            ListSource(
                self.right_schema,
                [],
            ),
            "R.id < S.id",
            frames=4,
        )

        with self.assertRaisesRegex(
            ValueError,
            "requires one equality",
        ):
            operator.open()

    def test_same_side_equality_rejected(self):

        operator = HashJoin(
            ListSource(
                self.left_schema,
                [],
            ),
            ListSource(
                self.right_schema,
                [],
            ),
            "R.id = R.value",
            frames=4,
        )

        with self.assertRaisesRegex(
            ValueError,
            "one left column",
        ):
            operator.open()

    def test_key_type_mismatch_rejected(self):

        operator = HashJoin(
            ListSource(
                self.left_schema,
                [],
            ),
            ListSource(
                [
                    ["S.id", "VARCHAR", 20],
                ],
                [],
            ),
            "R.id = S.id",
            frames=4,
        )

        with self.assertRaisesRegex(
            TypeError,
            "key types must match",
        ):
            operator.open()

    def test_empty_input_returns_cleanly(self):

        operator = HashJoin(
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

        operator.close()

    def test_output_schema_left_then_right(self):

        operator = HashJoin(
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

    def test_external_partitioning_and_cleanup(self):

        left_schema = [
            ["R.id", "INT"],
            ["R.payload", "VARCHAR", 1900],
        ]

        right_schema = [
            ["S.id", "INT"],
            ["S.payload", "VARCHAR", 1900],
        ]

        left_rows = [
            (
                value,
                "L" * 1900,
            )
            for value in range(
                1,
                9,
            )
        ]

        right_rows = [
            (
                value,
                "R" * 1900,
            )
            for value in [
                2, 4, 6, 8,
            ]
        ]

        with tempfile.TemporaryDirectory() as temp_dir:

            operator = HashJoin(
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
                temp_dir=temp_dir,
            )

            operator.open()

            result = self.collect(
                operator
            )

            self.assertEqual(
                {
                    row[0]
                    for row in result
                },
                {
                    2, 4, 6, 8,
                },
            )

            self.assertEqual(
                operator.partition_count,
                3,
            )

            self.assertGreater(
                operator.counters()[
                    "page_reads"
                ],
                0,
            )

            self.assertGreater(
                operator.counters()[
                    "page_writes"
                ],
                0,
            )

            self.assertLessEqual(
                operator.max_frames_held,
                4,
            )

            operator.close()

            leftovers = [
                name
                for name in os.listdir(
                    temp_dir
                )
                if name.startswith(
                    "exec_run_"
                )
            ]

            self.assertEqual(
                leftovers,
                [],
            )

    def test_skew_overflow_uses_bnl_fallback(self):

        left_schema = [
            ["R.id", "INT"],
            ["R.payload", "VARCHAR", 1900],
        ]

        right_schema = [
            ["S.id", "INT"],
            ["S.payload", "VARCHAR", 1900],
        ]

        # Eight large build tuples with exactly the same
        # key produce a build partition larger than B-1
        # pages when B=4.
        left_rows = [
            (
                1,
                f"L{index}".ljust(
                    1900,
                    "x",
                ),
            )
            for index in range(8)
        ]

        right_rows = [
            (
                1,
                f"R{index}".ljust(
                    1900,
                    "y",
                ),
            )
            for index in range(3)
        ]

        with tempfile.TemporaryDirectory() as temp_dir:

            operator = HashJoin(
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
                temp_dir=temp_dir,
            )

            operator.open()

            result = self.collect(
                operator
            )

            # 8 x 3 duplicate-key cross-product.
            self.assertEqual(
                len(result),
                24,
            )

            self.assertGreater(
                operator.overflow_fallbacks,
                0,
            )

            self.assertLessEqual(
                operator.max_frames_held,
                4,
            )

            operator.close()

            leftovers = [
                name
                for name in os.listdir(
                    temp_dir
                )
                if name.startswith(
                    "exec_run_"
                )
            ]

            self.assertEqual(
                leftovers,
                [],
            )

    def test_all_three_joins_return_same_bag(self):

        left_rows = [
            (1, 10),
            (2, 20),
            (2, 21),
            (3, 30),
        ]

        right_rows = [
            (2, 200),
            (2, 201),
            (3, 300),
            (4, 400),
        ]

        nested = NestedLoopJoin(
            ListSource(
                self.left_schema,
                left_rows,
            ),
            ListSource(
                self.right_schema,
                right_rows,
            ),
            "R.id = S.id",
            frames=4,
        )

        merge = SortMergeJoin(
            ListSource(
                self.left_schema,
                left_rows,
            ),
            ListSource(
                self.right_schema,
                right_rows,
            ),
            "R.id = S.id",
            frames=4,
        )

        hashed = HashJoin(
            ListSource(
                self.left_schema,
                left_rows,
            ),
            ListSource(
                self.right_schema,
                right_rows,
            ),
            "R.id = S.id",
            frames=4,
        )

        nested.open()
        merge.open()
        hashed.open()

        nested_rows = self.collect(
            nested
        )

        merge_rows = self.collect(
            merge
        )

        hash_rows = self.collect(
            hashed
        )

        nested.close()
        merge.close()
        hashed.close()

        self.assertEqual(
            Counter(nested_rows),
            Counter(merge_rows),
        )

        self.assertEqual(
            Counter(nested_rows),
            Counter(hash_rows),
        )


if __name__ == "__main__":
    unittest.main()