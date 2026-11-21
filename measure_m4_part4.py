from pathlib import Path
import csv
import json
import shutil
import subprocess
import copy

from optimizer.planner import plan_logical

DB = "m4_break_db"
FRAMES = 32

db_path = Path(DB)

if db_path.exists():
    shutil.rmtree(db_path)


def run(cmd):
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "\nCOMMAND FAILED:\n"
            + " ".join(cmd)
            + "\n\n"
            + result.stderr
            + "\n"
            + result.stdout
        )

    return result.stdout


# ------------------------------------------------------------
# 1. Generate correlated data
# ------------------------------------------------------------

customer_pad = ["C" * 255] * 7
probe_pad = ["P" * 255] * 7

with open(
    "corr_customers.csv",
    "w",
    newline="",
    encoding="utf-8",
) as f:

    writer = csv.writer(f)

    for i in range(1, 5001):

        region = ((i - 1) % 10) + 1

        # Perfect correlation
        segment = region

        writer.writerow([
            i,
            region,
            segment,
            *customer_pad,
        ])


with open(
    "corr_probe.csv",
    "w",
    newline="",
    encoding="utf-8",
) as f:

    writer = csv.writer(f)

    for i in range(1, 501):

        writer.writerow([
            i,
            *probe_pad,
        ])


# ------------------------------------------------------------
# 2. Build separate database
# ------------------------------------------------------------

run([
    "storage",
    "create-table",
    "--db", DB,
    "--name", "CorrCustomers",
    "--schema",
    (
        "id:INT,region:INT,segment:INT,"
        "p1:VARCHAR(255),p2:VARCHAR(255),"
        "p3:VARCHAR(255),p4:VARCHAR(255),"
        "p5:VARCHAR(255),p6:VARCHAR(255),"
        "p7:VARCHAR(255)"
    ),
])

run([
    "storage",
    "create-table",
    "--db", DB,
    "--name", "CorrProbe",
    "--schema",
    (
        "id:INT,"
        "p1:VARCHAR(255),p2:VARCHAR(255),"
        "p3:VARCHAR(255),p4:VARCHAR(255),"
        "p5:VARCHAR(255),p6:VARCHAR(255),"
        "p7:VARCHAR(255)"
    ),
])

run([
    "storage",
    "load",
    "--db", DB,
    "--table", "CorrCustomers",
    "--file", "corr_customers.csv",
])

run([
    "storage",
    "load",
    "--db", DB,
    "--table", "CorrProbe",
    "--file", "corr_probe.csv",
])

run([
    "opt",
    "analyze",
    "--db", DB,
    "--table", "CorrCustomers",
])

run([
    "opt",
    "analyze",
    "--db", DB,
    "--table", "CorrProbe",
])


# ------------------------------------------------------------
# 3. Correlation filter check
# ------------------------------------------------------------

filter_logical = {
    "op": "project",
    "columns": ["c.id"],
    "child": {
        "op": "select",
        "condition":
            "c.region = 1 AND c.segment = 1",
        "child": {
            "op": "rename",
            "to": "c",
            "child": {
                "op": "scan",
                "table": "CorrCustomers",
            },
        },
    },
}

filter_plan = plan_logical(
    DB,
    filter_logical,
    frames=FRAMES,
)

