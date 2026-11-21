import math


def _validate_pages(value, name):
    if value < 0:
        raise ValueError(
            f"{name} must be non-negative."
        )


def _validate_frames(frames):
    if frames < 3:
        raise ValueError(
            "Cost formulas require at least "
            "3 buffer frames."
        )


# ============================================================
# Basic operators
# ============================================================


def seqscan_cost(pages):
    """
    Sequential scan:

        cost = M
    """

    _validate_pages(
        pages,
        "pages",
    )

    return pages


def filter_cost():
    """
    Filter is pipelined and performs no I/O of its own.
    """

    return 0


def project_cost():
    """
    Project is pipelined and performs no I/O of its own.
    """

    return 0


def limit_cost():
    """
    Limit performs no I/O of its own.
    """

    return 0


# ============================================================
# External sort
# ============================================================


def sort_passes(
    pages,
    frames,
):
    """
    Module 4 / Module 2 formula:

        passes =
            1
            +
            ceil(
                log(ceil(M/B))
                /
                log(B-1)
            )

    For an empty input, there is no sort pass.

    The implementation below is mathematically equivalent,
    but uses integer arithmetic to avoid floating-point
    rounding at exact powers of B-1.
    """

    _validate_pages(
        pages,
        "pages",
    )

    _validate_frames(
        frames
    )

    if pages == 0:
        return 0

    initial_runs = math.ceil(
        pages
        / frames
    )

    # Pass 0 produces the initial runs.
    passes = 1

    runs = initial_runs

    # Each merge pass combines at most B-1 runs.
    while runs > 1:

        runs = math.ceil(
            runs
            / (
                frames - 1
            )
        )

        passes += 1

    return passes


def sort_cost(
    pages,
    frames,
):
    """
    Required Module 4 formula:

        2 * M * (passes - 1) + M
    """

    _validate_pages(
        pages,
        "pages",
    )

    _validate_frames(
        frames
    )

    if pages == 0:
        return 0

    passes = sort_passes(
        pages,
        frames,
    )

    return (
        2
        * pages
        * (
            passes - 1
        )
        + pages
    )


# ============================================================
# Hash partitioning
# ============================================================


def hash_partition_cost(
    pages,
):
    """
    One-input external hash partitioning cost.

    Read the input once,
    write partitions once,
    read partitions once:

        3 * M

    Used when distinct/group_by choose their hash-based
    Module 2 implementations.
    """

    _validate_pages(
        pages,
        "pages",
    )

    return (
        3
        * pages
    )


def distinct_cost(
    pages,
    frames,
    method,
):
    """
    Module 4 says DISTINCT costs whatever its chosen
    sort/hash implementation costs.
    """

    if method == "sort":

        return sort_cost(
            pages,
            frames,
        )

    if method == "hash":

        return hash_partition_cost(
            pages
        )

    raise ValueError(
        "Unknown DISTINCT method: "
        f"{method}"
    )


def group_by_cost(
    pages,
    frames,
    method,
):
    """
    Module 4 says GROUP BY costs whatever its chosen
    sort/hash implementation costs.
    """

    if method == "sort":

        return sort_cost(
            pages,
            frames,
        )

    if method == "hash":

        return hash_partition_cost(
            pages
        )

    raise ValueError(
        "Unknown GROUP BY method: "
        f"{method}"
    )


# ============================================================
# Join algorithms
# ============================================================


def nested_loop_join_cost(
    outer_pages,
    inner_pages,
    frames,
):
    """
    Block nested loop join:

        M + ceil(M / (B-2)) * N

    M is the OUTER relation.
    """

    _validate_pages(
        outer_pages,
        "outer_pages",
    )

    _validate_pages(
        inner_pages,
        "inner_pages",
    )

    _validate_frames(
        frames
    )

    if outer_pages == 0:
        return 0

    return (
        outer_pages
        +
        math.ceil(
            outer_pages
            /
            (
                frames - 2
            )
        )
        * inner_pages
    )


def sort_merge_join_cost(
    left_pages,
    right_pages,
    frames,
):
    """
    Sort-merge join:

        sort(M) + sort(N) + M + N
    """

    _validate_pages(
        left_pages,
        "left_pages",
    )

    _validate_pages(
        right_pages,
        "right_pages",
    )

    _validate_frames(
        frames
    )

    return (
        sort_cost(
            left_pages,
            frames,
        )
        +
        sort_cost(
            right_pages,
            frames,
        )
        +
        left_pages
        +
        right_pages
    )


def hash_join_cost(
    left_pages,
    right_pages,
):
    """
    Grace hash join:

        3 * (M + N)
    """

    _validate_pages(
        left_pages,
        "left_pages",
    )

    _validate_pages(
        right_pages,
        "right_pages",
    )

    return (
        3
        * (
            left_pages
            +
            right_pages
        )
    )


def join_algorithm_costs(
    left_pages,
    right_pages,
    frames,
    equality=True,
):
    """
    Return the legal physical join alternatives.

    Module 2 hash_join and sort_merge_join support equality
    joins only.

    nested_loop_join also supports non-equality predicates.
    """

    costs = {
        "nested_loop_join":
            nested_loop_join_cost(
                left_pages,
                right_pages,
                frames,
            ),
    }

    if equality:

        costs[
            "sort_merge_join"
        ] = sort_merge_join_cost(
            left_pages,
            right_pages,
            frames,
        )

        costs[
            "hash_join"
        ] = hash_join_cost(
            left_pages,
            right_pages,
        )

    return costs