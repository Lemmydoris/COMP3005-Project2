from pathlib import Path
import csv
import json
import subprocess

from optimizer.planner import plan_logical

DB = "m4_report_db"
FRAMES = 32

LOGICAL_DIR = Path("m4_logical")
RESULTS_DIR = Path("m4_results")
PLAN_DIR = Path("m4_ablation_fast")

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

# Already measured before stopping the slow script.
KNOWN_TOTALS = {
    1: 1806,
    2: 1828,
}


def load_optimized_io():
    result = {}

    with open(
        RESULTS_DIR / "optimized_io.csv",
        newline="",
        encoding="utf-8",
    ) as f:

        for row in csv.DictReader(f):
            q = row["query"]

            if "total_io" in row:
                io = int(float(row["total_io"]))
            elif "io" in row:
                io = int(float(row["io"]))
            else:
                io = (
                    int(float(row.get("reads", 0)))
                    + int(float(row.get("writes", 0)))
                )

            result[q] = io

    return result


def run_plan(plan, path):
    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(plan, f, indent=2)

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
            f"{result.stderr}\n"
            f"{result.stdout}"
        )

    data = json.loads(result.stdout)
    totals = data["totals"]

    return (
        int(totals["page_reads"])
        + int(totals["page_writes"])
    )


optimized_io = load_optimized_io()

optimized_total = sum(
    optimized_io.values()
)

summary = [
    {
        "rule": 1,
        "rule_name": RULE_NAMES[1],
        "all_rules_io": optimized_total,
        "disabled_rule_io": KNOWN_TOTALS[1],
        "difference": KNOWN_TOTALS[1] - optimized_total,
    },
    {
        "rule": 2,
        "rule_name": RULE_NAMES[2],
        "all_rules_io": optimized_total,
        "disabled_rule_io": KNOWN_TOTALS[2],
        "difference": KNOWN_TOTALS[2] - optimized_total,
    },
]


for rule in range(3, 8):

    print()
    print("=" * 65)
    print(
        f"RULE {rule}: {RULE_NAMES[rule]}"
    )
    print("=" * 65)

    rule_dir = PLAN_DIR / f"rule{rule}"
    rule_dir.mkdir(exist_ok=True)

    total_io = 0
    executed = 0
    reused = 0

    for i in range(1, 21):

        q = f"q{i:02d}"

        logical_path = (
            LOGICAL_DIR / f"{q}.json"
        )

        with open(
            logical_path,
            encoding="utf-8",
        ) as f:
            logical = json.load(f)

        normal_plan = plan_logical(
            DB,
            logical,
            frames=FRAMES,
        )

        disabled_plan = plan_logical(
            DB,
            logical,
            frames=FRAMES,
            disabled_rules={rule},
        )

        if disabled_plan == normal_plan:
            io = optimized_io[q]
            reused += 1

            print(
                f"Rule {rule} - {q}: "
                f"same plan -> reused I/O={io}"
            )

        else:
            plan_path = (
                rule_dir / f"{q}.json"
            )

            print(
                f"Rule {rule} - {q}: "
                f"plan changed -> executing...",
                flush=True,
            )

            io = run_plan(
                disabled_plan,
                plan_path,
            )

            executed += 1

            print(
                f"                 I/O={io}"
            )

        total_io += io

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
    print(
        f"Executed changed plans: {executed}"
    )
    print(
        f"Reused identical plans: {reused}"
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
    "All rules enabled:",
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
