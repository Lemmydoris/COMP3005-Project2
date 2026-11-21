import tempfile
import unittest

from execution.plan import (
    PlanError,
    build_operator,
)
from execution.seqscan import SeqScan
from storage.catalog import Catalog


class SeqScanAliasTests(
    unittest.TestCase
):

    def setUp(self):

        self.temp = (
            tempfile.TemporaryDirectory()
        )

        self.db_dir = (
            self.temp.name
        )

        catalog = Catalog(
            self.db_dir
        )

        catalog.create_table(
            "Emp",
            [
                [
                    "id",
                    "INT",
                ],
                [
                    "name",
                    "VARCHAR",
                    20,
                ],
            ],
        )

        catalog.flush()

    def tearDown(self):

        self.temp.cleanup()

    def test_unaliased_scan_keeps_table_qualifier(
        self,
    ):

        scan = SeqScan(
            self.db_dir,
            "Emp",
        )

        scan.open()

        try:

            self.assertEqual(
                scan.schema,
                [
                    [
                        "Emp.id",
                        "INT",
                    ],
                    [
                        "Emp.name",
                        "VARCHAR",
                        20,
                    ],
                ],
            )

        finally:

            scan.close()

    def test_alias_changes_visible_qualifier_only(
        self,
    ):

        scan = SeqScan(
            self.db_dir,
            "Emp",
            alias="e",
        )

        scan.open()

        try:

            self.assertEqual(
                scan.table_name,
                "Emp",
            )

            self.assertEqual(
                scan.alias,
                "e",
            )

            self.assertEqual(
                scan.schema,
                [
                    [
                        "e.id",
                        "INT",
                    ],
                    [
                        "e.name",
                        "VARCHAR",
                        20,
                    ],
                ],
            )

        finally:

            scan.close()

    def test_plan_builder_accepts_seqscan_alias(
        self,
    ):

        operator = build_operator(
            {
                "op":
                    "seqscan",
                "table":
                    "Emp",
                "alias":
                    "e",
            },
            db_dir=self.db_dir,
            frames=4,
        )

        self.assertIsInstance(
            operator,
            SeqScan,
        )

        self.assertEqual(
            operator.table_name,
            "Emp",
        )

        self.assertEqual(
            operator.alias,
            "e",
        )

    def test_plan_builder_still_rejects_other_extra_fields(
        self,
    ):

        with self.assertRaises(
            PlanError
        ):

            build_operator(
                {
                    "op":
                        "seqscan",
                    "table":
                        "Emp",
                    "alias":
                        "e",
                    "bad":
                        123,
                },
                db_dir=self.db_dir,
                frames=4,
            )

    def test_two_aliases_can_scan_same_base_table(
        self,
    ):

        left = build_operator(
            {
                "op":
                    "seqscan",
                "table":
                    "Emp",
                "alias":
                    "e",
            },
            db_dir=self.db_dir,
            frames=4,
        )

        right = build_operator(
            {
                "op":
                    "seqscan",
                "table":
                    "Emp",
                "alias":
                    "m",
            },
            db_dir=self.db_dir,
            frames=4,
        )

        left.open()
        right.open()

        try:

            self.assertEqual(
                left.schema[0][0],
                "e.id",
            )

            self.assertEqual(
                right.schema[0][0],
                "m.id",
            )

            self.assertNotEqual(
                left.schema,
                right.schema,
            )

        finally:

            left.close()
            right.close()


if __name__ == "__main__":
    unittest.main()