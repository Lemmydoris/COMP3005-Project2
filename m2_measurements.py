import csv
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

from execution.base import END
from execution.cli import plan_totals
from execution.plan import build_operator


ROOT = Path(__file__).resolve().parent
DB_DIR = ROOT / "m2_measurement_db"
OUT_DIR = ROOT / "m2_measurements"
TEMP_DIR = OUT_DIR / "temp"

PAGE_SIZE = 4096

# Long enough that exactly one tuple occupies each data page.
PAD_COLUMN_COUNT = 15
PAD = "x" * 255

PAD_SCHEMA = ",".join(
    f"pad{index}:VARCHAR(255)"
    for index in range(
        1,
        PAD_COLUMN_COUNT + 1,
    )
)

FRAMES = [4, 16, 64, 256]

# Required three relation sizes for cost-vs-formula.
JOIN_SIZES = [8, 32, 80]

# Extra sizes used for crossover.
ALL_SIZES = [4, 8, 16, 32, 64, 80]

JOIN_TYPES = [
    "nested_loop_join",
    "sort_merge_join",
    "hash_join",
]


def run_command(args):
    result = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "\nCOMMAND FAILED:\n"
            + " ".join(str(x) for x in args)
            + "\n\nSTDOUT:\n"
            + result.stdout
            + "\nSTDERR:\n"
            + result.stderr
        )

    return result.stdout.strip()


def storage(*args):
    return run_command(
        [
            sys.executable,
            "-m",
            "storage",
            *args,
        ]
    )


def write_csv(path, rows):
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not rows:
        return

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=list(
                rows[0].keys()
            ),
        )

        writer.writeheader()
        writer.writerows(rows)


def relation_pages(table_name):
    path = DB_DIR / f"{table_name}.db"

    total_pages = (
        path.stat().st_size
        // PAGE_SIZE
    )

    # Our test tables are well below the 681-entry
    # directory-page capacity, so page 0 is the only
    # directory page.
    data_pages = total_pages - 1

    return {
        "file_pages": total_pages,
        "data_pages": data_pages,
        "directory_pages": 1,
    }


def create_table(
    name,
    row_count,
    *,
    key_mode="matching",
    side="left",
):
    """
    Make a relation where each tuple is approximately
    one physical data page.

    key_mode:
        matching  -> unique matching keys on R/S
        uniform   -> unique matching keys
        skew      -> one key occurs in exactly 40%
                     of the tuples
    """

    csv_path = (
        DB_DIR
        / f"{name}.csv"
    )

    with csv_path.open(
        "w",
        encoding="ascii",
        newline="",
    ) as handle:

        skew_count = int(
            row_count * 0.40
        )

        for index in range(
            row_count
        ):

            row_id = index + 1

            if key_mode == "skew":

                if index < skew_count:
                    key = 1
                else:
                    key = (
                        index
                        - skew_count
                        + 2
                    )

            else:
                # Same keys on both relations so every
                # unique key has exactly one match.
                key = row_id

            pad_values = ",".join(
                [PAD] * PAD_COLUMN_COUNT
            )

            handle.write(
                f"{row_id},{key},{pad_values}\n"
            )      

    storage(
        "create-table",
        "--db",
        str(DB_DIR),
        "--name",
        name,
        "--schema",
        (
             "id:INT,key:INT,"
             + PAD_SCHEMA
        ),
    )

    storage(
        "load",
        "--db",
        str(DB_DIR),
        "--table",
        name,
        "--file",
        str(csv_path),
    )

    pages = relation_pages(
        name
    )

    if (
        pages["data_pages"]
        != row_count
    ):
        print(
            "WARNING:",
            name,
            "expected",
            row_count,
            "data pages but measured",
            pages["data_pages"],
        )


