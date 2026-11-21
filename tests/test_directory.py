import unittest
from storage.directory import (
    DirectoryPage,
    MAX_DIRECTORY_ENTRIES,
    NO_NEXT_PAGE
)

class DirectoryPageTests(unittest.TestCase):
    def test_empty_directory_page(self):
        page = DirectoryPage(0)

        self.assertEqual(
            page.page_id,
            0
        )

        self.assertEqual(
            page.next_dir_page,
            NO_NEXT_PAGE
        )

        self.assertEqual(
            page.entry_count,
            0
        )

        # Professor's exact capacity.
        self.assertEqual(
            MAX_DIRECTORY_ENTRIES,
            681
        )

    def test_add_and_update_entries(self):
        page = DirectoryPage(0)

        entry0 = page.add_entry(
            data_page_id=1,
            free_bytes=4088
        )

        entry1 = page.add_entry(
            data_page_id=2,
            free_bytes=2000
        )

        self.assertEqual(entry0, 0)
        self.assertEqual(entry1, 1)

        self.assertEqual(
            page.entry_count,
            2
        )

        self.assertEqual(
            page.get_entry(0),
            (1, 4088)
        )

        self.assertEqual(
            page.get_entry(1),
            (2, 2000)
        )

        # Pretend a record was inserted into page 1, so its free space decreased.
        page.update_free_bytes(
            0,
            4071
        )

        self.assertEqual(
            page.get_entry(0),
            (1, 4071)
        )

    def test_directory_round_trip(self):
        page = DirectoryPage(0)

        page.add_entry(
            1,
            4088
        )

        page.add_entry(
            2,
            3000
        )

        page.set_next_dir_page(10)

        raw = page.to_bytes()

        restored = DirectoryPage.from_bytes(raw)

        self.assertEqual(
            restored.page_id,
            0
        )

        self.assertEqual(
            restored.next_dir_page,
            10
        )

        self.assertEqual(
            restored.entry_count,
            2
        )

        self.assertEqual(
            restored.entries(),
            [
                (1, 4088),
                (2, 3000)
            ]
        )


if __name__ == "__main__":
    unittest.main()