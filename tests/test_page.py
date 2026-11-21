import unittest
from storage.page import SlottedPage

class SlottedPageTests(unittest.TestCase):

    def test_professor_worked_example(self):
        page = SlottedPage(0)

        #Empty page
        self.assertEqual(page.slot_count, 0)
        self.assertEqual(page.free_end, 4096)
        self.assertEqual(page.free_space(), 4088)

        #Insert 13 bytes
        slot0 = page.insert(b"A" * 13)

        self.assertEqual(slot0, 0)
        self.assertEqual(page.slot_count, 1)
        self.assertEqual(page.free_end, 4083)
        self.assertEqual(page.free_space(), 4071)

        #Insert 20 bytes
        slot1 = page.insert(b"B" * 20)

        self.assertEqual(slot1, 1)
        self.assertEqual(page.slot_count, 2)
        self.assertEqual(page.free_end, 4063)
        self.assertEqual(page.free_space(), 4047)

        #Insert another 13 bytes
        slot2 = page.insert(b"C" * 13)

        self.assertEqual(slot2, 2)
        self.assertEqual(page.slot_count, 3)
        self.assertEqual(page.free_end, 4050)
        self.assertEqual(page.free_space(), 4030)

        #Delete slot 1
        page.delete(1)

        #Deleting must NOT reclaim space.
        self.assertEqual(page.slot_count, 3)
        self.assertEqual(page.free_end, 4050)
        self.assertEqual(page.free_space(), 4030)

        #Other records still exist.
        self.assertEqual(page.get(0), b"A" * 13)
        self.assertEqual(page.get(2), b"C" * 13)

        #Deleted record must fail.
        with self.assertRaises(ValueError):
            page.get(1)


if __name__ == "__main__":
    unittest.main()