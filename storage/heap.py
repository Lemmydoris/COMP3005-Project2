from storage.directory import (
    DirectoryPage,
    MAX_DIRECTORY_ENTRIES,
    NO_NEXT_PAGE
)
from storage.page import (
    SlottedPage,
    NO_SPACE
)

MAX_RECORD_SIZE = 4088

class HeapFile:
    """
    Heap file backed by:

        page 0 = first directory page
        later pages = data or additional directory pages
    """

    def __init__(
        self,
        table_name,
        disk_manager,
        buffer_pool
    ):
        self.table_name = table_name
        self.disk = disk_manager
        self.buffer = buffer_pool

        # A brand-new table file must begin with directory page 0.
        if self.disk.num_pages() == 0:
            self._create_first_directory_page()

    # Initialization
    def _create_first_directory_page(self):

        expected_page_id = 0

        data = self.buffer.new_page()

        actual_page_id = self.disk.num_pages() - 1

        if actual_page_id != expected_page_id:
            raise RuntimeError(
                "First directory page must be page 0."
            )

        directory = DirectoryPage(0)

        data[:] = directory.to_bytes()

        self.buffer.unpin_page(
            0,
            is_dirty=True
        )

    # New data page
    def _allocate_data_page(self):

        # The new page ID will be the current page count.
        expected_page_id = self.disk.num_pages()

        data = self.buffer.new_page()

        page_id = self.disk.num_pages() - 1

        if page_id != expected_page_id:
            raise RuntimeError(
                "Unexpected page allocation order."
            )

        page = SlottedPage(page_id)

        data[:] = page.to_bytes()

        return page_id, data, page

    # Insert
    def insert(self, record):
        """
        Insert raw record bytes.

        Returns:
            (page_id, slot_no)
        """

        if len(record) > MAX_RECORD_SIZE:
            raise ValueError(
                f"{self.table_name}: record is larger "
                "than 4088 bytes."
            )

        required_space = len(record) + 4

        directory_page_id = 0

        while True:

            dir_data = self.buffer.fetch_page(
                directory_page_id
            )

            directory = DirectoryPage.from_bytes(
                dir_data
            )

            # First fit
            for entry_no in range(
                directory.entry_count
            ):

                data_page_id, free_bytes = (
                    directory.get_entry(entry_no)
                )

                if free_bytes >= required_space:

                    page_data = self.buffer.fetch_page(
                        data_page_id
                    )

                    page = SlottedPage.from_bytes(
                        page_data
                    )

                    slot_no = page.insert(record)

                    if slot_no == NO_SPACE:
                        # Directory said it fit but the page disagreed that is inconsistent state.
                        self.buffer.unpin_page(
                            data_page_id,
                            is_dirty=False
                        )

                        self.buffer.unpin_page(
                            directory_page_id,
                            is_dirty=False
                        )

                        raise RuntimeError(
                            "Directory free-space information "
                            "is inconsistent."
                        )

                    # Copy changed page back into its buffer frame.
                    page_data[:] = page.to_bytes()

                    # Update directory free-space value.
                    directory.update_free_bytes(
                        entry_no,
                        page.free_space()
                    )

                    dir_data[:] = directory.to_bytes()

                    self.buffer.unpin_page(
                        data_page_id,
                        is_dirty=True
                    )

                    self.buffer.unpin_page(
                        directory_page_id,
                        is_dirty=True
                    )

                    return (
                        data_page_id,
                        slot_no
                    )

            # No existing data page had enough room. If this directory still has space, create a new data page.
            if (
                directory.entry_count
                < MAX_DIRECTORY_ENTRIES
            ):

                (
                    data_page_id,
                    page_data,
                    page
                ) = self._allocate_data_page()

                slot_no = page.insert(record)

                if slot_no == NO_SPACE:
                    raise RuntimeError(
                        "New data page could not hold record."
                    )

                page_data[:] = page.to_bytes()

                directory.add_entry(
                    data_page_id,
                    page.free_space()
                )

                dir_data[:] = directory.to_bytes()

                self.buffer.unpin_page(
                    data_page_id,
                    is_dirty=True
                )

                self.buffer.unpin_page(
                    directory_page_id,
                    is_dirty=True
                )

                return (
                    data_page_id,
                    slot_no
                )

            # The directory is full. Follow the linked list if another directory already exists.
            if (
                directory.next_dir_page
                != NO_NEXT_PAGE
            ):

                next_directory_page = (
                    directory.next_dir_page
                )

                self.buffer.unpin_page(
                    directory_page_id,
                    is_dirty=False
                )

                directory_page_id = (
                    next_directory_page
                )

                continue

            # Directory is full AND no next directory exists then create another directory page.
            new_dir_data = self.buffer.new_page()

            new_directory_page_id = (
                self.disk.num_pages() - 1
            )

            new_directory = DirectoryPage(
                new_directory_page_id
            )

            new_dir_data[:] = (
                new_directory.to_bytes()
            )

            # Link old directory to new directory.
            directory.set_next_dir_page(
                new_directory_page_id
            )

            dir_data[:] = directory.to_bytes()

            self.buffer.unpin_page(
                directory_page_id,
                is_dirty=True
            )

            # New directory remains pinned.
            directory_page_id = (
                new_directory_page_id
            )

            directory = new_directory
            dir_data = new_dir_data

            # Allocate first data page for the new directory.
            (
                data_page_id,
                page_data,
                page
            ) = self._allocate_data_page()

            slot_no = page.insert(record)

            if slot_no == NO_SPACE:
                raise RuntimeError(
                    "New data page could not hold record."
                )

            page_data[:] = page.to_bytes()

            directory.add_entry(
                data_page_id,
                page.free_space()
            )

            dir_data[:] = directory.to_bytes()

            self.buffer.unpin_page(
                data_page_id,
                is_dirty=True
            )

            self.buffer.unpin_page(
                directory_page_id,
                is_dirty=True
            )

            return (
                data_page_id,
                slot_no
            )

    # Get
    def get(self, rid):
        """
        Retrieve one record by:

            rid = (page_id, slot_no)
        """
        page_id, slot_no = rid

        page_data = self.buffer.fetch_page(
            page_id
        )

        try:
            page = SlottedPage.from_bytes(
                page_data
            )

            try:
                return page.get(slot_no)

            except (ValueError, IndexError):
                raise ValueError(
                    f"Cannot read rid "
                    f"({page_id}, {slot_no}): "
                    "slot is dead or invalid."
                )
        finally:
            self.buffer.unpin_page(
                page_id,
                is_dirty=False
            )

    # Find directory entry
    def _find_directory_entry(
        self,
        target_data_page_id
    ):
        directory_page_id = 0

        while True:

            dir_data = self.buffer.fetch_page(
                directory_page_id
            )

            directory = DirectoryPage.from_bytes(
                dir_data
            )

            for entry_no in range(
                directory.entry_count
            ):

                data_page_id, _ = (
                    directory.get_entry(entry_no)
                )

                if (
                    data_page_id
                    == target_data_page_id
                ):
                    return (
                        directory_page_id,
                        dir_data,
                        directory,
                        entry_no
                    )

            next_page = directory.next_dir_page

            self.buffer.unpin_page(
                directory_page_id,
                is_dirty=False
            )

            if next_page == NO_NEXT_PAGE:
                raise ValueError(
                    f"Data page {target_data_page_id} "
                    "is not part of this heap file."
                )

            directory_page_id = next_page

    # Delete
    def delete(self, rid):
        page_id, slot_no = rid

        (
            directory_page_id,
            dir_data,
            directory,
            entry_no
        ) = self._find_directory_entry(page_id)

        page_data = self.buffer.fetch_page(
            page_id
        )

        try:
            page = SlottedPage.from_bytes(
                page_data
            )

            page.delete(slot_no)

            page_data[:] = page.to_bytes()

            # Deletion does not reclaim record bytes, so this normally stays unchanged.
            directory.update_free_bytes(
                entry_no,
                page.free_space()
            )

            dir_data[:] = directory.to_bytes()

        finally:
            self.buffer.unpin_page(
                page_id,
                is_dirty=True
            )

            self.buffer.unpin_page(
                directory_page_id,
                is_dirty=True
            )

    # Scan
    def scan(self):
        """
        Yield:

            ((page_id, slot_no), record)

        At most one directory page and one data page
        are pinned at the same time.
        """
        directory_page_id = 0

        while True:

            dir_data = self.buffer.fetch_page(
                directory_page_id
            )

            directory = DirectoryPage.from_bytes(
                dir_data
            )

            try:

                for entry_no in range(
                    directory.entry_count
                ):

                    data_page_id, _ = (
                        directory.get_entry(entry_no)
                    )

                    page_data = (
                        self.buffer.fetch_page(
                            data_page_id
                        )
                    )

                    try:
                        page = SlottedPage.from_bytes(
                            page_data
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
                                    slot_no
                                ),
                                record
                            )

                    finally:
                        self.buffer.unpin_page(
                            data_page_id,
                            is_dirty=False
                        )

                next_directory_page = (
                    directory.next_dir_page
                )

            finally:
                self.buffer.unpin_page(
                    directory_page_id,
                    is_dirty=False
                )

            if (
                next_directory_page
                == NO_NEXT_PAGE
            ):
                break

            directory_page_id = (
                next_directory_page
            )