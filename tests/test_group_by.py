import tempfile
import unittest
import os
from execution.base import END, Operator
from execution.group_by import GroupBy

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


class GroupByTests(unittest.TestCase):

    def setUp(self):
        self.schema = [
            ["R.dept", "VARCHAR", 20],
            ["R.salary", "INT"],
            ["R.name", "VARCHAR", 20],
        ]

        self.rows = [
            ("cs", 100, "bob"),
            ("math", 80, "amy"),
            ("cs", 200, "zoe"),
            ("math", 120, "dan"),
            ("cs", 300, "ann"),
        ]

    def collect(self, operator):
        result = []

        while True:
            row = operator.next()

            if row is END:
                break

            result.append(row)

        return result

    def test_sort_group_by_count(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                self.rows,
            ),
            mode="sort",
            keys=["R.dept"],
            aggregates=[
                ["count", "*"],
            ],
            frames=4,
        )

        operator.open()

        self.assertEqual(
            self.collect(operator),
            [
                ("cs", 3),
                ("math", 2),
            ],
        )

        operator.close()

    def test_sort_group_by_all_aggregates(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                self.rows,
            ),
            mode="sort",
            keys=["R.dept"],
            aggregates=[
                ["count", "*"],
                ["sum", "R.salary"],
                ["avg", "R.salary"],
                ["min", "R.name"],
                ["max", "R.name"],
            ],
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
                    "cs",
                    3,
                    600,
                    200.0,
                    "ann",
                    "zoe",
                ),
                (
                    "math",
                    2,
                    200,
                    100.0,
                    "amy",
                    "dan",
                ),
            ],
        )

    def test_output_schema(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                self.rows,
            ),
            mode="sort",
            keys=["R.dept"],
            aggregates=[
                ["count", "*"],
                ["avg", "R.salary"],
                ["max", "R.name"],
            ],
            frames=4,
        )

        operator.open()

        self.assertEqual(
            operator.schema,
            [
                [
                    "R.dept",
                    "VARCHAR",
                    20,
                ],
                [
                    "count_star",
                    "INT",
                ],
                [
                    "avg_R_salary",
                    "REAL",
                ],
                [
                    "max_R_name",
                    "VARCHAR",
                ],
            ],
        )

        operator.close()

    def test_global_count(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                self.rows,
            ),
            mode="sort",
            keys=[],
            aggregates=[
                ["count", "*"],
            ],
            frames=4,
        )

        operator.open()

        self.assertEqual(
            operator.next(),
            (5,),
        )

        self.assertIs(
            operator.next(),
            END,
        )

        operator.close()

    def test_empty_global_count_is_zero(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                [],
            ),
            mode="sort",
            keys=[],
            aggregates=[
                ["count", "*"],
            ],
            frames=4,
        )

        operator.open()

        self.assertEqual(
            operator.next(),
            (0,),
        )

        self.assertIs(
            operator.next(),
            END,
        )

        operator.close()

    def test_empty_global_non_count_is_error(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                [],
            ),
            mode="sort",
            keys=[],
            aggregates=[
                ["sum", "R.salary"],
            ],
            frames=4,
        )

        with self.assertRaisesRegex(
            ValueError,
            "undefined for empty input",
        ):
            operator.open()

    def test_empty_with_grouping_keys_returns_zero_rows(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                [],
            ),
            mode="sort",
            keys=["R.dept"],
            aggregates=[
                ["count", "*"],
            ],
            frames=4,
        )

        operator.open()

        self.assertIs(
            operator.next(),
            END,
        )

        operator.close()

    def test_sum_requires_int(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                self.rows,
            ),
            mode="sort",
            keys=["R.dept"],
            aggregates=[
                ["sum", "R.name"],
            ],
            frames=4,
        )

        with self.assertRaisesRegex(
            TypeError,
            "SUM requires an INT",
        ):
            operator.open()

    def test_avg_requires_int(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                self.rows,
            ),
            mode="sort",
            keys=["R.dept"],
            aggregates=[
                ["avg", "R.name"],
            ],
            frames=4,
        )

        with self.assertRaisesRegex(
            TypeError,
            "AVG requires an INT",
        ):
            operator.open()

    def test_external_sort_grouping(self):

        schema = [
            ["R.dept", "VARCHAR", 20],
            ["R.salary", "INT"],
            ["R.payload", "VARCHAR", 1900],
        ]

        rows = [
            ("b", 10, "x" * 1900),
            ("a", 20, "x" * 1900),
            ("b", 30, "x" * 1900),
            ("a", 40, "x" * 1900),
            ("c", 50, "x" * 1900),
            ("a", 60, "x" * 1900),
            ("c", 70, "x" * 1900),
            ("b", 80, "x" * 1900),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:

            operator = GroupBy(
                ListSource(
                    schema,
                    rows,
                ),
                mode="sort",
                keys=["R.dept"],
                aggregates=[
                    ["count", "*"],
                    ["sum", "R.salary"],
                ],
                frames=3,
                temp_dir=temp_dir,
            )

            operator.open()

            self.assertEqual(
                self.collect(operator),
                [
                    ("a", 3, 120),
                    ("b", 3, 120),
                    ("c", 2, 120),
                ],
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

            operator.close()

    def test_hash_group_by_count(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                self.rows,
            ),
            mode="hash",
            keys=["R.dept"],
            aggregates=[
                ["count", "*"],
            ],
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
                ("cs", 3),
                ("math", 2),
            },
        )

    def test_hash_group_by_all_aggregates(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                self.rows,
            ),
            mode="hash",
            keys=["R.dept"],
            aggregates=[
                ["count", "*"],
                ["sum", "R.salary"],
                ["avg", "R.salary"],
                ["min", "R.name"],
                ["max", "R.name"],
            ],
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
                (
                    "cs",
                    3,
                    600,
                    200.0,
                    "ann",
                    "zoe",
                ),
                (
                    "math",
                    2,
                    200,
                    100.0,
                    "amy",
                    "dan",
                ),
            },
        )

    def test_hash_and_sort_group_by_same_results(self):

        sort_operator = GroupBy(
            ListSource(
                self.schema,
                self.rows,
            ),
            mode="sort",
            keys=["R.dept"],
            aggregates=[
                ["count", "*"],
                ["sum", "R.salary"],
                ["max", "R.name"],
            ],
            frames=4,
        )

        hash_operator = GroupBy(
            ListSource(
                self.schema,
                self.rows,
            ),
            mode="hash",
            keys=["R.dept"],
            aggregates=[
                ["count", "*"],
                ["sum", "R.salary"],
                ["max", "R.name"],
            ],
            frames=4,
        )

        sort_operator.open()
        hash_operator.open()

        sort_result = (
            self.collect(
                sort_operator
            )
        )

        hash_result = (
            self.collect(
                hash_operator
            )
        )

        sort_operator.close()
        hash_operator.close()

        self.assertEqual(
            set(sort_result),
            set(hash_result),
        )

    def test_hash_group_by_empty_with_keys(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                [],
            ),
            mode="hash",
            keys=["R.dept"],
            aggregates=[
                ["count", "*"],
            ],
            frames=4,
        )

        operator.open()

        self.assertIs(
            operator.next(),
            END,
        )

        operator.close()

    def test_hash_global_count_empty_is_zero(self):

        operator = GroupBy(
            ListSource(
                self.schema,
                [],
            ),
            mode="hash",
            keys=[],
            aggregates=[
                ["count", "*"],
            ],
            frames=4,
        )

        operator.open()

        self.assertEqual(
            operator.next(),
            (0,),
        )

        self.assertIs(
            operator.next(),
            END,
        )

        operator.close()

    def test_hash_group_by_uses_disk_partitions(self):

        schema = [
            ["R.dept", "VARCHAR", 20],
            ["R.salary", "INT"],
            ["R.payload", "VARCHAR", 1900],
        ]

        rows = [
            ("a", 10, "x" * 1900),
            ("b", 20, "x" * 1900),
            ("c", 30, "x" * 1900),
            ("a", 40, "x" * 1900),
            ("b", 50, "x" * 1900),
            ("d", 60, "x" * 1900),
            ("c", 70, "x" * 1900),
            ("d", 80, "x" * 1900),
        ]

        with tempfile.TemporaryDirectory() as temp_dir:

            operator = GroupBy(
                ListSource(
                    schema,
                    rows,
                ),
                mode="hash",
                keys=["R.dept"],
                aggregates=[
                    ["count", "*"],
                    ["sum", "R.salary"],
                ],
                frames=4,
                temp_dir=temp_dir,
            )

            operator.open()

            result = self.collect(
                operator
            )

            self.assertEqual(
                set(result),
                {
                    ("a", 2, 50),
                    ("b", 2, 70),
                    ("c", 2, 100),
                    ("d", 2, 140),
                },
            )

            self.assertGreater(
                operator.partition_count,
                0,
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
                operator.max_hash_frames_held,
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