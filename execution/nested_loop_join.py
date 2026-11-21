from execution.base import (
    END,
    Operator,
    validate_schema,
)
from execution.conditions import (
    evaluate_condition,
    prepare_condition,
)


PAGE_BYTES = 4088
SLOT_BYTES = 4


class NestedLoopJoin(Operator):
    """
    Block nested-loop join.

    Memory:
        B - 2 page-equivalents of outer tuples
        1 inner tuple/page frame
        1 remaining frame

    Every left/right tuple pair is tested exactly once.
    """

    def __init__(
        self,
        left,
        right,
        condition,
        frames,
    ):
        super().__init__()

        self.left = left
        self.right = right
        self.condition = condition
        self.frames = frames

        self._parsed_condition = None

        self._left_schema = []
        self._right_schema = []

        self._outer_block = []
        self._outer_lookahead = None
        self._outer_pages = 0

        self._current_inner = None
        self._outer_index = 0

        self._left_exhausted = False
        self._right_open = False
        self._exhausted = False

        self.max_frames_held = 0
        self.outer_blocks = 0

    # Memory accounting
    def _row_size(
        self,
        schema,
        row,
    ):
        size = SLOT_BYTES

        for column, value in zip(
            schema,
            row,
        ):
            type_name = column[1]

            if type_name == "INT":
                size += 4

            elif type_name == "REAL":
                size += 8

            elif type_name == "VARCHAR":
                encoded = value.encode(
                    "utf-8"
                )

                size += (
                    2
                    + len(encoded)
                )

            else:
                raise ValueError(
                    f"Unsupported type in join: "
                    f"{type_name}"
                )

        return size

    def _update_frame_measurement(self):
        frames_used = self._outer_pages

        # Current inner stream.
        if self._right_open:
            frames_used += 1

        # A lookahead tuple can temporarily occupy the remaining frame while the current block is scanned.
        if self._outer_lookahead is not None:
            frames_used += 1

        self.max_frames_held = max(
            self.max_frames_held,
            frames_used,
        )

    def _snapshot_subtree_counters(
        self,
        operator,
    ):
        """
        Save counters for a logical child subtree.

        BNL may reopen its right subtree many times.
        open() resets operator counters, so without
        preserving them the trace would only show
        the final inner scan.
        """

        snapshot = [
            (
                operator,
                operator.counters().copy(),
            )
        ]

        if (
            hasattr(operator, "left")
            and hasattr(operator, "right")
        ):
            snapshot.extend(
                self._snapshot_subtree_counters(
                    operator.left
                )
            )

            snapshot.extend(
                self._snapshot_subtree_counters(
                    operator.right
                )
            )

        elif hasattr(
            operator,
            "child",
        ):
            snapshot.extend(
                self._snapshot_subtree_counters(
                    operator.child
                )
            )

        return snapshot

    def _restore_subtree_counters(
        self,
        snapshot,
    ):
        """
        Add counters from completed earlier scans
        back onto the freshly reopened subtree.
        """

        for operator, counters in snapshot:

            operator._counters.tuples_out += (
                counters["tuples_out"]
            )

            operator._counters.comparisons += (
                counters["comparisons"]
            )

            operator._counters.page_reads += (
                counters["page_reads"]
            )

            operator._counters.page_writes += (
                counters["page_writes"]
            )

    # Outer blocks
    def _load_outer_block(self):
        self._outer_block = []
        self._outer_pages = 0

        maximum_outer_pages = (
            self.frames - 2
        )

        free_bytes = 0

        if self._outer_lookahead is not None:
            row = self._outer_lookahead
            self._outer_lookahead = None
        else:
            row = self.left.next()

        while row is not END:

            needed = self._row_size(
                self._left_schema,
                row,
            )

            if needed > PAGE_BYTES:
                raise ValueError(
                    "Outer join tuple is too "
                    "large for one page."
                )

            if self._outer_pages == 0:
                self._outer_pages = 1
                free_bytes = PAGE_BYTES

            if needed > free_bytes:

                if (
                    self._outer_pages
                    >= maximum_outer_pages
                ):
                    self._outer_lookahead = row
                    break

                self._outer_pages += 1
                free_bytes = PAGE_BYTES

            self._outer_block.append(
                row
            )

            free_bytes -= needed

            row = self.left.next()

        if row is END:
            self._left_exhausted = True

        if self._outer_block:
            self.outer_blocks += 1

        self._update_frame_measurement()

        return bool(
            self._outer_block
        )

    # ---------------------------------------------------------
    # Inner restart
    # ---------------------------------------------------------

    def _restart_right(self):

        if self._right_open:
            self.right.close()

        # Save everything accumulated by previous
        # scans of the logical right subtree.
        previous_counters = (
            self._snapshot_subtree_counters(
                self.right
            )
        )

        # Reopen from the beginning. This resets the
        # operators' counters as part of open().
        self.right.open()

        # Restore the completed previous scans so
        # counters remain cumulative across BNL
        # inner rescans.
        self._restore_subtree_counters(
            previous_counters
        )

        self._right_open = True

        self._current_inner = None
        self._outer_index = 0

        self._update_frame_measurement()

    # ---------------------------------------------------------
    # Operator interface
    # ---------------------------------------------------------

    def open(self):
        if self.is_open:
            raise RuntimeError(
                "NestedLoopJoin is already open."
            )

        if self.frames < 4:
            raise ValueError(
                "nested_loop_join requires "
                "at least 4 frames."
            )

        self._reset_counters()

        self._outer_block = []
        self._outer_lookahead = None
        self._outer_pages = 0

        self._current_inner = None
        self._outer_index = 0

        self._left_exhausted = False
        self._right_open = False
        self._exhausted = False

        self.max_frames_held = 0
        self.outer_blocks = 0

        self.left.open()

        try:
            self.right.open()
            self._right_open = True

            self._left_schema = [
                list(column)
                for column
                in self.left.schema
            ]

            self._right_schema = [
                list(column)
                for column
                in self.right.schema
            ]

            validate_schema(
                self._left_schema
            )

            validate_schema(
                self._right_schema
            )

            self.schema = (
                self._left_schema
                + self._right_schema
            )

            # This catches a join producing the same
            # qualified column name twice.
            validate_schema(
                self.schema
            )

            self._parsed_condition = (
                prepare_condition(
                    self.condition,
                    self.schema,
                )
            )

        except Exception:
            self.left.close()

            if self._right_open:
                self.right.close()

            self._right_open = False
            raise

        self._update_frame_measurement()

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "NestedLoopJoin.next() "
                "called before open()."
            )

        if self._exhausted:
            return END

        while True:

            # Need an outer block.
            if not self._outer_block:

                if not self._load_outer_block():

                    self._exhausted = True

                    if self._right_open:
                        self.right.close()
                        self._right_open = False

                    return END

            # Need the next inner tuple.
            if self._current_inner is None:

                inner = self.right.next()

                if inner is END:
                    # Finished this pass over inner.
                    self.right.close()
                    self._right_open = False

                    self._outer_block = []
                    self._outer_pages = 0

                    # If no more outer tuples exist,
                    # the entire join is done.
                    if (
                        self._left_exhausted
                        and
                        self._outer_lookahead
                        is None
                    ):
                        self._exhausted = True
                        return END

                    # Build next outer block.
                    if not self._load_outer_block():
                        self._exhausted = True
                        return END

                    # Rescan inner from its beginning.
                    self._restart_right()

                    continue

                self._current_inner = inner
                self._outer_index = 0

                self._update_frame_measurement()

            # Compare this inner tuple against every tuple
            # in the current outer block.
            while (
                self._outer_index
                < len(
                    self._outer_block
                )
            ):
                outer = self._outer_block[
                    self._outer_index
                ]

                self._outer_index += 1

                joined = tuple(
                    outer
                ) + tuple(
                    self._current_inner
                )

                # Exactly ONE condition evaluation per
                # left/right pair.
                self._count_comparison()

                if evaluate_condition(
                    self._parsed_condition,
                    self.schema,
                    joined,
                ):
                    self._count_output()

                    return joined

            # This inner tuple has now been compared against
            # every row in the current outer block.
            self._current_inner = None
            self._outer_index = 0

    def close(self):
        if not self.is_open:
            return

        self.left.close()

        if self._right_open:
            self.right.close()

        self._right_open = False

        self._outer_block = []
        self._outer_lookahead = None
        self._current_inner = None

        self.is_open = False