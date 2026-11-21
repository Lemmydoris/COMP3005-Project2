import os

from execution.base import (
    END,
    Operator,
    validate_schema,
)

from storage.buffer import BufferPool
from storage.catalog import Catalog
from storage.directory import (
    DirectoryPage,
    NO_NEXT_PAGE,
)
from storage.disk import DiskManager
from storage.page import SlottedPage
from storage.record import decode_record


class SeqScan(Operator):
    """
    Module 2 sequential scan.

    Returns every live tuple in heap order.

    Module 2 requirement:
        one data page pinned at a time
        frames = 1
    """

    def __init__(
    self,
    db_dir,
    table_name,
    frames=1,
    policy="lru",
    alias=None,
    ):    
        super().__init__()

        self.db_dir = db_dir
        self.table_name = table_name
        self.frames = frames
        self.policy = policy
        self.alias = alias        
        self.catalog = None
        self.metadata = None

        self.disk = None
        self.buffer = None

        self._scan = None
        self._record_schema = None

        self._last_reads = 0
        self._last_writes = 0

        self.max_frames_held = 0

    # ---------------------------------------------------------
    # One-frame heap traversal
    # ---------------------------------------------------------

    def _one_frame_scan(self):
        """
        Directory metadata is read directly from the
        DiskManager.

        Only table DATA pages enter the BufferPool.
        The BufferPool has exactly one frame, therefore
        at most one data page can be pinned at a time.
        """

        directory_page_id = 0

        while True:

            # Directory metadata does not enter the
            # one-frame data-page BufferPool.
            directory_data = self.disk.read_page(
                directory_page_id
            )

            directory = DirectoryPage.from_bytes(
                directory_data
            )

            data_page_ids = []

            for entry_no in range(
                directory.entry_count
            ):
                data_page_id, _ = (
                    directory.get_entry(
                        entry_no
                    )
                )

                data_page_ids.append(
                    data_page_id
                )

            next_directory_page = (
                directory.next_dir_page
            )

            # Release the full directory-page representation
            # before scanning any data page.
            directory = None
            directory_data = None

            for data_page_id in data_page_ids:

                page_data = (
                    self.buffer.fetch_page(
                        data_page_id
                    )
                )

                self.max_frames_held = max(
                    self.max_frames_held,
                    1,
                )

                try:
                    page = (
                        SlottedPage.from_bytes(
                            page_data
                        )
                    )

                    for slot_no in range(
                        page.slot_count
                    ):
                        offset, length = (
                            page._read_slot(
                                slot_no
                            )
                        )

                        # Deleted slot.
                        if offset == 0:
                            continue

                        record = bytes(
                            page.data[
                                offset:
                                offset + length
                            ]
                        )

                        yield (
                            (
                                data_page_id,
                                slot_no,
                            ),
                            record,
                        )

                finally:
                    self.buffer.unpin_page(
                        data_page_id,
                        is_dirty=False,
                    )

            if (
                next_directory_page
                == NO_NEXT_PAGE
            ):
                break

            directory_page_id = (
                next_directory_page
            )

    # ---------------------------------------------------------
    # I/O counters
    # ---------------------------------------------------------

    def _sync_io_counters(self):
        if self.disk is None:
            return

        current_reads = self.disk.reads
        current_writes = self.disk.writes

        self._count_read(
            current_reads
            - self._last_reads
        )

        self._count_write(
            current_writes
            - self._last_writes
        )

        self._last_reads = current_reads
        self._last_writes = current_writes

    # ---------------------------------------------------------
    # Operator API
    # ---------------------------------------------------------

    def open(self):
        if self.is_open:
            raise RuntimeError(
                "SeqScan is already open."
            )

        if self.frames < 1:
            raise ValueError(
                "SeqScan requires at least "
                "1 frame."
            )

        self._reset_counters()

        self.max_frames_held = 0

        # Catalog lookup is an open-time metadata operation.
        # Module 1's catalog implementation may internally
        # require two frames, but it is not retained as the
        # table scan's working buffer.
        self.catalog = Catalog(
            self.db_dir,
            frames=max(
                2,
                self.frames,
            ),
            policy=self.policy,
        )

        try:
            self.metadata = (
                self.catalog.get_table(
                    self.table_name
                )
            )

        except KeyError as exc:
            raise ValueError(
                f"Unknown table: "
                f"{self.table_name}"
            ) from exc

        self._record_schema = (
            self.metadata["schema"]
        )

        # Module 2 uses qualified column names.
        #
        # The physical table remains table_name.
        # If an alias is present, only the visible
        # column qualifier changes.
        qualifier = (
            self.alias
            if self.alias is not None
            else self.table_name
        )

        self.schema = []

        for column in self._record_schema:

            qualified = [
                (
                    f"{qualifier}."
                    f"{column[0]}"
                ),
                *column[1:],
            ]

            self.schema.append(
                qualified
            )

        validate_schema(
            self.schema
        )
        
        table_file = os.path.join(
            self.db_dir,
            self.metadata["file"],
        )

        self.disk = DiskManager(
            table_file
        )

        # The important Module 2 change:
        # exactly ONE data-page frame.
        self.buffer = BufferPool(
            self.disk,
            frames=1,
            policy=self.policy,
        )

        self._last_reads = (
            self.disk.reads
        )

        self._last_writes = (
            self.disk.writes
        )

        self._scan = (
            self._one_frame_scan()
        )

        self.is_open = True

    def next(self):
        if not self.is_open:
            raise RuntimeError(
                "SeqScan.next() called "
                "before open()."
            )

        try:
            rid, record = next(
                self._scan
            )

        except StopIteration:
            self._sync_io_counters()
            return END

        self._sync_io_counters()

        values = decode_record(
            self._record_schema,
            record,
        )

        self._count_output()

        return tuple(values)

    def close(self):
        if not self.is_open:
            return

        # If a parent such as LIMIT stops early,
        # closing the generator executes the finally
        # around the currently pinned data page.
        if self._scan is not None:

            close_method = getattr(
                self._scan,
                "close",
                None,
            )

            if close_method is not None:
                close_method()

        self._sync_io_counters()

        self._scan = None

        self.is_open = False

    def counters(self):
        self._sync_io_counters()

        return super().counters()