def prepare_database():
    if DB_DIR.exists():
        shutil.rmtree(
            DB_DIR
        )

    if OUT_DIR.exists():
        shutil.rmtree(
            OUT_DIR
        )

    DB_DIR.mkdir(
        parents=True
    )

    OUT_DIR.mkdir(
        parents=True
    )

    TEMP_DIR.mkdir(
        parents=True
    )

    print(
        "Creating measurement tables..."
    )

    for size in ALL_SIZES:

        print(
            f"  R{size}, S{size}"
        )

        create_table(
            f"R{size}",
            size,
            side="left",
        )

        create_table(
            f"S{size}",
            size,
            side="right",
        )

    # Separate 40-row uniform and skew datasets.
    print(
        "  Uniform40R, Uniform40S"
    )

    create_table(
        "Uniform40R",
        40,
        key_mode="uniform",
    )

    create_table(
        "Uniform40S",
        40,
        key_mode="uniform",
    )

    print(
        "  Skew40R, Skew40S"
    )

    create_table(
        "Skew40R",
        40,
        key_mode="skew",
    )

    create_table(
        "Skew40S",
        40,
        key_mode="skew",
    )


def plan_children(operator):
    result = []

    if (
        hasattr(operator, "left")
        and hasattr(operator, "right")
    ):
        result.append(
            operator.left
        )

        result.append(
            operator.right
        )

    elif hasattr(
        operator,
        "child",
    ):
        result.append(
            operator.child
        )

    return result


def collect_max_frames(operator):
    values = []

    if hasattr(
        operator,
        "max_frames_held",
    ):
        values.append(
            operator.max_frames_held
        )

    for child in plan_children(
        operator
    ):
        values.extend(
            collect_max_frames(
                child
            )
        )

    return values


def run_plan(
    plan,
    frames,
    *,
    capture_attributes=None,
):
    """
    Execute a physical plan directly through the same
    Module 2 operators used by exec.

    Attributes are captured before close(), because
    some operators reset measurement fields on close.
    """

    capture_attributes = (
        capture_attributes
        or []
    )

    TEMP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # There should never be leftovers from the previous
    # completed plan.
    for item in TEMP_DIR.iterdir():
        if item.is_file():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(
                item
            )

    root = build_operator(
        plan,
        db_dir=str(DB_DIR),
        frames=frames,
        temp_dir=str(TEMP_DIR),
    )

    output_rows = 0
    attributes = {}

    root.open()

    try:
        while True:

            row = root.next()

            if row is END:
                break

            output_rows += 1

        totals = plan_totals(
            root
        )

        for name in capture_attributes:

            attributes[name] = getattr(
                root,
                name,
                None,
            )

        frame_values = (
            collect_max_frames(
                root
            )
        )

        max_frames = (
            max(frame_values)
            if frame_values
            else None
        )

    finally:
        root.close()

    leftovers = [
        str(path)
        for path
        in TEMP_DIR.iterdir()
    ]

    return {
        "rows": output_rows,
        "totals": totals,
        "attributes": attributes,
        "max_frames": max_frames,
        "temp_files_after_close":
            len(leftovers),
        "temp_leftovers":
            leftovers,
    }


def join_plan(
    join_type,
    left_table,
    right_table,
):
    return {
        "op": join_type,
        "condition":
            f"{left_table}.key = "
            f"{right_table}.key",
        "left": {
            "op": "seqscan",
            "table": left_table,
        },
        "right": {
            "op": "seqscan",
            "table": right_table,
        },
    }


def sort_plan(
    table,
):
    return {
        "op": "sort",
        "keys": [
            [
                f"{table}.key",
                "asc",
            ]
        ],
        "child": {
            "op": "seqscan",
            "table": table,
        },
    }


def ceil_div(a, b):
    return (
        a + b - 1
    ) // b


def sort_pass_formula(
    pages,
    frames,
):
    if pages <= 0:
        return 0

    runs = ceil_div(
        pages,
        frames,
    )

    passes = 1

    while runs > 1:
        runs = ceil_div(
            runs,
            frames - 1,
        )

        passes += 1

    return passes


def sort_cost_formula(
    pages,
    frames,
):
    """
    Standard formula used by the project cost model:
        2*M*(passes-1) + M
    """

    passes = sort_pass_formula(
        pages,
        frames,
    )

    if passes == 0:
        return 0

    return (
        2
        * pages
        * (passes - 1)
        + pages
    )


