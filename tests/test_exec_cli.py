import contextlib
import io
import json
import os
import tempfile
import unittest

from execution.base import (
    END,
    Operator,
)
from execution.cli import (
    execute_operator,
    main,
    operator_name,
    plan_totals,
    trace_lines,
)
from execution.limit import Limit


class CountingSource(Operator):

    def __init__(
        self,
        rows,
    ):
        super().__init__()

        self.schema = [
            ["R.a", "INT"],
        ]

        self.rows = [
            tuple(row)
            for row in rows
        ]

        self.position = 0

    def open(self):
        self.position = 0

        self._reset_counters()

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "CountingSource "
                "is not open."
            )

        if self.position >= len(
            self.rows
        ):
            return END

        row = self.rows[
            self.position
        ]

        self.position += 1

        self._count_output()

        # Synthetic owned counters used to
        # test CLI aggregation.
        self._count_read()
        self._count_comparison()

        return row

    def close(self):
        self.is_open = False


class ExecCLITests(unittest.TestCase):

    def test_execute_operator_collects_rows(self):

        source = CountingSource(
            [
                (1,),
                (2,),
                (3,),
            ]
        )

        result = execute_operator(
            source
        )

        self.assertEqual(
            result,
            {
                "schema": [
                    ["R.a", "INT"],
                ],
                "rows": [
                    [1],
                    [2],
                    [3],
                ],
            },
        )

        self.assertFalse(
            source.is_open
        )

    def test_plan_totals_use_root_tuple_count(self):

        source = CountingSource(
            [
                (1,),
                (2,),
                (3,),
            ]
        )

        root = Limit(
            source,
            2,
        )

        execute_operator(
            root
        )

        totals = plan_totals(
            root
        )

        # Result contains two tuples.
        self.assertEqual(
            totals[
                "tuples_out"
            ],
            2,
        )

        # Child was asked for only two rows.
        self.assertEqual(
            totals[
                "page_reads"
            ],
            2,
        )

        self.assertEqual(
            totals[
                "comparisons"
            ],
            2,
        )

    def test_trace_is_preorder_and_indented(self):

        source = CountingSource(
            [
                (1,),
            ]
        )

        root = Limit(
            source,
            1,
        )

        execute_operator(
            root
        )

        lines = trace_lines(
            root
        )

        self.assertEqual(
            len(lines),
            2,
        )

        self.assertTrue(
            lines[0].startswith(
                "limit 1"
            )
        )

        self.assertTrue(
            lines[1].startswith(
                "  CountingSource"
            )
        )

    def test_operator_name_limit(self):

        operator = Limit(
            CountingSource([]),
            7,
        )

        self.assertEqual(
            operator_name(
                operator
            ),
            "limit 7",
        )

    def test_main_rejects_frames_below_four(self):

        stderr = io.StringIO()

        with contextlib.redirect_stderr(
            stderr
        ):
            result = main(
                [
                    "run",
                    "--db",
                    "db",
                    "--plan",
                    "plan.json",
                    "--frames",
                    "3",
                ]
            )

        self.assertEqual(
            result,
            1,
        )

        self.assertIn(
            "at least 4",
            stderr.getvalue(),
        )

    def test_main_invalid_json_has_no_traceback(self):

        with tempfile.TemporaryDirectory() as temp_dir:

            plan_path = os.path.join(
                temp_dir,
                "bad.json",
            )

            with open(
                plan_path,
                "w",
                encoding="utf-8",
            ) as handle:
                handle.write(
                    '{"op":'
                )

            stderr = io.StringIO()

            with contextlib.redirect_stderr(
                stderr
            ):
                result = main(
                    [
                        "run",
                        "--db",
                        temp_dir,
                        "--plan",
                        plan_path,
                        "--frames",
                        "4",
                        "--json",
                    ]
                )

            message = (
                stderr.getvalue()
            )

            self.assertEqual(
                result,
                1,
            )

            self.assertIn(
                "error:",
                message,
            )

            self.assertNotIn(
                "Traceback",
                message,
            )

    def test_main_invalid_plan_node_names_error(self):

        with tempfile.TemporaryDirectory() as temp_dir:

            plan_path = os.path.join(
                temp_dir,
                "bad-plan.json",
            )

            with open(
                plan_path,
                "w",
                encoding="utf-8",
            ) as handle:
                json.dump(
                    {
                        "op":
                            "banana_scan",
                    },
                    handle,
                )

            stderr = io.StringIO()

            with contextlib.redirect_stderr(
                stderr
            ):
                result = main(
                    [
                        "run",
                        "--db",
                        temp_dir,
                        "--plan",
                        plan_path,
                        "--frames",
                        "4",
                        "--json",
                    ]
                )

            self.assertEqual(
                result,
                1,
            )

            self.assertIn(
                "root",
                stderr.getvalue(),
            )

            self.assertIn(
                "banana_scan",
                stderr.getvalue(),
            )


if __name__ == "__main__":
    unittest.main()