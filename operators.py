from dataclasses import dataclass
from ra_tree import (
    Relation, Attr, Literal, Comparison, Logical, Not,
    Select, Project, Rename, BinaryOp,
)

# ERRORS
class RAError(Exception):
    pass

class RANameError(RAError):
    pass

class SchemaError(RAError):
    pass

class RATypeError(RAError):
    pass

# TABLE REPRESENTATION
@dataclass
class Column:
    relation: str
    name: str
    type_name: str = None

    def display_name(self):
        if self.relation:
            return f"{self.relation}.{self.name}"
        return self.name

@dataclass
class Table:
    name: str
    columns: list
    rows: list

# TUPLE / SET HELPERS
def tuples_equal(a, b):
    if len(a) != len(b):
        return False

    for i in range(len(a)):
        if a[i] != b[i]:
            return False

    return True

def contains_tuple(rows, candidate):
    for row in rows:
        if tuples_equal(row, candidate):
            return True

    return False

def add_unique(rows, candidate):
    if not contains_tuple(rows, candidate):
        rows.append(tuple(candidate))

def value_type(value):
    if isinstance(value, (int, float)):
        return "number"

    if isinstance(value, str):
        return "string"

    raise RATypeError(
        f"Unsupported value type: {type(value).__name__}"
    )

# CREATE A BASE RELATION
def make_relation(name, attribute_names, rows):
    clean_rows = []

    for row in rows:
        if len(row) != len(attribute_names):
            raise SchemaError(
                f"Relation {name} expects "
                f"{len(attribute_names)} values per tuple, "
                f"but found {len(row)}"
            )

        # Project 2 uses bag semantics: duplicate base tuples are preserved.
        clean_rows.append(tuple(row))

    types = [None] * len(attribute_names)

    for row in clean_rows:
        for i, value in enumerate(row):
            current_type = value_type(value)

            if types[i] is None:
                types[i] = current_type

            elif types[i] != current_type:
                raise RATypeError(
                    f"Attribute {attribute_names[i]} contains "
                    f"incompatible value types"
                )
    columns = []

    for i, attribute_name in enumerate(attribute_names):
        columns.append(
            Column(
                relation=name,
                name=attribute_name,
                type_name=types[i],
            )
        )
    return Table(name, columns, clean_rows)

# ATTRIBUTE RESOLUTION
def resolve_attribute(table, attr):
    matches = []

    for i, column in enumerate(table.columns):

        if attr.relation is not None:
            if (
                column.relation == attr.relation
                and column.name == attr.name
            ):
                matches.append(i)

        else:
            if column.name == attr.name:
                matches.append(i)

    if len(matches) == 0:
        if attr.relation:
            name = f"{attr.relation}.{attr.name}"
        else:
            name = attr.name

        raise RANameError(
            f"Unknown attribute {name}"
        )

    if len(matches) > 1:
        raise RANameError(
            f"Ambiguous attribute {attr.name}; "
            f"use a qualified name"
        )
    return matches[0]

# CONDITION EVALUATION
def operand_value(node, table, row):
    if isinstance(node, Literal):
        return node.value

    if isinstance(node, Attr):
        index = resolve_attribute(table, node)
        return row[index]

    raise RAError(
        f"Invalid condition operand: {type(node).__name__}"
    )

def evaluate_condition(node, table, row):

    if isinstance(node, Not):
        return not evaluate_condition(
            node.condition,
            table,
            row
        )

    if isinstance(node, Logical):
        if node.op == "and":
            return (
                evaluate_condition(node.left, table, row)
                and
                evaluate_condition(node.right, table, row)
            )

        if node.op == "or":
            return (
                evaluate_condition(node.left, table, row)
                or
                evaluate_condition(node.right, table, row)
            )

    if isinstance(node, Comparison):
        left = operand_value(node.left, table, row)
        right = operand_value(node.right, table, row)

        left_type = value_type(left)
        right_type = value_type(right)

        if left_type != right_type:
            raise RATypeError(
                f"Cannot compare {left_type} with {right_type}"
            )

        if node.op == "=":
            return left == right

        if node.op == "!=":
            return left != right

        if node.op == "<":
            return left < right

        if node.op == "<=":
            return left <= right

        if node.op == ">":
            return left > right

        if node.op == ">=":
            return left >= right

    raise RAError(
        f"Invalid condition node: {type(node).__name__}"
    )

# RELATIONAL OPERATORS
def select_table(table, condition, counters):
    output_rows = []

    for row in table.rows:
        counters["select"] += 1

        if evaluate_condition(condition, table, row):
            output_rows.append(row)

    return Table(
        table.name,
        list(table.columns),
        output_rows
    )

def project_table(table, attributes):
    indexes = []
    output_columns = []

    for attr in attributes:
        index = resolve_attribute(table, attr)

        if index in indexes:
            raise SchemaError(
                f"Duplicate projection attribute {attr.name}"
            )

        indexes.append(index)
        output_columns.append(table.columns[index])

    output_rows = []

    for row in table.rows:
        projected = tuple(
            row[index] for index in indexes
        )

        output_rows.append(projected)

    return Table(
        table.name,
        output_columns,
        output_rows
    )

