import unittest

from execution.base import END, Operator
from execution.limit import Limit
from execution.union_all import UnionAll


class TrackingSource(Operator):

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
        self.next_calls = 0

    def open(self):
        self.position = 0
        self.next_calls = 0
        self._reset_counters()
        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "TrackingSource is not open."
            )

        self.next_calls += 1

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


class UnionAllLimitTests(unittest.TestCase):

    def setUp(self):
        self.left_schema = [
            ["R.a", "INT"],
            ["R.b", "VARCHAR", 20],
        ]

        self.right_schema = [
            ["S.x", "INT"],
            ["S.y", "VARCHAR", 20],
        ]

    def collect(self, operator):
        rows = []

        while True:
            row = operator.next()

            if row is END:
                break

            rows.append(row)

        return rows

    def test_union_all_concatenates(self):

        operator = UnionAll(
            TrackingSource(
                self.left_schema,
                [
                    (1, "a"),
                    (2, "b"),
                ],
            ),
            TrackingSource(
                self.right_schema,
                [
                    (3, "c"),
                    (4, "d"),
                ],
            ),
        )

        operator.open()

        self.assertEqual(
            self.collect(operator),
            [
                (1, "a"),
                (2, "b"),
                (3, "c"),
                (4, "d"),
            ],
        )

        operator.close()

    def test_union_all_preserves_duplicates(self):

        operator = UnionAll(
            TrackingSource(
                self.left_schema,
                [
                    (1, "a"),
                    (1, "a"),
                ],
            ),
            TrackingSource(
                self.right_schema,
                [
                    (1, "a"),
                ],
            ),
        )

        operator.open()

        self.assertEqual(
            self.collect(operator),
            [
                (1, "a"),
                (1, "a"),
                (1, "a"),
            ],
        )

        operator.close()

    def test_union_all_uses_left_schema_names(self):

        operator = UnionAll(
            TrackingSource(
                self.left_schema,
                [(1, "a")],
            ),
            TrackingSource(
                self.right_schema,
                [(2, "b")],
            ),
        )

        operator.open()

        self.assertEqual(
            operator.schema,
            self.left_schema,
        )

        operator.close()

    def test_union_all_rejects_column_count_mismatch(self):

        operator = UnionAll(
            TrackingSource(
                self.left_schema,
                [(1, "a")],
            ),
            TrackingSource(
                [
                    ["S.x", "INT"],
                ],
                [(2,)],
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "same number of columns",
        ):
            operator.open()

    def test_union_all_rejects_type_mismatch(self):

        operator = UnionAll(
            TrackingSource(
                self.left_schema,
                [(1, "a")],
            ),
            TrackingSource(
                [
                    ["S.x", "VARCHAR", 20],
                    ["S.y", "VARCHAR", 20],
                ],
                [
                    ("1", "a"),
                ],
            ),
        )

        with self.assertRaisesRegex(
            TypeError,
            "type mismatch",
        ):
            operator.open()

    def test_limit_returns_first_n(self):

        source = TrackingSource(
            self.left_schema,
            [
                (1, "a"),
                (2, "b"),
                (3, "c"),
                (4, "d"),
            ],
        )

        operator = Limit(
            source,
            2,
        )

        operator.open()

        self.assertEqual(
            self.collect(operator),
            [
                (1, "a"),
                (2, "b"),
            ],
        )

        operator.close()

    def test_limit_actually_stops_pulling_child(self):

        source = TrackingSource(
            self.left_schema,
            [
                (1, "a"),
                (2, "b"),
                (3, "c"),
                (4, "d"),
                (5, "e"),
            ],
        )

        operator = Limit(
            source,
            2,
        )

        operator.open()

        self.assertEqual(
            operator.next(),
            (1, "a"),
        )

        self.assertEqual(
            operator.next(),
            (2, "b"),
        )

        self.assertIs(
            operator.next(),
            END,
        )

        # This is the key requirement.
        # Only TWO child tuples were requested.
        self.assertEqual(
            source.next_calls,
            2,
        )

        # Repeated END must still not pull.
        self.assertIs(
            operator.next(),
            END,
        )

        self.assertEqual(
            source.next_calls,
            2,
        )

        operator.close()

    def test_limit_zero_never_pulls_child(self):

        source = TrackingSource(
            self.left_schema,
            [
                (1, "a"),
                (2, "b"),
            ],
        )

        operator = Limit(
            source,
            0,
        )

        operator.open()

        self.assertIs(
            operator.next(),
            END,
        )

        self.assertEqual(
            source.next_calls,
            0,
        )

        operator.close()

    def test_limit_larger_than_input(self):

        source = TrackingSource(
            self.left_schema,
            [
                (1, "a"),
                (2, "b"),
            ],
        )

        operator = Limit(
            source,
            10,
        )

        operator.open()

        self.assertEqual(
            self.collect(operator),
            [
                (1, "a"),
                (2, "b"),
            ],
        )

        operator.close()

    def test_limit_rejects_negative_value(self):

        operator = Limit(
            TrackingSource(
                self.left_schema,
                [],
            ),
            -1,
        )

        with self.assertRaisesRegex(
            ValueError,
            "cannot be negative",
        ):
            operator.open()

    def test_limit_has_no_own_io_or_comparisons(self):

        operator = Limit(
            TrackingSource(
                self.left_schema,
                [
                    (1, "a"),
                    (2, "b"),
                ],
            ),
            1,
        )

        operator.open()

        operator.next()

        counters = (
            operator.counters()
        )

        self.assertEqual(
            counters[
                "comparisons"
            ],
            0,
        )

        self.assertEqual(
            counters[
                "page_reads"
            ],
            0,
        )

        self.assertEqual(
            counters[
                "page_writes"
            ],
            0,
        )

        operator.close()


if __name__ == "__main__":
    unittest.main()