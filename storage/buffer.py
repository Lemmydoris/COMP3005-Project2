from dataclasses import dataclass, field
from storage.page import PAGE_SIZE

@dataclass
class Frame:
    page_id: int | None = None

    data: bytearray = field(
        default_factory=lambda: bytearray(PAGE_SIZE)
    )

    pin_count: int = 0
    dirty: bool = False

    # Used by CLOCK.
    ref_bit: int = 0

class BufferPool:
    """
    Fixed-size buffer pool.

    Supported replacement policies:
        lru
        clock
    """

    def __init__(self, disk_manager, frames, policy="lru"):

        if frames <= 0:
            raise ValueError(
                "Buffer pool must have at least one frame."
            )

        policy = policy.lower()

        if policy not in ("lru", "clock"):
            raise ValueError(
                "Policy must be 'lru' or 'clock'."
            )

        self.disk = disk_manager
        self.capacity = frames
        self.policy = policy

        self.frames = [
            Frame()
            for _ in range(frames)
        ]

        # page_id -> frame index
        self.page_table = {}

        # Used by LRU: least recent -> most recent
        self.lru_order = []

        # Used by CLOCK.
        self.clock_hand = 0

        self.hits = 0
        self.misses = 0
        self.evictions = 0

    # LRU
    def _mark_lru_recent(self, frame_index):

        if frame_index in self.lru_order:
            self.lru_order.remove(frame_index)

        self.lru_order.append(frame_index)

    def _choose_lru_victim(self):

        for frame_index in self.lru_order:

            frame = self.frames[frame_index]

            if frame.pin_count == 0:
                return frame_index

        return None

    # CLOCK
    def _choose_clock_victim(self):
        """
        Follow the CLOCK algorithm required by the
        Module 1 specification.
        """
        swept = 0
        while True:

            frame_index = self.clock_hand
            frame = self.frames[frame_index]
            # Pinned pages cannot be evicted.
            if frame.pin_count > 0:

                self.clock_hand = (
                    self.clock_hand + 1
                ) % self.capacity

                swept += 1

            # Give recently used pages another chance.
            elif frame.ref_bit == 1:

                frame.ref_bit = 0

                self.clock_hand = (
                    self.clock_hand + 1
                ) % self.capacity

                swept += 1

            else:
                # Found the victim.
                self.clock_hand = (
                    self.clock_hand + 1
                ) % self.capacity

                return frame_index

            if swept > 2 * self.capacity:
                return None

    # Empty frame handling
    def _find_empty_frame(self):

        # LRU can simply use the first empty frame.
        if self.policy == "lru":

            for index, frame in enumerate(self.frames):

                if frame.page_id is None:
                    return index

            return None

        # CLOCK loads empty frames in hand order.
        for _ in range(self.capacity):

            index = self.clock_hand
            frame = self.frames[index]

            if frame.page_id is None:
                # Newly loaded page means the hand moves past that frame.
                self.clock_hand = (
                    self.clock_hand + 1
                ) % self.capacity

                return index

            self.clock_hand = (
                self.clock_hand + 1
            ) % self.capacity

        return None

    # Access notification
    def _on_access(self, frame_index):

        if self.policy == "lru":

            self._mark_lru_recent(frame_index)

        else:
            # Every CLOCK hit or miss sets ref = 1.
            self.frames[frame_index].ref_bit = 1

    # Fetch page
    def fetch_page(self, page_id):
        # HIT
        if page_id in self.page_table:

            frame_index = self.page_table[page_id]
            frame = self.frames[frame_index]

            frame.pin_count += 1

            self.hits += 1

            self._on_access(frame_index)

            return frame.data

        # Try an unused frame first.
        frame_index = self._find_empty_frame()

        replacing_page = False

        # No empty frame you have to choose a victim.
        if frame_index is None:
            if self.policy == "lru":
                frame_index = self._choose_lru_victim()

            else:
                frame_index = self._choose_clock_victim()

            if frame_index is None:
                raise RuntimeError(
                    "no unpinned frame available"
                )

            replacing_page = True

        frame = self.frames[frame_index]

        #Eviction
        if replacing_page:
            old_page_id = frame.page_id

            #Dirty page must be written before removal.
            if frame.dirty:

                self.disk.write_page(
                    old_page_id,
                    bytes(frame.data)
                )

            del self.page_table[old_page_id]

            self.evictions += 1

        # We only count a miss once we know this fetch will actually require a disk read.
        self.misses += 1
        #Disk read
        raw_page = self.disk.read_page(page_id)

        frame.page_id = page_id
        frame.data = bytearray(raw_page)
        frame.pin_count = 1
        frame.dirty = False
        frame.ref_bit = 0

        self.page_table[page_id] = frame_index

        #Mark page as recently accessed.
        self._on_access(frame_index)

        return frame.data

    # New page
    def new_page(self):
        """
        Allocate a brand-new disk page and place it
        in the buffer pool.

        The new page is:
            - zero-filled
            - pinned
            - dirty

        It does NOT require a disk read.
        """
        # First we find an empty frame.
        frame_index = self._find_empty_frame()

        replacing_page = False

        # If the pool is full, choose an unpinned victim.
        if frame_index is None:
            if self.policy == "lru":
                frame_index = self._choose_lru_victim()
            else:
                frame_index = self._choose_clock_victim()

            if frame_index is None:
                raise RuntimeError(
                    "no unpinned frame available"
                )
            replacing_page = True

        frame = self.frames[frame_index]

        # If a page is being replaced, flush it first if it is dirty.
        if replacing_page:
            old_page_id = frame.page_id

            if frame.dirty:
                self.disk.write_page(
                    old_page_id,
                    bytes(frame.data)
                )

            del self.page_table[old_page_id]

        # Allocate the next page ID on disk.
        new_page_id = self.disk.allocate_page()

        # Important note: there is no disk.read_page() here. A new page starts as all zero bytes.
        frame.page_id = new_page_id
        frame.data = bytearray(PAGE_SIZE)
        frame.pin_count = 1
        frame.dirty = True
        frame.ref_bit = 0

        self.page_table[new_page_id] = frame_index

        self._on_access(frame_index)

        return frame.data

    #Unpin
    def unpin_page(self, page_id, is_dirty=False):

        if page_id not in self.page_table:
            raise ValueError(
                f"Page {page_id} is not resident."
            )

        frame_index = self.page_table[page_id]
        frame = self.frames[frame_index]

        if frame.pin_count == 0:
            raise ValueError(
                f"Page {page_id} has pin count 0."
            )

        if is_dirty:
            frame.dirty = True

        frame.pin_count -= 1

    #Flush
    def flush_all(self):

        for frame in self.frames:

            if (
                frame.page_id is not None
                and frame.dirty
            ):

                self.disk.write_page(
                    frame.page_id,
                    bytes(frame.data)
                )

                frame.dirty = False

    #Statistics
    def stats(self):

        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "reads": self.disk.reads,
            "writes": self.disk.writes
        }