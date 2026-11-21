import json
import tempfile
import unittest

from storage.catalog import Catalog


class CatalogStatisticsTests(unittest.TestCase):

    def setUp(self):

        self.temp = (
            tempfile.TemporaryDirectory()
        )

        self.db_dir = (
            self.temp.name
        )

    def tearDown(self):

        self.temp.cleanup()

    def test_large_statistics_round_trip(
        self,
    ):

        catalog = Catalog(
            self.db_dir
        )

        catalog.create_table(
            "StatsTable",
            [
                [
                    "payload",
                    "VARCHAR",
                    255,
                ]
            ],
        )

        large_statistics = {
            "n_tuples": 1000,
            "n_pages": 100,
            "width": 255.0,
            "columns": {
                "payload": {
                    "ndv": 1000,
                    "min": "a" * 255,
                    "max": "z" * 255,
                    "hist": [
                        {
                            "min":
                                (
                                    chr(
                                        65
                                        + (
                                            index
                                            % 26
                                        )
                                    )
                                    * 255
                                ),
                            "max":
                                (
                                    chr(
                                        65
                                        + (
                                            index
                                            % 26
                                        )
                                    )
                                    * 255
                                ),
                            "count": 50,
                            "ndv": 50,
                        }
                        for index
                        in range(20)
                    ],
                }
            },
        }

        raw_size = len(
            json.dumps(
                large_statistics
            ).encode(
                "utf-8"
            )
        )

        self.assertGreater(
            raw_size,
            4088,
        )

        catalog.update_statistics(
            "StatsTable",
            large_statistics,
        )

        catalog.flush()

        reopened = Catalog(
            self.db_dir
        )

        entry = reopened.get_table(
            "StatsTable"
        )

        self.assertEqual(
            entry["statistics"],
            large_statistics,
        )

        reopened.flush()

    def test_metadata_update_preserves_chunked_statistics(
        self,
    ):

        catalog = Catalog(
            self.db_dir
        )

        catalog.create_table(
            "Rstats",
            [
                [
                    "a",
                    "INT",
                ]
            ],
        )

        statistics = {
            "n_tuples": 5,
            "n_pages": 1,
            "width": 4.0,
            "columns": {
                "a": {
                    "ndv": 5,
                    "min": 1,
                    "max": 5,
                    "hist": [
                        {
                            "min": 1,
                            "max": 5,
                            "count": 5,
                            "ndv": 5,
                        }
                    ],
                }
            },
        }

        catalog.update_statistics(
            "Rstats",
            statistics,
        )

        catalog.update_table(
            "Rstats",
            num_tuples=5,
        )

        entry = catalog.get_table(
            "Rstats"
        )

        self.assertEqual(
            entry["num_tuples"],
            5,
        )

        self.assertEqual(
            entry["statistics"],
            statistics,
        )

        catalog.flush()


if __name__ == "__main__":
    unittest.main()