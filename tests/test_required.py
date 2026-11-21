import unittest
from tokenizer import Tokenizer, LexicalError
from parser import parse_query, ParseError
from ra_tree import BinaryOp, Select, Project, Logical, Not

from operators import (
    make_relation,
    Evaluator,
    SchemaError,
    RATypeError,
)

class RequiredTests(unittest.TestCase):

    def setUp(self):

        self.Employees = make_relation(
            "Employees",
            ["EID", "Name", "Age", "DID"],
            [
                ("E1", "John", 32, "D1"),
                ("E2", "Alice", 28, "D2"),
                ("E3", "Bob", 29, "D1"),
            ]
        )

        self.R = make_relation(
            "R",
            ["A", "B"],
            [
                (1, 1),
                (1, 2),
                (3, 3),
            ]
        )

        self.Emp = make_relation(
            "Emp",
            ["EID", "Name", "MgrID", "DID"],
            [
                ("E1", "John", "E2", "D1"),
                ("E2", "Alice", "E2", "D2"),
                ("E3", "Bob", "E1", "D1"),
            ]
        )

        self.Dept = make_relation(
            "Dept",
            ["DID", "DeptName"],
            [
                ("D1", "Sales"),
                ("D2", "Finance"),
            ]
        )

        self.A = make_relation(
            "A",
            ["x"],
            [(1,), (2,)]
        )

        self.B = make_relation(
            "B",
            ["x"],
            [(2,), (3,)]
        )

        self.C = make_relation(
            "C",
            ["x"],
            [(1,)]
        )

        self.D = make_relation(
            "D",
            ["x"],
            [(1,), (3,)]
        )

        self.S_bad = make_relation(
            "S_bad",
            ["X", "Y"],
            [
                (1, 2),
                (3, 4),
            ]
        )

        self.KeywordRelation = make_relation(
            "KeywordRelation",
            ["union"],
            [
                (3,),
                (4,),
            ]
        )

        self.relations = {
            "Employees": self.Employees,
            "R": self.R,
            "Emp": self.Emp,
            "Dept": self.Dept,
            "A": self.A,
            "B": self.B,
            "C": self.C,
            "D": self.D,
            "S_bad": self.S_bad,
            "KeywordRelation": self.KeywordRelation,
        }

        self.evaluator = Evaluator(self.relations)

    def evaluate(self, query):
        tree = parse_query(query)
        return self.evaluator.evaluate(tree)

    # 7.1 TOKENIZER
    def test_01_no_whitespace(self):
        tokens = Tokenizer(
            "select[x1=3](R)"
        ).tokenize()

        values = [
            token.value
            for token in tokens
            if token.type != "EOF"
        ]

        self.assertEqual(
            values,
            ["select", "[", "x1", "=", 3, "]", "(", "R", ")"]
        )

    def test_02_whitespace_same_parse_tree(self):
        tree1 = parse_query(
            "select[x1=3](R)"
        )

        tree2 = parse_query(
            "select[ x1 = 3 ](R)"
        )

        self.assertEqual(tree1, tree2)

    def test_03_greater_equal_one_token(self):
        tokens = Tokenizer(
            "select[Age>=30](R)"
        ).tokenize()

        operators = [
            token.value
            for token in tokens
            if token.type == "OP"
        ]

        self.assertEqual(
            operators,
            [">="]
        )

    def test_04_negative_number(self):
        tokens = Tokenizer(
            "select[Age>-30](R)"
        ).tokenize()

        values = [
            token.value
            for token in tokens
        ]

        self.assertIn(">", values)
        self.assertIn(-30, values)

    def test_05_parenthesis_inside_string(self):
        tokens = Tokenizer(
            "select[Name='Bob)'](R)"
        ).tokenize()

        strings = [
            token.value
            for token in tokens
            if token.type == "STRING"
        ]

        self.assertEqual(
            strings,
            ["Bob)"]
        )

    def test_06_comma_inside_string(self):
        tokens = Tokenizer(
            "select[Name='a,b'](R)"
        ).tokenize()

        strings = [
            token.value
            for token in tokens
            if token.type == "STRING"
        ]

        self.assertEqual(
            strings,
            ["a,b"]
        )

    def test_07_doubled_quote(self):
        tokens = Tokenizer(
            "select[Name='O''Brien'](R)"
        ).tokenize()

        strings = [
            token.value
            for token in tokens
            if token.type == "STRING"
        ]

        self.assertEqual(
            strings,
            ["O'Brien"]
        )

    def test_08_keyword_as_attribute(self):
        result = self.evaluate(
            "select[union=3](KeywordRelation)"
        )

        self.assertEqual(
            result.rows,
            [(3,)]
        )

    def test_09_unterminated_string(self):
        with self.assertRaises(LexicalError):
            Tokenizer(
                "select[Name='Bob](R)"
            ).tokenize()

    # 7.2 GRAMMAR AND PRECEDENCE
    def test_10_union_minus_grouping(self):
        tree = parse_query(
            "A union B minus C"
        )

        self.assertIsInstance(
            tree,
            BinaryOp
        )

        self.assertEqual(
            tree.op,
            "minus"
        )

        self.assertEqual(
            tree.left.op,
            "union"
        )

    def test_11_minus_left_associative(self):
        tree = parse_query(
            "A minus B minus C"
        )

        self.assertEqual(
            tree.op,
            "minus"
        )

        self.assertEqual(
            tree.left.op,
            "minus"
        )

    def test_12_not_and_or_precedence(self):
        tree = parse_query(
            "select[not (a=1 and b=2) or c>3](R)"
        )

        self.assertIsInstance(
            tree,
            Select
        )

        self.assertIsInstance(
            tree.condition,
            Logical
        )

        self.assertEqual(
            tree.condition.op,
            "or"
        )

        self.assertIsInstance(
            tree.condition.left,
            Not
        )

        self.assertEqual(
            tree.condition.left.condition.op,
            "and"
        )

    def test_13_and_before_or(self):
        tree = parse_query(
            "select[a=1 and b=2 or c=3](R)"
        )

        self.assertEqual(
            tree.condition.op,
            "or"
        )

        self.assertEqual(
            tree.condition.left.op,
            "and"
        )

    def test_14_nested_expressions(self):
        tree = parse_query(
            "project[Name]"
            "(select[Age>30]"
            "(select[DID='D1'](Employees)))"
        )

        self.assertIsInstance(
            tree,
            Project
        )

        self.assertIsInstance(
            tree.source,
            Select
        )

        self.assertIsInstance(
            tree.source.source,
            Select
        )

    def test_15_parentheses_override_precedence(self):
        tree = parse_query(
            "(A union B) minus (C intersect D)"
        )

        self.assertEqual(
            tree.op,
            "minus"
        )

        self.assertEqual(
            tree.left.op,
            "union"
        )

        self.assertEqual(
            tree.right.op,
            "intersect"
        )

    def test_16_missing_parenthesis(self):
        with self.assertRaises(ParseError):
            parse_query(
                "select[Age>30](R"
            )

    def test_17_empty_projection(self):
        with self.assertRaises(ParseError):
            parse_query(
                "project[](R)"
            )

    # 7.3 SEMANTICS
    def test_18_attribute_vs_attribute(self):
        result = self.evaluate(
            "select[A=B](R)"
        )

        self.assertEqual(
            result.rows,
            [
                (1, 1),
                (3, 3),
            ]
        )

    def test_19_qualified_join_names(self):
        result = self.evaluate(
            "Emp join[Emp.DID=Dept.DID] Dept"
        )

        names = [
            column.display_name()
            for column in result.columns
        ]

        self.assertIn(
            "Emp.DID",
            names
        )

        self.assertIn(
            "Dept.DID",
            names
        )

        self.assertEqual(
            len(result.rows),
            3
        )

    def test_20_self_join_with_rename(self):
        result = self.evaluate(
            "rename[E2](Emp) "
            "join[Emp.MgrID=E2.EID] Emp"
        )

        names = [
            column.display_name()
            for column in result.columns
        ]

        self.assertIn(
            "E2.EID",
            names
        )

        self.assertIn(
            "Emp.EID",
            names
        )

        self.assertEqual(
            len(result.rows),
            3
        )

    def test_21_incompatible_union(self):
        with self.assertRaises(SchemaError):
            self.evaluate(
                "R union S_bad"
            )

    def test_22_number_string_comparison(self):
        with self.assertRaises(RATypeError):
            self.evaluate(
                "select[Age>'30'](Employees)"
            )

    def test_23_projection_keeps_duplicates_for_project2(self):
        result = self.evaluate(
            "project[DID](Employees)"
        )

        self.assertEqual(
            result.rows,
            [
                ("D1",),
                ("D2",),
                ("D1",),
            ]
        )

    def test_24_duplicate_projection_attribute(self):
        with self.assertRaises(SchemaError):
            self.evaluate(
                "project[Name, Name](Employees)"
            )

    def test_25_empty_result_keeps_schema(self):
        result = self.evaluate(
            "select[Age>100](Employees)"
        )

        self.assertEqual(
            result.rows,
            []
        )

        self.assertEqual(
            len(result.columns),
            4
        )

if __name__ == "__main__":
    unittest.main()