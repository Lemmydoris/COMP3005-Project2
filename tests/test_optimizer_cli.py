import io
import tempfile
import unittest

from contextlib import (
    redirect_stderr,
    redirect_stdout,
)
from pathlib import Path

from optimizer.cli import (
    build_argument_parser,
    main,
)

from storage.buffer import BufferPool
from storage.catalog import Catalog
from storage.disk import DiskManager
from storage.heap import HeapFile
from storage.record import encode_record


class OptimizerCLITests(
    unittest.TestCase
):

    def setUp(self):

        self.temp = (
            tempfile.TemporaryDirectory()
        )

        self.db_dir = (
            self.temp.name
        )

    def tearDown(self):

        self.temp.cleanup()

    def _create_table(
        self,
        name="R",
        rows=None,
    ):

        if rows is None:

            rows = [
                (1,),
                (2,),
                (3,),
                (4,),
            ]

        schema = [
            ["a", "INT"],
        ]

        catalog = Catalog(
            self.db_dir
        )

        catalog.create_table(
            name,
            schema,
        )

        metadata = (
            catalog.get_table(
                name
            )
        )

        path = (
            Path(
                self.db_dir
            )
            / metadata["file"]
        )

        disk = DiskManager(
            path
        )

        buffer = BufferPool(
            disk,
            frames=4,
            policy="lru",
        )

        heap = HeapFile(
            name,
            disk,
            buffer,
        )

        for row in rows:

            heap.insert(
                encode_record(
                    schema,
                    row,
                )
            )

        buffer.flush_all()

        catalog.update_table(
            name,
            num_pages=(
                disk.num_pages()
            ),
            num_tuples=(
                len(rows)
            ),
        )

        catalog.flush()

    def test_analyze_parser_defaults_to_twenty_buckets(
        self,
    ):

        parser = (
            build_argument_parser()
        )

        args = parser.parse_args(
            [
                "analyze",
                "--db",
                self.db_dir,
                "--table",
                "R",
            ]
        )

        self.assertEqual(
            args.buckets,
            20,
        )

    def test_analyze_success_is_silent_and_persists_statistics(
        self,
    ):

        self._create_table()

        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(
            stdout
        ), redirect_stderr(
            stderr
        ):

            code = main(
                [
                    "analyze",
                    "--db",
                    self.db_dir,
                    "--table",
                    "R",
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

        catalog = Catalog(
            self.db_dir
        )

        statistics = (
            catalog
            .get_table(
                "R"
            )[
                "statistics"
            ]
        )

        self.assertEqual(
            statistics[
                "n_tuples"
            ],
            4,
        )

        self.assertEqual(
            statistics[
                "columns"
            ][
                "a"
            ][
                "ndv"
            ],
            4,
        )

        catalog.flush()

    def test_custom_bucket_count_is_used(
        self,
    ):

        self._create_table()

        code = main(
            [
                "analyze",
                "--db",
                self.db_dir,
                "--table",
                "R",
                "--buckets",
                "2",
            ]
        )

        self.assertEqual(
            code,
            0,
        )

        catalog = Catalog(
            self.db_dir
        )

        histogram = (
            catalog
            .get_table(
                "R"
            )[
                "statistics"
            ][
                "columns"
            ][
                "a"
            ][
                "hist"
            ]
        )

        self.assertEqual(
            len(histogram),
            2,
        )

        catalog.flush()

    def test_unknown_table_returns_one_without_traceback(
        self,
    ):

        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(
            stdout
        ), redirect_stderr(
            stderr
        ):

            code = main(
                [
                    "analyze",
                    "--db",
                    self.db_dir,
                    "--table",
                    "Missing",
                ]
            )

        self.assertEqual(
            code,
            1,
        )

        message = (
            stderr.getvalue()
        )

        self.assertIn(
            "Unknown table",
            message,
        )

        self.assertIn(
            "error: optimizer:",
            message,
        )

        self.assertNotIn(
            "Traceback",
            message,
        )

        self.assertEqual(
            stdout.getvalue(),
            "",
        )


if __name__ == "__main__":
    unittest.main()