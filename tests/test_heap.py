import os
import tempfile
import unittest

from storage.buffer import BufferPool
from storage.disk import DiskManager
from storage.heap import HeapFile

class HeapFileTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        db_path = os.path.join(
            self.temp_dir.name,
            "R.db"
        )

        self.disk = DiskManager(db_path)

        self.pool = BufferPool(
            self.disk,
            frames=4,
            policy="lru"
        )

        self.heap = HeapFile(
            "R",
            self.disk,
            self.pool
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_page_zero_is_directory(self):

        self.assertEqual(
            self.disk.num_pages(),
            1
        )

    def test_insert_and_get(self):
        record1 = b"A" * 13
        record2 = b"B" * 20

        rid1 = self.heap.insert(record1)
        rid2 = self.heap.insert(record2)

        self.assertEqual(
            rid1,
            (1, 0)
        )

        self.assertEqual(
            rid2,
            (1, 1)
        )

        self.assertEqual(
            self.heap.get(rid1),
            record1
        )

        self.assertEqual(
            self.heap.get(rid2),
            record2
        )

    def test_scan_returns_live_records(self):
        records = [
            b"A" * 13,
            b"B" * 20,
            b"C" * 13
        ]

        for record in records:
            self.heap.insert(record)

        scanned = [
            record
            for _, record
            in self.heap.scan()
        ]

        self.assertEqual(
            scanned,
            records
        )

    def test_delete_removes_record_from_scan(self):
        rid1 = self.heap.insert(
            b"A" * 13
        )

        rid2 = self.heap.insert(
            b"B" * 13
        )

        self.heap.delete(rid1)

        scanned = list(
            self.heap.scan()
        )

        self.assertEqual(
            scanned,
            [
                (
                    rid2,
                    b"B" * 13
                )
            ]
        )

        with self.assertRaisesRegex(
            ValueError,
            r"\(1, 0\)"
        ):
            self.heap.get(rid1)

    def test_241_records_require_second_data_page(self):
        """
        Professor's fixed-record capacity:
        L = 13
        floor(4088 / (13 + 4)) = 240
        """
        rids = []

        for _ in range(241):
            rids.append(
                self.heap.insert(
                    b"A" * 13
                )
            )

        # First 240 records fit on page 1.
        self.assertEqual(
            rids[0],
            (1, 0)
        )

        self.assertEqual(
            rids[239],
            (1, 239)
        )

        # Record 241 needs page 2.
        self.assertEqual(
            rids[240],
            (2, 0)
        )

    def test_record_over_4088_bytes_fails(self):
        with self.assertRaises(ValueError):
            self.heap.insert(
                b"X" * 4089
            )

    def test_records_survive_flush_and_reopen(self):
        record1 = b"A" * 13
        record2 = b"B" * 20

        rid1 = self.heap.insert(record1)
        rid2 = self.heap.insert(record2)

        # Actually write dirty buffer pages to the .db file.
        self.pool.flush_all()

        # Reopen the same database file using brand-new DiskManager and BufferPool objects.
        reopened_disk = DiskManager(
            self.disk.file_path
        )

        reopened_pool = BufferPool(
            reopened_disk,
            frames=4,
            policy="lru"
        )

        reopened_heap = HeapFile(
            "R",
            reopened_disk,
            reopened_pool
        )

        self.assertEqual(
            reopened_heap.get(rid1),
            record1
        )

        self.assertEqual(
            reopened_heap.get(rid2),
            record2
        )

    def test_delete_every_record_then_scan_is_empty(self):

        rids = []

        for i in range(10):
            rids.append(
                self.heap.insert(
                    bytes([65 + i]) * 13
                )
            )

        for rid in rids:
            self.heap.delete(rid)

        scanned = list(
            self.heap.scan()
        )

        self.assertEqual(
            scanned,
            []
        )

    def test_large_scan_never_pins_more_than_two_pages(self):
        """
        Professor checklist:

        A table twenty times larger than B must scan
        successfully while never pinning more than
        two pages at once.

        B = 2
        data pages = 40
        """
        large_path = os.path.join(
            self.temp_dir.name,
            "Large.db"
        )

        disk = DiskManager(
            large_path
        )

        pool = BufferPool(
            disk,
            frames=2,
            policy="lru"
        )

        heap = HeapFile(
            "Large",
            disk,
            pool
        )

        # 4084-byte record + 4-byte slot = exactly 4088 bytes, so each data page holds one.
        record = b"X" * 4084

        for _ in range(40):
            heap.insert(record)

        pool.flush_all()

        # Reopen with a fresh B=2 buffer pool.
        reopened_disk = DiskManager(
            large_path
        )

        reopened_pool = BufferPool(
            reopened_disk,
            frames=2,
            policy="lru"
        )

        reopened_heap = HeapFile(
            "Large",
            reopened_disk,
            reopened_pool
        )

        maximum_pinned = 0
        records_seen = 0

        for _, raw_record in reopened_heap.scan():

            records_seen += 1

            pinned_now = sum(
                frame.pin_count
                for frame
                in reopened_pool.frames
            )

            maximum_pinned = max(
                maximum_pinned,
                pinned_now
            )

            self.assertEqual(
                raw_record,
                record
            )

        self.assertEqual(
            records_seen,
            40
        )

        self.assertLessEqual(
            maximum_pinned,
            2
        )

        # Everything should be unpinned after scan.
        self.assertEqual(
            sum(
                frame.pin_count
                for frame
                in reopened_pool.frames
            ),
            0
        )

if __name__ == "__main__":
    unittest.main()