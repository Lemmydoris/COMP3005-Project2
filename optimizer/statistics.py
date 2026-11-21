import math
import os

from execution.base import (
    END,
    Operator,
)
from execution.sort import Sort
from execution.temp_run import TempRun

from storage.buffer import BufferPool
from storage.catalog import Catalog
from storage.directory import (
    DirectoryPage,
    NO_NEXT_PAGE,
)
from storage.disk import DiskManager
from storage.heap import HeapFile
from storage.record import decode_record


# opt analyze has no --frames option in the Module 4
# command-line contract.
#
# ANALYZE therefore uses a small deterministic internal
# working-memory budget for Module 2 external sorts.
ANALYZE_SORT_FRAMES = 8


class _TempRunColumnSource(Operator):
    """
    Streaming child operator for Module 2 Sort.

    The base table is scanned exactly once and materialized
    into a TempRun. For each column, this operator streams
    only that column out of the materialized run.

    Therefore Sort receives a one-column relation and can use
    the existing external-memory implementation unchanged.
    """

    def __init__(
        self,
        run,
        column_index,
        column_schema,
    ):
        super().__init__()

        self.run = run
        self.column_index = column_index

        self.schema = [
            list(
                column_schema
            )
        ]

        self._rows = None

    def open(self):

        if self.is_open:
            raise RuntimeError(
                "_TempRunColumnSource "
                "is already open."
            )

        self._reset_counters()

        self._rows = iter(
            self.run.rows()
        )

        self.is_open = True

    def next(self):

        if not self.is_open:
            raise RuntimeError(
                "_TempRunColumnSource.next() "
                "called before open()."
            )

        try:

            row = next(
                self._rows
            )

        except StopIteration:

            return END

        value = row[
            self.column_index
        ]

        self._count_output()

        return (
            value,
        )

    def close(self):

        if not self.is_open:
            return

        self._rows = None
        self.is_open = False


def _count_data_pages(
    table_path,
):
    """
    Count data pages from the heap-file directory chain.

    Module 4's n_pages(T) excludes directory pages.
    """

    disk = DiskManager(
        table_path
    )

    directory_page_id = 0
    total = 0

    while True:

        raw = disk.read_page(
            directory_page_id
        )

        directory = (
            DirectoryPage.from_bytes(
                raw
            )
        )

        total += (
            directory.entry_count
        )

        next_page = (
            directory.next_dir_page
        )

        if (
            next_page
            == NO_NEXT_PAGE
        ):
            break

        directory_page_id = (
            next_page
        )

    return total


def _finalize_bucket(
    buckets,
    bucket_min,
    bucket_max,
    bucket_count,
    bucket_ndv,
):
    """
    Append one histogram bucket.
    """

    if bucket_count == 0:
        return

    buckets.append(
        {
            "min":
                bucket_min,
            "max":
                bucket_max,
            "count":
                bucket_count,
            "ndv":
                bucket_ndv,
        }
    )


def _column_statistics(
    run,
    table_name,
    column_index,
    column_definition,
    n_tuples,
    buckets,
    sort_frames,
    temp_dir,
):
    """
    Compute exact statistics for one column.

    The materialized base-table run is streamed through a
    one-column source and externally sorted by Module 2 Sort.

    Equal values are never split between histogram buckets.
    This makes bucket ranges non-overlapping and makes
    equality estimation deterministic.
    """

    column_name = (
        column_definition[0]
    )

    qualified_name = (
        f"{table_name}."
        f"{column_name}"
    )

    sort_schema = [
        qualified_name,
        *column_definition[1:],
    ]

    if n_tuples == 0:

        return {
            "ndv": 0,
            "min": None,
            "max": None,
            "hist": [],
        }

    effective_buckets = min(
        buckets,
        n_tuples,
    )

    child = _TempRunColumnSource(
        run,
        column_index,
        sort_schema,
    )

    sorter = Sort(
        child=child,
        keys=[
            [
                qualified_name,
                "asc",
            ]
        ],
        frames=sort_frames,
        temp_dir=temp_dir,
    )

    histogram = []

    global_min = None
    global_max = None
    global_ndv = 0

    previous_value = None
    have_previous = False

    bucket_min = None
    bucket_max = None
    bucket_count = 0
    bucket_ndv = 0
    bucket_last_value = None
    bucket_has_value = False

    rows_seen = 0

    # First desired boundary:
    #
    # ceil(1 * n / k)
    #
    # Subsequent boundaries are:
    #
    # ceil(2 * n / k), ...
    boundary_number = 1

    boundary = math.ceil(
        boundary_number
        * n_tuples
        / effective_buckets
    )

    sorter.open()

    try:

        while True:

            row = sorter.next()

            if row is END:
                break

            value = row[0]

            # ------------------------------------------
            # If the target boundary has already been
            # reached, close the previous bucket before
            # accepting a new distinct value.
            #
            # Equal values stay together.
            # ------------------------------------------

            if (
                bucket_count > 0
                and rows_seen >= boundary
                and boundary_number
                < effective_buckets
                and value != bucket_max
            ):

                _finalize_bucket(
                    histogram,
                    bucket_min,
                    bucket_max,
                    bucket_count,
                    bucket_ndv,
                )

                bucket_min = None
                bucket_max = None
                bucket_count = 0
                bucket_ndv = 0
                bucket_last_value = None
                bucket_has_value = False

                boundary_number += 1

                boundary = math.ceil(
                    boundary_number
                    * n_tuples
                    / effective_buckets
                )

            # ------------------------------------------
            # Global statistics
            # ------------------------------------------

            if global_min is None:
                global_min = value

            global_max = value

            if (
                not have_previous
                or value != previous_value
            ):

                global_ndv += 1

            previous_value = value
            have_previous = True

            # ------------------------------------------
            # Bucket statistics
            # ------------------------------------------

            if bucket_count == 0:
                bucket_min = value

            bucket_max = value
            bucket_count += 1

            if (
                not bucket_has_value
                or value != bucket_last_value
            ):

                bucket_ndv += 1

            bucket_last_value = value
            bucket_has_value = True

            rows_seen += 1

        _finalize_bucket(
            histogram,
            bucket_min,
            bucket_max,
            bucket_count,
            bucket_ndv,
        )

    finally:

        sorter.close()

    return {
        "ndv":
            global_ndv,
        "min":
            global_min,
        "max":
            global_max,
        "hist":
            histogram,
    }


