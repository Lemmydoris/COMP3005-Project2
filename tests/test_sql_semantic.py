import tempfile
import unittest

from storage.catalog import Catalog

from sql_frontend.parser import (
    parse_sql,
)
from sql_frontend.semantic import (
    AnalyzedSelect,
    AnalyzedSet,
    ResolvedColumn,
    SQLSemanticAnalyzer,
    SQLSemanticError,
)


class SQLSemanticTests(unittest.TestCase):

    def setUp(self):

        self.temp = (
            tempfile.TemporaryDirectory()
        )

        self.catalog = Catalog(
            self.temp.name
        )

        self.catalog.create_table(
            "Emp",
            [
                ["eid", "INT"],
                ["name", "VARCHAR", 20],
                ["age", "INT"],
                ["did", "INT"],
                ["mgr", "INT"],
                ["salary", "INT"],
                ["city", "VARCHAR", 20],
            ],
        )

        self.catalog.create_table(
            "Dept",
            [
                ["did", "INT"],
                ["title", "VARCHAR", 20],
                ["budget", "INT"],
                ["city", "VARCHAR", 20],
            ],
        )

        self.catalog.create_table(
            "Office",
            [
                ["oid", "INT"],
                ["city", "VARCHAR", 20],
            ],
        )

        self.catalog.create_table(
            "Codes",
            [
                ["code", "VARCHAR", 10],
            ],
        )

        self.analyzer = (
            SQLSemanticAnalyzer(
                self.catalog
            )
        )

    def tearDown(self):

        self.catalog.flush()

        self.temp.cleanup()

    def analyze_one(
        self,
        sql,
    ):

        program = parse_sql(
            sql
        )

        analyzed = (
            self.analyzer
            .analyze_program(
                program
            )
        )

        self.assertEqual(
            len(
                analyzed.statements
            ),
            1,
        )

        return (
            analyzed.statements[
                0
            ]
        )

    def test_unqualified_column_becomes_fully_qualified(
        self,
    ):

        query = self.analyze_one(
            "SELECT name, age "
            "FROM Emp "
            "WHERE age > 30"
        )

        self.assertIsInstance(
            query,
            AnalyzedSelect,
        )

        self.assertEqual(
            [
                item.source_name
                for item
                in query.projection
            ],
            [
                "Emp.name",
                "Emp.age",
            ],
        )

        self.assertIsInstance(
            query.where.left,
            ResolvedColumn,
        )

        self.assertEqual(
            query.where.left.plan_name,
            "Emp.age",
        )

    def test_select_star_expands_in_from_and_schema_order(
        self,
    ):

        query = self.analyze_one(
            "SELECT * "
            "FROM Emp e, "
            "Dept d, "
            "Office o"
        )

        names = [
            item.source_name
            for item
            in query.projection
        ]

        self.assertEqual(
            names[:7],
            [
                "e.eid",
                "e.name",
                "e.age",
                "e.did",
                "e.mgr",
                "e.salary",
                "e.city",
            ],
        )

        self.assertEqual(
            names[7:11],
            [
                "d.did",
                "d.title",
                "d.budget",
                "d.city",
            ],
        )

        self.assertEqual(
            names[11:],
            [
                "o.oid",
                "o.city",
            ],
        )

    def test_ambiguous_unqualified_column_is_rejected(
        self,
    ):

        with self.assertRaisesRegex(
            SQLSemanticError,
            "Ambiguous column did",
        ) as context:

            self.analyze_one(
                "SELECT did "
                "FROM Emp, Dept"
            )

        self.assertEqual(
            context.exception.category,
            "ambiguity",
        )

        message = str(
            context.exception
        )

        self.assertIn(
            "Emp.did",
            message,
        )

        self.assertIn(
            "Dept.did",
            message,
        )

    def test_self_join_aliases_resolve_independently(
        self,
    ):

        query = self.analyze_one(
            "SELECT e.name, m.name "
            "FROM Emp e "
            "JOIN Emp m "
            "ON e.mgr = m.eid"
        )

        self.assertEqual(
            query.projection[
                0
            ].source_name,
            "e.name",
        )

        self.assertEqual(
            query.projection[
                1
            ].source_name,
            "m.name",
        )

        self.assertEqual(
            (
                query.from_source
                .condition
                .left
                .plan_name
            ),
            "e.mgr",
        )

        self.assertEqual(
            (
                query.from_source
                .condition
                .right
                .plan_name
            ),
            "m.eid",
        )

    def test_unknown_table_and_unknown_column_have_different_messages(
        self,
    ):

        with self.assertRaisesRegex(
            SQLSemanticError,
            "Unknown table",
        ):

            self.analyze_one(
                "SELECT x "
                "FROM Missing"
            )

        with self.assertRaisesRegex(
            SQLSemanticError,
            "Unknown column",
        ):

            self.analyze_one(
                "SELECT missing "
                "FROM Emp"
            )

    def test_duplicate_scope_name_is_rejected(
        self,
    ):

        with self.assertRaisesRegex(
            SQLSemanticError,
            "Duplicate table alias",
        ):

            self.analyze_one(
                "SELECT * "
                "FROM Emp, Emp"
            )

    def test_int_to_string_comparison_is_type_error(
        self,
    ):

        with self.assertRaisesRegex(
            SQLSemanticError,
            "Cannot compare INT to VARCHAR",
        ) as context:

            self.analyze_one(
                "SELECT name "
                "FROM Emp "
                "WHERE age > '30'"
            )

        self.assertEqual(
            context.exception.category,
            "type",
        )

    def test_aggregate_in_where_is_rejected(
        self,
    ):

        with self.assertRaisesRegex(
            SQLSemanticError,
            "not allowed before grouping",
        ) as context:

            self.analyze_one(
                "SELECT did "
                "FROM Emp "
                "WHERE COUNT(*) > 1 "
                "GROUP BY did"
            )

        self.assertEqual(
            context.exception.category,
            "aggregate",
        )

    def test_non_grouped_select_column_is_rejected(
        self,
    ):

        with self.assertRaisesRegex(
            SQLSemanticError,
            "must appear in GROUP BY",
        ):

            self.analyze_one(
                "SELECT did, name, "
                "COUNT(*) "
                "FROM Emp "
                "GROUP BY did"
            )

    def test_grouping_having_and_order_alias(
        self,
    ):

        query = self.analyze_one(
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

        self.assertTrue(
            query.aggregating
        )

        self.assertEqual(
            [
                column.plan_name
                for column
                in query.group_by
            ],
            [
                "Emp.did",
            ],
        )

        self.assertEqual(
            [
                (
                    aggregate.function,
                    aggregate.argument,
                    aggregate.output_name,
                )
                for aggregate
                in query.aggregates
            ],
            [
                (
                    "count",
                    "*",
                    "n",
                ),
                (
                    "avg",
                    "Emp.salary",
                    "avg_sal",
                ),
            ],
        )

        # HAVING COUNT(*) > 5 resolves
        # to the grouped output n > 5.
        self.assertEqual(
            query.having.left.plan_name,
            "n",
        )

        self.assertEqual(
            query.order_by[
                0
            ].name,
            "n",
        )

        self.assertEqual(
            query.order_by[
                0
            ].direction,
            "desc",
        )

    def test_count_star_without_group_by_is_valid(
        self,
    ):

        query = self.analyze_one(
            "SELECT COUNT(*) "
            "FROM Emp"
        )

        self.assertTrue(
            query.aggregating
        )

        self.assertEqual(
            len(query.group_by),
            0,
        )

        self.assertEqual(
            query.aggregates[
                0
            ].output_name,
            "count_star",
        )

        self.assertEqual(
            query.output_schema[
                0
            ].type_name,
            "INT",
        )

    def test_sum_and_avg_require_int(
        self,
    ):

        with self.assertRaisesRegex(
            SQLSemanticError,
            "SUM requires an INT",
        ):

            self.analyze_one(
                "SELECT SUM(name) "
                "FROM Emp"
            )

        with self.assertRaisesRegex(
            SQLSemanticError,
            "AVG requires an INT",
        ):

            self.analyze_one(
                "SELECT AVG(city) "
                "FROM Emp"
            )

    def test_order_by_column_not_in_select_list_is_allowed(
        self,
    ):

        query = self.analyze_one(
            "SELECT name "
            "FROM Emp "
            "ORDER BY age DESC"
        )

        self.assertEqual(
            [
                item.source_name
                for item
                in query.projection
            ],
            [
                "Emp.name",
            ],
        )

        self.assertEqual(
            query.order_by[
                0
            ].name,
            "Emp.age",
        )

    def test_subquery_output_becomes_outer_scope(
        self,
    ):

        query = self.analyze_one(
            "SELECT t.did, t.n "
            "FROM "
            "("
            "SELECT did, "
            "COUNT(*) AS n "
            "FROM Emp "
            "GROUP BY did"
            ") AS t "
            "WHERE t.n > 3"
        )

        self.assertEqual(
            query.projection[
                0
            ].source_name,
            "t.did",
        )

        self.assertEqual(
            query.projection[
                1
            ].source_name,
            "t.n",
        )

        self.assertEqual(
            query.where.left.plan_name,
            "t.n",
        )

    def test_union_type_mismatch_is_schema_error(
        self,
    ):

        with self.assertRaisesRegex(
            SQLSemanticError,
            "Set-operation type mismatch",
        ) as context:

            self.analyze_one(
                "SELECT eid FROM Emp "
                "UNION "
                "SELECT code FROM Codes"
            )

        self.assertEqual(
            context.exception.category,
            "schema",
        )

    def test_union_all_keeps_left_output_schema(
        self,
    ):

        query = self.analyze_one(
            "SELECT city FROM Emp "
            "UNION ALL "
            "SELECT city FROM Dept"
        )

        self.assertIsInstance(
            query,
            AnalyzedSet,
        )

        self.assertEqual(
            query.operator,
            "union_all",
        )

        self.assertEqual(
            query.output_schema[
                0
            ].name,
            "city",
        )

        self.assertEqual(
            query.output_schema[
                0
            ].type_name,
            "VARCHAR",
        )


if __name__ == "__main__":
    unittest.main()