import unittest
from storage.record import encode_record, decode_record

class RecordTests(unittest.TestCase):
    def setUp(self):
        self.schema = [
            ("a", "INT"),
            ("b", "VARCHAR", 5),
            ("c", "INT")
        ]

    def test_professor_record_example(self):
        record = encode_record(
            self.schema,
            (42, "bob", 7)
        )
        # Professor's example says this must be 13 bytes.
        self.assertEqual(len(record), 13)
        # Exact required byte layout:
        expected = bytes([
            0x2A, 0x00, 0x00, 0x00,       # 42
            0x03, 0x00,                   # string length = 3
            0x62, 0x6F, 0x62,             # "bob"
            0x07, 0x00, 0x00, 0x00        # 7
        ])

        self.assertEqual(record, expected)

    def test_encode_decode_round_trip(self):
        original = (42, "bob", 7)

        record = encode_record(
            self.schema,
            original
        )

        decoded = decode_record(
            self.schema,
            record
        )

        self.assertEqual(decoded, original)

    def test_varchar_too_long(self):
        with self.assertRaises(ValueError):
            encode_record(
                self.schema,
                (42, "longer", 7)
            )

if __name__ == "__main__":
    unittest.main()