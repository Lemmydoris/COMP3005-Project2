import csv
import json
import re
import statistics
import subprocess
from pathlib import Path

DB = "m4_report_db"
LOGICAL_DIR = Path("m4_logical")
RESULTS = Path("m4_results")
PLANS = RESULTS / "plans"

RESULTS.mkdir(exist_ok=True)
PLANS.mkdir(exist_ok=True)

EXPLAIN_RE = re.compile(
    r"^(?P<indent>\s*)(?P<label>.*?)\s+"
    r"est_rows=(?P<rows>[-+0-9.eE]+)\s+"
    r"est_cost=(?P<cost>[-+0-9.eE]+)\s*$"
)

TRACE_RE = re.compile(
    r"^(?P<indent>\s*)(?P<label>.*?)\s+"
    r"tuples_out=(?P<rows>\d+)\s+"
    r"comparisons=(?P<comparisons>\d+)\s+"
    r"reads=(?P<reads>\d+)\s+"
    r"writes=(?P<writes>\d+)\s*$"
)

def run_command(args):
    result = subprocess.run(
        args,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "COMMAND FAILED:\n"
            + " ".join(args)
            + "\n\nSTDOUT:\n"
            + result.stdout
            + "\nSTDERR:\n"
            + result.stderr
        )

    return result.stdout


def parse_explain(text):
    rows = []

    for line in text.splitlines():
        m = EXPLAIN_RE.match(line)

        if not m:
            continue

        rows.append({
            "depth": len(m.group("indent")) // 2,
            "label": m.group("label").strip(),
            "estimated_rows": float(m.group("rows")),
            "estimated_cost": float(m.group("cost")),
        })

    return rows


def parse_trace(text):
    rows = []

    for line in text.splitlines():
        m = TRACE_RE.match(line)

        if not m:
            continue

        rows.append({
            "depth": len(m.group("indent")) // 2,
            "label": m.group("label").strip(),
            "actual_rows": int(m.group("rows")),
            "comparisons": int(m.group("comparisons")),
            "reads": int(m.group("reads")),
            "writes": int(m.group("writes")),
        })

    return rows


def q_error(estimated, actual):
    estimated = float(estimated)
    actual = float(actual)

    if estimated == 0 and actual == 0:
        return 1.0

    if estimated == 0 or actual == 0:
        return max(1.0, estimated, actual)

    return max(estimated, actual) / min(estimated, actual)


all_nodes = []
io_rows = []
all_qerrors = []

for number in range(1, 21):

    q = f"q{number:02d}"
    logical = LOGICAL_DIR / f"{q}.json"
    physical = PLANS / f"{q}.json"

    print()
    print("=" * 60)
    print(f"RUNNING {q}")
    print("=" * 60)

    # --------------------------------------------------------
    # Produce physical JSON.
    # --------------------------------------------------------

    plan_text = run_command([
        "opt", "plan",
        "--db", DB,
        "--logical", str(logical),
        "--frames", "32",
        "--json",
    ])

    # Validate before saving.
    plan_json = json.loads(plan_text)

    physical.write_text(
        json.dumps(plan_json, indent=2),
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Estimated rows.
    # --------------------------------------------------------

    explain_text = run_command([
        "opt", "explain",
        "--db", DB,
        "--logical", str(logical),
        "--frames", "32",
    ])

    estimated = parse_explain(explain_text)

    # --------------------------------------------------------
    # Actual rows + actual I/O.
    # This executes the physical plan ONCE.
    # --------------------------------------------------------

    trace_text = run_command([
        "exec", "trace",
        "--db", DB,
        "--plan", str(physical),
        "--frames", "32",
    ])

    (RESULTS / f"{q}_trace.txt").write_text(
        trace_text,
        encoding="utf-8",
    )

    actual = parse_trace(trace_text)

    if len(estimated) != len(actual):
        print(
            f"WARNING: node-count mismatch for {q}: "
            f"estimated={len(estimated)}, actual={len(actual)}"
        )

    count = min(
        len(estimated),
        len(actual),
    )

    query_qerrors = []

    for index in range(count):

        e = estimated[index]
        a = actual[index]

        qe = q_error(
            e["estimated_rows"],
            a["actual_rows"],
        )

        query_qerrors.append(qe)
        all_qerrors.append(qe)

        all_nodes.append({
            "query": q,
            "node": index + 1,
            "depth": a["depth"],
            "operator": a["label"],
            "estimated_rows": e["estimated_rows"],
            "actual_rows": a["actual_rows"],
            "q_error": qe,
            "reads": a["reads"],
            "writes": a["writes"],
        })

    total_reads = sum(
        row["reads"]
        for row in actual
    )

    total_writes = sum(
        row["writes"]
        for row in actual
    )

    total_io = (
        total_reads
        + total_writes
    )

    io_rows.append({
        "query": q,
        "reads": total_reads,
        "writes": total_writes,
        "total_io": total_io,
    })

    print(
        f"{q}: "
        f"nodes={count}, "
        f"I/O={total_io}, "
        f"worst q-error="
        f"{max(query_qerrors) if query_qerrors else 'N/A'}"
    )


# ============================================================
# WRITE ESTIMATION TABLE
# ============================================================

with open(
    RESULTS / "estimation_nodes.csv",
    "w",
    newline="",
    encoding="utf-8",
) as f:

    fields = [
        "query",
        "node",
        "depth",
        "operator",
        "estimated_rows",
        "actual_rows",
        "q_error",
        "reads",
        "writes",
    ]

    writer = csv.DictWriter(
        f,
        fieldnames=fields,
    )

    writer.writeheader()
    writer.writerows(all_nodes)


# ============================================================
# WRITE OPTIMIZED I/O TABLE
# ============================================================

with open(
    RESULTS / "optimized_io.csv",
    "w",
    newline="",
    encoding="utf-8",
) as f:

    fields = [
        "query",
        "reads",
        "writes",
        "total_io",
    ]

    writer = csv.DictWriter(
        f,
        fieldnames=fields,
    )

    writer.writeheader()
    writer.writerows(io_rows)


# ============================================================
# SUMMARY
# ============================================================

if all_qerrors:

    median_q = statistics.median(
        all_qerrors
    )

    worst_node = max(
        all_nodes,
        key=lambda row: row["q_error"],
    )

    worst_q = worst_node["q_error"]

else:
    median_q = None
    worst_q = None
    worst_node = None


summary = {
    "queries_completed": len(io_rows),
    "nodes_measured": len(all_nodes),
    "median_q_error": median_q,
    "worst_q_error": worst_q,
    "worst_node": worst_node,
    "optimized_total_io": sum(
        row["total_io"]
        for row in io_rows
    ),
}


(RESULTS / "part1_summary.json").write_text(
    json.dumps(
        summary,
        indent=2,
    ),
    encoding="utf-8",
)


print()
print("=" * 60)
print("PART 1 COMPLETE")
print("=" * 60)
print("Queries completed:", summary["queries_completed"])
print("Nodes measured:", summary["nodes_measured"])
print("Median q-error:", summary["median_q_error"])
print("Worst q-error:", summary["worst_q_error"])

if worst_node:
    print(
        "Worst node:",
        worst_node["query"],
        "-",
        worst_node["operator"],
    )

print(
    "Total optimized I/O:",
    summary["optimized_total_io"],
)

print()
print("Files created:")
print("  m4_results\\estimation_nodes.csv")
print("  m4_results\\optimized_io.csv")
print("  m4_results\\part1_summary.json")
