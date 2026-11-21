import tempfile
import unittest

from storage.catalog import Catalog

from sql_frontend.parser import parse_sql
from sql_frontend.semantic import (
    SQLSemanticAnalyzer,
    SQLSemanticError,
)
from sql_frontend.translator import (
    LogicalPlanTranslator,
)


class Module3RequiredCasesTests(
    unittest.TestCase
):

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
                ["oid", "INT"],
            ],
        )

        self.catalog.create_table(
            "Office",
            [
                ["oid", "INT"],
                ["city", "VARCHAR", 20],
                ["rid", "INT"],
            ],
        )

        self.catalog.create_table(
            "Region",
            [
                ["rid", "INT"],
                ["region_name", "VARCHAR", 20],
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

        self.translator = (
            LogicalPlanTranslator()
        )

    def tearDown(self):

        self.catalog.flush()

        self.temp.cleanup()

    def analyze_one(
        self,
        sql,
    ):

        parsed = parse_sql(
            sql
        )

        analyzed = (
            self.analyzer
            .analyze_program(
                parsed
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

    def compile_one(
        self,
        sql,
    ):

        analyzed = (
            self.analyze_one(
                sql
            )
        )

        return (
            self.translator
            .translate_query(
                analyzed
            )
        )

    def collect_ops(
        self,
        node,
    ):

        result = [
            node["op"]
        ]

        if "child" in node:

            result.extend(
                self.collect_ops(
                    node["child"]
                )
            )

        if "left" in node:

            result.extend(
                self.collect_ops(
                    node["left"]
                )
            )

        if "right" in node:

            result.extend(
                self.collect_ops(
                    node["right"]
                )
            )

        return result

    # --------------------------------------------------------
    # 1
    # Self join from Section 5.5:
    # two renames over one base table.
    # --------------------------------------------------------

    def test_01_self_join_has_two_renames(
        self,
    ):

        plan = self.compile_one(
            "SELECT e.name, m.name "
            "FROM Emp e "
            "JOIN Emp m "
            "ON e.mgr = m.eid"
        )

        join = plan[
            "child"
        ]

        self.assertEqual(
            join["op"],
            "join",
        )

        self.assertEqual(
            join["condition"],
            "e.mgr = m.eid",
        )

        self.assertEqual(
            join["left"]["op"],
            "rename",
        )

        self.assertEqual(
            join["left"]["to"],
            "e",
        )

        self.assertEqual(
            join["right"]["op"],
            "rename",
        )

        self.assertEqual(
            join["right"]["to"],
            "m",
        )

        self.assertEqual(
            join["left"]["child"],
            {
                "op": "scan",
                "table": "Emp",
            },
        )

        self.assertEqual(
            join["right"]["child"],
            {
                "op": "scan",
                "table": "Emp",
            },
        )

    # --------------------------------------------------------
    # 2
    # SELECT * over three tables where names overlap.
    # Expansion must qualify every output column.
    # --------------------------------------------------------

    def test_02_select_star_three_tables_qualifies_shared_names(
        self,
    ):

        plan = self.compile_one(
            "SELECT * "
            "FROM Emp e, "
            "Dept d, "
            "Office o"
        )

        self.assertEqual(
            plan["op"],
            "project",
        )

        columns = plan[
            "columns"
        ]

        self.assertIn(
            "e.city",
            columns,
        )

        self.assertIn(
            "d.city",
            columns,
        )

        self.assertIn(
            "o.city",
            columns,
        )

        self.assertIn(
            "e.did",
            columns,
        )

        self.assertIn(
            "d.did",
            columns,
        )

        for column in columns:

            self.assertIn(
                ".",
                column,
            )

    # --------------------------------------------------------
    # 3
    # Unqualified shared column is ambiguous.
    # --------------------------------------------------------

    def test_03_ambiguous_column_names_both_candidates(
        self,
    ):

        with self.assertRaises(
            SQLSemanticError
        ) as context:

            self.analyze_one(
                "SELECT did "
                "FROM Emp, Dept"
            )

        error = context.exception

        self.assertEqual(
            error.category,
            "ambiguity",
        )

        message = str(
            error
        )

        self.assertIn(
            "Emp.did",
            message,
        )

        self.assertIn(
            "Dept.did",
            message,
        )

    # --------------------------------------------------------
    # 4
    # UNION and UNION ALL must produce different plans.
    # --------------------------------------------------------

    def test_04_union_and_union_all_differ(
        self,
    ):

        union_plan = (
            self.compile_one(
                "SELECT city "
                "FROM Emp "
                "UNION "
                "SELECT city "
                "FROM Dept"
            )
        )

        union_all_plan = (
            self.compile_one(
                "SELECT city "
                "FROM Emp "
                "UNION ALL "
                "SELECT city "
                "FROM Dept"
            )
        )

        self.assertEqual(
            union_plan["op"],
            "union",
        )

        self.assertEqual(
            union_all_plan["op"],
            "union_all",
        )

        self.assertEqual(
            union_plan["left"],
            union_all_plan["left"],
        )

        self.assertEqual(
            union_plan["right"],
            union_all_plan["right"],
        )

    # --------------------------------------------------------
    # 5
    # WHERE below grouping, HAVING above grouping.
    # --------------------------------------------------------

    def test_05_where_and_having_are_on_opposite_sides_of_grouping(
        self,
    ):

        plan = self.compile_one(
            "SELECT did, "
            "COUNT(*) AS n "
            "FROM Emp "
            "WHERE age > 25 "
            "GROUP BY did "
            "HAVING COUNT(*) > 1"
        )

        project = plan

        self.assertEqual(
            project["op"],
            "project",
        )

        having = project[
            "child"
        ]

        self.assertEqual(
            having["op"],
            "select",
        )

        self.assertEqual(
            having["condition"],
            "n > 1",
        )

        grouping = having[
            "child"
        ]

        self.assertEqual(
            grouping["op"],
            "group_by",
        )

        where = grouping[
            "child"
        ]

        self.assertEqual(
            where["op"],
            "select",
        )

        self.assertEqual(
            where["condition"],
            "Emp.age > 25",
        )

        self.assertEqual(
            where["child"]["op"],
            "scan",
        )

    # --------------------------------------------------------
    # 6
    # Non-grouped column in an aggregating select.
    # --------------------------------------------------------

    def test_06_non_grouped_select_column_is_aggregate_error(
        self,
    ):

        with self.assertRaises(
            SQLSemanticError
        ) as context:

            self.analyze_one(
                "SELECT did, name, "
                "COUNT(*) "
                "FROM Emp "
                "GROUP BY did"
            )

        self.assertEqual(
            context.exception.category,
            "aggregate",
        )

    # --------------------------------------------------------
    # 7
    # Aggregate in WHERE.
    # --------------------------------------------------------

    def test_07_aggregate_in_where_is_aggregate_error(
        self,
    ):

        with self.assertRaises(
            SQLSemanticError
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

    # --------------------------------------------------------
    # 8
    # FROM subquery with alias joined to a base table.
    # --------------------------------------------------------

    def test_08_subquery_alias_joined_to_base_table(
        self,
    ):

        plan = self.compile_one(
            "SELECT t.did, d.title "
            "FROM "
            "("
            "SELECT did "
            "FROM Emp"
            ") AS t "
            "JOIN Dept d "
            "ON t.did = d.did"
        )

        self.assertEqual(
            plan["op"],
            "project",
        )

        join = plan[
            "child"
        ]

        self.assertEqual(
            join["op"],
            "join",
        )

        self.assertEqual(
            join["condition"],
            "t.did = d.did",
        )

        self.assertEqual(
            join["left"]["op"],
            "rename",
        )

        self.assertEqual(
            join["left"]["to"],
            "t",
        )

        self.assertEqual(
            join["right"]["op"],
            "rename",
        )

        self.assertEqual(
            join["right"]["to"],
            "d",
        )

    # --------------------------------------------------------
    # 9
    # ORDER BY may use a FROM-scope column that is not
    # in the select list.
    # --------------------------------------------------------

    def test_09_order_by_non_selected_column(
        self,
    ):

        plan = self.compile_one(
            "SELECT name "
            "FROM Emp "
            "ORDER BY age DESC"
        )

        self.assertEqual(
            plan["op"],
            "sort",
        )

        self.assertEqual(
            plan["keys"],
            [
                [
                    "Emp.age",
                    "desc",
                ]
            ],
        )

        self.assertEqual(
            plan["child"]["op"],
            "project",
        )

        self.assertEqual(
            plan["child"][
                "columns"
            ],
            [
                "Emp.name",
            ],
        )

    # --------------------------------------------------------
    # 10
    # INT compared with VARCHAR.
    # --------------------------------------------------------

    def test_10_int_string_comparison_is_type_error(
        self,
    ):

        with self.assertRaises(
            SQLSemanticError
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

        self.assertIn(
            "INT",
            str(
                context.exception
            ),
        )

        self.assertIn(
            "VARCHAR",
            str(
                context.exception
            ),
        )

    # --------------------------------------------------------
    # 11
    # Unknown table and unknown column use different messages.
    # --------------------------------------------------------

    def test_11_unknown_table_and_column_have_different_messages(
        self,
    ):

        with self.assertRaises(
            SQLSemanticError
        ) as table_context:

            self.analyze_one(
                "SELECT eid "
                "FROM Missing"
            )

        with self.assertRaises(
            SQLSemanticError
        ) as column_context:

            self.analyze_one(
                "SELECT missing "
                "FROM Emp"
            )

        table_error = str(
            table_context.exception
        )

        column_error = str(
            column_context.exception
        )

        self.assertIn(
            "Unknown table",
            table_error,
        )

        self.assertIn(
            "Unknown column",
            column_error,
        )

        self.assertNotEqual(
            table_error,
            column_error,
        )

    # --------------------------------------------------------
    # 12
    # FROM Emp, Emp without aliases.
    # --------------------------------------------------------

    def test_12_duplicate_table_scope_name_is_error(
        self,
    ):

        with self.assertRaises(
            SQLSemanticError
        ) as context:

            self.analyze_one(
                "SELECT * "
                "FROM Emp, Emp"
            )

        self.assertEqual(
            context.exception.category,
            "name",
        )

        self.assertIn(
            "Duplicate table alias",
            str(
                context.exception
            ),
        )

    # --------------------------------------------------------
    # 13
    # Global COUNT(*) without GROUP BY.
    #
    # Logical representation is group_by with no keys.
    # Module 2 already verifies empty global COUNT returns 0.
    # --------------------------------------------------------

    def test_13_global_count_without_group_by(
        self,
    ):

        plan = self.compile_one(
            "SELECT COUNT(*) "
            "FROM Emp"
        )

        self.assertEqual(
            plan["op"],
            "project",
        )

        self.assertEqual(
            plan["columns"],
            [
                "count_star",
            ],
        )

        grouping = plan[
            "child"
        ]

        self.assertEqual(
            grouping["op"],
            "group_by",
        )

        self.assertEqual(
            grouping["keys"],
            [],
        )

        self.assertEqual(
            grouping["aggregates"],
            [
                [
                    "count",
                    "*",
                    "count_star",
                ]
            ],
        )

    # --------------------------------------------------------
    # 14
    # Set-operation type mismatch.
    # --------------------------------------------------------

    def test_14_union_type_mismatch_is_schema_error(
        self,
    ):

        with self.assertRaises(
            SQLSemanticError
        ) as context:

            self.analyze_one(
                "SELECT eid "
                "FROM Emp "
                "UNION "
                "SELECT code "
                "FROM Codes"
            )

        self.assertEqual(
            context.exception.category,
            "schema",
        )

        self.assertIn(
            "type mismatch",
            str(
                context.exception
            ).lower(),
        )

    # --------------------------------------------------------
    # 15
    # Same four-table logical join written:
    #     a) commas + WHERE
    #     b) explicit JOIN ... ON
    #
    # Module 3 must preserve where predicates were written.
    # --------------------------------------------------------

    def test_15_four_table_comma_and_join_forms_keep_predicates_in_different_places(
        self,
    ):

        comma_plan = self.compile_one(
            "SELECT e.eid "
            "FROM "
            "Emp e, "
            "Dept d, "
            "Office o, "
            "Region r "
            "WHERE "
            "e.did = d.did "
            "AND d.oid = o.oid "
            "AND o.rid = r.rid"
        )

        join_plan = self.compile_one(
            "SELECT e.eid "
            "FROM Emp e "
            "JOIN Dept d "
            "ON e.did = d.did "
            "JOIN Office o "
            "ON d.oid = o.oid "
            "JOIN Region r "
            "ON o.rid = r.rid"
        )

        # Both finish with the same projection.
        self.assertEqual(
            comma_plan["op"],
            "project",
        )

        self.assertEqual(
            join_plan["op"],
            "project",
        )

        self.assertEqual(
            comma_plan["columns"],
            [
                "e.eid",
            ],
        )

        self.assertEqual(
            join_plan["columns"],
            [
                "e.eid",
            ],
        )

        comma_ops = (
            self.collect_ops(
                comma_plan
            )
        )

        join_ops = (
            self.collect_ops(
                join_plan
            )
        )

        # Comma version:
        # one WHERE select above three crosses.
        self.assertEqual(
            comma_ops.count(
                "cross"
            ),
            3,
        )

        self.assertEqual(
            comma_ops.count(
                "select"
            ),
            1,
        )

        self.assertEqual(
            comma_ops.count(
                "join"
            ),
            0,
        )

        comma_where = (
            comma_plan[
                "child"
            ]
        )

        self.assertEqual(
            comma_where["op"],
            "select",
        )

        self.assertEqual(
            comma_where[
                "condition"
            ],
            (
                "e.did = d.did "
                "AND d.oid = o.oid "
                "AND o.rid = r.rid"
            ),
        )

        # Explicit JOIN version:
        # predicates stay attached to
        # three join nodes.
        self.assertEqual(
            join_ops.count(
                "join"
            ),
            3,
        )

        self.assertEqual(
            join_ops.count(
                "select"
            ),
            0,
        )

        self.assertEqual(
            join_ops.count(
                "cross"
            ),
            0,
        )

        top_join = (
            join_plan[
                "child"
            ]
        )

        self.assertEqual(
            top_join["condition"],
            "o.rid = r.rid",
        )

        middle_join = (
            top_join[
                "left"
            ]
        )

        self.assertEqual(
            middle_join["condition"],
            "d.oid = o.oid",
        )

        first_join = (
            middle_join[
                "left"
            ]
        )

        self.assertEqual(
            first_join["condition"],
            "e.did = d.did",
        )


if __name__ == "__main__":
    unittest.main()