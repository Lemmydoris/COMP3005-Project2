import os
import tempfile
import unittest
from pathlib import Path

from optimizer.statistics import (
    analyze_table,
)

from storage.buffer import BufferPool
from storage.catalog import Catalog
from storage.disk import DiskManager
from storage.heap import HeapFile
from storage.record import encode_record


class OptimizerStatisticsTests(
    unittest.TestCase
):

    def setUp(self):

        self.temp = (
            tempfile.TemporaryDirectory()
        )

        self.db_dir = (
            self.temp.name
        )

    def tearDown(self):

        self.temp.cleanup()

    def _create_table(
        self,
        name,
        schema,
        rows,
    ):

        catalog = Catalog(
            self.db_dir
        )

        catalog.create_table(
            name,
            schema,
        )

        metadata = (
            catalog.get_table(
                name
            )
        )

        table_path = (
            Path(
                self.db_dir
            )
            / metadata[
                "file"
            ]
        )

        disk = DiskManager(
            table_path
        )

        buffer = BufferPool(
            disk,
            frames=4,
            policy="lru",
        )

        heap = HeapFile(
            name,
            disk,
            buffer,
        )

        for row in rows:

            record = encode_record(
                schema,
                row,
            )

            heap.insert(
                record
            )

        buffer.flush_all()

        catalog.update_table(
            name,
            num_pages=(
                disk.num_pages()
            ),
            num_tuples=(
                len(rows)
            ),
        )

        catalog.flush()

    def test_exact_table_statistics(
        self,
    ):

        schema = [
            ["a", "INT"],
            [
                "b",
                "VARCHAR",
                10,
            ],
        ]

        rows = [
            (1, "a"),
            (2, "bbb"),
            (3, "cc"),
        ]

        self._create_table(
            "R",
            schema,
            rows,
        )

        statistics = analyze_table(
            self.db_dir,
            "R",
            buckets=2,
        )

        self.assertEqual(
            statistics[
                "n_tuples"
            ],
            3,
        )

        # One data page.
        self.assertEqual(
            statistics[
                "n_pages"
            ],
            1,
        )

        # Encoded lengths:
        #
        # (1,"a")   = 4 + 2 + 1 = 7
        # (2,"bbb") = 4 + 2 + 3 = 9
        # (3,"cc")  = 4 + 2 + 2 = 8
        #
        # average = 8
        self.assertEqual(
            statistics[
                "width"
            ],
            8.0,
        )

        a = (
            statistics[
                "columns"
            ][
                "a"
            ]
        )

        self.assertEqual(
            a["ndv"],
            3,
        )

        self.assertEqual(
            a["min"],
            1,
        )

        self.assertEqual(
            a["max"],
            3,
        )

        b = (
            statistics[
                "columns"
            ][
                "b"
            ]
        )

        self.assertEqual(
            b["ndv"],
            3,
        )

        self.assertEqual(
            b["min"],
            "a",
        )

        self.assertEqual(
            b["max"],
            "cc",
        )

    def test_histogram_is_equi_depth(
        self,
    ):

        schema = [
            ["a", "INT"],
        ]

        rows = [
            (1,),
            (1,),
            (2,),
            (3,),
            (3,),
            (3,),
            (4,),
            (5,),
        ]

        self._create_table(
            "H",
            schema,
            rows,
        )

        statistics = analyze_table(
            self.db_dir,
            "H",
            buckets=3,
        )

        hist = (
            statistics[
                "columns"
            ][
                "a"
            ][
                "hist"
            ]
        )

        self.assertEqual(
            hist,
            [
                {
                    "min": 1,
                    "max": 2,
                    "count": 3,
                    "ndv": 2,
                },
                {
                    "min": 3,
                    "max": 3,
                    "count": 3,
                    "ndv": 1,
                },
                {
                    "min": 4,
                    "max": 5,
                    "count": 2,
                    "ndv": 2,
                },
            ],
        )

    def test_empty_table_statistics(
        self,
    ):

        schema = [
            ["a", "INT"],
        ]

        self._create_table(
            "Empty",
            schema,
            [],
        )

        statistics = analyze_table(
            self.db_dir,
            "Empty",
        )

        self.assertEqual(
            statistics[
                "n_tuples"
            ],
            0,
        )

        self.assertEqual(
            statistics[
                "n_pages"
            ],
            0,
        )

        self.assertEqual(
            statistics[
                "width"
            ],
            0.0,
        )

        self.assertEqual(
            statistics[
                "columns"
            ][
                "a"
            ],
            {
                "ndv": 0,
                "min": None,
                "max": None,
                "hist": [],
            },
        )

    def test_data_page_count_excludes_directory_page(
        self,
    ):

        schema = [
            ["a", "INT"],
        ]

        # An INT record is 4 bytes and needs another
        # 4-byte slot, so one page holds:
        #
        # floor(4088 / 8) = 511
        #
        # 600 rows therefore need exactly 2 data pages.
        rows = [
            (value,)
            for value
            in range(600)
        ]

        self._create_table(
            "Pages",
            schema,
            rows,
        )

        statistics = analyze_table(
            self.db_dir,
            "Pages",
            buckets=5,
        )

        self.assertEqual(
            statistics[
                "n_pages"
            ],
            2,
        )

    def test_statistics_persist_and_rerun_is_deterministic(
        self,
    ):

        schema = [
            ["a", "INT"],
            [
                "name",
                "VARCHAR",
                10,
            ],
        ]

        rows = [
            (3, "c"),
            (1, "a"),
            (2, "b"),
            (2, "b"),
            (4, "d"),
        ]

        self._create_table(
            "Persist",
            schema,
            rows,
        )

        first = analyze_table(
            self.db_dir,
            "Persist",
            buckets=3,
        )

        second = analyze_table(
            self.db_dir,
            "Persist",
            buckets=3,
        )

        self.assertEqual(
            first,
            second,
        )

        reopened = Catalog(
            self.db_dir
        )

        entry = reopened.get_table(
            "Persist"
        )

        self.assertEqual(
            entry[
                "statistics"
            ],
            second,
        )

        # ANALYZE must clean its temporary files.
        leftovers = [
            filename
            for filename
            in os.listdir(
                self.db_dir
            )
            if filename.startswith(
                "exec_run_"
            )
            and filename.endswith(
                ".tmp"
            )
        ]

        self.assertEqual(
            leftovers,
            [],
        )

        reopened.flush()

    def test_invalid_bucket_count_is_rejected(
        self,
    ):

        schema = [
            ["a", "INT"],
        ]

        self._create_table(
            "BadBuckets",
            schema,
            [(1,)],
        )

        with self.assertRaises(
            ValueError
        ):

            analyze_table(
                self.db_dir,
                "BadBuckets",
                buckets=0,
            )


if __name__ == "__main__":
    unittest.main()