import unittest

from optimizer.join_order import (
    JoinPredicateInfo,
    RelationInfo,
    enumerate_left_deep,
)


class OptimizerJoinOrderTests(
    unittest.TestCase
):

    def setUp(self):

        # Professor's Section 5.1 example.
        self.relations = [
            RelationInfo(
                name="A",
                pages=100,
                rows=5000,
            ),
            RelationInfo(
                name="B'",
                pages=10,
                rows=500,
            ),
            RelationInfo(
                name="C",
                pages=400,
                rows=20000,
            ),
        ]

        self.predicates = [
            JoinPredicateInfo(
                left="A",
                right="B'",
                condition=
                    "A.x = B'.x",
                equality=True,
                pair_rows=1000,
                pair_pages=20,
            ),
            JoinPredicateInfo(
                left="B'",
                right="C",
                condition=
                    "B'.y = C.y",
                equality=True,
                pair_rows=2000,
                pair_pages=40,
            ),
        ]

        self.result = (
            enumerate_left_deep(
                self.relations,
                self.predicates,
                frames=32,
            )
        )

    def test_singleton_scan_costs_match_professor_table(
        self,
    ):

        self.assertEqual(
            self.result.best[
                frozenset(
                    {"A"}
                )
            ].cost,
            100,
        )

        self.assertEqual(
            self.result.best[
                frozenset(
                    {"B'"}
                )
            ].cost,
            10,
        )

        self.assertEqual(
            self.result.best[
                frozenset(
                    {"C"}
                )
            ].cost,
            400,
        )

    def test_A_B_pair_matches_professor_table(
        self,
    ):

        entry = (
            self.result.best[
                frozenset(
                    {
                        "A",
                        "B'",
                    }
                )
            ]
        )

        self.assertEqual(
            entry.cost,
            110,
        )

        self.assertEqual(
            entry.pages,
            20,
        )

        self.assertEqual(
            entry.rows,
            1000,
        )

        self.assertEqual(
            entry.algorithm,
            "nested_loop_join",
        )

        # B' must be the outer/left side.
        self.assertEqual(
            entry.plan[
                "left"
            ][
                "table"
            ],
            "B'",
        )

        self.assertEqual(
            entry.plan[
                "right"
            ][
                "table"
            ],
            "A",
        )

    def test_B_C_pair_matches_professor_table(
        self,
    ):

        entry = (
            self.result.best[
                frozenset(
                    {
                        "B'",
                        "C",
                    }
                )
            ]
        )

        self.assertEqual(
            entry.cost,
            410,
        )

        self.assertEqual(
            entry.pages,
            40,
        )

        self.assertEqual(
            entry.rows,
            2000,
        )

        self.assertEqual(
            entry.plan[
                "left"
            ][
                "table"
            ],
            "B'",
        )

        self.assertEqual(
            entry.plan[
                "right"
            ][
                "table"
            ],
            "C",
        )

    def test_A_C_is_skipped_without_predicate(
        self,
    ):

        subset = frozenset(
            {
                "A",
                "C",
            }
        )

        self.assertNotIn(
            subset,
            self.result.best,
        )

        self.assertEqual(
            self.result.candidates[
                subset
            ],
            [],
        )

    def test_professor_winning_three_way_plan_costs_530(
        self,
    ):

        final = (
            self.result.best[
                frozenset(
                    {
                        "A",
                        "B'",
                        "C",
                    }
                )
            ]
        )

        self.assertEqual(
            final.cost,
            530,
        )

        self.assertEqual(
            final.algorithm,
            "nested_loop_join",
        )

        self.assertEqual(
            final.added_relation,
            "C",
        )

        self.assertEqual(
            final.left_relations,
            frozenset(
                {
                    "A",
                    "B'",
                }
            ),
        )

    def test_second_three_way_candidate_uses_correct_BNL_formula(
        self,
    ):

        subset = frozenset(
            {
                "A",
                "B'",
                "C",
            }
        )

        alternatives = (
            self.result.candidates[
                subset
            ]
        )

        matching = [
            candidate
            for candidate
            in alternatives
            if (
                candidate.left_relations
                ==
                frozenset(
                    {
                        "B'",
                        "C",
                    }
                )
                and
                candidate.added_relation
                == "A"
                and
                candidate.algorithm
                == "nested_loop_join"
            )
        ]

        self.assertEqual(
            len(matching),
            1,
        )

        alternative = (
            matching[0]
        )

        # B = 32 -> B-2 = 30.
        #
        # 40 outer pages therefore require two blocks:
        #
        # incremental =
        #     40 + ceil(40/30) * 100
        #   = 240
        #
        # total =
        #     410 + 240
        #   = 650
        #
        # The handout prints 550 here, which conflicts with
        # its own BNL formula. We preserve the formula.
        self.assertEqual(
            alternative.incremental_cost,
            240,
        )

        self.assertEqual(
            alternative.total_cost,
            650,
        )

    def test_equality_considers_all_three_join_algorithms(
        self,
    ):

        subset = frozenset(
            {
                "A",
                "B'",
            }
        )

        algorithms = {
            candidate.algorithm
            for candidate
            in self.result.candidates[
                subset
            ]
        }

        self.assertEqual(
            algorithms,
            {
                "nested_loop_join",
                "sort_merge_join",
                "hash_join",
            },
        )

    def test_non_equality_only_considers_nested_loop(
        self,
    ):

        relations = [
            RelationInfo(
                "A",
                10,
                100,
            ),
            RelationInfo(
                "C",
                20,
                200,
            ),
        ]

        predicates = [
            JoinPredicateInfo(
                left="A",
                right="C",
                condition=
                    "A.x > C.x",
                equality=False,
                selectivity=0.1,
            ),
        ]

        result = (
            enumerate_left_deep(
                relations,
                predicates,
                frames=8,
            )
        )

        algorithms = {
            candidate.algorithm
            for candidate
            in result.candidates[
                frozenset(
                    {
                        "A",
                        "C",
                    }
                )
            ]
        }

        self.assertEqual(
            algorithms,
            {
                "nested_loop_join",
            },
        )

    def test_more_than_six_relations_is_rejected(
        self,
    ):

        relations = [
            RelationInfo(
                name=f"R{i}",
                pages=1,
                rows=1,
            )
            for i in range(
                7
            )
        ]

        with self.assertRaises(
            ValueError
        ):

            enumerate_left_deep(
                relations,
                [],
                frames=4,
            )


if __name__ == "__main__":
    unittest.main()