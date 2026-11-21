import os
import tempfile

from storage.disk import DiskManager
from storage.page import SlottedPage
from storage.record import decode_record, encode_record

class TempRun:
    """
    A temporary disk-backed sequence of tuples.

    Each temporary-file page is a normal Module 1 slotted page.
    There is no directory page because a run is scanned strictly
    from page 0 through page N-1.
    """

    def __init__(
        self,
        schema,
        temp_dir=None,
        read_callback=None,
        write_callback=None,
    ):
        self.schema = [
            list(column)
            for column in schema
        ]

        self.read_callback = read_callback
        self.write_callback = write_callback

        handle = tempfile.NamedTemporaryFile(
            prefix="exec_run_",
            suffix=".tmp",
            dir=temp_dir,
            delete=False,
        )

        self.path = handle.name
        handle.close()

        self.disk = DiskManager(self.path)

        self._page = None
        self._finished = False

        self.tuple_count = 0

    def _new_page(self):
        page_id = self.disk.allocate_page()

        self._page = SlottedPage(
            page_id
        )

    def _flush_page(self):
        if self._page is None:
            return

        self.disk.write_page(
            self._page.page_id,
            self._page.to_bytes(),
        )

        if self.write_callback is not None:
            self.write_callback()

        self._page = None

    def append(self, row):
        if self._finished:
            raise RuntimeError(
                "Cannot append to a finished temporary run."
            )

        record = encode_record(
            self.schema,
            row,
        )

        if len(record) > 4088:
            raise ValueError(
                "Tuple is too large for a temporary page."
            )

        if self._page is None:
            self._new_page()

        slot = self._page.insert(record)

        if slot == -1:
            self._flush_page()
            self._new_page()

            slot = self._page.insert(record)

            if slot == -1:
                raise ValueError(
                    "Tuple is too large for a temporary page."
                )

        self.tuple_count += 1

    def finish(self):
        if self._finished:
            return

        self._flush_page()
        self._finished = True

    def rows(self):
        """
        Stream the run one page at a time.
        """

        self.finish()

        for page_id in range(
            self.disk.num_pages()
        ):
            raw = self.disk.read_page(
                page_id
            )

            if self.read_callback is not None:
                self.read_callback()

            page = SlottedPage.from_bytes(
                raw
            )

            for slot_no in range(
                page.slot_count
            ):
                record = page.get(
                    slot_no
                )

                if record is None:
                    continue

                yield tuple(
                    decode_record(
                        self.schema,
                        record,
                    )
                )

    def delete(self):
        self._page = None

        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass