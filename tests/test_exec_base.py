import unittest

from execution.base import (
    END,
    OperatorCounters,
    column_index,
    validate_schema,
)

class ExecutionBaseTests(unittest.TestCase):

    def test_end_is_unique_sentinel(self):
        self.assertIsNotNone(END)

    def test_counters_start_at_zero(self):

        counters = OperatorCounters()

        self.assertEqual(
            counters.as_dict(),
            {
                "tuples_out": 0,
                "comparisons": 0,
                "page_reads": 0,
                "page_writes": 0,
            },
        )

    def test_validate_schema_accepts_unique_qualified_names(self):

        schema = [
            ["R.a", "INT"],
            ["R.b", "VARCHAR", 20],
        ]

        validate_schema(schema)

    def test_validate_schema_rejects_duplicate_qualified_name(self):

        schema = [
            ["R.a", "INT"],
            ["R.a", "INT"],
        ]

        with self.assertRaisesRegex(
            ValueError,
            "Duplicate qualified column name"
        ):
            validate_schema(schema)

    def test_column_index(self):

        schema = [
            ["R.a", "INT"],
            ["R.b", "VARCHAR", 20],
            ["R.c", "INT"],
        ]

        self.assertEqual(
            column_index(schema, "R.b"),
            1,
        )

    def test_column_index_rejects_unknown_column(self):

        schema = [
            ["R.a", "INT"],
        ]

        with self.assertRaisesRegex(
            ValueError,
            "Unknown column"
        ):
            column_index(
                schema,
                "R.missing",
            )


if __name__ == "__main__":
    unittest.main()