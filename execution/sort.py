import heapq
from functools import cmp_to_key
from execution.base import (
    END,
    Operator,
    column_index,
    validate_schema,
)
from execution.conditions import resolve_column_name
from execution.temp_run import TempRun
from storage.record import encode_record


PAGE_SIZE = 4096
PAGE_HEADER_SIZE = 8
SLOT_SIZE = 4
USABLE_PAGE_BYTES = (
    PAGE_SIZE - PAGE_HEADER_SIZE
)

class _HeapItem:
    """
    Item used by heapq during k-way merge.
    """

    def __init__(
        self,
        row,
        reader_index,
        sequence,
        owner,
    ):
        self.row = row
        self.reader_index = reader_index
        self.sequence = sequence
        self.owner = owner

    def __lt__(self, other):
        result = self.owner._compare_rows(
            self.row,
            other.row,
        )

        if result != 0:
            return result < 0

        # Deterministic tie breaking.
        if self.reader_index != other.reader_index:
            return (
                self.reader_index
                < other.reader_index
            )

        return self.sequence < other.sequence


class Sort(Operator):
    """
    External merge-sort operator.

    Run generation:
        at most B page-equivalents in memory.

    Merge:
        at most B-1 input runs plus one output page.

    The final merge is streamed through next().
    """

    def __init__(
        self,
        child,
        keys,
        frames,
        temp_dir=None,
    ):
        super().__init__()

        self.child = child
        self.keys = [
            list(key)
            for key in keys
        ]

        self.frames = frames
        self.temp_dir = temp_dir

        self._key_info = []

        self._memory_rows = None
        self._memory_position = 0

        self._runs = []

        self._final_readers = []
        self._heap = []
        self._sequence = 0
        self._merge_initialized = False

        self._exhausted = False

        # Useful for required Module 2 measurements.
        self.passes = 0
        self.max_frames_held = 0

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

    def _prepare_keys(self):
        if not self.keys:
            raise ValueError(
                "Sort requires at least one key."
            )

        self._key_info = []

        for key in self.keys:
            if len(key) != 2:
                raise ValueError(
                    "Each sort key must contain "
                    "[column, direction]."
                )

            requested, direction = key

            direction = direction.lower()

            if direction not in (
                "asc",
                "desc",
            ):
                raise ValueError(
                    f"Invalid sort direction: "
                    f"{direction}"
                )

            resolved = resolve_column_name(
                self.schema,
                requested,
            )

            index = column_index(
                self.schema,
                resolved,
            )

            type_name = self.schema[index][1]

            self._key_info.append(
                (
                    index,
                    type_name,
                    direction,
                )
            )

    def _compare_rows(
        self,
        left,
        right,
    ):
        for (
            index,
            type_name,
            direction,
        ) in self._key_info:

            a = left[index]
            b = right[index]

            if type_name == "VARCHAR":
                a = a.encode("utf-8")
                b = b.encode("utf-8")

            self._count_comparison()

            if a < b:
                result = -1
            elif a > b:
                result = 1
            else:
                result = 0

            if result != 0:
                if direction == "desc":
                    result = -result

                return result

        return 0

    def _sort_rows(self, rows):
        rows.sort(
            key=cmp_to_key(
                self._compare_rows
            )
        )

    def _record_bytes(self, row):
        return len(
            encode_record(
                self.schema,
                row,
            )
        ) + SLOT_SIZE

    def _write_sorted_run(self, rows):
        self._sort_rows(rows)

        run = self._make_run()

        for row in rows:
            run.append(row)

        run.finish()

        self._runs.append(run)

    def _generate_initial_runs(self):
        """
        Consume the child.

        The Python row list is explicitly counted as
        page-equivalent working memory. It is never allowed
        to represent more than B slotted pages.
        """

        rows = []

        pages_used = 0
        free_bytes = 0

        external = False

        while True:
            row = self.child.next()

            if row is END:
                break

            needed = self._record_bytes(
                row
            )

            if needed > USABLE_PAGE_BYTES:
                raise ValueError(
                    "Tuple is too large for sort."
                )

            if pages_used == 0:
                pages_used = 1
                free_bytes = (
                    USABLE_PAGE_BYTES
                )

            if needed > free_bytes:

                if pages_used == self.frames:
                    # Current B-page run is full.
                    external = True

                    self.max_frames_held = max(
                        self.max_frames_held,
                        self.frames,
                    )

                    self._write_sorted_run(
                        rows
                    )

                    rows = []
                    pages_used = 1
                    free_bytes = (
                        USABLE_PAGE_BYTES
                    )

                else:
                    pages_used += 1

                    free_bytes = (
                        USABLE_PAGE_BYTES
                    )

            rows.append(row)
            free_bytes -= needed

            self.max_frames_held = max(
                self.max_frames_held,
                pages_used,
            )

        if not external:
            # Entire relation fits in B frames.
            self._sort_rows(rows)

            self._memory_rows = rows
            self._memory_position = 0

            if rows:
                self.passes = 1

            return

        if rows:
            self._write_sorted_run(
                rows
            )

        # Pass 0 has now completed.
        self.passes = 1

    def _merge_group_to_run(
        self,
        group,
    ):
        """
        Merge at most B-1 runs and write one output run.
        """

        output = self._make_run()

        readers = [
            iter(run.rows())
            for run in group
        ]

        heap = []
        sequence = 0

        for index, reader in enumerate(
            readers
        ):
            try:
                row = next(reader)
            except StopIteration:
                continue

            heapq.heappush(
                heap,
                _HeapItem(
                    row,
                    index,
                    sequence,
                    self,
                ),
            )

            sequence += 1

        self.max_frames_held = max(
            self.max_frames_held,
            min(
                self.frames,
                len(group) + 1,
            ),
        )

        while heap:
            item = heapq.heappop(
                heap
            )

            output.append(
                item.row
            )

            reader = readers[
                item.reader_index
            ]

            try:
                row = next(reader)
            except StopIteration:
                continue

            heapq.heappush(
                heap,
                _HeapItem(
                    row,
                    item.reader_index,
                    sequence,
                    self,
                ),
            )

            sequence += 1

        output.finish()

        return output

    def _perform_intermediate_merges(self):
        """
        Keep merging until at most B-1 runs remain.

        A single leftover run is carried forward untouched,
        matching the professor's documented valid strategy.
        """

        while len(self._runs) > (
            self.frames - 1
        ):
            new_runs = []

            step = self.frames - 1

            for start in range(
                0,
                len(self._runs),
                step,
            ):
                group = self._runs[
                    start:start + step
                ]

                if len(group) == 1:
                    new_runs.append(
                        group[0]
                    )
                    continue

                merged = (
                    self._merge_group_to_run(
                        group
                    )
                )

                new_runs.append(
                    merged
                )

                for run in group:
                    run.delete()

            self._runs = new_runs
            self.passes += 1

    def _initialize_final_merge(self):
        if self._merge_initialized:
            return

        self._merge_initialized = True

        self._final_readers = [
            iter(run.rows())
            for run in self._runs
        ]

        self._heap = []

        for index, reader in enumerate(
            self._final_readers
        ):
            try:
                row = next(reader)
            except StopIteration:
                continue

            heapq.heappush(
                self._heap,
                _HeapItem(
                    row,
                    index,
                    self._sequence,
                    self,
                ),
            )

            self._sequence += 1

        self.max_frames_held = max(
            self.max_frames_held,
            len(self._final_readers),
        )

    def open(self):
        if self.is_open:
            raise RuntimeError(
                "Sort is already open."
            )

        if self.frames < 3:
            raise ValueError(
                "External sort requires "
                "at least 3 frames."
            )

        self._reset_counters()

        self.passes = 0
        self.max_frames_held = 0

        self._memory_rows = None
        self._memory_position = 0

        self._runs = []
        self._final_readers = []
        self._heap = []

        self._sequence = 0
        self._merge_initialized = False
        self._exhausted = False

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

            self._prepare_keys()

            self._generate_initial_runs()

            # Child is fully consumed because sort is blocking.
            self.child.close()

            if self._memory_rows is None:
                self._perform_intermediate_merges()

                if len(self._runs) > 1:
                    # This is the final merge pass. It will happen lazily through next().
                    self.passes += 1

        except Exception:
            self.child.close()
            self._cleanup_runs()
            raise

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "Sort.next() called before open()."
            )

        if self._exhausted:
            return END

        # In-memory case.
        if self._memory_rows is not None:

            if self._memory_position >= len(
                self._memory_rows
            ):
                self._exhausted = True
                return END

            row = self._memory_rows[
                self._memory_position
            ]

            self._memory_position += 1
            self._count_output()

            return row

        # External case.
        self._initialize_final_merge()

        if not self._heap:
            self._exhausted = True
            return END

        item = heapq.heappop(
            self._heap
        )

        result = item.row

        reader = self._final_readers[
            item.reader_index
        ]

        try:
            row = next(reader)

            heapq.heappush(
                self._heap,
                _HeapItem(
                    row,
                    item.reader_index,
                    self._sequence,
                    self,
                ),
            )

            self._sequence += 1

        except StopIteration:
            pass

        self._count_output()

        return result

    def _cleanup_runs(self):
        for run in self._runs:
            run.delete()

        self._runs = []

    def close(self):
        if not self.is_open:
            return

        self.child.close()

        self._cleanup_runs()

        self._memory_rows = None
        self._final_readers = []
        self._heap = []

        self.is_open = False