from pathlib import Path
from storage.page import PAGE_SIZE

class DiskManager:
    """
    Reads, writes, and allocates fixed-size 4096-byte pages
    inside one database file.
    """
    def __init__(self, file_path):
        self.file_path = Path(file_path)

        #Make the parent directory if necessary.
        self.file_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        #Create the file if it does not already exist.
        self.file_path.touch(exist_ok=True)
        self.reads = 0
        self.writes = 0

        #Database files must contain complete 4096-byte pages.
        size = self.file_path.stat().st_size
        if size % PAGE_SIZE != 0:
            raise ValueError(
                "Database file size is not a multiple of 4096 bytes."
            )

    # Number of pages
    def num_pages(self):
        """
        Return the number of 4096-byte pages currently in the file.
        """
        return self.file_path.stat().st_size // PAGE_SIZE

    # Allocate
    def allocate_page(self):
        """
        Add one new zero-filled page to the end of the file.

        Returns:
            the new page_id
        """

        page_id = self.num_pages()

        new_size = (page_id + 1) * PAGE_SIZE

        #Extend the file the newly allocated bytes are zero-filled.
        with self.file_path.open("r+b") as db_file:
            db_file.truncate(new_size)

        return page_id

    # Read
    def read_page(self, page_id):
        """
        Read exactly one 4096-byte page.
        """
        self._validate_page_id(page_id)

        offset = page_id * PAGE_SIZE

        with self.file_path.open("rb") as db_file:
            db_file.seek(offset)
            data = db_file.read(PAGE_SIZE)

        if len(data) != PAGE_SIZE:
            raise IOError(
                f"Page {page_id} could not be read completely."
            )

        self.reads += 1

        return data

    # Write
    def write_page(self, page_id, page_data):
        """
        Write exactly one 4096-byte page.
        """

        self._validate_page_id(page_id)

        if len(page_data) != PAGE_SIZE:
            raise ValueError(
                "A disk page must contain exactly 4096 bytes."
            )

        offset = page_id * PAGE_SIZE

        with self.file_path.open("r+b") as db_file:
            db_file.seek(offset)
            db_file.write(page_data)

        self.writes += 1

    # Validation  
    def _validate_page_id(self, page_id):
        if not isinstance(page_id, int):
            raise TypeError("page_id must be an integer.")

        if page_id < 0 or page_id >= self.num_pages():
            raise IndexError(
                f"Invalid page id: {page_id}"
            )

    # Statistics
    def stats(self):
        return {
            "reads": self.reads,
            "writes": self.writes
        }