import os
import tempfile
import unittest

from execution.base import END, Operator
from execution.distinct import Distinct

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


class DistinctTests(unittest.TestCase):

    def setUp(self):

        self.schema = [
            ["R.a", "INT"],
            ["R.b", "VARCHAR", 20],
        ]

    def collect(self, operator):

        rows = []

        while True:
            row = operator.next()

            if row is END:
                break

            rows.append(row)

        return rows

    def test_sort_distinct_removes_duplicates(self):

        source = ListSource(
            self.schema,
            [
                (2, "b"),
                (1, "a"),
                (2, "b"),
                (1, "a"),
                (3, "c"),
            ],
        )

        operator = Distinct(
            source,
            mode="sort",
            frames=4,
        )

        operator.open()

        self.assertEqual(
            self.collect(operator),
            [
                (1, "a"),
                (2, "b"),
                (3, "c"),
            ],
        )

        operator.close()

    def test_sort_distinct_keeps_schema(self):

        operator = Distinct(
            ListSource(
                self.schema,
                [(1, "a")],
            ),
            mode="sort",
            frames=4,
        )

        operator.open()

        self.assertEqual(
            operator.schema,
            self.schema,
        )

        operator.close()

    def test_sort_distinct_empty_input(self):

        operator = Distinct(
            ListSource(
                self.schema,
                [],
            ),
            mode="sort",
            frames=4,
        )

        operator.open()

        self.assertIs(
            operator.next(),
            END,
        )

        self.assertEqual(
            operator.counters()[
                "tuples_out"
            ],
            0,
        )

        operator.close()

    def test_sort_distinct_external_input(self):

        schema = [
            ["R.a", "INT"],
            ["R.payload", "VARCHAR", 1900],
        ]

        rows = []

        for value in [
            8, 3, 7, 1,
            6, 2, 5, 4,
            3, 1, 8, 4,
        ]:
            rows.append(
                (
                    value,
                    "x" * 1900,
                )
            )

        with tempfile.TemporaryDirectory() as temp_dir:

            operator = Distinct(
                ListSource(
                    schema,
                    rows,
                ),
                mode="sort",
                frames=3,
                temp_dir=temp_dir,
            )

            operator.open()

            result = self.collect(
                operator
            )

            self.assertEqual(
                [row[0] for row in result],
                [
                    1, 2, 3, 4,
                    5, 6, 7, 8,
                ],
            )

            counters = operator.counters()

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

    def test_sort_distinct_counts_only_unique_output(self):

        operator = Distinct(
            ListSource(
                self.schema,
                [
                    (1, "a"),
                    (1, "a"),
                    (1, "a"),
                    (2, "b"),
                ],
            ),
            mode="sort",
            frames=4,
        )

        operator.open()

        self.collect(operator)

        self.assertEqual(
            operator.counters()[
                "tuples_out"
            ],
            2,
        )

        operator.close()

    def test_invalid_mode_fails_at_open(self):

        operator = Distinct(
            ListSource(
                self.schema,
                [(1, "a")],
            ),
            mode="banana",
            frames=4,
        )

        with self.assertRaisesRegex(
            ValueError,
            "Invalid distinct mode",
        ):
            operator.open()

    def test_hash_distinct_removes_duplicates(self):

        operator = Distinct(
            ListSource(
                self.schema,
                [
                    (3, "c"),
                    (1, "a"),
                    (2, "b"),
                    (1, "a"),
                    (3, "c"),
                    (2, "b"),
                ],
            ),
            mode="hash",
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
                (1, "a"),
                (2, "b"),
                (3, "c"),
            },
        )

        self.assertEqual(
            len(result),
            3,
        )

    def test_hash_distinct_empty_input(self):

        operator = Distinct(
            ListSource(
                self.schema,
                [],
            ),
            mode="hash",
            frames=4,
        )

        operator.open()

        self.assertIs(
            operator.next(),
            END,
        )

        operator.close()

    def test_hash_distinct_uses_disk_partitions(self):

        schema = [
            ["R.a", "INT"],
            ["R.payload", "VARCHAR", 1900],
        ]

        rows = [
            (
                value,
                "x" * 1900,
            )
            for value in
            [
                1, 2, 3, 4,
                5, 6, 7, 8,
                1, 2, 3, 4,
            ]
        ]

        with tempfile.TemporaryDirectory() as temp_dir:

            operator = Distinct(
                ListSource(
                    schema,
                    rows,
                ),
                mode="hash",
                frames=4,
                temp_dir=temp_dir,
            )

            operator.open()

            result = self.collect(
                operator
            )

            self.assertEqual(
                len(result),
                8,
            )

            self.assertGreater(
                operator.partition_count,
                0,
            )

            self.assertGreater(
                operator.counters()[
                    "page_writes"
                ],
                0,
            )

            self.assertGreater(
                operator.counters()[
                    "page_reads"
                ],
                0,
            )

            self.assertLessEqual(
                operator.max_hash_frames_held,
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

    def test_hash_and_sort_distinct_same_set(self):

        rows = [
            (4, "d"),
            (1, "a"),
            (3, "c"),
            (1, "a"),
            (2, "b"),
            (4, "d"),
            (2, "b"),
        ]

        sort_operator = Distinct(
            ListSource(
                self.schema,
                rows,
            ),
            mode="sort",
            frames=4,
        )

        hash_operator = Distinct(
            ListSource(
                self.schema,
                rows,
            ),
            mode="hash",
            frames=4,
        )

        sort_operator.open()
        hash_operator.open()

        sort_result = self.collect(
            sort_operator
        )

        hash_result = self.collect(
            hash_operator
        )

        sort_operator.close()
        hash_operator.close()

        self.assertEqual(
            set(sort_result),
            set(hash_result),
        )

    def test_hash_distinct_requires_four_frames(self):

        operator = Distinct(
            ListSource(
                self.schema,
                [(1, "a")],
            ),
            mode="hash",
            frames=3,
        )

        with self.assertRaisesRegex(
            ValueError,
            "at least 4 frames",
        ):
            operator.open()
            
if __name__ == "__main__":
    unittest.main()