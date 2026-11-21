from pathlib import Path
import csv
import json
import subprocess

from optimizer.planner import plan_logical

DB = "m4_report_db"
FRAMES = 32

LOGICAL_DIR = Path("m4_logical")
RESULTS_DIR = Path("m4_results")
PLAN_DIR = Path("m4_ablation_plans")

RESULTS_DIR.mkdir(exist_ok=True)
PLAN_DIR.mkdir(exist_ok=True)

RULE_NAMES = {
    1: "split conjunctions",
    2: "selection pushdown",
    3: "cross/select to join",
    4: "push through rename/union",
    5: "push below group_by",
    6: "projection pushdown",
    7: "cleanup",
}


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
            f"Execution failed:\n{result.stderr}\n{result.stdout}"
        )

    data = json.loads(result.stdout)
    totals = data["totals"]

    reads = int(totals["page_reads"])
    writes = int(totals["page_writes"])

    return reads + writes


# All-rules total from Part 1
optimized_total = 0

with open(
    RESULTS_DIR / "optimized_io.csv",
    newline="",
    encoding="utf-8",
) as f:
    for row in csv.DictReader(f):
        if "total_io" in row:
            optimized_total += int(float(row["total_io"]))
        elif "io" in row:
            optimized_total += int(float(row["io"]))
        else:
            optimized_total += (
                int(float(row.get("reads", 0)))
                + int(float(row.get("writes", 0)))
            )


summary = []

for rule in range(1, 8):

    print()
    print("=" * 65)
    print(
        f"DISABLING RULE {rule}: "
        f"{RULE_NAMES[rule]}"
    )
    print("=" * 65)

    rule_dir = PLAN_DIR / f"rule{rule}"
    rule_dir.mkdir(exist_ok=True)

    total_io = 0

    for i in range(1, 21):

        q = f"q{i:02d}"

        print(
            f"Rule {rule} - {q}",
            end=" ... ",
            flush=True,
        )

        logical_path = (
            LOGICAL_DIR / f"{q}.json"
        )

        with open(
            logical_path,
            encoding="utf-8",
        ) as f:
            logical = json.load(f)

        physical = plan_logical(
            DB,
            logical,
            frames=FRAMES,
            disabled_rules={rule},
        )

        plan_path = (
            rule_dir / f"{q}.json"
        )

        with open(
            plan_path,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                physical,
                f,
                indent=2,
            )

        io = run_plan(plan_path)

        total_io += io

        print(f"I/O={io}")

    difference = (
        total_io - optimized_total
    )

    summary.append({
        "rule": rule,
        "rule_name": RULE_NAMES[rule],
        "all_rules_io": optimized_total,
        "disabled_rule_io": total_io,
        "difference": difference,
    })

    print()
    print(
        f"RULE {rule} TOTAL = {total_io}"
    )


out_path = (
    RESULTS_DIR / "rewrite_ablation.csv"
)

with open(
    out_path,
    "w",
    newline="",
    encoding="utf-8",
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=[
            "rule",
            "rule_name",
            "all_rules_io",
            "disabled_rule_io",
            "difference",
        ],
    )

    writer.writeheader()
    writer.writerows(summary)


print()
print("=" * 65)
print("PART 3 COMPLETE")
print("=" * 65)
print(
    "All rules enabled total I/O:",
    optimized_total,
)

for row in summary:
    print(
        f"Rule {row['rule']}: "
        f"{row['disabled_rule_io']} "
        f"(difference "
        f"{row['difference']:+d})"
    )

print()
print("Created:")
print("  m4_results\\rewrite_ablation.csv")
