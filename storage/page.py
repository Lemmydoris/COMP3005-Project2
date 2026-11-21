import struct

PAGE_SIZE = 4096
HEADER_SIZE = 8
SLOT_SIZE = 4
NO_SPACE = -1

class SlottedPage:
    """
    Represents one 4096-byte slotted page.

    Page layout:
        bytes 0-3 : page_id
        bytes 4-5 : slot_count
        bytes 6-7 : free_end
        bytes 8+  : slot directory

    Record data grows backward from the end of the page.
    """

    def __init__(self, page_id):
        self.data = bytearray(PAGE_SIZE)

        self._set_page_id(page_id)
        self._set_slot_count(0)
        self._set_free_end(PAGE_SIZE)

    # Header fields

    @property
    def page_id(self):
        return struct.unpack_from("<I", self.data, 0)[0]

    @property
    def slot_count(self):
        return struct.unpack_from("<H", self.data, 4)[0]

    @property
    def free_end(self):
        return struct.unpack_from("<H", self.data, 6)[0]

    def _set_page_id(self, page_id):
        struct.pack_into("<I", self.data, 0, page_id)

    def _set_slot_count(self, slot_count):
        struct.pack_into("<H", self.data, 4, slot_count)

    def _set_free_end(self, free_end):
        struct.pack_into("<H", self.data, 6, free_end)

    # Free-space calculation

    def free_space(self):
        """
        free_end - (8 + 4 * slot_count)
        """
        return self.free_end - (
            HEADER_SIZE + SLOT_SIZE * self.slot_count
        )

    # Slot helpers

    def _slot_position(self, slot_no):
        return HEADER_SIZE + (slot_no * SLOT_SIZE)

    def _read_slot(self, slot_no):
        if slot_no < 0 or slot_no >= self.slot_count:
            raise IndexError("Invalid slot number.")

        position = self._slot_position(slot_no)

        offset, length = struct.unpack_from(
            "<HH",
            self.data,
            position
        )

        return offset, length

    def _write_slot(self, slot_no, offset, length):
        position = self._slot_position(slot_no)

        struct.pack_into(
            "<HH",
            self.data,
            position,
            offset,
            length
        )

    # Required page operations

    def insert(self, record):
        """
        Insert raw record bytes.

        Returns:
            slot number on success
            NO_SPACE (-1) if the record does not fit
        """

        if not isinstance(record, (bytes, bytearray)):
            raise TypeError("Record must be bytes.")

        record_length = len(record)

        # A new record also needs a new 4-byte slot.
        if self.free_space() < record_length + SLOT_SIZE:
            return NO_SPACE

        slot_no = self.slot_count

        new_free_end = self.free_end - record_length

        # Write record data at the back of the page.
        self.data[
            new_free_end:new_free_end + record_length
        ] = record

        # Adding its slot entry.
        self._write_slot(
            slot_no,
            new_free_end,
            record_length
        )

        self._set_free_end(new_free_end)
        self._set_slot_count(slot_no + 1)

        return slot_no

    def get(self, slot_no):
        """
        Return the raw bytes stored in a slot.
        """

        offset, length = self._read_slot(slot_no)

        if offset == 0:
            raise ValueError("Record has been deleted.")

        return bytes(
            self.data[offset:offset + length]
        )

    def delete(self, slot_no):
        """
        Mark a slot as dead.

        Space is NOT reclaimed.
        """

        offset, _ = self._read_slot(slot_no)

        if offset == 0:
            raise ValueError("Record is already deleted.")

        self._write_slot(slot_no, 0, 0)

    # This will be Useful for later disk storage
    def to_bytes(self):
        return bytes(self.data)

    @classmethod
    def from_bytes(cls, raw_page):
        if len(raw_page) != PAGE_SIZE:
            raise ValueError(
                "A page must contain exactly 4096 bytes."
            )

        page = cls.__new__(cls)
        page.data = bytearray(raw_page)

        return page