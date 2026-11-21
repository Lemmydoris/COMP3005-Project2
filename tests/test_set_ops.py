import tempfile
import unittest

from execution.base import END, Operator
from execution.set_ops import (
    Except,
    Intersect,
    Union,
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


class SetOperatorTests(unittest.TestCase):

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

    def test_union_removes_duplicates(self):

        operator = Union(
            ListSource(
                self.left_schema,
                [
                    (1, "a"),
                    (2, "b"),
                    (2, "b"),
                ],
            ),
            ListSource(
                self.right_schema,
                [
                    (2, "b"),
                    (3, "c"),
                ],
            ),
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

    def test_union_uses_left_schema(self):

        operator = Union(
            ListSource(
                self.left_schema,
                [(1, "a")],
            ),
            ListSource(
                self.right_schema,
                [(2, "b")],
            ),
            frames=4,
        )

        operator.open()

        self.assertEqual(
            operator.schema,
            self.left_schema,
        )

        operator.close()

    def test_intersect_set_semantics(self):

        operator = Intersect(
            ListSource(
                self.left_schema,
                [
                    (1, "a"),
                    (2, "b"),
                    (2, "b"),
                    (3, "c"),
                ],
            ),
            ListSource(
                self.right_schema,
                [
                    (2, "b"),
                    (2, "b"),
                    (4, "d"),
                ],
            ),
            frames=4,
        )

        operator.open()

        self.assertEqual(
            self.collect(operator),
            [
                (2, "b"),
            ],
        )

        operator.close()

    def test_except_set_semantics(self):

        operator = Except(
            ListSource(
                self.left_schema,
                [
                    (1, "a"),
                    (1, "a"),
                    (2, "b"),
                    (3, "c"),
                ],
            ),
            ListSource(
                self.right_schema,
                [
                    (2, "b"),
                    (4, "d"),
                ],
            ),
            frames=4,
        )

        operator.open()

        self.assertEqual(
            self.collect(operator),
            [
                (1, "a"),
                (3, "c"),
            ],
        )

        operator.close()

    def test_intersect_empty_input(self):

        operator = Intersect(
            ListSource(
                self.left_schema,
                [],
            ),
            ListSource(
                self.right_schema,
                [
                    (1, "a"),
                ],
            ),
            frames=4,
        )

        operator.open()

        self.assertIs(
            operator.next(),
            END,
        )

        operator.close()

    def test_except_empty_right_returns_unique_left(self):

        operator = Except(
            ListSource(
                self.left_schema,
                [
                    (2, "b"),
                    (1, "a"),
                    (2, "b"),
                ],
            ),
            ListSource(
                self.right_schema,
                [],
            ),
            frames=4,
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

    def test_set_operator_rejects_column_count_mismatch(self):

        operator = Intersect(
            ListSource(
                self.left_schema,
                [],
            ),
            ListSource(
                [
                    ["S.x", "INT"],
                ],
                [],
            ),
            frames=4,
        )

        with self.assertRaisesRegex(
            ValueError,
            "same number of columns",
        ):
            operator.open()

    def test_set_operator_rejects_type_mismatch(self):

        operator = Except(
            ListSource(
                self.left_schema,
                [],
            ),
            ListSource(
                [
                    ["S.x", "VARCHAR", 20],
                    ["S.y", "VARCHAR", 20],
                ],
                [],
            ),
            frames=4,
        )

        with self.assertRaisesRegex(
            TypeError,
            "type mismatch",
        ):
            operator.open()

    def test_intersect_external_inputs(self):

        schema_left = [
            ["R.a", "INT"],
            ["R.payload", "VARCHAR", 1900],
        ]

        schema_right = [
            ["S.a", "INT"],
            ["S.payload", "VARCHAR", 1900],
        ]

        left_rows = [
            (value, "x" * 1900)
            for value in
            [8, 1, 2, 3, 4, 5, 6, 7]
        ]

        right_rows = [
            (value, "x" * 1900)
            for value in
            [10, 8, 6, 4, 2]
        ]

        with tempfile.TemporaryDirectory() as temp_dir:

            operator = Intersect(
                ListSource(
                    schema_left,
                    left_rows,
                ),
                ListSource(
                    schema_right,
                    right_rows,
                ),
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
                    2,
                    4,
                    6,
                    8,
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

    def test_except_external_inputs(self):

        schema_left = [
            ["R.a", "INT"],
            ["R.payload", "VARCHAR", 1900],
        ]

        schema_right = [
            ["S.a", "INT"],
            ["S.payload", "VARCHAR", 1900],
        ]

        left_rows = [
            (value, "x" * 1900)
            for value in
            [1, 2, 3, 4, 5, 6, 7, 8]
        ]

        right_rows = [
            (value, "x" * 1900)
            for value in
            [2, 4, 6, 8]
        ]

        with tempfile.TemporaryDirectory() as temp_dir:

            operator = Except(
                ListSource(
                    schema_left,
                    left_rows,
                ),
                ListSource(
                    schema_right,
                    right_rows,
                ),
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
                    1,
                    3,
                    5,
                    7,
                ],
            )

            operator.close()


if __name__ == "__main__":
    unittest.main()