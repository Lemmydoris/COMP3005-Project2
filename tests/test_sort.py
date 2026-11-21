import os
import tempfile
import unittest

from execution.base import END, Operator
from execution.sort import Sort

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


class SortTests(unittest.TestCase):

    def setUp(self):
        self.schema = [
            ["R.a", "INT"],
            ["R.b", "VARCHAR", 20],
        ]

    def collect(self, operator):
        result = []

        while True:
            row = operator.next()

            if row is END:
                break

            result.append(row)

        return result

    def test_in_memory_sort_ascending(self):

        source = ListSource(
            self.schema,
            [
                (3, "c"),
                (1, "a"),
                (2, "b"),
            ],
        )

        operator = Sort(
            source,
            [["R.a", "asc"]],
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

        self.assertEqual(
            operator.passes,
            1,
        )

        operator.close()

    def test_multiple_keys_with_descending(self):

        source = ListSource(
            self.schema,
            [
                (1, "a"),
                (2, "b"),
                (1, "c"),
                (2, "a"),
            ],
        )

        operator = Sort(
            source,
            [
                ["R.a", "asc"],
                ["R.b", "desc"],
            ],
            frames=4,
        )

        operator.open()

        self.assertEqual(
            self.collect(operator),
            [
                (1, "c"),
                (1, "a"),
                (2, "b"),
                (2, "a"),
            ],
        )

        operator.close()

    def test_sort_preserves_duplicates(self):

        source = ListSource(
            self.schema,
            [
                (2, "x"),
                (1, "a"),
                (2, "x"),
                (1, "a"),
            ],
        )

        operator = Sort(
            source,
            [["R.a", "asc"]],
            frames=4,
        )

        operator.open()

        self.assertEqual(
            self.collect(operator),
            [
                (1, "a"),
                (1, "a"),
                (2, "x"),
                (2, "x"),
            ],
        )

        operator.close()

    def test_unknown_sort_column_fails_at_open(self):

        source = ListSource(
            self.schema,
            [(1, "a")],
        )

        operator = Sort(
            source,
            [["R.missing", "asc"]],
            frames=4,
        )

        with self.assertRaisesRegex(
            ValueError,
            "Unknown column",
        ):
            operator.open()

    def test_invalid_direction_fails_at_open(self):

        source = ListSource(
            self.schema,
            [(1, "a")],
        )

        operator = Sort(
            source,
            [["R.a", "sideways"]],
            frames=4,
        )

        with self.assertRaisesRegex(
            ValueError,
            "Invalid sort direction",
        ):
            operator.open()

    def test_external_sort_uses_temp_files(self):

        schema = [
            ["R.a", "INT"],
            ["R.payload", "VARCHAR", 1900],
        ]

        rows = [
            (value, "x" * 1900)
            for value in
            [8, 3, 7, 1, 6, 2, 5, 4]
        ]

        with tempfile.TemporaryDirectory() as temp_dir:

            source = ListSource(
                schema,
                rows,
            )

            operator = Sort(
                source,
                [["R.a", "asc"]],
                frames=3,
                temp_dir=temp_dir,
            )

            operator.open()

            self.assertGreaterEqual(
                operator.passes,
                2,
            )

            self.assertGreater(
                operator.counters()[
                    "page_writes"
                ],
                0,
            )

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

            self.assertGreater(
                operator.counters()[
                    "page_reads"
                ],
                0,
            )

            operator.close()

            remaining = [
                filename
                for filename
                in os.listdir(temp_dir)
                if filename.startswith(
                    "exec_run_"
                )
            ]

            self.assertEqual(
                remaining,
                [],
            )

    def test_sort_never_reports_more_than_B_frames(self):

        schema = [
            ["R.a", "INT"],
            ["R.payload", "VARCHAR", 1900],
        ]

        rows = [
            (value, "z" * 1900)
            for value in range(
                20,
                0,
                -1,
            )
        ]

        with tempfile.TemporaryDirectory() as temp_dir:

            operator = Sort(
                ListSource(
                    schema,
                    rows,
                ),
                [["R.a", "asc"]],
                frames=4,
                temp_dir=temp_dir,
            )

            operator.open()

            self.collect(operator)

            self.assertLessEqual(
                operator.max_frames_held,
                4,
            )

            operator.close()

    def test_empty_sort_returns_cleanly(self):

        operator = Sort(
            ListSource(
                self.schema,
                [],
            ),
            [["R.a", "asc"]],
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


if __name__ == "__main__":
    unittest.main()