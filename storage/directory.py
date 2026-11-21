import struct
from storage.page import PAGE_SIZE

DIRECTORY_HEADER_SIZE = 10
DIRECTORY_ENTRY_SIZE = 6
NO_NEXT_PAGE = 0xFFFFFFFF
MAX_DIRECTORY_ENTRIES = (
    PAGE_SIZE - DIRECTORY_HEADER_SIZE
) // DIRECTORY_ENTRY_SIZE

class DirectoryPage:
    """
    Directory page for a heap file.

    Exact layout:

        offset 0 : page_id          uint32
        offset 4 : next_dir_page    uint32
        offset 8 : entry_count      uint16
        offset 10: entries

    Each entry:
        data_page_id    uint32
        free_bytes      uint16
    """

    def __init__(self, page_id):
        self.data = bytearray(PAGE_SIZE)

        self._set_page_id(page_id)
        self._set_next_dir_page(NO_NEXT_PAGE)
        self._set_entry_count(0)

    # Header
    @property
    def page_id(self):
        return struct.unpack_from(
            "<I",
            self.data,
            0
        )[0]

    @property
    def next_dir_page(self):
        return struct.unpack_from(
            "<I",
            self.data,
            4
        )[0]

    @property
    def entry_count(self):
        return struct.unpack_from(
            "<H",
            self.data,
            8
        )[0]

    def _set_page_id(self, page_id):
        struct.pack_into(
            "<I",
            self.data,
            0,
            page_id
        )

    def _set_next_dir_page(self, page_id):
        struct.pack_into(
            "<I",
            self.data,
            4,
            page_id
        )

    def _set_entry_count(self, count):
        struct.pack_into(
            "<H",
            self.data,
            8,
            count
        )

    # Next directory page
    def set_next_dir_page(self, page_id):
        self._set_next_dir_page(page_id)

    # Entries
    def _entry_position(self, entry_no):
        return (
            DIRECTORY_HEADER_SIZE
            + entry_no * DIRECTORY_ENTRY_SIZE
        )

    def get_entry(self, entry_no):
        if (
            entry_no < 0
            or entry_no >= self.entry_count
        ):
            raise IndexError(
                "Invalid directory entry number."
            )

        position = self._entry_position(entry_no)

        data_page_id, free_bytes = struct.unpack_from(
            "<IH",
            self.data,
            position
        )

        return data_page_id, free_bytes

    def add_entry(self, data_page_id, free_bytes):
        """
        Add a data-page entry.
        Returns the new entry number.
        """

        if self.entry_count >= MAX_DIRECTORY_ENTRIES:
            raise OverflowError(
                "Directory page is full."
            )

        entry_no = self.entry_count
        position = self._entry_position(entry_no)

        struct.pack_into(
            "<IH",
            self.data,
            position,
            data_page_id,
            free_bytes
        )

        self._set_entry_count(entry_no + 1)

        return entry_no

    def update_free_bytes(
        self,
        entry_no,
        free_bytes
    ):
        """
        Change only the free-space value for one entry.
        """
        data_page_id, _ = self.get_entry(entry_no)
        position = self._entry_position(entry_no)

        struct.pack_into(
            "<IH",
            self.data,
            position,
            data_page_id,
            free_bytes
        )

    def entries(self):
        """
        Return all directory entries in order.
        """
        result = []
        for entry_no in range(self.entry_count):
            result.append(
                self.get_entry(entry_no)
            )

        return result

    # Serialization
    def to_bytes(self):
        return bytes(self.data)

    @classmethod
    def from_bytes(cls, raw_page):
        if len(raw_page) != PAGE_SIZE:
            raise ValueError(
                "A directory page must contain exactly "
                "4096 bytes."
            )

        page = cls.__new__(cls)
        page.data = bytearray(raw_page)

        return page