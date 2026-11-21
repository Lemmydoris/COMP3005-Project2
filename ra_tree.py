from dataclasses import dataclass
import json


class Node:
    def label(self):
        return self.__class__.__name__

    def children(self):
        return []


@dataclass
class Relation(Node):
    name: str

    def label(self):
        return f"Relation({self.name})"


@dataclass
class Attr(Node):
    name: str
    relation: str = None

    def label(self):
        if self.relation:
            return f"Attr({self.relation}.{self.name})"
        return f"Attr({self.name})"


@dataclass
class Literal(Node):
    value: object
    kind: str

    def label(self):
        if self.kind == "NUMBER":
            return f"Num({self.value})"
        return f"String({self.value!r})"


@dataclass
class Comparison(Node):
    op: str
    left: Node
    right: Node

    def label(self):
        names = {
            "=": "Eq",
            "!=": "Ne",
            "<>": "Ne",
            "<": "Lt",
            "<=": "Le",
            ">": "Gt",
            ">=": "Ge",
        }
        return names[self.op]

    def children(self):
        return [self.left, self.right]


@dataclass
class Logical(Node):
    op: str
    left: Node
    right: Node

    def label(self):
        return self.op.capitalize()

    def children(self):
        return [self.left, self.right]


@dataclass
class Not(Node):
    condition: Node

    def children(self):
        return [self.condition]


@dataclass
class Select(Node):
    condition: Node
    source: Node

    def label(self):
        return "Select"

    def children(self):
        return [self.condition, self.source]


@dataclass
class Project(Node):
    attributes: list
    source: Node

    def label(self):
        names = []
        for attr in self.attributes:
            if attr.relation:
                names.append(f"{attr.relation}.{attr.name}")
            else:
                names.append(attr.name)
        return f"Project(attrs=[{', '.join(names)}])"

    def children(self):
        return [self.source]


@dataclass
class Rename(Node):
    new_name: str
    source: Node

    def label(self):
        return f"Rename({self.new_name})"

    def children(self):
        return [self.source]


@dataclass
class BinaryOp(Node):
    op: str
    left: Node
    right: Node
    condition: Node = None

    def label(self):
        return self.op.capitalize()

    def children(self):
        if self.condition is not None:
            return [self.condition, self.left, self.right]
        return [self.left, self.right]


def format_tree(node):
    lines = []

    def visit(current, prefix="", is_last=True, root=True):
        if root:
            lines.append(current.label())
        else:
            connector = "└── " if is_last else "├── "
            lines.append(prefix + connector + current.label())

        children = current.children()
        for index, child in enumerate(children):
            child_is_last = index == len(children) - 1
            if root:
                new_prefix = ""
            else:
                new_prefix = prefix + ("    " if is_last else "│   ")
            visit(child, new_prefix, child_is_last, False)

    visit(node)
    return "\n".join(lines)


def node_to_dict(node):
    if isinstance(node, Relation):
        return {"type": "relation", "name": node.name}
    if isinstance(node, Attr):
        return {"type": "attr", "name": node.name, "relation": node.relation}
    if isinstance(node, Literal):
        return {"type": "literal", "value": node.value, "kind": node.kind}
    if isinstance(node, Comparison):
        return {"type": "comparison", "op": node.op, "left": node_to_dict(node.left), "right": node_to_dict(node.right)}
    if isinstance(node, Logical):
        return {"type": "logical", "op": node.op, "left": node_to_dict(node.left), "right": node_to_dict(node.right)}
    if isinstance(node, Not):
        return {"type": "not", "condition": node_to_dict(node.condition)}
    if isinstance(node, Select):
        return {"type": "select", "condition": node_to_dict(node.condition), "source": node_to_dict(node.source)}
    if isinstance(node, Project):
        return {"type": "project", "attributes": [node_to_dict(a) for a in node.attributes], "source": node_to_dict(node.source)}
    if isinstance(node, Rename):
        return {"type": "rename", "new_name": node.new_name, "source": node_to_dict(node.source)}
    if isinstance(node, BinaryOp):
        result = {"type": "binary", "op": node.op, "left": node_to_dict(node.left), "right": node_to_dict(node.right)}
        if node.condition is not None:
            result["condition"] = node_to_dict(node.condition)
        return result
    raise TypeError(f"Unsupported tree node: {type(node).__name__}")


def node_from_dict(data):
    node_type = data.get("type")
    if node_type == "relation":
        return Relation(data["name"])
    if node_type == "attr":
        return Attr(data["name"], data.get("relation"))
    if node_type == "literal":
        return Literal(data["value"], data["kind"])
    if node_type == "comparison":
        return Comparison(data["op"], node_from_dict(data["left"]), node_from_dict(data["right"]))
    if node_type == "logical":
        return Logical(data["op"], node_from_dict(data["left"]), node_from_dict(data["right"]))
    if node_type == "not":
        return Not(node_from_dict(data["condition"]))
    if node_type == "select":
        return Select(node_from_dict(data["condition"]), node_from_dict(data["source"]))
    if node_type == "project":
        return Project([node_from_dict(a) for a in data["attributes"]], node_from_dict(data["source"]))
    if node_type == "rename":
        return Rename(data["new_name"], node_from_dict(data["source"]))
    if node_type == "binary":
        condition = data.get("condition")
        return BinaryOp(data["op"], node_from_dict(data["left"]), node_from_dict(data["right"]), node_from_dict(condition) if condition is not None else None)
    raise ValueError(f"Unknown tree node type: {node_type!r}")


def tree_to_json(node, *, indent=2):
    return json.dumps(node_to_dict(node), indent=indent, sort_keys=True)


def tree_from_json(text):
    return node_from_dict(json.loads(text))
