import unittest

from optimizer.cost import (
    distinct_cost,
    filter_cost,
    group_by_cost,
    hash_join_cost,
    join_algorithm_costs,
    limit_cost,
    nested_loop_join_cost,
    project_cost,
    seqscan_cost,
    sort_cost,
    sort_merge_join_cost,
    sort_passes,
)


class OptimizerCostTests(
    unittest.TestCase
):

    def test_seqscan_and_pipelined_costs(
        self,
    ):

        self.assertEqual(
            seqscan_cost(200),
            200,
        )

        self.assertEqual(
            filter_cost(),
            0,
        )

        self.assertEqual(
            project_cost(),
            0,
        )

        self.assertEqual(
            limit_cost(),
            0,
        )

    def test_sort_one_pass_when_input_fits(
        self,
    ):

        self.assertEqual(
            sort_passes(
                8,
                8,
            ),
            1,
        )

        self.assertEqual(
            sort_cost(
                8,
                8,
            ),
            8,
        )

    def test_sort_multiple_passes(
        self,
    ):

        # M=20, B=4
        #
        # initial runs = ceil(20/4) = 5
        # merge fan-in = 3
        #
        # pass 0: 5 runs
        # pass 1: 2 runs
        # pass 2: 1 run
        #
        # total passes = 3

        self.assertEqual(
            sort_passes(
                20,
                4,
            ),
            3,
        )

        self.assertEqual(
            sort_cost(
                20,
                4,
            ),
            100,
        )

    def test_sort_twenty_times_B_example(
        self,
    ):

        # Required Module 2 measurement includes
        # a case where M = 20 * B.
        #
        # B=4 -> M=80
        #
        # initial runs = 20
        # 20 -> 7 -> 3 -> 1
        #
        # passes = 4

        self.assertEqual(
            sort_passes(
                80,
                4,
            ),
            4,
        )

        self.assertEqual(
            sort_cost(
                80,
                4,
            ),
            560,
        )

    def test_nested_loop_join_formula(
        self,
    ):

        # B=32 means B-2=30.
        #
        # 20 outer pages fit in one outer block:
        #
        # 20 + ceil(20/30) * 400
        # = 420

        self.assertEqual(
            nested_loop_join_cost(
                20,
                400,
                32,
            ),
            420,
        )

    def test_hash_join_formula(
        self,
    ):

        self.assertEqual(
            hash_join_cost(
                20,
                400,
            ),
            1260,
        )

    def test_sort_merge_join_formula(
        self,
    ):

        # sort(20,32) = 20
        #
        # sort(400,32):
        # initial runs = 13, so 2 passes
        # cost = 1200
        #
        # total:
        # 20 + 1200 + 20 + 400
        # = 1640

        self.assertEqual(
            sort_merge_join_cost(
                20,
                400,
                32,
            ),
            1640,
        )

    def test_memory_budget_can_change_best_join(
        self,
    ):

        low_memory = (
            join_algorithm_costs(
                20,
                400,
                4,
                equality=True,
            )
        )

        high_memory = (
            join_algorithm_costs(
                20,
                400,
                32,
                equality=True,
            )
        )

        self.assertEqual(
            min(
                low_memory,
                key=low_memory.get,
            ),
            "hash_join",
        )

        self.assertEqual(
            min(
                high_memory,
                key=high_memory.get,
            ),
            "nested_loop_join",
        )

    def test_non_equality_join_only_offers_nested_loop(
        self,
    ):

        costs = (
            join_algorithm_costs(
                20,
                400,
                32,
                equality=False,
            )
        )

        self.assertEqual(
            set(
                costs
            ),
            {
                "nested_loop_join",
            },
        )

    def test_distinct_and_group_by_follow_chosen_method(
        self,
    ):

        self.assertEqual(
            distinct_cost(
                20,
                4,
                "sort",
            ),
            100,
        )

        self.assertEqual(
            distinct_cost(
                20,
                4,
                "hash",
            ),
            60,
        )

        self.assertEqual(
            group_by_cost(
                20,
                4,
                "sort",
            ),
            100,
        )

        self.assertEqual(
            group_by_cost(
                20,
                4,
                "hash",
            ),
            60,
        )

    def test_invalid_memory_budget_is_rejected(
        self,
    ):

        with self.assertRaises(
            ValueError
        ):

            sort_cost(
                20,
                2,
            )

        with self.assertRaises(
            ValueError
        ):

            nested_loop_join_cost(
                20,
                40,
                2,
            )


if __name__ == "__main__":
    unittest.main()