with open(
    "m4_break_filter.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(filter_plan, f, indent=2)


# ------------------------------------------------------------
# 4. Main logical query
# ------------------------------------------------------------

output_columns = ["c.id"]

for i in range(1, 8):
    output_columns.append(f"c.p{i}")

for i in range(1, 8):
    output_columns.append(f"p.p{i}")


logical = {
    "op": "project",
    "columns": output_columns,
    "child": {
        "op": "select",
        "condition":
            "c.region = 1 AND c.segment = 1",
        "child": {
            "op": "join",
            "condition":
                "c.id = p.id",
            "left": {
                "op": "rename",
                "to": "c",
                "child": {
                    "op": "scan",
                    "table": "CorrCustomers",
                },
            },
            "right": {
                "op": "rename",
                "to": "p",
                "child": {
                    "op": "scan",
                    "table": "CorrProbe",
                },
            },
        },
    },
}


with open(
    "m4_break_logical.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(logical, f, indent=2)


# ------------------------------------------------------------
# 5. Optimizer chosen plan
# ------------------------------------------------------------

chosen = plan_logical(
    DB,
    logical,
    frames=FRAMES,
)

with open(
    "m4_break_chosen.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(chosen, f, indent=2)


# ------------------------------------------------------------
# 6. Equivalent hash-join alternative
# ------------------------------------------------------------

better = copy.deepcopy(chosen)


def replace_first_nlj(node):

    if not isinstance(node, dict):
        return False

    if node.get("op") == "nested_loop_join":
        node["op"] = "hash_join"
        return True

    for key in ("child", "left", "right"):

        if key in node:
            if replace_first_nlj(node[key]):
                return True

    return False


changed = replace_first_nlj(better)

with open(
    "m4_break_hash.json",
    "w",
    encoding="utf-8",
) as f:
    json.dump(better, f, indent=2)


# ------------------------------------------------------------
# 7. Execute plans
# ------------------------------------------------------------

def execute(plan_path):

    output = run([
        "exec",
        "run",
        "--db", DB,
        "--plan", plan_path,
        "--frames", str(FRAMES),
        "--json",
    ])

    data = json.loads(output)

    totals = data["totals"]

    reads = int(totals["page_reads"])
    writes = int(totals["page_writes"])
    rows = int(totals["tuples_out"])

    return (
        reads,
        writes,
        reads + writes,
        rows,
    )


_, _, _, filter_rows = execute(
    "m4_break_filter.json"
)

chosen_reads, chosen_writes, chosen_io, chosen_rows = (
    execute("m4_break_chosen.json")
)

hash_reads, hash_writes, hash_io, hash_rows = (
    execute("m4_break_hash.json")
)


# ------------------------------------------------------------
# 8. Report-ready output
# ------------------------------------------------------------

print()
print("=" * 65)
print("PART 4 — WHERE THE OPTIMIZER BREAKS")
print("=" * 65)

print()
print("Correlated columns:")
print("  CorrCustomers.region")
print("  CorrCustomers.segment")

print()
print("Data relationship:")
print("  segment = region for every row")

print()
print("Rows in CorrCustomers:")
print("  5000")

print()
print("Single predicate selectivity:")
print("  region = 1  -> 0.10")
print("  segment = 1 -> 0.10")

print()
print("Independence estimate:")
print("  5000 * 0.10 * 0.10 = 50 rows")

print()
print("Actual filtered rows:")
print(f"  {filter_rows}")

print()
print("Q-error:")
print(f"  {filter_rows} / 50 = {filter_rows / 50}")

print()
print("Optimizer chose nested-loop:")
print(f"  {changed}")

print()
print("Chosen plan actual:")
print(
    f"  reads={chosen_reads}, "
    f"writes={chosen_writes}, "
    f"I/O={chosen_io}, "
    f"rows={chosen_rows}"
)

print()
print("Hash alternative actual:")
print(
    f"  reads={hash_reads}, "
    f"writes={hash_writes}, "
    f"I/O={hash_io}, "
    f"rows={hash_rows}"
)

print()

if changed and hash_io < chosen_io:

    print(
        "RESULT: the correlation error caused "
        "the optimizer to choose the worse plan."
    )

    print(
        f"Hash join saves "
        f"{chosen_io - hash_io} page I/Os."
    )

elif not changed:

    print(
        "RESULT: optimizer did not choose "
        "nested-loop join."
    )

else:

    print(
        "RESULT: nested-loop was not worse "
        "on this configuration."
    )

print()
print("Failed assumption:")
print(
    "  region and segment were treated "
    "as statistically independent."
)

print()
print("Statistic that would prevent the error:")
print(
    "  a multi-column/joint statistic for "
    "(region, segment)"
)