def analyze_table(
    db_dir,
    table_name,
    buckets=20,
    sort_frames=ANALYZE_SORT_FRAMES,
):
    """
    Compute exact Module 4 statistics for one table and
    persist them in Module 1's catalog.

    Base-table records are scanned exactly once.

    The one scan computes:
        n_tuples
        total encoded record bytes

    and materializes decoded rows into a disk-backed TempRun.

    Each column is then externally sorted from that TempRun to
    compute:
        ndv
        min
        max
        equi-depth histogram
    """

    if buckets < 1:

        raise ValueError(
            "Histogram bucket count "
            "must be at least 1."
        )

    if sort_frames < 3:

        raise ValueError(
            "ANALYZE external sort "
            "requires at least 3 frames."
        )

    catalog = Catalog(
        db_dir,
        frames=max(
            2,
            sort_frames,
        ),
        policy="lru",
    )

    try:

        metadata = (
            catalog.get_table(
                table_name
            )
        )

    except KeyError as exc:

        raise ValueError(
            f"Unknown table: "
            f"{table_name}"
        ) from exc

    record_schema = [
        list(column)
        for column
        in metadata["schema"]
    ]

    table_path = os.path.join(
        str(db_dir),
        metadata["file"],
    )

    # n_pages(T) means DATA pages only.
    n_pages = _count_data_pages(
        table_path
    )

    # ----------------------------------------------------
    # One base-table scan.
    # ----------------------------------------------------

    disk = DiskManager(
        table_path
    )

    buffer = BufferPool(
        disk,
        frames=2,
        policy="lru",
    )

    heap = HeapFile(
        table_name,
        disk,
        buffer,
    )

    # The materialized relation uses the original table
    # schema. Column names do not affect record encoding.
    materialized = TempRun(
        record_schema,
        temp_dir=str(
            db_dir
        ),
    )

    n_tuples = 0
    total_record_bytes = 0

    try:

        for (
            _rid,
            raw_record,
        ) in heap.scan():

            n_tuples += 1

            total_record_bytes += (
                len(
                    raw_record
                )
            )

            values = decode_record(
                record_schema,
                raw_record,
            )

            materialized.append(
                tuple(
                    values
                )
            )

        materialized.finish()

        if n_tuples == 0:

            width = 0.0

        else:

            width = (
                total_record_bytes
                / n_tuples
            )

        # ------------------------------------------------
        # Exact column statistics.
        # ------------------------------------------------

        column_statistics = {}

        for (
            column_index,
            column_definition,
        ) in enumerate(
            record_schema
        ):

            column_name = (
                column_definition[0]
            )

            column_statistics[
                column_name
            ] = _column_statistics(
                run=materialized,
                table_name=table_name,
                column_index=column_index,
                column_definition=(
                    column_definition
                ),
                n_tuples=n_tuples,
                buckets=buckets,
                sort_frames=sort_frames,
                temp_dir=str(
                    db_dir
                ),
            )

        statistics = {
            "n_tuples":
                n_tuples,
            "n_pages":
                n_pages,
            "width":
                width,
            "columns":
                column_statistics,
        }

        catalog.update_statistics(
            table_name,
            statistics,
        )

        catalog.flush()

        return statistics

    finally:

        materialized.delete()