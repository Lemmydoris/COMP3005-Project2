import importlib
import unittest

from tokenizer import Tokenizer
from parser import parse_query, parse_condition_text
from ra_tree import tree_to_json, tree_from_json, Attr, Logical
from operators import make_relation, Evaluator


class RefactorTests(unittest.TestCase):
    def test_layers_import_independently(self):
        for name in ("tokenizer", "parser", "ra_tree", "operators"):
            self.assertIsNotNone(importlib.import_module(name))

    def test_sql_style_comment_is_ignored(self):
        values = [t.value for t in Tokenizer("a=1 -- comment\nand b=2").tokenize() if t.type != "EOF"]
        self.assertEqual(values, ["a", "=", 1, "and", "b", "=", 2])

    def test_condition_parser_is_standalone(self):
        condition = parse_condition_text("R.b = S.b and not R.a < 5")
        self.assertIsInstance(condition, Logical)
        self.assertEqual(condition.op, "and")

    def test_qualified_attribute_parses(self):
        condition = parse_condition_text("R.b = S.b")
        self.assertIsInstance(condition.left, Attr)
        self.assertEqual((condition.left.relation, condition.left.name), ("R", "b"))

    def test_tree_json_round_trip(self):
        tree = parse_query("project[Emp.Name](select[Emp.DID='D1'](rename[Emp](Employees)))")
        restored = tree_from_json(tree_to_json(tree))
        self.assertEqual(restored, tree)

    def test_evaluator_uses_data_source_contract(self):
        relation = make_relation("R", ["a"], [(1,), (2,)])
        class Source:
            def get_relation(self, name):
                if name == "R":
                    return relation
                raise KeyError(name)
        result = Evaluator(Source()).evaluate(parse_query("R"))
        self.assertEqual(result.rows, [(1,), (2,)])

    def test_projection_uses_bag_semantics(self):
        relation = make_relation("R", ["a", "b"], [(1, 10), (1, 20), (2, 30)])
        result = Evaluator({"R": relation}).evaluate(parse_query("project[a](R)"))
        self.assertEqual(result.rows, [(1,), (1,), (2,)])


if __name__ == "__main__":
    unittest.main()
