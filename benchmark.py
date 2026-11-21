import csv
import time
from generator import generate_relations
from operators import (
    Table,
    Column,
    Evaluator,
)
from parser import parse_query

SIZES = [
    1000,
    2000,
    4000,
    8000,
    16000,
    32000,
    64000,
]

def build_tables(n, match_rate=1):
    r_rows, s_rows = generate_relations(
        n=n,
        m=n,
        match_rate=match_rate
    )

    # The generator already produces unique tuples,
    # so we can construct the benchmark tables directly.
    R = Table(
        "R",
        [
            Column("R", "a", "number"),
            Column("R", "b", "number"),
        ],
        r_rows
    )

    S = Table(
        "S",
        [
            Column("S", "b", "number"),
            Column("S", "c", "number"),
        ],
        s_rows
    )

    return R, S

def run_join_benchmark(n, match_rate=1):
    R, S = build_tables(
        n,
        match_rate
    )

    evaluator = Evaluator({
        "R": R,
        "S": S,
    })

    tree = parse_query(
        "R join[R.b=S.b] S"
    )

    start = time.perf_counter()

    result = evaluator.evaluate(tree)

    end = time.perf_counter()

    elapsed = end - start

    return {
        "n": n,
        "m": n,
        "comparisons": evaluator.counters["join"],
        "wall_time": elapsed,
        "output_tuples": len(result.rows),
    }

def main():
    results = []

    for n in SIZES:
        print()
        print("=" * 60)
        print(f"Running join benchmark for n = {n:,}")

        result = run_join_benchmark(n)

        results.append(result)

        print(
            f"Comparisons: "
            f"{result['comparisons']:,}"
        )

        print(
            f"Wall time: "
            f"{result['wall_time']:.6f} seconds"
        )

        print(
            f"Output tuples: "
            f"{result['output_tuples']:,}"
        )

        with open(
            "benchmark_results.csv",
            "w",
            newline="",
            encoding="utf-8"
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "n",
                    "m",
                    "comparisons",
                    "wall_time",
                    "output_tuples",
                ]
            )

            writer.writeheader()
            writer.writerows(results)

    print()
    print("Finished.")
    print(
        "Results saved to "
        "benchmark_results.csv"
    )

if __name__ == "__main__":
    main()