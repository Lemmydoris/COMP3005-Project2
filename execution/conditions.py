from execution.base import column_index
from parser import parse_condition_text
from ra_tree import Attr, Comparison, Literal, Logical, Not


def resolve_column_name(schema, name):
    """
    Resolve a column name against a qualified Module 2 schema.

    Qualified names such as R.a are matched exactly.

    An unqualified name such as a is accepted only when it
    uniquely identifies one column.
    """

    if "." in name:
        column_index(schema, name)
        return name

    matches = [
        column[0]
        for column in schema
        if column[0].split(".")[-1] == name
    ]

    if not matches:
        raise ValueError(
            f"Unknown column: {name}"
        )

    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous column: {name}"
        )

    return matches[0]


def attr_name(attr):
    """
    Convert a parsed Attr node into its textual column name.
    """

    if attr.relation:
        return f"{attr.relation}.{attr.name}"

    return attr.name


def schema_type(schema, column_name):
    """
    Return INT or VARCHAR for a schema column.
    """

    resolved = resolve_column_name(
        schema,
        column_name,
    )

    index = column_index(
        schema,
        resolved,
    )

    return schema[index][1]


def literal_type(node):
    if not isinstance(node, Literal):
        raise TypeError(
            "Expected a literal node."
        )

    if isinstance(node.value, bool):
        raise TypeError(
            "Boolean literals are not supported."
        )

    if isinstance(node.value, int):
        return "INT"

    if isinstance(node.value, str):
        return "VARCHAR"

    raise TypeError(
        f"Unsupported literal type: "
        f"{type(node.value).__name__}"
    )


def operand_type(node, schema):
    if isinstance(node, Attr):
        return schema_type(
            schema,
            attr_name(node),
        )

    if isinstance(node, Literal):
        return literal_type(node)

    raise TypeError(
        f"Invalid comparison operand: "
        f"{type(node).__name__}"
    )


def validate_condition(node, schema):
    """
    Validate every referenced column and every comparison
    before execution begins.
    """

    if isinstance(node, Not):
        validate_condition(
            node.condition,
            schema,
        )
        return

    if isinstance(node, Logical):
        validate_condition(
            node.left,
            schema,
        )

        validate_condition(
            node.right,
            schema,
        )

        return

    if isinstance(node, Comparison):
        left_type = operand_type(
            node.left,
            schema,
        )

        right_type = operand_type(
            node.right,
            schema,
        )

        if left_type != right_type:
            raise TypeError(
                f"Cannot compare "
                f"{left_type} with {right_type}"
            )

        return

    raise ValueError(
        f"Invalid condition node: "
        f"{type(node).__name__}"
    )


def operand_value(node, schema, row):
    if isinstance(node, Literal):
        return node.value

    if isinstance(node, Attr):
        resolved = resolve_column_name(
            schema,
            attr_name(node),
        )

        index = column_index(
            schema,
            resolved,
        )

        return row[index]

    raise ValueError(
        f"Invalid comparison operand: "
        f"{type(node).__name__}"
    )


def compare_values(left, right, type_name, op):
    """
    Perform a Module 2 comparison.

    VARCHAR ordering is explicitly performed on UTF-8 bytes.
    """

    if type_name == "VARCHAR":
        left = left.encode("utf-8")
        right = right.encode("utf-8")

    if op == "=":
        return left == right

    if op == "!=":
        return left != right

    if op == "<":
        return left < right

    if op == "<=":
        return left <= right

    if op == ">":
        return left > right

    if op == ">=":
        return left >= right

    raise ValueError(
        f"Unknown comparison operator: {op}"
    )


def evaluate_condition(node, schema, row):
    """
    Evaluate an already validated condition against one tuple.

    The Filter operator, rather than this function, owns the
    comparison counter. That allows one count per tuple examined
    even for compound conditions.
    """

    if isinstance(node, Not):
        return not evaluate_condition(
            node.condition,
            schema,
            row,
        )

    if isinstance(node, Logical):
        if node.op == "and":
            return (
                evaluate_condition(
                    node.left,
                    schema,
                    row,
                )
                and
                evaluate_condition(
                    node.right,
                    schema,
                    row,
                )
            )

        if node.op == "or":
            return (
                evaluate_condition(
                    node.left,
                    schema,
                    row,
                )
                or
                evaluate_condition(
                    node.right,
                    schema,
                    row,
                )
            )

        raise ValueError(
            f"Unknown logical operator: {node.op}"
        )

    if isinstance(node, Comparison):
        left = operand_value(
            node.left,
            schema,
            row,
        )

        right = operand_value(
            node.right,
            schema,
            row,
        )

        type_name = operand_type(
            node.left,
            schema,
        )

        return compare_values(
            left,
            right,
            type_name,
            node.op,
        )

    raise ValueError(
        f"Invalid condition node: "
        f"{type(node).__name__}"
    )


def prepare_condition(condition, schema):
    """
    Accept either condition text or an already parsed tree.
    """

    if isinstance(condition, str):
        condition = parse_condition_text(
            condition
        )

    validate_condition(
        condition,
        schema,
    )

    return condition