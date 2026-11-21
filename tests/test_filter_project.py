import unittest
from execution.base import END, Operator
from execution.filter import Filter
from execution.project import Project

class ListSource(Operator):
    """
    Small streaming child used to isolate Filter and Project
    from storage during unit tests.
    """

    def __init__(self, schema, rows):
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
        self.next_calls = 0

    def open(self):
        self.position = 0
        self.next_calls = 0
        self._reset_counters()
        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "ListSource is not open."
            )

        self.next_calls += 1

        if self.position >= len(self.rows):
            return END

        row = self.rows[self.position]
        self.position += 1

        self._count_output()

        return row

    def close(self):
        self.is_open = False


class FilterProjectTests(unittest.TestCase):

    def setUp(self):
        self.schema = [
            ["R.a", "INT"],
            ["R.b", "VARCHAR", 20],
            ["R.c", "INT"],
        ]

        self.rows = [
            (10, "cs", 1),
            (20, "math", 2),
            (30, "cs", 3),
            (40, "history", 4),
        ]

    def test_filter_returns_matching_rows(self):

        source = ListSource(
            self.schema,
            self.rows,
        )

        operator = Filter(
            source,
            "R.a >= 20 and R.b = 'cs'",
        )

        operator.open()

        result = []

        while True:
            row = operator.next()

            if row is END:
                break

            result.append(row)

        operator.close()

        self.assertEqual(
            result,
            [
                (30, "cs", 3),
            ],
        )

    def test_filter_counts_once_per_tuple_examined(self):

        source = ListSource(
            self.schema,
            self.rows,
        )

        operator = Filter(
            source,
            "R.a >= 20 and R.c < 10",
        )

        operator.open()

        while operator.next() is not END:
            pass

        operator.close()

        self.assertEqual(
            operator.counters()["comparisons"],
            4,
        )

    def test_filter_preserves_schema(self):

        source = ListSource(
            self.schema,
            self.rows,
        )

        operator = Filter(
            source,
            "R.a > 10",
        )

        operator.open()

        self.assertEqual(
            operator.schema,
            self.schema,
        )

        operator.close()

    def test_filter_unknown_column_fails_at_open(self):

        source = ListSource(
            self.schema,
            self.rows,
        )

        operator = Filter(
            source,
            "R.missing = 3",
        )

        with self.assertRaisesRegex(
            ValueError,
            "Unknown column",
        ):
            operator.open()

        self.assertFalse(
            source.is_open
        )

    def test_filter_type_mismatch_fails_at_open(self):

        source = ListSource(
            self.schema,
            self.rows,
        )

        operator = Filter(
            source,
            "R.a = '10'",
        )

        with self.assertRaisesRegex(
            TypeError,
            "Cannot compare INT with VARCHAR",
        ):
            operator.open()

    def test_project_keeps_requested_order(self):

        source = ListSource(
            self.schema,
            self.rows,
        )

        operator = Project(
            source,
            [
                "R.c",
                "R.a",
            ],
        )

        operator.open()

        self.assertEqual(
            operator.schema,
            [
                ["R.c", "INT"],
                ["R.a", "INT"],
            ],
        )

        self.assertEqual(
            operator.next(),
            (1, 10),
        )

        operator.close()

    def test_project_preserves_duplicates(self):

        source = ListSource(
            [
                ["R.a", "INT"],
                ["R.b", "VARCHAR", 20],
            ],
            [
                (1, "x"),
                (1, "y"),
                (2, "z"),
                (1, "w"),
            ],
        )

        operator = Project(
            source,
            ["R.a"],
        )

        operator.open()

        result = []

        while True:
            row = operator.next()

            if row is END:
                break

            result.append(row)

        operator.close()

        self.assertEqual(
            result,
            [
                (1,),
                (1,),
                (2,),
                (1,),
            ],
        )

    def test_project_unknown_column_fails_at_open(self):

        source = ListSource(
            self.schema,
            self.rows,
        )

        operator = Project(
            source,
            ["R.missing"],
        )

        with self.assertRaisesRegex(
            ValueError,
            "Unknown column",
        ):
            operator.open()

    def test_project_duplicate_column_is_schema_error(self):

        source = ListSource(
            self.schema,
            self.rows,
        )

        operator = Project(
            source,
            [
                "R.a",
                "R.a",
            ],
        )

        with self.assertRaisesRegex(
            ValueError,
            "Duplicate qualified column name",
        ):
            operator.open()

    def test_filter_and_project_pipeline(self):

        source = ListSource(
            self.schema,
            self.rows,
        )

        filtered = Filter(
            source,
            "R.a >= 20",
        )

        projected = Project(
            filtered,
            [
                "R.b",
                "R.a",
            ],
        )

        projected.open()

        self.assertEqual(
            projected.next(),
            ("math", 20),
        )

        # The pipeline should not have consumed the entire input just to return its first row.
        self.assertEqual(
            source.next_calls,
            2,
        )

        projected.close()

        self.assertFalse(
            source.is_open
        )


if __name__ == "__main__":
    unittest.main()