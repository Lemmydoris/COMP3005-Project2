from pathlib import Path
import csv
import json
import subprocess

DB = "m4_report_db"
FRAMES = 32

LOGICAL_DIR = Path("m4_logical")
RESULTS_DIR = Path("m4_results")
BASELINE_DIR = Path("m4_baseline")

RESULTS_DIR.mkdir(exist_ok=True)
BASELINE_DIR.mkdir(exist_ok=True)


def baseline_plan(node):
    """
    Convert the ORIGINAL logical plan directly to a physical plan.

    Baseline rules:
      - preserve written join order
      - fixed nested-loop join algorithm
      - no predicate pushdown
      - no projection pushdown
      - cross remains a Cartesian nested-loop product
    """

    op = node["op"]

    if op == "scan":
        return {
            "op": "seqscan",
            "table": node["table"],
        }

    if op == "rename":
        return {
            "op": "rename",
            "to": node["to"],
            "child": baseline_plan(node["child"]),
        }

    if op == "select":
        return {
            "op": "filter",
            "condition": node["condition"],
            "child": baseline_plan(node["child"]),
        }

    if op == "project":
        return {
            "op": "project",
            "columns": node["columns"],
            "child": baseline_plan(node["child"]),
        }

    if op == "join":
        return {
            "op": "nested_loop_join",
            "condition": node["condition"],
            "left": baseline_plan(node["left"]),
            "right": baseline_plan(node["right"]),
        }

    if op == "cross":
        return {
            "op": "nested_loop_join",
            "condition": "1 = 1",
            "left": baseline_plan(node["left"]),
            "right": baseline_plan(node["right"]),
        }

    if op == "group_by":
        return {
            "op": "group_by",
            "mode": "sort",
            "keys": node["keys"],
            "aggregates": node["aggregates"],
            "child": baseline_plan(node["child"]),
        }

    if op == "sort":
        return {
            "op": "sort",
            "keys": node["keys"],
            "child": baseline_plan(node["child"]),
        }

    if op == "limit":
        return {
            "op": "limit",
            "n": node["n"],
            "child": baseline_plan(node["child"]),
        }

    if op == "distinct":
        return {
            "op": "distinct",
            "mode": "sort",
            "child": baseline_plan(node["child"]),
        }

    if op in {"union_all", "union", "intersect", "except"}:
        return {
            "op": op,
            "left": baseline_plan(node["left"]),
            "right": baseline_plan(node["right"]),
        }

    raise ValueError(f"Unsupported logical operator: {op}")


def run_plan(path):
    result = subprocess.run(
        [
            "exec",
            "run",
            "--db",
            DB,
            "--plan",
            str(path),
            "--frames",
            str(FRAMES),
            "--json",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Execution failed for {path}\n"
            f"{result.stderr}\n{result.stdout}"
        )

    data = json.loads(result.stdout)

    totals = data["totals"]

    reads = int(totals["page_reads"])
    writes = int(totals["page_writes"])

    return reads, writes, reads + writes


def load_optimized_io():
    path = RESULTS_DIR / "optimized_io.csv"

    result = {}

    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            query = row["query"]

            if "total_io" in row:
                value = int(float(row["total_io"]))
            elif "io" in row:
                value = int(float(row["io"]))
            else:
                reads = int(float(row.get("reads", 0)))
                writes = int(float(row.get("writes", 0)))
                value = reads + writes

            result[query] = value

    return result


optimized = load_optimized_io()

rows = []

for i in range(1, 21):
    q = f"q{i:02d}"

    print()
    print("=" * 60)
    print("BASELINE", q)
    print("=" * 60)

    logical_path = LOGICAL_DIR / f"{q}.json"

    with open(logical_path, encoding="utf-8") as f:
        logical = json.load(f)

    physical = baseline_plan(logical)

    baseline_path = BASELINE_DIR / f"{q}.json"

    with open(
        baseline_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(physical, f, indent=2)

    reads, writes, baseline_io = run_plan(
        baseline_path
    )

    optimized_io = optimized[q]

    ratio = (
        baseline_io / optimized_io
        if optimized_io > 0
        else None
    )

    rows.append({
        "query": q,
        "optimized_io": optimized_io,
        "baseline_reads": reads,
        "baseline_writes": writes,
        "baseline_io": baseline_io,
        "baseline_over_optimized": ratio,
    })

    print(
        f"{q}: optimized={optimized_io}, "
        f"baseline={baseline_io}, "
        f"ratio={ratio}"
    )


out_path = RESULTS_DIR / "optimization_payoff.csv"

with open(
    out_path,
    "w",
    newline="",
    encoding="utf-8",
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=[
            "query",
            "optimized_io",
            "baseline_reads",
            "baseline_writes",
            "baseline_io",
            "baseline_over_optimized",
        ],
    )

    writer.writeheader()
    writer.writerows(rows)


ratios = [
    row["baseline_over_optimized"]
    for row in rows
    if row["baseline_over_optimized"] is not None
]

print()
print("=" * 60)
print("PART 2 COMPLETE")
print("=" * 60)

print("Queries:", len(rows))
print(
    "Total optimized I/O:",
    sum(row["optimized_io"] for row in rows),
)
print(
    "Total baseline I/O:",
    sum(row["baseline_io"] for row in rows),
)
print("Smallest ratio:", min(ratios))
print("Largest ratio:", max(ratios))
print()
print("Created:")
print("  m4_results\\optimization_payoff.csv")