def join_cost_formula(
    join_type,
    M,
    N,
    B,
):
    if (
        join_type
        == "nested_loop_join"
    ):
        return (
            M
            + ceil_div(
                M,
                B - 2,
            )
            * N
        )

    if join_type == "hash_join":
        return 3 * (
            M + N
        )

    if (
        join_type
        == "sort_merge_join"
    ):
        return (
            sort_cost_formula(
                M,
                B,
            )
            + sort_cost_formula(
                N,
                B,
            )
            + M
            + N
        )

    raise ValueError(
        join_type
    )


JOIN_CACHE = {}


def run_join(
    size,
    frames,
    join_type,
):
    key = (
        size,
        frames,
        join_type,
    )

    if key in JOIN_CACHE:
        return JOIN_CACHE[key]

    print(
        f"  {join_type:20} "
        f"size={size:3} "
        f"B={frames:3}"
    )

    result = run_plan(
        join_plan(
            join_type,
            f"R{size}",
            f"S{size}",
        ),
        frames,
        capture_attributes=[
            "max_frames_held",
            "outer_blocks",
            "passes",
            "partition_sizes",
            "overflow_fallbacks",
        ],
    )

    JOIN_CACHE[key] = result

    return result


def measurement_join_costs():
    print(
        "\n1. Join cost vs formula"
    )

    rows = []

    for size in JOIN_SIZES:

        left_pages = (
            relation_pages(
                f"R{size}"
            )
        )

        right_pages = (
            relation_pages(
                f"S{size}"
            )
        )

        M = left_pages[
            "data_pages"
        ]

        N = right_pages[
            "data_pages"
        ]

        for B in FRAMES:

            for join_type in JOIN_TYPES:

                result = run_join(
                    size,
                    B,
                    join_type,
                )

                totals = result[
                    "totals"
                ]

                measured = (
                    totals[
                        "page_reads"
                    ]
                    + totals[
                        "page_writes"
                    ]
                )

                formula = (
                    join_cost_formula(
                        join_type,
                        M,
                        N,
                        B,
                    )
                )

                rows.append(
                    {
                        "relation_size":
                            size,
                        "M_data_pages":
                            M,
                        "N_data_pages":
                            N,
                        "R_file_pages":
                            left_pages[
                                "file_pages"
                            ],
                        "S_file_pages":
                            right_pages[
                                "file_pages"
                            ],
                        "B": B,
                        "join":
                            join_type,
                        "measured_reads":
                            totals[
                                "page_reads"
                            ],
                        "measured_writes":
                            totals[
                                "page_writes"
                            ],
                        "measured_total_io":
                            measured,
                        "formula_io":
                            formula,
                        "gap":
                            measured
                            - formula,
                        "tuples_out":
                            totals[
                                "tuples_out"
                            ],
                        "comparisons":
                            totals[
                                "comparisons"
                            ],
                        "max_frames":
                            result[
                                "max_frames"
                            ],
                        "temp_files_after":
                            result[
                                "temp_files_after_close"
                            ],
                    }
                )

    write_csv(
        OUT_DIR
        / "join_costs.csv",
        rows,
    )


def measurement_sort_passes():
    print(
        "\n2. Sort passes"
    )

    combinations = [
        (8, 4),
        (16, 4),
        (32, 4),
        (32, 8),
        (64, 8),
        (80, 4),   # N = 20 * B
    ]

    rows = []

    for N, B in combinations:

        print(
            f"  sort N={N}, B={B}"
        )

        result = run_plan(
            sort_plan(
                f"R{N}"
            ),
            B,
            capture_attributes=[
                "passes",
                "max_frames_held",
            ],
        )

        totals = result[
            "totals"
        ]

        measured_passes = (
            result[
                "attributes"
            ][
                "passes"
            ]
        )

        formula_passes = (
            sort_pass_formula(
                N,
                B,
            )
        )

        rows.append(
            {
                "N_data_pages": N,
                "B": B,
                "measured_passes":
                    measured_passes,
                "formula_passes":
                    formula_passes,
                "pass_gap":
                    measured_passes
                    - formula_passes,
                "measured_reads":
                    totals[
                        "page_reads"
                    ],
                "measured_writes":
                    totals[
                        "page_writes"
                    ],
                "measured_total_io":
                    totals[
                        "page_reads"
                    ]
                    + totals[
                        "page_writes"
                    ],
                "max_frames_held":
                    result[
                        "attributes"
                    ][
                        "max_frames_held"
                    ],
                "temp_files_after":
                    result[
                        "temp_files_after_close"
                    ],
            }
        )

    write_csv(
        OUT_DIR
        / "sort_passes.csv",
        rows,
    )


