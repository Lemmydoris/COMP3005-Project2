import argparse
import json
import sys
from dataclasses import (
    fields,
    is_dataclass,
)
from pathlib import Path

from storage.catalog import Catalog

from sql_frontend.ast import (
    SelectQuery,
    SetQuery,
)
from sql_frontend.lexer import (
    SQLLexError,
)
from sql_frontend.parser import (
    SQLSyntaxError,
    parse_sql,
)
from sql_frontend.semantic import (
    AnalyzedSelect,
    AnalyzedSet,
    SQLSemanticAnalyzer,
    SQLSemanticError,
)
from sql_frontend.translator import (
    LogicalPlanTranslator,
    SQLTranslationError,
)


def read_sql_file(path):

    file_path = Path(path)

    try:
        return file_path.read_text(
            encoding="utf-8"
        )

    except OSError as exc:
        raise ValueError(
            "Could not read SQL file "
            f"{file_path}: {exc}"
        )


# ============================================================
# Parse-tree explanation
# ============================================================


def explain_ast(
    value,
    indent=0,
    label=None,
):

    prefix = "  " * indent

    lines = []

    if label is not None:
        label_prefix = (
            f"{label}: "
        )
    else:
        label_prefix = ""

    if is_dataclass(value):

        lines.append(
            prefix
            + label_prefix
            + type(value).__name__
        )

        for field in fields(value):

            # Source positions are useful in
            # errors but make --explain noisy.
            if field.name in {
                "line",
                "column",
            }:
                continue

            child = getattr(
                value,
                field.name,
            )

            if is_dataclass(child):

                lines.extend(
                    explain_ast(
                        child,
                        indent + 1,
                        field.name,
                    )
                )

            elif isinstance(
                child,
                (
                    list,
                    tuple,
                ),
            ):

                lines.append(
                    "  " * (
                        indent + 1
                    )
                    + f"{field.name}:"
                )

                for index, item in enumerate(
                    child
                ):

                    if is_dataclass(
                        item
                    ):

                        lines.extend(
                            explain_ast(
                                item,
                                indent + 2,
                                f"[{index}]",
                            )
                        )

                    else:

                        lines.append(
                            "  " * (
                                indent + 2
                            )
                            + f"[{index}] "
                            + repr(item)
                        )

            else:

                lines.append(
                    "  " * (
                        indent + 1
                    )
                    + f"{field.name}: "
                    + repr(child)
                )

        return lines

    lines.append(
        prefix
        + label_prefix
        + repr(value)
    )

    return lines


# ============================================================
# Compilation helpers
# ============================================================


def analyze_text(
    text,
    db_dir,
):

    program = parse_sql(
        text
    )

    catalog = Catalog(
        db_dir
    )

    try:

        analyzer = (
            SQLSemanticAnalyzer(
                catalog
            )
        )

        return (
            analyzer.analyze_program(
                program
            )
        )

    finally:

        catalog.flush()


def compile_text(
    text,
    db_dir,
):

    analyzed = analyze_text(
        text,
        db_dir,
    )

    translator = (
        LogicalPlanTranslator()
    )

    plans = []

    for statement in (
        analyzed.statements
    ):

        if isinstance(
            statement,
            (
                AnalyzedSelect,
                AnalyzedSet,
            ),
        ):

            plans.append(
                translator.translate_query(
                    statement
                )
            )

        else:

            # CREATE and INSERT belong to the
            # SQL grammar and can be validated by
            # `sql check`, but the Module 3 handout
            # defines logical plan nodes only for
            # queries.
            raise SQLSemanticError(
                "schema",
                (
                    "sql compile accepts "
                    "query statements only; "
                    "use sql check to validate "
                    "CREATE or INSERT."
                ),
                (
                    statement.statement.line
                ),
                (
                    statement.statement.column
                ),
            )

    if len(plans) == 1:
        return plans[0]

    return plans


# ============================================================
# Commands
# ============================================================


def parse_command(args):

    program = parse_sql(
        args.query
    )

    if args.explain:

        print(
            "\n".join(
                explain_ast(
                    program
                )
            )
        )

    return 0


def compile_command(args):

    text = read_sql_file(
        args.file
    )

    plan = compile_text(
        text,
        args.db,
    )

    if args.json:

        print(
            json.dumps(
                plan,
                separators=(
                    ",",
                    ":",
                ),
            )
        )

    else:

        print(
            json.dumps(
                plan,
                indent=2,
            )
        )

    return 0


def check_command(args):

    text = read_sql_file(
        args.file
    )

    analyze_text(
        text,
        args.db,
    )

    # Successful check is intentionally
    # silent: "errors only".
    return 0


# ============================================================
# Argument parser
# ============================================================


def build_argument_parser():

    parser = argparse.ArgumentParser(
        prog="sql",
        description=(
            "COMP 3005 Module 3 "
            "SQL front end"
        ),
    )

    subparsers = (
        parser.add_subparsers(
            dest="command",
            required=True,
        )
    )

    # --------------------------------------------------------
    # sql parse
    # --------------------------------------------------------

    parse_parser = (
        subparsers.add_parser(
            "parse",
            help=(
                "Parse SQL without "
                "using a catalog."
            ),
        )
    )

    parse_parser.add_argument(
        "--query",
        required=True,
        help="SQL query text",
    )

    parse_parser.add_argument(
        "--explain",
        action="store_true",
        help=(
            "Print the indented "
            "parse tree."
        ),
    )

    parse_parser.set_defaults(
        handler=parse_command
    )

    # --------------------------------------------------------
    # sql compile
    # --------------------------------------------------------

    compile_parser = (
        subparsers.add_parser(
            "compile",
            help=(
                "Compile SQL to a "
                "logical plan."
            ),
        )
    )

    compile_parser.add_argument(
        "--db",
        required=True,
        help="Database directory",
    )

    compile_parser.add_argument(
        "--file",
        required=True,
        help="SQL input file",
    )

    compile_parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Print compact JSON."
        ),
    )

    compile_parser.set_defaults(
        handler=compile_command
    )

    # --------------------------------------------------------
    # sql check
    # --------------------------------------------------------

    check_parser = (
        subparsers.add_parser(
            "check",
            help=(
                "Parse and semantically "
                "check SQL."
            ),
        )
    )

    check_parser.add_argument(
        "--db",
        required=True,
        help="Database directory",
    )

    check_parser.add_argument(
        "--file",
        required=True,
        help="SQL input file",
    )

    check_parser.set_defaults(
        handler=check_command
    )

    return parser


# ============================================================
# Main
# ============================================================


def main(argv=None):

    parser = (
        build_argument_parser()
    )

    args = parser.parse_args(
        argv
    )

    try:

        return args.handler(
            args
        )

    except (
        SQLLexError,
        SQLSyntaxError,
        SQLSemanticError,
    ) as exc:

        print(
            str(exc),
            file=sys.stderr,
        )

        return 1

    except SQLTranslationError as exc:

        print(
            (
                "error: schema: "
                f"{exc} "
                "at line 1, column 1"
            ),
            file=sys.stderr,
        )

        return 1

    except ValueError as exc:

        print(
            f"error: schema: {exc}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )