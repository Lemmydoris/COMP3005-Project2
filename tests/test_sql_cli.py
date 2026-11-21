import io
import json
import tempfile
import unittest
from contextlib import (
    redirect_stderr,
    redirect_stdout,
)
from pathlib import Path

from storage.catalog import Catalog

from sql_frontend.cli import (
    main,
)


class SQLCLITests(unittest.TestCase):

    def setUp(self):

        self.temp = (
            tempfile.TemporaryDirectory()
        )

        self.db_dir = Path(
            self.temp.name
        ) / "db"

        self.db_dir.mkdir()

        catalog = Catalog(
            self.db_dir
        )

        catalog.create_table(
            "Emp",
            [
                ["eid", "INT"],
                ["name", "VARCHAR", 20],
                ["age", "INT"],
                ["did", "INT"],
            ],
        )

        catalog.create_table(
            "Dept",
            [
                ["did", "INT"],
                ["title", "VARCHAR", 20],
            ],
        )

        catalog.flush()

    def tearDown(self):

        self.temp.cleanup()

    def write_sql(
        self,
        text,
        name="q.sql",
    ):

        path = (
            Path(
                self.temp.name
            )
            / name
        )

        path.write_text(
            text,
            encoding="utf-8",
        )

        return path

    def test_parse_explain_needs_no_catalog(
        self,
    ):

        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):

            code = main(
                [
                    "parse",
                    "--query",
                    (
                        "SELECT name "
                        "FROM Emp "
                        "WHERE age > 30"
                    ),
                    "--explain",
                ]
            )

        self.assertEqual(
            code,
            0,
        )

        output = (
            stdout.getvalue()
        )

        self.assertIn(
            "Program",
            output,
        )

        self.assertIn(
            "SelectQuery",
            output,
        )

        self.assertIn(
            "Comparison",
            output,
        )

        self.assertEqual(
            stderr.getvalue(),
            "",
        )

    def test_compile_json_matches_logical_shape(
        self,
    ):

        sql_file = self.write_sql(
            "SELECT name, age "
            "FROM Emp "
            "WHERE age > 30;"
        )

        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):

            code = main(
                [
                    "compile",
                    "--db",
                    str(
                        self.db_dir
                    ),
                    "--file",
                    str(sql_file),
                    "--json",
                ]
            )

        self.assertEqual(
            code,
            0,
        )

        plan = json.loads(
            stdout.getvalue()
        )

        self.assertEqual(
            plan,
            {
                "op": "project",
                "columns": [
                    "Emp.name",
                    "Emp.age",
                ],
                "child": {
                    "op": "select",
                    "condition":
                        "Emp.age > 30",
                    "child": {
                        "op": "scan",
                        "table": "Emp",
                    },
                },
            },
        )

        self.assertEqual(
            stderr.getvalue(),
            "",
        )

    def test_check_success_is_silent(
        self,
    ):

        sql_file = self.write_sql(
            "SELECT name "
            "FROM Emp;"
        )

        stdout = io.StringIO()
        stderr = io.StringIO()

        with (
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):

            code = main(
                [
                    "check",
                    "--db",
                    str(
                        self.db_dir
                    ),
                    "--file",
                    str(sql_file),
                ]
            )

        self.assertEqual(
            code,
            0,
        )

        self.assertEqual(
            stdout.getvalue(),
            "",
        )

        self.assertEqual(
            stderr.getvalue(),
            "",
        )

    def test_check_unknown_column_returns_one(
        self,
    ):

        sql_file = self.write_sql(
            "SELECT missing "
            "FROM Emp;"
        )

        stderr = io.StringIO()

        with redirect_stderr(
            stderr
        ):

            code = main(
                [
                    "check",
                    "--db",
                    str(
                        self.db_dir
                    ),
                    "--file",
                    str(sql_file),
                ]
            )

        self.assertEqual(
            code,
            1,
        )

        self.assertIn(
            "error: name:",
            stderr.getvalue(),
        )

        self.assertIn(
            "Unknown column",
            stderr.getvalue(),
        )

    def test_check_ambiguity_category(
        self,
    ):

        sql_file = self.write_sql(
            "SELECT did "
            "FROM Emp, Dept;"
        )

        stderr = io.StringIO()

        with redirect_stderr(
            stderr
        ):

            code = main(
                [
                    "check",
                    "--db",
                    str(
                        self.db_dir
                    ),
                    "--file",
                    str(sql_file),
                ]
            )

        self.assertEqual(
            code,
            1,
        )

        self.assertIn(
            "error: ambiguity:",
            stderr.getvalue(),
        )

    def test_compile_join_has_no_physical_join_name(
        self,
    ):

        sql_file = self.write_sql(
            "SELECT e.name, d.title "
            "FROM Emp e "
            "JOIN Dept d "
            "ON e.did = d.did;"
        )

        stdout = io.StringIO()

        with redirect_stdout(
            stdout
        ):

            code = main(
                [
                    "compile",
                    "--db",
                    str(
                        self.db_dir
                    ),
                    "--file",
                    str(sql_file),
                    "--json",
                ]
            )

        self.assertEqual(
            code,
            0,
        )

        output = (
            stdout.getvalue()
        )

        self.assertIn(
            '"op":"join"',
            output,
        )

        self.assertNotIn(
            "hash_join",
            output,
        )

        self.assertNotIn(
            "sort_merge_join",
            output,
        )

        self.assertNotIn(
            "nested_loop_join",
            output,
        )

    def test_compile_multiple_queries_returns_array(
        self,
    ):

        sql_file = self.write_sql(
            "SELECT name FROM Emp;"
            "SELECT title FROM Dept;"
        )

        stdout = io.StringIO()

        with redirect_stdout(
            stdout
        ):

            code = main(
                [
                    "compile",
                    "--db",
                    str(
                        self.db_dir
                    ),
                    "--file",
                    str(sql_file),
                    "--json",
                ]
            )

        self.assertEqual(
            code,
            0,
        )

        result = json.loads(
            stdout.getvalue()
        )

        self.assertIsInstance(
            result,
            list,
        )

        self.assertEqual(
            len(result),
            2,
        )

        self.assertEqual(
            result[0]["op"],
            "project",
        )

        self.assertEqual(
            result[1]["op"],
            "project",
        )

    def test_parse_syntax_error_returns_one(
        self,
    ):

        stderr = io.StringIO()

        with redirect_stderr(
            stderr
        ):

            code = main(
                [
                    "parse",
                    "--query",
                    (
                        "SELECT name "
                        "Emp"
                    ),
                    "--explain",
                ]
            )

        self.assertEqual(
            code,
            1,
        )

        self.assertIn(
            "error: syntax:",
            stderr.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()