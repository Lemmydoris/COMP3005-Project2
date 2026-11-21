import math
from dataclasses import dataclass
from itertools import combinations

from optimizer.cost import (
    join_algorithm_costs,
)
from optimizer.selectivity import (
    estimate_pages,
)


MAX_DP_RELATIONS = 6
DEFAULT_JOIN_SELECTIVITY = 0.1


@dataclass(frozen=True)
class RelationInfo:
    """
    Statistics for one base relation/access path.
    """

    name: str
    pages: int
    rows: int
    width: float = 0.0

    def effective_width(self):
        """
        If an explicit average tuple width is unavailable,
        derive a page-density approximation.
        """

        if self.width > 0:
            return self.width

        if (
            self.rows > 0
            and self.pages > 0
        ):
            return (
                self.pages
                * 4096
                / self.rows
            )

        return 0.0


@dataclass(frozen=True)
class JoinPredicateInfo:
    """
    A predicate connecting two base relations.

    pair_rows / pair_pages are optional exact estimates for
    the two-relation subset. They are useful for reproducing
    the professor's Section 5.1 example.

    For normal optimizer operation, selectivity is supplied
    by optimizer.selectivity.
    """

    left: str
    right: str
    condition: str

    equality: bool = True
    selectivity: float | None = None

    pair_rows: int | None = None
    pair_pages: int | None = None

    def connects(
        self,
        relation,
        relations,
    ):
        """
        Does this predicate connect 'relation' to any relation
        already in 'relations'?
        """

        return (
            (
                self.left == relation
                and self.right in relations
            )
            or
            (
                self.right == relation
                and self.left in relations
            )
        )

    def relation_pair(self):
        return frozenset(
            {
                self.left,
                self.right,
            }
        )


@dataclass
class DPCandidate:
    relations: frozenset
    left_relations: frozenset
    added_relation: str

    algorithm: str
    condition: str

    incremental_cost: int
    total_cost: int

    rows: int
    pages: int
    width: float

    plan: dict


@dataclass
class DPEntry:
    relations: frozenset

    cost: int
    rows: int
    pages: int
    width: float

    plan: dict

    algorithm: str | None = None
    condition: str | None = None

    left_relations: frozenset | None = None
    added_relation: str | None = None


@dataclass
class DPResult:
    best: dict
    candidates: dict

    @property
    def final(self):

        if not self.best:
            return None

        largest = max(
            self.best,
            key=len,
        )

        return self.best[
            largest
        ]


def _predicate_text(
    predicates,
):
    return " AND ".join(
        predicate.condition
        for predicate
        in predicates
    )


def _combined_selectivity(
    predicates,
    relation_lookup,
):
    """
    Combine join predicates using the same independence
    assumption used elsewhere in Module 4.
    """

    selectivity = 1.0

    for predicate in predicates:

        if predicate.selectivity is not None:

            value = (
                predicate.selectivity
            )

        elif predicate.pair_rows is not None:

            left_rows = (
                relation_lookup[
                    predicate.left
                ].rows
            )

            right_rows = (
                relation_lookup[
                    predicate.right
                ].rows
            )

            denominator = (
                left_rows
                * right_rows
            )

            if denominator <= 0:
                value = 0.0
            else:
                value = (
                    predicate.pair_rows
                    / denominator
                )

        else:

            value = (
                DEFAULT_JOIN_SELECTIVITY
            )

        value = max(
            0.0,
            min(
                1.0,
                value,
            ),
        )

        selectivity *= value

    return selectivity


def _estimate_join_output(
    left_entry,
    right_relation,
    predicates,
    relation_lookup,
):
    """
    Estimate rows/pages for one DP extension.
    """

    all_relations = (
        set(
            left_entry.relations
        )
        |
        {
            right_relation.name,
        }
    )

    # --------------------------------------------------------
    # Exact two-relation estimate supplied by the reference
    # example or caller.
    # --------------------------------------------------------

    if len(
        all_relations
    ) == 2:

        pair = frozenset(
            all_relations
        )

        matching = [
            predicate
            for predicate
            in predicates
            if (
                predicate.relation_pair()
                == pair
            )
        ]

        if len(
            matching
        ) == 1:

            predicate = (
                matching[0]
            )

            if (
                predicate.pair_rows
                is not None
                and
                predicate.pair_pages
                is not None
            ):

                width = (
                    left_entry.width
                    +
                    right_relation
                    .effective_width()
                )

                return (
                    predicate.pair_rows,
                    predicate.pair_pages,
                    width,
                )

    # --------------------------------------------------------
    # General estimate.
    # --------------------------------------------------------

    selectivity = (
        _combined_selectivity(
            predicates,
            relation_lookup,
        )
    )

    rows = max(
        1,
        math.ceil(
            left_entry.rows
            * right_relation.rows
            * selectivity
        ),
    )

    width = (
        left_entry.width
        +
        right_relation
        .effective_width()
    )

    pages = estimate_pages(
        rows,
        width,
    )

    return (
        rows,
        pages,
        width,
    )


def _base_entry(
    relation,
):
    return DPEntry(
        relations=frozenset(
            {
                relation.name,
            }
        ),
        cost=relation.pages,
        rows=relation.rows,
        pages=relation.pages,
        width=(
            relation.effective_width()
        ),
        plan={
            "op":
                "seqscan",
            "table":
                relation.name,
        },
    )


