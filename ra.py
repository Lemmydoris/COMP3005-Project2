import argparse
from tokenizer import LexicalError
from parser import ParseError, parse_query
from ra_tree import format_tree
from operators import (
    RAError,
    Evaluator,
)
from cli_output import format_table
from relation_loader import (
    RelationDefinitionError,
    load_relations_file,
)

def main():
    argument_parser = argparse.ArgumentParser(
        description="Relational Algebra Engine"
    )

    argument_parser.add_argument(
        "--tree",
        action="store_true",
        help="Print the parse tree without executing the query"
    )

    argument_parser.add_argument(
        "--data",
        help="File containing relation definitions"
    )

    argument_parser.add_argument(
        "query",
        nargs="?",
        help="Relational algebra query"
    )

    args = argument_parser.parse_args()

    if args.query is None:
        print("Error: no query was provided.")
        return

    try:
        # First parse the query.
        tree = parse_query(args.query)

        # tree prints the tree only.
        if args.tree:
            print(format_tree(tree))
            return

        # Execution requires relation data.
        if args.data is None:
            print(
                "Error: executing a query requires "
                "--data <filename>."
            )
            return

        # Load the relations.
        relations = load_relations_file(args.data)

        # Evaluate the parse tree.
        evaluator = Evaluator(relations)
        result = evaluator.evaluate(tree)

        # Print the result.
        print(format_table(result))

        print()
        print(
            "Select examined:",
            evaluator.counters["select"]
        )

        print(
            "Join comparisons:",
            evaluator.counters["join"]
        )

    except LexicalError as error:
        print(f"Lexical error: {error}")

    except ParseError as error:
        print(error)

    except RelationDefinitionError as error:
        print(error)

    except RAError as error:
        print(
            f"{type(error).__name__}: {error}"
        )

    except FileNotFoundError:
        print(
            f"Error: data file {args.data!r} "
            f"was not found."
        )

    except Exception as error:
        # The command line user should never see a stack trace.
        print(f"Error: {error}")


if __name__ == "__main__":
    main()