def cheapest_join(records):
    minimum = min(
        row["measured_total_io"]
        for row in records
    )

    winners = [
        row["join"]
        for row in records
        if (
            row[
                "measured_total_io"
            ]
            == minimum
        )
    ]

    return (
        minimum,
        " + ".join(
            winners
        ),
    )


def write_simple_svg(
    path,
    records,
    *,
    x_field,
    x_label,
    title,
):
    """
    Dependency-free SVG line plot.
    """

    width = 900
    height = 560

    left = 85
    right = 35
    top = 55
    bottom = 75

    plot_width = (
        width
        - left
        - right
    )

    plot_height = (
        height
        - top
        - bottom
    )

    x_values = sorted(
        {
            row[x_field]
            for row in records
        }
    )

    y_values = [
        row[
            "measured_total_io"
        ]
        for row in records
    ]

    y_max = max(
        y_values
    )

    if y_max == 0:
        y_max = 1

    x_positions = {}

    if len(x_values) == 1:
        x_positions[
            x_values[0]
        ] = (
            left
            + plot_width / 2
        )

    else:
        for index, value in enumerate(
            x_values
        ):
            x_positions[value] = (
                left
                + plot_width
                * index
                / (
                    len(x_values)
                    - 1
                )
            )

    def y_position(value):
        return (
            top
            + plot_height
            - (
                value
                / y_max
                * plot_height
            )
        )

    dash_styles = {
        "nested_loop_join":
            "",
        "sort_merge_join":
            "10 5",
        "hash_join":
            "3 4",
    }

    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width / 2}" y="28" '
        'text-anchor="middle" '
        'font-family="Arial" '
        'font-size="20">'
        f'{title}</text>',
        f'<line x1="{left}" y1="{top}" '
        f'x2="{left}" y2="{top + plot_height}" '
        'stroke="black"/>',
        f'<line x1="{left}" '
        f'y1="{top + plot_height}" '
        f'x2="{left + plot_width}" '
        f'y2="{top + plot_height}" '
        'stroke="black"/>',
    ]

    # Y-axis grid/ticks.
    for tick in range(6):

        value = (
            y_max
            * tick
            / 5
        )

        y = y_position(
            value
        )

        lines.append(
            f'<line x1="{left - 5}" '
            f'y1="{y}" '
            f'x2="{left + plot_width}" '
            f'y2="{y}" '
            'stroke="black" '
            'stroke-opacity="0.15"/>'
        )

        lines.append(
            f'<text x="{left - 10}" '
            f'y="{y + 5}" '
            'text-anchor="end" '
            'font-family="Arial" '
            'font-size="12">'
            f'{value:.0f}</text>'
        )

    # X ticks.
    for value in x_values:

        x = x_positions[
            value
        ]

        lines.append(
            f'<line x1="{x}" '
            f'y1="{top + plot_height}" '
            f'x2="{x}" '
            f'y2="{top + plot_height + 6}" '
            'stroke="black"/>'
        )

        lines.append(
            f'<text x="{x}" '
            f'y="{top + plot_height + 24}" '
            'text-anchor="middle" '
            'font-family="Arial" '
            'font-size="12">'
            f'{value}</text>'
        )

    for join_type in JOIN_TYPES:

        series = sorted(
            [
                row
                for row in records
                if (
                    row["join"]
                    == join_type
                )
            ],
            key=lambda row:
                row[x_field],
        )

        points = " ".join(
            (
                f'{x_positions[row[x_field]]},'
                f'{y_position(row["measured_total_io"])}'
            )
            for row in series
        )

        dash = (
            dash_styles[
                join_type
            ]
        )

        dash_attribute = (
            (
                f' stroke-dasharray="{dash}"'
            )
            if dash
            else ""
        )

        lines.append(
            f'<polyline points="{points}" '
            'fill="none" '
            'stroke="black" '
            'stroke-width="2"'
            f'{dash_attribute}/>'
        )

    lines.extend(
        [
            f'<text x="{left + plot_width / 2}" '
            f'y="{height - 22}" '
            'text-anchor="middle" '
            'font-family="Arial" '
            'font-size="14">'
            f'{x_label}</text>',
            (
                '<text '
                f'x="20" y="{top + plot_height / 2}" '
                'text-anchor="middle" '
                'font-family="Arial" '
                'font-size="14" '
                f'transform="rotate(-90 20 '
                f'{top + plot_height / 2})">'
                'Measured page I/O'
                '</text>'
            ),
        ]
    )

    legend_y = 52

    for index, join_type in enumerate(
        JOIN_TYPES
    ):
        y = (
            legend_y
            + index * 22
        )

        dash = (
            dash_styles[
                join_type
            ]
        )

        dash_attribute = (
            (
                f' stroke-dasharray="{dash}"'
            )
            if dash
            else ""
        )

        lines.append(
            f'<line x1="{width - 240}" '
            f'y1="{y}" '
            f'x2="{width - 190}" '
            f'y2="{y}" '
            'stroke="black" '
            'stroke-width="2"'
            f'{dash_attribute}/>'
        )

        lines.append(
            f'<text x="{width - 180}" '
            f'y="{y + 5}" '
            'font-family="Arial" '
            'font-size="12">'
            f'{join_type}</text>'
        )

    lines.append(
        "</svg>"
    )

    path.write_text(
        "\n".join(
            lines
        ),
        encoding="utf-8",
    )


