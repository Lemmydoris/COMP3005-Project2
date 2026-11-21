import os
import tempfile
import unittest

from execution.base import END
from execution.seqscan import SeqScan
from storage.buffer import BufferPool
from storage.catalog import Catalog
from storage.disk import DiskManager
from storage.heap import HeapFile
from storage.record import encode_record


class SeqScanTests(unittest.TestCase):
    def setUp(self):

        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_dir = self.temp_dir.name

        self.schema = [
            ["a", "INT"],
            ["b", "VARCHAR", 20],
            ["c", "INT"],
        ]

        catalog = Catalog(
            self.db_dir,
            frames=4,
        )
        catalog.create_table(
            "R",
            self.schema,
        )

        # Persist catalog metadata before a different Catalog instance is opened by SeqScan.
        catalog.flush()

        metadata = catalog.get_table("R")
       
        table_path = os.path.join(
            self.db_dir,
            metadata["file"],
        )

        disk = DiskManager(table_path)

        buffer = BufferPool(
            disk,
            frames=4,
        )

        heap = HeapFile(
            "R",
            disk,
            buffer,
        )

        rows = [
            [42, "bob", 7],
            [43, "amy", 9],
            [44, "bob", 11],
        ]

        for row in rows:
            heap.insert(
                encode_record(
                    self.schema,
                    row,
                )
            )

        buffer.flush_all()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_seqscan_returns_all_rows_in_heap_order(self):

        scan = SeqScan(
            self.db_dir,
            "R",
            frames=4,
        )

        scan.open()

        rows = []

        while True:

            row = scan.next()

            if row is END:
                break

            rows.append(row)

        scan.close()

        self.assertEqual(
            rows,
            [
                (42, "bob", 7),
                (43, "amy", 9),
                (44, "bob", 11),
            ],
        )

    def test_seqscan_has_qualified_schema(self):

        scan = SeqScan(
            self.db_dir,
            "R",
            frames=4,
        )

        scan.open()

        self.assertEqual(
            scan.schema,
            [
                ["R.a", "INT"],
                ["R.b", "VARCHAR", 20],
                ["R.c", "INT"],
            ],
        )

        scan.close()

    def test_seqscan_counters(self):

        scan = SeqScan(
            self.db_dir,
            "R",
            frames=4,
        )

        scan.open()

        while scan.next() is not END:
            pass

        scan.close()

        counters = scan.counters()

        self.assertEqual(
            counters["tuples_out"],
            3,
        )

        self.assertEqual(
            counters["comparisons"],
            0,
        )

        self.assertGreater(
            counters["page_reads"],
            0,
        )

        self.assertEqual(
            counters["page_writes"],
            0,
        )

    def test_seqscan_end_is_repeatable(self):

        scan = SeqScan(
            self.db_dir,
            "R",
            frames=4,
        )

        scan.open()

        self.assertEqual(
            scan.next(),
            (42, "bob", 7),
        )

        self.assertEqual(
            scan.next(),
            (43, "amy", 9),
        )

        self.assertEqual(
            scan.next(),
            (44, "bob", 11),
        )

        self.assertIs(
            scan.next(),
            END,
        )

        self.assertIs(
            scan.next(),
            END,
        )

        scan.close()

    def test_close_releases_pinned_pages(self):

        scan = SeqScan(
            self.db_dir,
            "R",
            frames=4,
        )

        scan.open()

        # Pull only one tuple, then stop early.
        self.assertEqual(
            scan.next(),
            (42, "bob", 7),
        )

        buffer = scan.buffer

        scan.close()

        for frame in buffer.frames:
            self.assertEqual(
                frame.pin_count,
                0,
            )

    def test_unknown_table_fails_at_open(self):

        scan = SeqScan(
            self.db_dir,
            "MissingTable",
            frames=4,
        )

        with self.assertRaisesRegex(
            ValueError,
            "Unknown table",
        ):
            scan.open()


if __name__ == "__main__":
    unittest.main()