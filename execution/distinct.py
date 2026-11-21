import hashlib

from execution.base import END, Operator, validate_schema
from execution.sort import Sort
from execution.temp_run import TempRun
from storage.record import encode_record

PAGE_BYTES = 4088
SLOT_BYTES = 4


class Distinct(Operator):
    """
    Module 2 duplicate-removal operator.

    mode="sort":
        External sort followed by adjacent duplicate removal.

    mode="hash":
        Deterministic disk partitioning followed by
        partition-at-a-time duplicate removal.

        If a partition's unique tuples exceed the available
        in-memory budget, that partition is recursively
        repartitioned with a different hash seed.
    """

    def __init__(
        self,
        child,
        mode,
        frames,
        temp_dir=None,
    ):
        super().__init__()

        self.child = child
        self.mode = mode
        self.frames = frames
        self.temp_dir = temp_dir

        # Sort mode state.
        self._sort = None
        self._previous = None
        self._have_previous = False

        self._last_sort_comparisons = 0
        self._last_sort_reads = 0
        self._last_sort_writes = 0

        # Hash mode state.
        self._partition_queue = []
        self._current_unique_rows = None
        self._current_unique_position = 0

        self._exhausted = False

        # Measurement/debugging information.
        self.partition_count = 0
        self.repartition_count = 0
        self.max_hash_frames_held = 0

    # Shared helpers
    def _temp_read(self):
        self._count_read()

    def _temp_write(self):
        self._count_write()

    def _make_run(self):
        return TempRun(
            self.schema,
            temp_dir=self.temp_dir,
            read_callback=self._temp_read,
            write_callback=self._temp_write,
        )

    def _stable_hash(self, row, depth):
        """
        Python's built-in hash() is randomized between processes,
        so use a stable hash to keep counters/results deterministic.
        """

        raw = encode_record(
            self.schema,
            row,
        )

        seed = depth.to_bytes(
            4,
            byteorder="little",
            signed=False,
        )

        digest = hashlib.blake2b(
            seed + raw,
            digest_size=8,
        ).digest()

        return int.from_bytes(
            digest,
            byteorder="little",
            signed=False,
        )

    def _row_memory_bytes(self, row):
        """
        Conceptual slotted-page footprint of one tuple.
        """

        return (
            len(
                encode_record(
                    self.schema,
                    row,
                )
            )
            + SLOT_BYTES
        )

    # Sort mode
    def _sync_sort_counters(self):
        if self._sort is None:
            return

        counters = self._sort.counters()

        comparisons = counters[
            "comparisons"
        ]

        reads = counters[
            "page_reads"
        ]

        writes = counters[
            "page_writes"
        ]

        self._count_comparison(
            comparisons
            - self._last_sort_comparisons
        )

        self._count_read(
            reads
            - self._last_sort_reads
        )

        self._count_write(
            writes
            - self._last_sort_writes
        )

        self._last_sort_comparisons = (
            comparisons
        )

        self._last_sort_reads = reads
        self._last_sort_writes = writes

    def _open_sort_mode(self):
        # Obtain schema first.
        self.child.open()

        try:
            self.schema = [
                list(column)
                for column
                in self.child.schema
            ]

            validate_schema(
                self.schema
            )

        finally:
            self.child.close()

        if not self.schema:
            raise ValueError(
                "Distinct requires at least one column."
            )

        sort_keys = [
            [column[0], "asc"]
            for column in self.schema
        ]

        self._sort = Sort(
            self.child,
            sort_keys,
            frames=self.frames,
            temp_dir=self.temp_dir,
        )

        self._sort.open()

        self._sync_sort_counters()

    def _next_sort(self):
        while True:
            row = self._sort.next()

            self._sync_sort_counters()

            if row is END:
                self._exhausted = True
                return END

            if (
                not self._have_previous
                or row != self._previous
            ):
                self._previous = row
                self._have_previous = True

                self._count_output()

                return row

    # Hash mode
    def _partition_source(
        self,
        source_rows,
        depth,
    ):
        """
        Partition a streaming input into B-1 temporary runs.

        Conceptual memory:
            B-1 output pages
            1 input page

        Total: B frames.
        """

        partition_total = (
            self.frames - 1
        )

        partitions = [
            self._make_run()
            for _ in range(
                partition_total
            )
        ]

        self.max_hash_frames_held = max(
            self.max_hash_frames_held,
            self.frames,
        )

        try:
            for row in source_rows:
                partition_no = (
                    self._stable_hash(
                        row,
                        depth,
                    )
                    % partition_total
                )

                partitions[
                    partition_no
                ].append(row)

            for partition in partitions:
                partition.finish()

        except Exception:
            for partition in partitions:
                partition.delete()
            raise

        self.partition_count += len(
            partitions
        )

        return partitions

    def _open_hash_mode(self):
        if self.frames < 4:
            raise ValueError(
                "Hash distinct requires "
                "at least 4 frames."
            )

        self.child.open()

        try:
            self.schema = [
                list(column)
                for column
                in self.child.schema
            ]

            validate_schema(
                self.schema
            )

            if not self.schema:
                raise ValueError(
                    "Distinct requires "
                    "at least one column."
                )

            partitions = (
                self._partition_source(
                    self._child_rows(),
                    depth=0,
                )
            )

        finally:
            self.child.close()

        self._partition_queue = [
            (partition, 1)
            for partition in partitions
        ]

    def _child_rows(self):
        while True:
            row = self.child.next()

            if row is END:
                return

            yield row

    def _partition_unique_rows(
        self,
        run,
        depth,
    ):
        """
        Try to deduplicate one partition in memory.

        While reading one partition page, at most B-1
        page-equivalents may be occupied by the unique set.

        If that budget would be exceeded, return None so
        the entire partition can be repartitioned.
        """

        memory_budget = (
            self.frames - 1
        ) * PAGE_BYTES

        memory_used = 0
        seen = set()
        unique_rows = []

        self.max_hash_frames_held = max(
            self.max_hash_frames_held,
            self.frames,
        )

        for row in run.rows():
            # One logical membership probe.
            self._count_comparison()

            if row in seen:
                continue

            required = self._row_memory_bytes(
                row
            )

            if (
                memory_used + required
                > memory_budget
            ):
                return None

            seen.add(row)
            unique_rows.append(row)

            memory_used += required

        return unique_rows

    def _repartition_run(
        self,
        run,
        depth,
    ):
        """
        Repartition one overflowing partition using a
        different deterministic hash seed.
        """

        partitions = self._partition_source(
            run.rows(),
            depth=depth,
        )

        run.delete()

        self.repartition_count += 1

        # Process these before later partitions.
        new_items = [
            (partition, depth + 1)
            for partition in partitions
        ]

        self._partition_queue = (
            new_items
            + self._partition_queue
        )

    def _prepare_next_hash_partition(self):
        while self._partition_queue:

            run, depth = (
                self._partition_queue.pop(0)
            )

            unique_rows = (
                self._partition_unique_rows(
                    run,
                    depth,
                )
            )

            if unique_rows is None:
                # No tuples from this partition have been emitted yet, so it is safe to rescan and repartition the whole thing.
                self._repartition_run(
                    run,
                    depth,
                )
                continue

            run.delete()

            self._current_unique_rows = (
                unique_rows
            )

            self._current_unique_position = 0

            return True

        return False

    def _next_hash(self):
        while True:

            if (
                self._current_unique_rows
                is not None
                and
                self._current_unique_position
                < len(
                    self._current_unique_rows
                )
            ):
                row = self._current_unique_rows[
                    self._current_unique_position
                ]

                self._current_unique_position += 1

                self._count_output()

                return row

            self._current_unique_rows = None
            self._current_unique_position = 0

            if not self._prepare_next_hash_partition():
                self._exhausted = True
                return END

    # Operator interface
    def open(self):
        if self.is_open:
            raise RuntimeError(
                "Distinct is already open."
            )

        if self.mode not in (
            "sort",
            "hash",
        ):
            raise ValueError(
                f"Invalid distinct mode: "
                f"{self.mode}"
            )

        self._reset_counters()

        self._previous = None
        self._have_previous = False
        self._exhausted = False

        self._last_sort_comparisons = 0
        self._last_sort_reads = 0
        self._last_sort_writes = 0

        self._partition_queue = []
        self._current_unique_rows = None
        self._current_unique_position = 0

        self.partition_count = 0
        self.repartition_count = 0
        self.max_hash_frames_held = 0

        if self.mode == "sort":
            self._open_sort_mode()

        else:
            self._open_hash_mode()

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "Distinct.next() called before open()."
            )

        if self._exhausted:
            return END

        if self.mode == "sort":
            return self._next_sort()

        return self._next_hash()

    def close(self):
        if not self.is_open:
            return

        if self._sort is not None:
            self._sort.close()
            self._sync_sort_counters()

        self._sort = None

        for run, _ in self._partition_queue:
            run.delete()

        self._partition_queue = []

        self._current_unique_rows = None

        self.child.close()

        self.is_open = False