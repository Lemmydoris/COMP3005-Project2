import csv
import time
from benchmark import build_tables
from operators import Evaluator
from parser import parse_query

N = 1000
MATCH_RATES = [1, 2, 4]

def main():
    results = []
    tree = parse_query("R join[R.b=S.b] S")

    for rate in MATCH_RATES:
        R, S = build_tables(N, match_rate=rate)

        evaluator = Evaluator({
            "R": R,
            "S": S,
        })

        start = time.perf_counter()
        result = evaluator.evaluate(tree)
        elapsed = time.perf_counter() - start

        row = {
            "match_rate": rate,
            "n": len(R.rows),
            "m": len(S.rows),
            "comparisons": evaluator.counters["join"],
            "wall_time": elapsed,
            "output_tuples": len(result.rows),
        }

        results.append(row)

        print(f"\nMatch rate: {rate}")
        print(f"Comparisons: {row['comparisons']:,}")
        print(f"Wall time: {elapsed:.6f} seconds")
        print(f"Output tuples: {row['output_tuples']:,}")

    with open(
        "match_rate_results.csv",
        "w",
        newline="",
        encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "match_rate",
                "n",
                "m",
                "comparisons",
                "wall_time",
                "output_tuples",
            ]
        )
        writer.writeheader()
        writer.writerows(results)

    print("\nResults saved to match_rate_results.csv")

if __name__ == "__main__":
    main()