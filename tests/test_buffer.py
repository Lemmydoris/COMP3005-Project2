import os
import tempfile
import unittest
from storage.disk import DiskManager
from storage.buffer import BufferPool

class BufferPoolTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

        self.db_path = os.path.join(
            self.temp_dir.name,
            "trace.db"
        )

        self.disk = DiskManager(self.db_path)

        # We need page IDs 0, 1, 2, 3, 4.
        for _ in range(5):
            self.disk.allocate_page()

    def tearDown(self):
        self.temp_dir.cleanup()

    # LRU professor's example
    def test_professor_lru_trace(self):
        """
        Professor's example:

        B = 3
        trace = 1 2 3 1 4 2

        Expected:
        hits      = 1
        misses    = 5
        evictions = 2
        """

        pool = BufferPool(
            self.disk,
            frames=3
        )

        trace = [1, 2, 3, 1, 4, 2]

        for page_id in trace:
            pool.fetch_page(page_id)

            pool.unpin_page(
                page_id,
                is_dirty=False
            )

        stats = pool.stats()

        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 5)
        self.assertEqual(stats["evictions"], 2)
        self.assertEqual(stats["reads"], 5)
        self.assertEqual(stats["writes"], 0)

    def test_pinned_page_cannot_be_evicted(self):

        pool = BufferPool(
            self.disk,
            frames=1
        )

        # Page 0 is a legitimate miss/read.
        pool.fetch_page(0)

        # Keep page 0 pinned, so there is no available frame for page 1.
        with self.assertRaises(RuntimeError):
            pool.fetch_page(1)

        stats = pool.stats()

        # Only the successful fetch of page 0 counts as a miss/read.
        self.assertEqual(
            stats["hits"],
            0
        )

        self.assertEqual(
            stats["misses"],
            1
        )

        self.assertEqual(
            stats["reads"],
            1
        )

        # Page 0 was never replaced because the second fetch failed.
        self.assertEqual(
            stats["evictions"],
            0
        )

    # Dirty page write
    def test_dirty_page_written_on_eviction(self):

        pool = BufferPool(
            self.disk,
            frames=1
        )

        data = pool.fetch_page(0)

        # Modify the page.
        data[0] = 99

        pool.unpin_page(
            0,
            is_dirty=True
        )

        # Fetching page 1 forces page 0 out.
        pool.fetch_page(1)

        stats = pool.stats()

        self.assertEqual(stats["evictions"], 1)
        self.assertEqual(stats["writes"], 1)

    # CLOCK professor example
    def test_professor_clock_trace(self):
        """
        Professor's exact CLOCK example:

        B = 3
        trace = 1 2 3 1 4 2

        Expected:
        hits      = 2
        misses    = 4
        evictions = 1
        """

        pool = BufferPool(
            self.disk,
            frames=3,
            policy="clock"
        )
        trace = [1, 2, 3, 1, 4, 2]

        for page_id in trace:
            pool.fetch_page(page_id)

            pool.unpin_page(
                page_id,
                is_dirty=False
            )

        stats = pool.stats()

        self.assertEqual(stats["hits"], 2)
        self.assertEqual(stats["misses"], 4)
        self.assertEqual(stats["evictions"], 1)
        self.assertEqual(stats["reads"], 4)
        self.assertEqual(stats["writes"], 0)

    def test_new_page_is_zero_filled_pinned_and_dirty(self):
        pool = BufferPool(
        self.disk,
        frames=2
        )

        # Five pages already exist from setUp(), so this should allocate page 5.
        data = pool.new_page()

        self.assertEqual(
            self.disk.num_pages(),
            6
        )

        self.assertEqual(
            data,
            bytearray(4096)
        )

        frame_index = pool.page_table[5]
        frame = pool.frames[frame_index]

        self.assertEqual(
            frame.page_id,
            5
        )

        self.assertEqual(
            frame.pin_count,
            1
        )

        self.assertTrue(
            frame.dirty
        )

        # Creating a new page did not read it from disk.
        self.assertEqual(
            self.disk.reads,
            0
        )

    def test_new_page_fails_when_every_frame_is_pinned(self):
        pool = BufferPool(
            self.disk,
            frames=1
        )

        # Keep page 0 pinned.
        pool.fetch_page(0)
        with self.assertRaises(RuntimeError):
            pool.new_page()

    def test_unpin_at_pin_count_zero_is_error(self):

        pool = BufferPool(
            self.disk,
            frames=1
        )

        pool.fetch_page(0)

        pool.unpin_page(
            0,
            is_dirty=False
        )

        # Pin count is now 0. Unpinning again must fail.
        with self.assertRaisesRegex(
            ValueError,
            "pin count 0"
        ):
            pool.unpin_page(
                0,
                is_dirty=False
            )

if __name__ == "__main__":
    unittest.main()