
import json
import os
import tempfile
import unittest

from storage.catalog import Catalog


class CatalogTests(unittest.TestCase):

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

    def test_catalog_db_is_created(self):

        catalog_path = os.path.join(
            self.temp_dir.name,
            "catalog.db"
        )

        self.assertTrue(
            os.path.exists(catalog_path)
        )

        # Page 0 is the catalog heap's first directory page.
        self.assertEqual(
            self.catalog.disk.num_pages(),
            1
        )

    def test_create_table(self):

        entry = self.catalog.create_table(
            "R",
            [
                ("a", "INT"),
                ("b", "VARCHAR", 20),
                ("c", "INT")
            ]
        )

        table_path = os.path.join(
            self.temp_dir.name,
            "R.db"
        )

        self.assertTrue(
            os.path.exists(table_path)
        )

        self.assertEqual(
            entry["name"],
            "R"
        )

        self.assertEqual(
            entry["schema"],
            [
                ["a", "INT"],
                ["b", "VARCHAR", 20],
                ["c", "INT"]
            ]
        )

        self.assertEqual(
            entry["file"],
            "R.db"
        )

        # New table contains only page 0, its first directory page.
        self.assertEqual(
            entry["num_pages"],
            1
        )

        self.assertEqual(
            entry["num_tuples"],
            0
        )

        self.assertEqual(
            entry["statistics"],
            {}
        )

    def test_catalog_survives_reopen(self):

        self.catalog.create_table(
            "R",
            [
                ("a", "INT"),
                ("b", "VARCHAR", 20)
            ]
        )

        self.catalog.flush()

        reopened = Catalog(
            self.temp_dir.name,
            frames=4
        )

        entry = reopened.get_table("R")

        self.assertEqual(
            entry["name"],
            "R"
        )

        self.assertEqual(
            entry["schema"],
            [
                ["a", "INT"],
                ["b", "VARCHAR", 20]
            ]
        )

    def test_list_and_update_tables(self):

        self.catalog.create_table(
            "R",
            [
                ("a", "INT")
            ]
        )

        self.catalog.create_table(
            "S",
            [
                ("b", "VARCHAR", 10)
            ]
        )

        self.catalog.update_table(
            "R",
            num_pages=3,
            num_tuples=250
        )

        tables = (
            self.catalog.list_tables()
        )

        self.assertEqual(
            [table["name"] for table in tables],
            ["R", "S"]
        )

        r = self.catalog.get_table("R")

        self.assertEqual(
            r["num_pages"],
            3
        )

        self.assertEqual(
            r["num_tuples"],
            250
        )

        # Updating R must not make R appear twice.
        self.assertEqual(
            len(tables),
            2
        )

    def test_large_statistics_round_trip(self):

        catalog =  self.catalog

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
                            "min": (
                                chr(
                                    65
                                    + (
                                        index
                                        % 26
                                    )
                                )
                                * 255
                            ),
                            "max": (
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

        # Definitely larger than one catalog record.
        self.assertGreater(
            len(
                json.dumps(
                    large_statistics
                ).encode(
                    "utf-8"
                )
            ),
            4088,
        )

        catalog.update_statistics(
            "StatsTable",
            large_statistics,
        )

        catalog.flush()

        reopened = Catalog(
            self.temp_dir.name
        )

        entry = reopened.get_table(
            "StatsTable"
        )

        self.assertEqual(
            entry["statistics"],
            large_statistics,
        )

    def test_metadata_update_preserves_chunked_statistics(
        self,
    ):

        catalog =  self.catalog

        catalog.create_table(
            "Rstats",
            [
                ["a", "INT"],
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


if __name__ == "__main__":
    unittest.main()