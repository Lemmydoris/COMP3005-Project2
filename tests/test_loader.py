import os
import tempfile
import unittest

from storage.buffer import BufferPool
from storage.catalog import Catalog
from storage.disk import DiskManager
from storage.heap import HeapFile
from storage.loader import TableLoader
from storage.record import decode_record


class LoaderTests(unittest.TestCase):
    def setUp(self):

        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.catalog = Catalog(
            self.temp_dir.name,
            frames=4
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_load_csv(self):
        self.catalog.create_table(
            "R",
            [
                ("a", "INT"),
                ("b", "VARCHAR", 20),
                ("c", "INT")
            ]
        )

        csv_path = os.path.join(
            self.temp_dir.name,
            "r.csv"
        )

        with open(
            csv_path,
            "w",
            encoding="utf-8",
            newline=""
        ) as file:

            file.write(
                "42,bob,7\n"
                "43,amy,9\n"
            )

        loader = TableLoader(
            self.catalog,
            frames=4
        )

        result = loader.load(
            "R",
            csv_path
        )

        self.assertEqual(
            result["rows_loaded"],
            2
        )

        metadata = (
            self.catalog.get_table("R")
        )

        self.assertEqual(
            metadata["num_tuples"],
            2
        )

        # One directory page + one data page.
        self.assertEqual(
            metadata["num_pages"],
            2
        )

    def test_quoted_comma_in_varchar(self):
        self.catalog.create_table(
            "R",
            [
                ("a", "INT"),
                ("b", "VARCHAR", 20),
                ("c", "INT")
            ]
        )

        csv_path = os.path.join(
            self.temp_dir.name,
            "quoted.csv"
        )

        with open(
            csv_path,
            "w",
            encoding="utf-8",
            newline=""
        ) as file:

            file.write(
                '42,"bob,smith",7\n'
            )

        loader = TableLoader(
            self.catalog,
            frames=4
        )

        loader.load(
            "R",
            csv_path
        )

        metadata = (
            self.catalog.get_table("R")
        )

        disk = DiskManager(
            os.path.join(
                self.temp_dir.name,
                metadata["file"]
            )
        )

        pool = BufferPool(
            disk,
            frames=4
        )

        heap = HeapFile(
            "R",
            disk,
            pool
        )

        rows = []

        for _, raw_record in heap.scan():

            rows.append(
                decode_record(
                    metadata["schema"],
                    raw_record
                )
            )

        self.assertEqual(
            rows,
            [
                (42, "bob,smith", 7)
            ]
        )

    def test_invalid_int_names_line_number(self):
        self.catalog.create_table(
            "R",
            [
                ("a", "INT"),
                ("b", "VARCHAR", 20)
            ]
        )

        csv_path = os.path.join(
            self.temp_dir.name,
            "bad_int.csv"
        )

        with open(
            csv_path,
            "w",
            encoding="utf-8",
            newline=""
        ) as file:

            file.write(
                "42,bob\n"
                "not-an-int,amy\n"
            )

        loader = TableLoader(
            self.catalog,
            frames=4
        )

        with self.assertRaisesRegex(
            ValueError,
            "Line 2"
        ):
            loader.load(
                "R",
                csv_path
            )

        # First row was successfully inserted before loading stopped.
        metadata = (
            self.catalog.get_table("R")
        )

        self.assertEqual(
            metadata["num_tuples"],
            1
        )

    def test_varchar_too_long_names_line_number(self):
        self.catalog.create_table(
            "R",
            [
                ("a", "INT"),
                ("b", "VARCHAR", 3)
            ]
        )

        csv_path = os.path.join(
            self.temp_dir.name,
            "too_long.csv"
        )

        with open(
            csv_path,
            "w",
            encoding="utf-8",
            newline=""
        ) as file:

            file.write(
                "1,bob\n"
                "2,alice\n"
            )

        loader = TableLoader(
            self.catalog,
            frames=4
        )

        with self.assertRaisesRegex(
            ValueError,
            "Line 2"
        ):
            loader.load(
                "R",
                csv_path
            )

    def test_oversized_record_names_table_and_row(self):
        schema = [
            (
                f"c{i}",
                "VARCHAR",
                255
            )
            for i in range(17)
        ]

        self.catalog.create_table(
            "R",
            schema
        )

        csv_path = os.path.join(
            self.temp_dir.name,
            "huge.csv"
        )

        huge_field = "x" * 255

        with open(
            csv_path,
            "w",
            encoding="utf-8",
            newline=""
        ) as file:

            file.write(
                ",".join(
                    [huge_field] * 17
                )
                + "\n"
            )

        loader = TableLoader(
            self.catalog,
            frames=4
        )

        with self.assertRaisesRegex(
            ValueError,
            r"Line 1.*table R.*row 1"
        ):
            loader.load(
                "R",
                csv_path
            )

        metadata = (
            self.catalog.get_table("R")
        )

        self.assertEqual(
            metadata["num_tuples"],
            0
        )

if __name__ == "__main__":
    unittest.main()