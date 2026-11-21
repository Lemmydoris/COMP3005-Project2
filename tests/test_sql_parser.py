import unittest

from sql_frontend.ast import (
    AggregateCall,
    Comparison,
    CreateTable,
    FromCross,
    FromJoin,
    InsertStatement,
    LogicalCondition,
    NotCondition,
    SelectQuery,
    SetQuery,
    TableRef,
)
from sql_frontend.parser import (
    SQLSyntaxError,
    parse_sql,
)


class SQLParserTests(unittest.TestCase):

    def one(self, sql):

        program = parse_sql(sql)

        self.assertEqual(
            len(program.statements),
            1,
        )

        return program.statements[0]

    def test_simple_select(self):

        query = self.one(
            "SELECT name FROM Emp"
        )

        self.assertIsInstance(
            query,
            SelectQuery,
        )

        self.assertFalse(
            query.distinct
        )

        self.assertFalse(
            query.select_all
        )

        self.assertEqual(
            query.items[
                0
            ].expression.name,
            "name",
        )

        self.assertEqual(
            query.from_source.name,
            "Emp",
        )

    def test_select_star(self):

        query = self.one(
            "SELECT * FROM Emp"
        )

        self.assertTrue(
            query.select_all
        )

        self.assertEqual(
            query.items,
            [],
        )

    def test_table_alias_with_and_without_as(self):

        query1 = self.one(
            "SELECT e.name "
            "FROM Emp e"
        )

        query2 = self.one(
            "SELECT e.name "
            "FROM Emp AS e"
        )

        self.assertEqual(
            query1.from_source.alias,
            "e",
        )

        self.assertEqual(
            query2.from_source.alias,
            "e",
        )

    def test_explicit_join(self):

        query = self.one(
            "SELECT e.name, d.title "
            "FROM Emp e "
            "JOIN Dept d "
            "ON e.did = d.did"
        )

        self.assertIsInstance(
            query.from_source,
            FromJoin,
        )

        self.assertEqual(
            query.from_source.left.alias,
            "e",
        )

        self.assertEqual(
            query.from_source.right.alias,
            "d",
        )

        self.assertIsInstance(
            query.from_source.condition,
            Comparison,
        )

    def test_comma_from_builds_cross(self):

        query = self.one(
            "SELECT * "
            "FROM Emp e, Dept d "
            "WHERE e.did = d.did"
        )

        self.assertIsInstance(
            query.from_source,
            FromCross,
        )

        self.assertIsInstance(
            query.where,
            Comparison,
        )

    def test_group_by_having_order_limit(self):

        query = self.one(
            "SELECT did, "
            "COUNT(*) AS n, "
            "AVG(salary) AS avg_sal "
            "FROM Emp "
            "WHERE age > 25 "
            "GROUP BY did "
            "HAVING COUNT(*) > 5 "
            "ORDER BY n DESC "
            "LIMIT 10"
        )

        self.assertEqual(
            len(query.group_by),
            1,
        )

        self.assertIsInstance(
            query.items[1].expression,
            AggregateCall,
        )

        self.assertEqual(
            query.items[1].alias,
            "n",
        )

        self.assertIsInstance(
            query.having,
            Comparison,
        )

        self.assertEqual(
            query.order_by[
                0
            ].column_ref.name,
            "n",
        )

        self.assertEqual(
            query.order_by[
                0
            ].direction,
            "desc",
        )

        self.assertEqual(
            query.limit,
            10,
        )

    def test_not_and_or_precedence(self):

        query = self.one(
            "SELECT * FROM R "
            "WHERE NOT a = 1 "
            "AND b = 2 "
            "OR c = 3"
        )

        # OR is loosest, so it is
        # the root.
        self.assertIsInstance(
            query.where,
            LogicalCondition,
        )

        self.assertEqual(
            query.where.operator,
            "or",
        )

        self.assertEqual(
            query.where.left.operator,
            "and",
        )

        self.assertIsInstance(
            query.where.left.left,
            NotCondition,
        )

    def test_parentheses_override_condition_precedence(
        self,
    ):

        query = self.one(
            "SELECT * FROM R "
            "WHERE a = 1 "
            "AND (b = 2 OR c = 3)"
        )

        self.assertEqual(
            query.where.operator,
            "and",
        )

        self.assertEqual(
            query.where.right.operator,
            "or",
        )

    def test_set_operators_are_left_associative(
        self,
    ):

        query = self.one(
            "SELECT a FROM R "
            "UNION "
            "SELECT a FROM S "
            "EXCEPT "
            "SELECT a FROM T"
        )

        self.assertIsInstance(
            query,
            SetQuery,
        )

        self.assertEqual(
            query.operator,
            "except",
        )

        self.assertIsInstance(
            query.left,
            SetQuery,
        )

        self.assertEqual(
            query.left.operator,
            "union",
        )

    def test_union_all_is_distinct_ast_operator(
        self,
    ):

        query = self.one(
            "SELECT a FROM R "
            "UNION ALL "
            "SELECT a FROM S"
        )

        self.assertEqual(
            query.operator,
            "union_all",
        )

    def test_subquery_in_from_requires_alias(
        self,
    ):

        query = self.one(
            "SELECT t.did "
            "FROM "
            "(SELECT did FROM Emp) "
            "AS t"
        )

        source = query.from_source

        self.assertIsInstance(
            source,
            TableRef,
        )

        self.assertEqual(
            source.alias,
            "t",
        )

        self.assertIsNotNone(
            source.subquery,
        )

        with self.assertRaisesRegex(
            SQLSyntaxError,
            "requires AS",
        ):
            self.one(
                "SELECT did "
                "FROM "
                "(SELECT did FROM Emp)"
            )

    def test_create_table(self):

        statement = self.one(
            "CREATE TABLE Emp "
            "("
            "eid INT, "
            "name VARCHAR(20)"
            ")"
        )

        self.assertIsInstance(
            statement,
            CreateTable,
        )

        self.assertEqual(
            statement.name,
            "Emp",
        )

        self.assertEqual(
            statement.columns[
                0
            ].type_name,
            "INT",
        )

        self.assertEqual(
            statement.columns[
                1
            ].length,
            20,
        )

    def test_insert(self):

        statement = self.one(
            "INSERT INTO Emp "
            "VALUES "
            "(1, 'O''Brien')"
        )

        self.assertIsInstance(
            statement,
            InsertStatement,
        )

        self.assertEqual(
            statement.table,
            "Emp",
        )

        self.assertEqual(
            statement.values[
                0
            ].value,
            1,
        )

        self.assertEqual(
            statement.values[
                1
            ].value,
            "O'Brien",
        )

    def test_multiple_statements(self):

        program = parse_sql(
            "CREATE TABLE R "
            "(a INT);"
            "INSERT INTO R "
            "VALUES (1);"
            "SELECT a FROM R;"
        )

        self.assertEqual(
            len(program.statements),
            3,
        )

        self.assertIsInstance(
            program.statements[0],
            CreateTable,
        )

        self.assertIsInstance(
            program.statements[1],
            InsertStatement,
        )

        self.assertIsInstance(
            program.statements[2],
            SelectQuery,
        )


if __name__ == "__main__":
    unittest.main()