
import hashlib

from execution.base import (
    END,
    Operator,
    column_index,
    validate_schema,
)
from execution.conditions import resolve_column_name
from execution.sort import Sort
from execution.temp_run import TempRun
from storage.record import encode_record


PAGE_BYTES = 4088


class GroupBy(Operator):
    """
    Module 2 GROUP BY.

    mode="sort":
        External sort by grouping keys, then aggregate
        adjacent groups.

    mode="hash":
        Partition input to disk by grouping key, then
        aggregate one partition at a time.

        If one partition still contains too many groups
        for the available memory, repartition it using a
        different deterministic hash seed.
    """

    def __init__(
        self,
        child,
        mode,
        keys,
        aggregates,
        frames,
        temp_dir=None,
    ):
        super().__init__()

        self.child = child
        self.mode = mode

        self.keys = list(keys)

        self.aggregates = [
            list(aggregate)
            for aggregate in aggregates
        ]

        self.frames = frames
        self.temp_dir = temp_dir

        self._input_schema = []

        self._key_indices = []
        self._aggregate_info = []

        # Sort mode.
        self._sort = None

        self._pending_row = None
        self._input_exhausted = False

        self._last_sort_comparisons = 0
        self._last_sort_reads = 0
        self._last_sort_writes = 0

        # Hash mode.
        self._partition_queue = []

        self._current_groups = None
        self._current_group_iter = None

        self.partition_count = 0
        self.repartition_count = 0
        self.max_hash_frames_held = 0

        # Global aggregation.
        self._global_empty_row = None
        self._global_empty_returned = False

        self._exhausted = False

    # =========================================================
    # Schema and validation
    # =========================================================

    def _aggregate_name(
        self,
        function,
        column,
    ):
        if column == "*":
            suffix = "star"
        else:
            suffix = column.replace(
                ".",
                "_",
            )

        return (
            f"{function}_{suffix}"
        )

    def _prepare_schema(self):
        self._input_schema = [
            list(column)
            for column
            in self.child.schema
        ]

        validate_schema(
            self._input_schema
        )

        self.schema = []
        self._key_indices = []

        for requested in self.keys:

            resolved = resolve_column_name(
                self._input_schema,
                requested,
            )

            index = column_index(
                self._input_schema,
                resolved,
            )

            self._key_indices.append(
                index
            )

            self.schema.append(
                list(
                    self._input_schema[
                        index
                    ]
                )
            )

        self._aggregate_info = []

        for aggregate in self.aggregates:

            # Accept the original Module 2 form:
            #
            #     [function, column]
            #
            # and the Module 3/4 form:
            #
            #     [function, column, output_name]
            #
            if len(aggregate) not in (
                2,
                3,
            ):
                raise ValueError(
                    "Each aggregate must contain "
                    "[function, column] or "
                    "[function, column, output_name]."
                )

            function = (
                aggregate[0].lower()
            )

            requested = aggregate[1]

            if function not in (
                "count",
                "sum",
                "avg",
                "min",
                "max",
            ):
                raise ValueError(
                    f"Unsupported aggregate: "
                    f"{function}"
                )

            if requested == "*":

                if function != "count":
                    raise ValueError(
                        f"{function.upper()}(*) "
                        f"is not supported."
                    )

                index = None
                input_type = None

            else:
                resolved = resolve_column_name(
                    self._input_schema,
                    requested,
                )

                index = column_index(
                    self._input_schema,
                    resolved,
                )

                input_type = (
                    self._input_schema[
                        index
                    ][1]
                )

                requested = resolved

            if (
                function in (
                    "sum",
                    "avg",
                )
                and input_type != "INT"
            ):
                raise TypeError(
                    f"{function.upper()} requires "
                    f"an INT column."
                )

            # -------------------------------------------------
            # Optional explicit aggregate output name.
            #
            # Examples:
            #
            # ["count", "*"]
            #       -> count_star
            #
            # ["count", "*", "total"]
            #       -> total
            # -------------------------------------------------

            if len(aggregate) == 3:

                output_name = (
                    aggregate[2]
                )

                if (
                    not isinstance(
                        output_name,
                        str,
                    )
                    or not output_name
                ):
                    raise ValueError(
                        "Aggregate output name "
                        "must be a non-empty string."
                    )

            else:

                output_name = (
                    self._aggregate_name(
                        function,
                        requested,
                    )
                )

            if function in (
                "count",
                "sum",
            ):
                output_type = "INT"

            elif function == "avg":
                output_type = "REAL"

            else:
                output_type = input_type

            self.schema.append(
                [
                    output_name,
                    output_type,
                ]
            )

            self._aggregate_info.append(
                {
                    "function": function,
                    "column": requested,
                    "index": index,
                    "input_type": input_type,
                }
            )

        validate_schema(
            self.schema
        )

    # =========================================================
    # Aggregate state
    # =========================================================

    def _new_states(self):
        states = []

        for info in self._aggregate_info:

            function = info[
                "function"
            ]

            if function == "count":
                states.append(
                    {
                        "count": 0,
                    }
                )

            elif function == "sum":
                states.append(
                    {
                        "sum": 0,
                    }
                )

            elif function == "avg":
                states.append(
                    {
                        "sum": 0,
                        "count": 0,
                    }
                )

            elif function in (
                "min",
                "max",
            ):
                states.append(
                    {
                        "value": None,
                        "seen": False,
                    }
                )

        return states

    def _value_less(
        self,
        left,
        right,
        type_name,
    ):
        self._count_comparison()

        if type_name == "VARCHAR":
            left = left.encode(
                "utf-8"
            )

            right = right.encode(
                "utf-8"
            )

        return left < right

    def _update_states(
        self,
        states,
        row,
    ):
        for state, info in zip(
            states,
            self._aggregate_info,
        ):
            function = info[
                "function"
            ]

            index = info[
                "index"
            ]

            if function == "count":
                state["count"] += 1

            elif function == "sum":
                state["sum"] += (
                    row[index]
                )

            elif function == "avg":
                state["sum"] += (
                    row[index]
                )

                state["count"] += 1

            elif function == "min":

                value = row[index]

                if (
                    not state["seen"]
                    or self._value_less(
                        value,
                        state["value"],
                        info[
                            "input_type"
                        ],
                    )
                ):
                    state["value"] = value
                    state["seen"] = True

            elif function == "max":

                value = row[index]

                if (
                    not state["seen"]
                    or self._value_less(
                        state["value"],
                        value,
                        info[
                            "input_type"
                        ],
                    )
                ):
                    state["value"] = value
                    state["seen"] = True

    def _finish_states(
        self,
        states,
    ):
        values = []

        for state, info in zip(
            states,
            self._aggregate_info,
        ):
            function = info[
                "function"
            ]

            if function == "count":
                values.append(
                    state["count"]
                )

            elif function == "sum":
                values.append(
                    state["sum"]
                )

            elif function == "avg":
                values.append(
                    round(
                        state["sum"]
                        / state["count"],
                        4,
                    )
                )

            elif function in (
                "min",
                "max",
            ):
                values.append(
                    state["value"]
                )

        return values

    # =========================================================
    # Group keys
    # =========================================================

    def _group_key(
        self,
        row,
    ):
        return tuple(
            row[index]
            for index
            in self._key_indices
        )

    def _keys_equal(
        self,
        left,
        right,
    ):
        for index in self._key_indices:

            self._count_comparison()

            a = left[index]
            b = right[index]

            type_name = (
                self._input_schema[
                    index
                ][1]
            )

            if type_name == "VARCHAR":

                a = a.encode(
                    "utf-8"
                )

                b = b.encode(
                    "utf-8"
                )

            if a != b:
                return False

        return True

    # =========================================================
    # Sort-mode counters
    # =========================================================

    def _sync_sort_counters(self):
        if self._sort is None:
            return

        counters = (
            self._sort.counters()
        )

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

    # =========================================================
    # Empty/global aggregation
    # =========================================================

    def _prepare_empty_global(self):
        values = []

        for info in self._aggregate_info:

            if (
                info["function"]
                == "count"
            ):
                values.append(0)

            else:
                raise ValueError(
                    f"{info['function'].upper()} "
                    f"is undefined for empty input."
                )

        self._global_empty_row = tuple(
            values
        )

    def _open_global_mode(self):
        """
        No grouping keys means there is exactly one
        global group.

        This path works for both sort and hash mode.
        """

        first = self.child.next()

        if first is END:
            self.child.close()

            self._prepare_empty_global()
            return

        self._pending_row = first

    def _next_global_group(self):

        if (
            self._global_empty_row
            is not None
        ):
            if self._global_empty_returned:
                self._exhausted = True
                return END

            self._global_empty_returned = True

            self._count_output()

            return (
                self._global_empty_row
            )

        if self._input_exhausted:
            self._exhausted = True
            return END

        states = self._new_states()

        if self._pending_row is not None:

            self._update_states(
                states,
                self._pending_row,
            )

            self._pending_row = None

        while True:

            row = self.child.next()

            if row is END:
                break

            self._update_states(
                states,
                row,
            )

        self.child.close()

        self._input_exhausted = True

        result = tuple(
            self._finish_states(
                states
            )
        )

        self._count_output()

        return result

    # =========================================================
    # Sort mode
    # =========================================================

    def _open_sort_mode(self):

        self.child.open()

        self._prepare_schema()

        if not self.keys:
            self._open_global_mode()
            return

        self.child.close()

        sort_keys = [
            [key, "asc"]
            for key in self.keys
        ]

        self._sort = Sort(
            self.child,
            sort_keys,
            frames=self.frames,
            temp_dir=self.temp_dir,
        )

        self._sort.open()

        self._sync_sort_counters()

        first = self._sort.next()

        self._sync_sort_counters()

        if first is END:
            self._input_exhausted = True
        else:
            self._pending_row = first

    def _next_sorted_group(self):

        if self._input_exhausted:
            self._exhausted = True
            return END

        first = self._pending_row

        if first is None:
            self._exhausted = True
            return END

        self._pending_row = None

        group_key = self._group_key(
            first
        )

        states = self._new_states()

        self._update_states(
            states,
            first,
        )

        while True:

            row = self._sort.next()

            self._sync_sort_counters()

            if row is END:
                self._input_exhausted = True
                break

            if not self._keys_equal(
                first,
                row,
            ):
                self._pending_row = row
                break

            self._update_states(
                states,
                row,
            )

        result = tuple(
            group_key
            + tuple(
                self._finish_states(
                    states
                )
            )
        )

        self._count_output()

        return result

    # =========================================================
    # Hash mode helpers
    # =========================================================

    def _temp_read(self):
        self._count_read()

    def _temp_write(self):
        self._count_write()

    def _make_partition(self):
        return TempRun(
            self._input_schema,
            temp_dir=self.temp_dir,
            read_callback=self._temp_read,
            write_callback=self._temp_write,
        )

    def _stable_group_hash(
        self,
        key,
        depth,
    ):
        """
        Deterministic hashing.

        Built-in hash() is deliberately avoided because
        Python randomizes it between processes.
        """

        raw = repr(key).encode(
            "utf-8"
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

    def _child_rows(self):

        while True:

            row = self.child.next()

            if row is END:
                return

            yield row

    def _partition_rows(
        self,
        rows,
        depth,
    ):
        """
        Uses:
            B-1 partition output pages
            1 streaming input page

        Total conceptual frames = B.
        """

        partition_total = (
            self.frames - 1
        )

        partitions = [
            self._make_partition()
            for _ in range(
                partition_total
            )
        ]

        self.max_hash_frames_held = max(
            self.max_hash_frames_held,
            self.frames,
        )

        try:

            for row in rows:

                key = self._group_key(
                    row
                )

                partition_no = (
                    self._stable_group_hash(
                        key,
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

        self.partition_count += (
            len(partitions)
        )

        return partitions

    def _group_memory_cost(
        self,
        row,
    ):
        """
        Conservative conceptual memory charge for one
        in-memory group.

        We charge the encoded input tuple plus extra state
        space for the grouping dictionary and aggregates.
        """

        record_bytes = len(
            encode_record(
                self._input_schema,
                row,
            )
        )

        aggregate_state_bytes = (
            32
            * max(
                1,
                len(
                    self._aggregate_info
                ),
            )
        )

        dictionary_overhead = 64

        return (
            record_bytes
            + aggregate_state_bytes
            + dictionary_overhead
        )

    def _aggregate_partition(
        self,
        run,
    ):
        """
        Attempt to aggregate one partition in memory.

        One frame is conceptually used to stream input,
        leaving B-1 page-equivalents for the hash table.

        Returns:
            dict of key -> aggregate states

        or:
            None if the partition must be repartitioned.
        """

        memory_budget = (
            self.frames - 1
        ) * PAGE_BYTES

        memory_used = 0

        groups = {}

        self.max_hash_frames_held = max(
            self.max_hash_frames_held,
            self.frames,
        )

        for row in run.rows():

            key = self._group_key(
                row
            )

            # One hash-table group lookup.
            self._count_comparison()

            if key not in groups:

                required = (
                    self._group_memory_cost(
                        row
                    )
                )

                if (
                    memory_used
                    + required
                    > memory_budget
                ):
                    return None

                groups[key] = (
                    self._new_states()
                )

                memory_used += required

            self._update_states(
                groups[key],
                row,
            )

        return groups

    def _repartition_run(
        self,
        run,
        depth,
    ):

        partitions = (
            self._partition_rows(
                run.rows(),
                depth,
            )
        )

        run.delete()

        self.repartition_count += 1

        new_items = [
            (
                partition,
                depth + 1,
            )
            for partition
            in partitions
        ]

        # Process recursively created partitions first.
        self._partition_queue = (
            new_items
            + self._partition_queue
        )

    def _prepare_next_hash_partition(
        self,
    ):

        while self._partition_queue:

            run, depth = (
                self._partition_queue.pop(
                    0
                )
            )

            groups = (
                self._aggregate_partition(
                    run
                )
            )

            if groups is None:

                self._repartition_run(
                    run,
                    depth,
                )

                continue

            run.delete()

            self._current_groups = groups

            self._current_group_iter = iter(
                groups.items()
            )

            return True

        return False

    def _open_hash_mode(self):

        if self.frames < 4:
            raise ValueError(
                "Hash group_by requires "
                "at least 4 frames."
            )

        self.child.open()

        self._prepare_schema()

        # Zero grouping keys are handled as one global
        # streaming group; no partitioning is necessary.
        if not self.keys:
            self._open_global_mode()
            return

        try:
            partitions = (
                self._partition_rows(
                    self._child_rows(),
                    depth=0,
                )
            )

        finally:
            self.child.close()

        self._partition_queue = [
            (
                partition,
                1,
            )
            for partition
            in partitions
        ]

    def _next_hash_group(self):

        while True:

            if (
                self._current_group_iter
                is not None
            ):
                try:
                    (
                        key,
                        states,
                    ) = next(
                        self._current_group_iter
                    )

                    result = tuple(
                        key
                        + tuple(
                            self._finish_states(
                                states
                            )
                        )
                    )

                    self._count_output()

                    return result

                except StopIteration:

                    self._current_groups = None
                    self._current_group_iter = None

            if not self._prepare_next_hash_partition():

                self._exhausted = True

                return END

    # =========================================================
    # Operator interface
    # =========================================================

    def open(self):

        if self.is_open:
            raise RuntimeError(
                "GroupBy is already open."
            )

        if self.mode not in (
            "sort",
            "hash",
        ):
            raise ValueError(
                f"Invalid group_by mode: "
                f"{self.mode}"
            )

        self._reset_counters()

        self._input_schema = []

        self._sort = None

        self._pending_row = None
        self._input_exhausted = False

        self._global_empty_row = None
        self._global_empty_returned = False

        self._last_sort_comparisons = 0
        self._last_sort_reads = 0
        self._last_sort_writes = 0

        self._partition_queue = []

        self._current_groups = None
        self._current_group_iter = None

        self.partition_count = 0
        self.repartition_count = 0
        self.max_hash_frames_held = 0

        self._exhausted = False

        if self.mode == "sort":

            self._open_sort_mode()

        else:

            self._open_hash_mode()

        self.is_open = True

    def next(self):

        if not self.is_open:
            raise RuntimeError(
                "GroupBy.next() called before open()."
            )

        if self._exhausted:
            return END

        if not self.keys:

            return (
                self._next_global_group()
            )

        if self.mode == "sort":

            return (
                self._next_sorted_group()
            )

        return (
            self._next_hash_group()
        )

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

        self._current_groups = None
        self._current_group_iter = None

        self.child.close()

        self.is_open = False