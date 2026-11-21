import tempfile
import unittest

from storage.catalog import Catalog

from sql_frontend.parser import (
    parse_sql,
)
from sql_frontend.semantic import (
    SQLSemanticAnalyzer,
)
from sql_frontend.translator import (
    LogicalPlanTranslator,
)


class SQLTranslatorTests(
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
            ],
        )

        self.catalog.create_table(
            "Office",
            [
                ["oid", "INT"],
                ["city", "VARCHAR", 20],
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

    def compile_one(
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
            self.translator
            .translate_query(
                analyzed.statements[
                    0
                ]
            )
        )

    def test_plain_filter_and_projection_matches_handout(
        self,
    ):

        plan = self.compile_one(
            "SELECT name, age "
            "FROM Emp "
            "WHERE age > 30"
        )

        self.assertEqual(
            plan,
            {
                "op": "project",
                "columns": [
                    "Emp.name",
                    "Emp.age",
                ],
                "child": {
                    "op": "select",
                    "condition":
                        "Emp.age > 30",
                    "child": {
                        "op": "scan",
                        "table": "Emp",
                    },
                },
            },
        )

    def test_join_alias_example_matches_handout(
        self,
    ):

        plan = self.compile_one(
            "SELECT e.name, d.title "
            "FROM Emp e "
            "JOIN Dept d "
            "ON e.did = d.did "
            "WHERE d.budget > 1000"
        )

        self.assertEqual(
            plan["op"],
            "project",
        )

        self.assertEqual(
            plan["columns"],
            [
                "e.name",
                "d.title",
            ],
        )

        select = plan[
            "child"
        ]

        self.assertEqual(
            select["op"],
            "select",
        )

        self.assertEqual(
            select["condition"],
            "d.budget > 1000",
        )

        join = select[
            "child"
        ]

        self.assertEqual(
            join["op"],
            "join",
        )

        self.assertEqual(
            join["condition"],
            "e.did = d.did",
        )

        self.assertEqual(
            join["left"],
            {
                "op": "rename",
                "to": "e",
                "child": {
                    "op": "scan",
                    "table": "Emp",
                },
            },
        )

        self.assertEqual(
            join["right"],
            {
                "op": "rename",
                "to": "d",
                "child": {
                    "op": "scan",
                    "table": "Dept",
                },
            },
        )

    def test_comma_join_keeps_predicate_above_cross(
        self,
    ):

        plan = self.compile_one(
            "SELECT e.name, d.title "
            "FROM Emp e, Dept d "
            "WHERE e.did = d.did"
        )

        select = plan[
            "child"
        ]

        self.assertEqual(
            select["op"],
            "select",
        )

        self.assertEqual(
            select["condition"],
            "e.did = d.did",
        )

        cross = select[
            "child"
        ]

        self.assertEqual(
            cross["op"],
            "cross",
        )

        self.assertNotIn(
            "condition",
            cross,
        )

    def test_grouping_example_has_canonical_order(
        self,
    ):

        plan = self.compile_one(
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
            plan["op"],
            "limit",
        )

        self.assertEqual(
            plan["n"],
            10,
        )

        sort = plan[
            "child"
        ]

        self.assertEqual(
            sort,
            {
                "op": "sort",
                "keys": [
                    [
                        "n",
                        "desc",
                    ]
                ],
                "child":
                    sort["child"],
            },
        )

        project = sort[
            "child"
        ]

        self.assertEqual(
            project["op"],
            "project",
        )

        self.assertEqual(
            project["columns"],
            [
                "Emp.did",
                "n",
                "avg_sal",
            ],
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
            "n > 5",
        )

        grouping = having[
            "child"
        ]

        self.assertEqual(
            grouping["op"],
            "group_by",
        )

        self.assertEqual(
            grouping["keys"],
            [
                "Emp.did",
            ],
        )

        self.assertEqual(
            grouping["aggregates"],
            [
                [
                    "count",
                    "*",
                    "n",
                ],
                [
                    "avg",
                    "Emp.salary",
                    "avg_sal",
                ],
            ],
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
            where["child"],
            {
                "op": "scan",
                "table": "Emp",
            },
        )

    def test_self_join_uses_two_renames(
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

    def test_subquery_in_from_is_translated_then_renamed(
        self,
    ):

        plan = self.compile_one(
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
            plan["op"],
            "project",
        )

        self.assertEqual(
            plan["columns"],
            [
                "t.did",
                "t.n",
            ],
        )

        select = plan[
            "child"
        ]

        self.assertEqual(
            select["op"],
            "select",
        )

        self.assertEqual(
            select["condition"],
            "t.n > 3",
        )

        rename = select[
            "child"
        ]

        self.assertEqual(
            rename["op"],
            "rename",
        )

        self.assertEqual(
            rename["to"],
            "t",
        )

        inner_project = rename[
            "child"
        ]

        self.assertEqual(
            inner_project["op"],
            "project",
        )

        self.assertEqual(
            inner_project["columns"],
            [
                "Emp.did",
                "n",
            ],
        )

        grouping = (
            inner_project[
                "child"
            ]
        )

        self.assertEqual(
            grouping["op"],
            "group_by",
        )

        self.assertEqual(
            grouping["keys"],
            [
                "Emp.did",
            ],
        )

        self.assertEqual(
            grouping["aggregates"],
            [
                [
                    "count",
                    "*",
                    "n",
                ]
            ],
        )

    def test_union_and_union_all_are_different_nodes(
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
            union_all_plan[
                "op"
            ],
            "union_all",
        )

        self.assertEqual(
            union_plan["left"][
                "columns"
            ],
            [
                "Emp.city",
            ],
        )

        self.assertEqual(
            union_plan["right"][
                "columns"
            ],
            [
                "Dept.city",
            ],
        )

    def test_distinct_is_above_project(
        self,
    ):

        plan = self.compile_one(
            "SELECT DISTINCT city "
            "FROM Emp"
        )

        self.assertEqual(
            plan["op"],
            "distinct",
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
                "Emp.city",
            ],
        )

    def test_distinct_above_group_by_is_not_emitted(
        self,
    ):

        plan = self.compile_one(
            "SELECT DISTINCT did "
            "FROM Emp "
            "GROUP BY did"
        )

        self.assertEqual(
            plan["op"],
            "project",
        )

        self.assertEqual(
            plan["child"]["op"],
            "group_by",
        )

        def collect_ops(node):

            result = [
                node["op"]
            ]

            if "child" in node:
                result.extend(
                    collect_ops(
                        node["child"]
                    )
                )

            if "left" in node:
                result.extend(
                    collect_ops(
                        node["left"]
                    )
                )

            if "right" in node:
                result.extend(
                    collect_ops(
                        node["right"]
                    )
                )

            return result

        self.assertNotIn(
            "distinct",
            collect_ops(plan),
        )

    def test_order_by_column_not_projected_stays_above_project(
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

    def test_condition_serialization_preserves_precedence(
        self,
    ):

        plan = self.compile_one(
            "SELECT eid "
            "FROM Emp "
            "WHERE "
            "NOT age = 10 "
            "AND "
            "(did = 2 OR did = 3)"
        )

        condition = (
            plan[
                "child"
            ][
                "condition"
            ]
        )

        self.assertEqual(
            condition,
            (
                "NOT Emp.age = 10 "
                "AND "
                "(Emp.did = 2 "
                "OR Emp.did = 3)"
            ),
        )

    def test_no_physical_operator_names_appear(
        self,
    ):

        plan = self.compile_one(
            "SELECT e.name, d.title "
            "FROM Emp e "
            "JOIN Dept d "
            "ON e.did = d.did "
            "WHERE d.budget > 1000"
        )

        physical_names = {
            "seqscan",
            "nested_loop_join",
            "sort_merge_join",
            "hash_join",
        }

        def walk(node):

            self.assertNotIn(
                node["op"],
                physical_names,
            )

            if "child" in node:
                walk(
                    node["child"]
                )

            if "left" in node:
                walk(
                    node["left"]
                )

            if "right" in node:
                walk(
                    node["right"]
                )

        walk(plan)


if __name__ == "__main__":
    unittest.main()