def distinct_table(table):
    output_rows = []
    for row in table.rows:
        add_unique(output_rows, row)
    return Table(table.name, list(table.columns), output_rows)


def rename_table(table, new_name):
    columns = []

    for column in table.columns:
        columns.append(
            Column(
                relation=new_name,
                name=column.name,
                type_name=column.type_name
            )
        )

    return Table(
        new_name,
        columns,
        list(table.rows)
    )

def combined_schema(left, right):
    columns = []

    for column in left.columns + right.columns:
        key = (column.relation, column.name)

        for existing in columns:
            existing_key = (
                existing.relation,
                existing.name
            )

            if key == existing_key:
                raise SchemaError(
                    f"Qualified attribute collision: "
                    f"{column.display_name()}"
                )

        columns.append(column)

    return columns

def times_table(left, right):
    columns = combined_schema(left, right)
    rows = []

    for left_row in left.rows:
        for right_row in right.rows:
            combined = tuple(left_row) + tuple(right_row)
            rows.append(combined)

    return Table(
        None,
        columns,
        rows
    )

def join_table(left, right, condition, counters):
    columns = combined_schema(left, right)

    temporary = Table(
        None,
        columns,
        []
    )

    output_rows = []

    for left_row in left.rows:
        for right_row in right.rows:
            counters["join"] += 1

            combined = tuple(left_row) + tuple(right_row)

            if evaluate_condition(
                condition,
                temporary,
                combined
            ):
                output_rows.append(combined)

    return Table(
        None,
        columns,
        output_rows
    )

def schemas_union_compatible(left, right):
    if len(left.columns) != len(right.columns):
        raise SchemaError(
            "Relations have different numbers of attributes"
        )

    for i in range(len(left.columns)):
        left_col = left.columns[i]
        right_col = right.columns[i]

        if left_col.name != right_col.name:
            raise SchemaError(
                "Relations have different attribute names "
                "or attribute order"
            )

        if (
            left_col.type_name is not None
            and right_col.type_name is not None
            and left_col.type_name != right_col.type_name
        ):
            raise SchemaError(
                f"Incompatible types for attribute "
                f"{left_col.name}"
            )


def union_table(left, right):
    schemas_union_compatible(left, right)

    rows = []

    for row in left.rows:
        add_unique(rows, row)

    for row in right.rows:
        add_unique(rows, row)

    return Table(
        left.name,
        list(left.columns),
        rows
    )

def intersect_table(left, right):
    schemas_union_compatible(left, right)

    rows = []

    for left_row in left.rows:
        if contains_tuple(right.rows, left_row):
            add_unique(rows, left_row)

    return Table(
        left.name,
        list(left.columns),
        rows
    )

def minus_table(left, right):
    schemas_union_compatible(left, right)
    rows = []

    for left_row in left.rows:
        if not contains_tuple(right.rows, left_row):
            add_unique(rows, left_row)

    return Table(
        left.name,
        list(left.columns),
        rows
    )

# DATA SOURCE ADAPTER
class DictDataSource:
    def __init__(self, relations):
        self.relations = relations

    def get_relation(self, name):
        if name not in self.relations:
            raise RANameError(f"Unknown relation {name}")
        return self.relations[name]


# TREE EVALUATOR
class Evaluator:
    def __init__(self, source):
        # Accept the old dict form for compatibility, but operators now pull
        # relations through a source object rather than owning the data.
        if isinstance(source, dict):
            source = DictDataSource(source)
        if not hasattr(source, "get_relation"):
            raise TypeError("source must provide get_relation(name)")
        self.source = source

        self.counters = {
            "select": 0,
            "join": 0,
        }

    def reset_counters(self):
        self.counters["select"] = 0
        self.counters["join"] = 0

    def evaluate(self, node):

        if isinstance(node, Relation):
            return self.source.get_relation(node.name)

        if isinstance(node, Select):
            source = self.evaluate(node.source)

            return select_table(
                source,
                node.condition,
                self.counters
            )

        if isinstance(node, Project):
            source = self.evaluate(node.source)

            return project_table(
                source,
                node.attributes
            )

        if isinstance(node, Rename):
            source = self.evaluate(node.source)

            return rename_table(
                source,
                node.new_name
            )

        if isinstance(node, BinaryOp):
            left = self.evaluate(node.left)
            right = self.evaluate(node.right)

            if node.op == "union":
                return union_table(left, right)

            if node.op == "intersect":
                return intersect_table(left, right)

            if node.op == "minus":
                return minus_table(left, right)

            if node.op == "times":
                return times_table(left, right)

            if node.op == "join":
                return join_table(
                    left,
                    right,
                    node.condition,
                    self.counters
                )

        raise RAError(
            f"Unsupported parse-tree node "
            f"{type(node).__name__}"
        )
