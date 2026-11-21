import csv
import time
from operators import Table, Column, Evaluator
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

def build_relation(n):
    rows = []

    for i in range(n):
        # category repeats so projection has duplicates to remove
        category = i % 100
        rows.append((i, category))

    return Table(
        "R",
        [
            Column("R", "a", "number"),
            Column("R", "b", "number"),
        ],
        rows,
    )

def run_select(n):
    R = build_relation(n)
    evaluator = Evaluator({
        "R": R
    })
    tree = parse_query(
        "select[a>=0](R)"
    )
    start = time.perf_counter()
    result = evaluator.evaluate(tree)
    end = time.perf_counter()
    return {
        "n": n,
        "wall_time": end - start,
        "examined": evaluator.counters["select"],
        "output_tuples": len(result.rows),
    }

def run_project(n):
    R = build_relation(n)

    evaluator = Evaluator({
        "R": R
    })

    tree = parse_query(
        "project[b](R)"
    )
    start = time.perf_counter()
    result = evaluator.evaluate(tree)
    end = time.perf_counter()

    return {
        "n": n,
        "wall_time": end - start,
        "output_tuples": len(result.rows),
    }

def main():
    results = []

    for n in SIZES:
        print()
        print("=" * 60)
        print(f"Running select/project benchmark for n = {n:,}")

        select_result = run_select(n)
        project_result = run_project(n)

        row = {
            "n": n,
            "select_time": select_result["wall_time"],
            "select_examined": select_result["examined"],
            "select_output": select_result["output_tuples"],
            "project_time": project_result["wall_time"],
            "project_output": project_result["output_tuples"],
        }

        results.append(row)

        print(
            f"Select: {select_result['wall_time']:.6f}s, "
            f"examined {select_result['examined']:,}, "
            f"output {select_result['output_tuples']:,}"
        )

        print(
            f"Project: {project_result['wall_time']:.6f}s, "
            f"output {project_result['output_tuples']:,}"
        )

        with open(
            "select_project_results.csv",
            "w",
            newline="",
            encoding="utf-8",
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "n",
                    "select_time",
                    "select_examined",
                    "select_output",
                    "project_time",
                    "project_output",
                ],
            )

            writer.writeheader()
            writer.writerows(results)

    print()
    print("Finished.")
    print(
        "Results saved to select_project_results.csv"
    )

if __name__ == "__main__":
    main()