def measurement_crossover():
    print(
        "\n3. Crossover"
    )

    # Part A:
    # Fixed relations, vary B.
    fixed_size = 64

    varying_B = [
        4,
        8,
        16,
        32,
        64,
        128,
        256,
    ]

    rows_B = []

    for B in varying_B:

        group = []

        for join_type in JOIN_TYPES:

            result = run_join(
                fixed_size,
                B,
                join_type,
            )

            totals = result[
                "totals"
            ]

            row = {
                "relation_size":
                    fixed_size,
                "B": B,
                "join":
                    join_type,
                "measured_reads":
                    totals[
                        "page_reads"
                    ],
                "measured_writes":
                    totals[
                        "page_writes"
                    ],
                "measured_total_io":
                    totals[
                        "page_reads"
                    ]
                    + totals[
                        "page_writes"
                    ],
            }

            group.append(
                row
            )

            rows_B.append(
                row
            )

        minimum, winner = (
            cheapest_join(
                group
            )
        )

        for row in group:
            row[
                "cheapest_at_B"
            ] = winner

    write_csv(
        OUT_DIR
        / "crossover_vary_B.csv",
        rows_B,
    )

    write_simple_svg(
        OUT_DIR
        / "crossover_vary_B.svg",
        rows_B,
        x_field="B",
        x_label="Buffer frames B",
        title=(
            "Join Crossover: "
            "Fixed 64-page Relations"
        ),
    )

    # Part B:
    # Fixed B, vary relation size.
    fixed_B = 16

    rows_size = []

    for size in ALL_SIZES:

        group = []

        for join_type in JOIN_TYPES:

            result = run_join(
                size,
                fixed_B,
                join_type,
            )

            totals = result[
                "totals"
            ]

            row = {
                "relation_size":
                    size,
                "B": fixed_B,
                "join":
                    join_type,
                "measured_reads":
                    totals[
                        "page_reads"
                    ],
                "measured_writes":
                    totals[
                        "page_writes"
                    ],
                "measured_total_io":
                    totals[
                        "page_reads"
                    ]
                    + totals[
                        "page_writes"
                    ],
            }

            group.append(
                row
            )

            rows_size.append(
                row
            )

        minimum, winner = (
            cheapest_join(
                group
            )
        )

        for row in group:
            row[
                "cheapest_at_size"
            ] = winner

    write_csv(
        OUT_DIR
        / "crossover_vary_size.csv",
        rows_size,
    )

    write_simple_svg(
        OUT_DIR
        / "crossover_vary_size.svg",
        rows_size,
        x_field="relation_size",
        x_label=(
            "Pages in each relation"
        ),
        title=(
            "Join Crossover: "
            "Fixed B = 16"
        ),
    )


