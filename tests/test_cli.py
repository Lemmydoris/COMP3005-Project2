import io
import json
import os
import tempfile
import unittest

from contextlib import redirect_stdout
from storage.cli import (
    main,
    parse_schema
)

class StorageCLITests(unittest.TestCase):
    def setUp(self):

        self.temp_dir = (
            tempfile.TemporaryDirectory()
        )

        self.db_dir = (
            self.temp_dir.name
        )

    def tearDown(self):

        self.temp_dir.cleanup()

    def run_cli(self, arguments):

        output = io.StringIO()

        with redirect_stdout(output):

            result = main(
                arguments
            )

        return (
            result,
            output.getvalue()
        )

    # Schema parser
    def test_parse_schema(self):

        schema = parse_schema(
            "a:INT,b:VARCHAR(20),c:INT"
        )

        self.assertEqual(
            schema,
            [
                ("a", "INT"),
                ("b", "VARCHAR", 20),
                ("c", "INT")
            ]
        )

    # create -> load -> scan --json
    def test_create_load_scan_json(self):

        result, _ = self.run_cli(
            [
                "create-table",
                "--db",
                self.db_dir,
                "--name",
                "R",
                "--schema",
                "a:INT,b:VARCHAR(20),c:INT"
            ]
        )

        self.assertEqual(
            result,
            0
        )

        csv_path = os.path.join(
            self.db_dir,
            "r.csv"
        )

        with open(
            csv_path,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(
                "42,bob,7\n"
                "43,amy,9\n"
            )

        result, _ = self.run_cli(
            [
                "load",
                "--db",
                self.db_dir,
                "--table",
                "R",
                "--file",
                csv_path
            ]
        )

        self.assertEqual(
            result,
            0
        )

        result, output = self.run_cli(
            [
                "scan",
                "--db",
                self.db_dir,
                "--table",
                "R",
                "--frames",
                "8",
                "--json"
            ]
        )

        self.assertEqual(
            result,
            0
        )

        parsed = json.loads(
            output
        )

        self.assertEqual(
            parsed["table"],
            "R"
        )

        self.assertEqual(
            parsed["schema"],
            [
                ["a", "INT"],
                ["b", "VARCHAR", 20],
                ["c", "INT"]
            ]
        )

        self.assertEqual(
            parsed["rows"],
            [
                [42, "bob", 7],
                [43, "amy", 9]
            ]
        )

        self.assertEqual(
            set(parsed["stats"].keys()),
            {
                "hits",
                "misses",
                "evictions",
                "reads",
                "writes"
            }
        )

    # LRU professor trace
    def test_trace_lru_professor_example(self):

        trace_path = os.path.join(
            self.db_dir,
            "trace.txt"
        )

        with open(
            trace_path,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(
                "1\n"
                "2\n"
                "3\n"
                "1\n"
                "4\n"
                "2\n"
            )

        result, output = self.run_cli(
            [
                "trace",
                "--db",
                self.db_dir,
                "--file",
                trace_path,
                "--frames",
                "3",
                "--policy",
                "lru",
                "--json"
            ]
        )
        self.assertEqual(
            result,
            0
        )
        parsed = json.loads(
            output
        )
        self.assertEqual(
            parsed,
            {
                "policy": "lru",
                "frames": 3,
                "hits": 1,
                "misses": 5,
                "evictions": 2,
                "reads": 5,
                "writes": 0
            }
        )

    # CLOCK professor trace
    def test_trace_clock_professor_example(self):
        trace_path = os.path.join(
            self.db_dir,
            "trace.txt"
        )
        with open(
            trace_path,
            "w",
            encoding="utf-8"
        ) as file:
            file.write(
                "1\n"
                "2\n"
                "3\n"
                "1\n"
                "4\n"
                "2\n"
            )

        result, output = self.run_cli(
            [
                "trace",
                "--db",
                self.db_dir,
                "--file",
                trace_path,
                "--frames",
                "3",
                "--policy",
                "clock",
                "--json"
            ]
        )

        self.assertEqual(
            result,
            0
        )
        parsed = json.loads(
            output
        )
        self.assertEqual(
            parsed,
            {
                "policy": "clock",
                "frames": 3,
                "hits": 2,
                "misses": 4,
                "evictions": 1,
                "reads": 4,
                "writes": 0
            }
        )

    # Layout command
    def test_layout_reports_page_information(self):
        self.run_cli(
            [
                "create-table",
                "--db",
                self.db_dir,
                "--name",
                "R",
                "--schema",
                "a:INT"
            ]
        )

        csv_path = os.path.join(
            self.db_dir,
            "r.csv"
        )
        with open(
            csv_path,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(
                "42\n"
            )

        self.run_cli(
            [
                "load",
                "--db",
                self.db_dir,
                "--table",
                "R",
                "--file",
                csv_path
            ]
        )

        result, output = self.run_cli(
            [
                "layout",
                "--db",
                self.db_dir,
                "--table",
                "R",
                "--page",
                "1"
            ]
        )

        self.assertEqual(
            result,
            0
        )

        self.assertIn(
            "page_type: data",
            output
        )

        self.assertIn(
            "slot_count: 1",
            output
        )

    def test_scan_counters_are_deterministic(self):
        self.run_cli(
            [
                "create-table",
                "--db",
                self.db_dir,
                "--name",
                "R",
                "--schema",
                "a:INT,b:VARCHAR(20)"
            ]
        )

        csv_path = os.path.join(
            self.db_dir,
            "deterministic.csv"
        )
        with open(
            csv_path,
            "w",
            encoding="utf-8"
        ) as file:

            for i in range(50):
                file.write(
                    f"{i},name{i}\n"
                )
        self.run_cli(
            [
                "load",
                "--db",
                self.db_dir,
                "--table",
                "R",
                "--file",
                csv_path
            ]
        )
        result1, output1 = self.run_cli(
            [
                "scan",
                "--db",
                self.db_dir,
                "--table",
                "R",
                "--frames",
                "2",
                "--json"
            ]
        )
        result2, output2 = self.run_cli(
            [
                "scan",
                "--db",
                self.db_dir,
                "--table",
                "R",
                "--frames",
                "2",
                "--json"
            ]
        )

        self.assertEqual(
            result1,
            0
        )
        self.assertEqual(
            result2,
            0
        )
        scan1 = json.loads(
            output1
        )
        scan2 = json.loads(
            output2
        )
        
        self.assertEqual(
            scan1["rows"],
            scan2["rows"]
        )

        self.assertEqual(
            scan1["stats"],
            scan2["stats"]
        )

if __name__ == "__main__":
    unittest.main()