import os
import tempfile
import unittest

from execution.base import (
    END,
    Operator,
)
from execution.sort_merge_join import (
    SortMergeJoin,
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


class SortMergeJoinTests(unittest.TestCase):

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

        operator = SortMergeJoin(
            ListSource(
                self.left_schema,
                [
                    (3, 30),
                    (1, 10),
                    (2, 20),
                ],
            ),
            ListSource(
                self.right_schema,
                [
                    (4, 400),
                    (2, 200),
                    (3, 300),
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
                (2, 20, 2, 200),
                (3, 30, 3, 300),
            ],
        )

    def test_professor_duplicate_example_returns_four(self):

        left = [
            (1, 10),
            (2, 20),
            (2, 21),
            (3, 30),
        ]

        right = [
            (2, 200),
            (2, 201),
            (4, 400),
        ]

        operator = SortMergeJoin(
            ListSource(
                self.left_schema,
                left,
            ),
            ListSource(
                self.right_schema,
                right,
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

    def test_condition_can_be_reversed(self):

        operator = SortMergeJoin(
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

    def test_inequality_is_rejected(self):

        operator = SortMergeJoin(
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

    def test_same_side_equality_is_rejected(self):

        operator = SortMergeJoin(
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

    def test_type_mismatch_is_rejected(self):

        operator = SortMergeJoin(
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

        operator = SortMergeJoin(
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

        operator = SortMergeJoin(
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

    def test_unknown_column_fails_at_open(self):

        operator = SortMergeJoin(
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

    def test_external_inputs_use_temp_files_and_cleanup(self):

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
            for value in
            [
                8, 3, 7, 1,
                6, 2, 5, 4,
            ]
        ]

        right_rows = [
            (
                value,
                "R" * 1900,
            )
            for value in
            [
                10, 8, 6, 4, 2,
            ]
        ]

        with tempfile.TemporaryDirectory() as temp_dir:

            operator = SortMergeJoin(
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
                [
                    row[0]
                    for row in result
                ],
                [
                    2,
                    4,
                    6,
                    8,
                ],
            )

            counters = (
                operator.counters()
            )

            self.assertGreater(
                counters[
                    "page_reads"
                ],
                0,
            )

            self.assertGreater(
                counters[
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
                for name
                in os.listdir(
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


if __name__ == "__main__":
    unittest.main()