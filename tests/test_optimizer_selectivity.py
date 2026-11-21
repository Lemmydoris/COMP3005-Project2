import unittest

from optimizer.selectivity import (
    DEFAULT_JOIN_SELECTIVITY,
    SelectivityEstimator,
    estimate_join_rows,
    estimate_pages,
    estimate_rows,
)


class OptimizerSelectivityTests(
    unittest.TestCase
):

    def setUp(self):

        self.schema = [
            ["R.did", "INT"],
            ["R.age", "INT"],
            [
                "R.name",
                "VARCHAR",
                20,
            ],
            ["S.did", "INT"],
        ]

        self.statistics = {
            "R": {
                "n_tuples": 10000,
                "n_pages": 200,
                "width": 40.0,
                "columns": {
                    "did": {
                        "ndv": 50,
                        "min": 1,
                        "max": 50,
                        "hist": [
                            {
                                "min": 1,
                                "max": 50,
                                "count": 10000,
                                "ndv": 50,
                            }
                        ],
                    },
                    "age": {
                        "ndv": 51,
                        "min": 20,
                        "max": 70,
                        "hist": [
                            {
                                "min": 20,
                                "max": 70,
                                "count": 10000,
                                "ndv": 51,
                            }
                        ],
                    },
                    "name": {
                        "ndv": 26,
                        "min": "a",
                        "max": "z",
                        "hist": [
                            {
                                "min": "a",
                                "max": "z",
                                "count": 10000,
                                "ndv": 26,
                            }
                        ],
                    },
                },
            },
            "S": {
                "n_tuples": 50,
                "n_pages": 1,
                "width": 8.0,
                "columns": {
                    "did": {
                        "ndv": 50,
                        "min": 1,
                        "max": 50,
                        "hist": [
                            {
                                "min": 1,
                                "max": 50,
                                "count": 50,
                                "ndv": 50,
                            }
                        ],
                    },
                },
            },
        }

        self.estimator = (
            SelectivityEstimator(
                self.schema,
                self.statistics,
            )
        )

    def test_equality_uses_histogram_bucket(
        self,
    ):

        result = (
            self.estimator
            .estimate(
                "R.did = 7"
            )
        )

        self.assertAlmostEqual(
            result,
            0.02,
        )

    def test_equality_without_histogram_uses_ndv(
        self,
    ):

        statistics = {
            "R": {
                "n_tuples": 100,
                "columns": {
                    "did": {
                        "ndv": 10,
                        "min": 1,
                        "max": 10,
                        "hist": [],
                    }
                },
            }
        }

        estimator = (
            SelectivityEstimator(
                [
                    [
                        "R.did",
                        "INT",
                    ]
                ],
                statistics,
            )
        )

        self.assertAlmostEqual(
            estimator.estimate(
                "R.did = 4"
            ),
            0.1,
        )

    def test_range_matches_professor_worked_example(
        self,
    ):

        result = (
            self.estimator
            .estimate(
                "R.age > 60"
            )
        )

        self.assertAlmostEqual(
            result,
            0.20,
        )

    def test_not_equal_is_one_minus_equality(
        self,
    ):

        result = (
            self.estimator
            .estimate(
                "R.did != 7"
            )
        )

        self.assertAlmostEqual(
            result,
            0.98,
        )

    def test_and_or_and_not_formulas(
        self,
    ):

        conjunction = (
            self.estimator
            .estimate(
                "R.did = 7 "
                "and R.age > 60"
            )
        )

        self.assertAlmostEqual(
            conjunction,
            0.004,
        )

        disjunction = (
            self.estimator
            .estimate(
                "R.did = 7 "
                "or R.age > 60"
            )
        )

        self.assertAlmostEqual(
            disjunction,
            0.216,
        )

        negated = (
            self.estimator
            .estimate(
                "not R.did = 7"
            )
        )

        self.assertAlmostEqual(
            negated,
            0.98,
        )

    def test_equality_join_uses_max_ndv(
        self,
    ):

        selectivity = (
            self.estimator
            .estimate(
                "R.did = S.did"
            )
        )

        self.assertAlmostEqual(
            selectivity,
            1.0 / 50.0,
        )

        rows = estimate_join_rows(
            10000,
            50,
            selectivity,
        )

        self.assertEqual(
            rows,
            10000,
        )

    def test_non_equality_join_uses_default(
        self,
    ):

        selectivity = (
            self.estimator
            .estimate(
                "R.did > S.did"
            )
        )

        self.assertEqual(
            selectivity,
            DEFAULT_JOIN_SELECTIVITY,
        )

    def test_reversed_literal_comparison(
        self,
    ):

        normal = (
            self.estimator
            .estimate(
                "R.age > 60"
            )
        )

        reversed_condition = (
            self.estimator
            .estimate(
                "60 < R.age"
            )
        )

        self.assertAlmostEqual(
            normal,
            reversed_condition,
        )

    def test_cardinality_and_page_helpers(
        self,
    ):

        self.assertEqual(
            estimate_rows(
                10000,
                0.004,
            ),
            40,
        )

        self.assertEqual(
            estimate_rows(
                100,
                0.0,
            ),
            1,
        )

        self.assertEqual(
            estimate_pages(
                100,
                40,
            ),
            1,
        )

        self.assertEqual(
            estimate_pages(
                1000,
                40,
            ),
            10,
        )

    def test_varchar_range_uses_byte_order_interpolation(
        self,
    ):

        result = (
            self.estimator
            .estimate(
                "R.name < 'm'"
            )
        )

        expected = (
            (ord("m") - ord("a"))
            /
            (ord("z") - ord("a"))
        )

        self.assertAlmostEqual(
            result,
            expected,
        )


if __name__ == "__main__":
    unittest.main()