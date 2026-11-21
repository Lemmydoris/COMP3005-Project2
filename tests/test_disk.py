import os
import tempfile
import unittest

from storage.disk import DiskManager
from storage.page import PAGE_SIZE

class DiskManagerTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

        self.db_path = os.path.join(
            self.temp_dir.name,
            "R.db"
        )

        self.disk = DiskManager(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_allocate_pages(self):
        page0 = self.disk.allocate_page()
        page1 = self.disk.allocate_page()

        self.assertEqual(page0, 0)
        self.assertEqual(page1, 1)

        self.assertEqual(
            self.disk.num_pages(),
            2
        )

        self.assertEqual(
            os.path.getsize(self.db_path),
            PAGE_SIZE * 2
        )

    def test_new_page_is_zero_filled(self):
        page_id = self.disk.allocate_page()

        data = self.disk.read_page(page_id)

        self.assertEqual(
            data,
            bytes(PAGE_SIZE)
        )

    def test_write_then_read_page(self):
        page_id = self.disk.allocate_page()

        data = bytearray(PAGE_SIZE)

        data[0:4] = b"TEST"
        data[4092:4096] = b"END!"

        self.disk.write_page(
            page_id,
            bytes(data)
        )

        result = self.disk.read_page(page_id)

        self.assertEqual(result, bytes(data))

    def test_read_write_counters(self):
        page_id = self.disk.allocate_page()

        data = bytes(PAGE_SIZE)

        self.disk.write_page(
            page_id,
            data
        )

        self.disk.read_page(page_id)
        self.disk.read_page(page_id)

        stats = self.disk.stats()

        self.assertEqual(stats["writes"], 1)
        self.assertEqual(stats["reads"], 2)

if __name__ == "__main__":
    unittest.main()