def _candidate_cost(
    left_entry,
    incremental_cost,
):
    """
    Match the handout's DP accounting.

    For a two-relation plan, the join algorithm's formula
    already includes reading both base inputs, so we do not
    add the singleton scan cost a second time.

    For larger subsets, best[left] has already paid to
    produce the intermediate result, so its cost is added
    before the next join consumes that intermediate.
    """

    if len(
        left_entry.relations
    ) == 1:

        return incremental_cost

    return (
        left_entry.cost
        +
        incremental_cost
    )


def enumerate_left_deep(
    relations,
    predicates,
    frames,
):
    """
    Selinger-style dynamic programming over left-deep trees.

    Up to six relations.

    The right input of every new join is one base relation.

    Pairings without a join predicate are skipped. This
    matches the connected-subset behavior in Section 5.1;
    disconnected-query fallback can be added at the physical
    planning integration layer.
    """

    relations = list(
        relations
    )

    predicates = list(
        predicates
    )

    if not relations:

        raise ValueError(
            "DP enumeration needs at "
            "least one relation."
        )

    if len(
        relations
    ) > MAX_DP_RELATIONS:

        raise ValueError(
            "DP enumeration supports "
            f"at most {MAX_DP_RELATIONS} "
            "relations."
        )

    names = [
        relation.name
        for relation
        in relations
    ]

    if len(
        names
    ) != len(
        set(
            names
        )
    ):

        raise ValueError(
            "Relation names must be unique "
            "inside DP enumeration."
        )

    relation_lookup = {
        relation.name:
            relation
        for relation
        in relations
    }

    for predicate in predicates:

        if (
            predicate.left
            not in relation_lookup
            or
            predicate.right
            not in relation_lookup
        ):

            raise ValueError(
                "Join predicate references "
                "an unknown relation."
            )

    best = {}
    candidates = {}

    # ========================================================
    # Size 1
    # ========================================================

    for relation in relations:

        subset = frozenset(
            {
                relation.name,
            }
        )

        best[
            subset
        ] = _base_entry(
            relation
        )

        candidates[
            subset
        ] = []

    # ========================================================
    # Sizes 2..n
    # ========================================================

    for size in range(
        2,
        len(
            relations
        )
        + 1,
    ):

        for names_subset in combinations(
            names,
            size,
        ):

            subset = frozenset(
                names_subset
            )

            subset_candidates = []

            # ------------------------------------------------
            # Left-deep recurrence:
            #
            # choose one base relation r as the right input.
            # The remaining set must already have a best plan.
            # ------------------------------------------------

            for added_relation_name in sorted(
                subset
            ):

                left_relations = (
                    subset
                    -
                    {
                        added_relation_name
                    }
                )

                if left_relations not in best:
                    continue

                left_entry = (
                    best[
                        left_relations
                    ]
                )

                connecting = [
                    predicate
                    for predicate
                    in predicates
                    if predicate.connects(
                        added_relation_name,
                        left_relations,
                    )
                ]

                # Section 5.1 skips {A,C} because there is
                # no join predicate.
                if not connecting:
                    continue

                right_relation = (
                    relation_lookup[
                        added_relation_name
                    ]
                )

                equality = all(
                    predicate.equality
                    for predicate
                    in connecting
                )

                rows, pages, width = (
                    _estimate_join_output(
                        left_entry,
                        right_relation,
                        connecting,
                        relation_lookup,
                    )
                )

                condition = (
                    _predicate_text(
                        connecting
                    )
                )

                algorithm_costs = (
                    join_algorithm_costs(
                        left_entry.pages,
                        right_relation.pages,
                        frames,
                        equality=equality,
                    )
                )

                for (
                    algorithm,
                    incremental_cost,
                ) in (
                    algorithm_costs.items()
                ):

                    total_cost = (
                        _candidate_cost(
                            left_entry,
                            incremental_cost,
                        )
                    )

                    plan = {
                        "op":
                            algorithm,
                        "condition":
                            condition,
                        "left":
                            left_entry.plan,
                        "right": {
                            "op":
                                "seqscan",
                            "table":
                                right_relation.name,
                        },
                    }

                    subset_candidates.append(
                        DPCandidate(
                            relations=
                                subset,
                            left_relations=
                                left_relations,
                            added_relation=
                                added_relation_name,
                            algorithm=
                                algorithm,
                            condition=
                                condition,
                            incremental_cost=
                                incremental_cost,
                            total_cost=
                                total_cost,
                            rows=
                                rows,
                            pages=
                                pages,
                            width=
                                width,
                            plan=
                                plan,
                        )
                    )

            candidates[
                subset
            ] = (
                subset_candidates
            )

            if not subset_candidates:

                # No connected left-deep plan for this subset.
                # Example: {A,C} in Section 5.1.
                continue

            winner = min(
                subset_candidates,
                key=lambda candidate: (
                    candidate.total_cost,
                    candidate.algorithm,
                    candidate.added_relation,
                ),
            )

            best[
                subset
            ] = DPEntry(
                relations=
                    subset,
                cost=
                    winner.total_cost,
                rows=
                    winner.rows,
                pages=
                    winner.pages,
                width=
                    winner.width,
                plan=
                    winner.plan,
                algorithm=
                    winner.algorithm,
                condition=
                    winner.condition,
                left_relations=
                    winner.left_relations,
                added_relation=
                    winner.added_relation,
            )

    return DPResult(
        best=best,
        candidates=candidates,
    )