def measurement_skew():
    print(
        "\n4. Hash-join skew"
    )

    B = 16

    uniform_plan = join_plan(
        "hash_join",
        "Uniform40R",
        "Uniform40S",
    )

    skew_plan = join_plan(
        "hash_join",
        "Skew40R",
        "Skew40S",
    )

    uniform = run_plan(
        uniform_plan,
        B,
        capture_attributes=[
            "partition_count",
            "partition_sizes",
            "overflow_fallbacks",
            "max_frames_held",
        ],
    )

    skew = run_plan(
        skew_plan,
        B,
        capture_attributes=[
            "partition_count",
            "partition_sizes",
            "overflow_fallbacks",
            "max_frames_held",
        ],
    )

    result = {
        "B": B,
        "rows_per_side": 40,
        "skew_rows_per_side": 16,
        "skew_fraction": 0.40,
        "uniform": uniform,
        "skew": skew,
    }

    (
        OUT_DIR
        / "skew_results.json"
    ).write_text(
        json.dumps(
            result,
            indent=2,
        ),
        encoding="utf-8",
    )


def measurement_budget():
    print(
        "\n5. B=4 budget test"
    )

    # Required:
    # sort of 20 * B pages.
    B = 4
    N = 20 * B

    result = run_plan(
        sort_plan(
            f"R{N}"
        ),
        B,
        capture_attributes=[
            "passes",
            "max_frames_held",
        ],
    )

    totals = result[
        "totals"
    ]

    row = {
        "B": B,
        "N_data_pages": N,
        "N_equals_20_times_B":
            N == 20 * B,
        "completed":
            result["rows"] == N,
        "rows_out":
            result["rows"],
        "passes":
            result[
                "attributes"
            ][
                "passes"
            ],
        "max_frames_held":
            result[
                "attributes"
            ][
                "max_frames_held"
            ],
        "within_budget":
            (
                result[
                    "attributes"
                ][
                    "max_frames_held"
                ]
                <= B
            ),
        "page_reads":
            totals[
                "page_reads"
            ],
        "page_writes":
            totals[
                "page_writes"
            ],
        "total_io":
            (
                totals[
                    "page_reads"
                ]
                + totals[
                    "page_writes"
                ]
            ),
        "temp_files_after_close":
            result[
                "temp_files_after_close"
            ],
    }

    write_csv(
        OUT_DIR
        / "budget_test.csv",
        [row],
    )


def write_summary():
    files = sorted(
        path.name
        for path in OUT_DIR.iterdir()
        if path.is_file()
    )

    lines = [
        "COMP 3005 Module 2 measurement run complete.",
        "",
        "Generated files:",
    ]

    lines.extend(
        f"- {name}"
        for name in files
    )

    lines.extend(
        [
            "",
            "Important page-count convention:",
            (
                "The formula columns use DATA pages "
                "(directory page excluded)."
            ),
            (
                "Measured executor counters are left "
                "unchanged and therefore include actual "
                "DiskManager calls made by the implementation."
            ),
            (
                "Any difference is intentional evidence "
                "to explain in REPORT_M2.md."
            ),
        ]
    )

    (
        OUT_DIR
        / "README.txt"
    ).write_text(
        "\n".join(
            lines
        ),
        encoding="utf-8",
    )


def main():
    prepare_database()

    measurement_join_costs()
    measurement_sort_passes()
    measurement_crossover()
    measurement_skew()
    measurement_budget()

    write_summary()

    print(
        "\n===================================="
    )

    print(
        "MEASUREMENTS COMPLETE"
    )

    print(
        "===================================="
    )

    print(
        f"Results: {OUT_DIR}"
    )

    print(
        "\nGenerated:"
    )

    for path in sorted(
        OUT_DIR.iterdir()
    ):

        if path.is_file():
            print(
                " ",
                path.name,
            )


if __name__ == "__main__":
    main()