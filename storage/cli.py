import argparse
import json
import sys
from pathlib import Path

from storage.buffer import BufferPool
from storage.catalog import Catalog
from storage.directory import DirectoryPage, NO_NEXT_PAGE
from storage.disk import DiskManager
from storage.heap import HeapFile
from storage.loader import TableLoader
from storage.page import PAGE_SIZE, SlottedPage
from storage.record import decode_record

# Schema parsing
def parse_schema(schema_text):
    """
    Convert:

        a:INT,b:VARCHAR(20),c:INT

    into:

        [
            ("a", "INT"),
            ("b", "VARCHAR", 20),
            ("c", "INT")
        ]
    """

    if not schema_text.strip():
        raise ValueError("Schema cannot be empty.")

    schema = []

    for raw_column in schema_text.split(","):

        raw_column = raw_column.strip()

        if ":" not in raw_column:
            raise ValueError(
                f"Invalid column definition: {raw_column}"
            )

        name, type_text = raw_column.split(":", 1)

        name = name.strip()
        type_text = type_text.strip().upper()

        if not name:
            raise ValueError(
                "Column name cannot be empty."
            )

        # INT
        if type_text == "INT":

            schema.append(
                (name, "INT")
            )

        # VARCHAR(n)
        elif (
            type_text.startswith("VARCHAR(")
            and type_text.endswith(")")
        ):

            length_text = type_text[
                len("VARCHAR("):-1
            ]

            try:
                length = int(length_text)

            except ValueError:
                raise ValueError(
                    f"Invalid VARCHAR length: {type_text}"
                )

            if length < 1 or length > 255:
                raise ValueError(
                    "VARCHAR length must be "
                    "between 1 and 255."
                )

            schema.append(
                (
                    name,
                    "VARCHAR",
                    length
                )
            )

        else:
            raise ValueError(
                f"Unsupported type: {type_text}"
            )

    return schema

# create-table
def command_create_table(args):
    catalog = Catalog(
        args.db,
        frames=8
    )

    schema = parse_schema(
        args.schema
    )

    entry = catalog.create_table(
        args.name,
        schema
    )

    catalog.flush()

    print(
        f"Created table {entry['name']} "
        f"with file {entry['file']}."
    )

# load
def command_load(args):
    catalog = Catalog(
        args.db,
        frames=8
    )

    loader = TableLoader(
        catalog,
        frames=8
    )

    result = loader.load(
        args.table,
        args.file
    )

    print(
        f"Loaded {result['rows_loaded']} rows "
        f"into {result['table']}."
    )

# scan
def command_scan(args):

    catalog = Catalog(
        args.db,
        frames=args.frames
    )

    metadata = catalog.get_table(
        args.table
    )

    table_path = (
        Path(args.db)
        / metadata["file"]
    )

    disk = DiskManager(
        table_path
    )

    pool = BufferPool(
        disk,
        frames=args.frames,
        policy="lru"
    )

    heap = HeapFile(
        args.table,
        disk,
        pool
    )

    rows = []

    scan_iterator = heap.scan()

    try:
        for _, raw_record in scan_iterator:

            row = decode_record(
                metadata["schema"],
                raw_record
            )

            rows.append(
                list(row)
            )

            if (
                args.limit is not None
                and len(rows) >= args.limit
            ):
                break

    finally:

        # Important if --limit stops a scan early then force the generator's finally blocks to unpin its pages.
        scan_iterator.close()

    result = {
        "table": args.table,
        "schema": metadata["schema"],
        "rows": rows,
        "stats": pool.stats()
    }

    if args.json:

        print(
            json.dumps(
                result,
                separators=(",", ":")
            )
        )

    else:

        print(
            f"Table: {args.table}"
        )

        print(
            f"Schema: {metadata['schema']}"
        )

        for row in rows:
            print(row)

        print(
            f"Stats: {pool.stats()}"
        )


# layout
def _directory_page_ids(disk):
    """
    Follow the directory-page linked list so we can
    distinguish directory pages from data pages.
    """

    result = set()

    if disk.num_pages() == 0:
        return result

    page_id = 0

    while page_id != NO_NEXT_PAGE:

        if page_id in result:
            raise RuntimeError(
                "Directory-page cycle detected."
            )

        if (
            page_id < 0
            or page_id >= disk.num_pages()
        ):
            raise RuntimeError(
                "Invalid directory-page link."
            )

        result.add(page_id)

        raw = disk.read_page(
            page_id
        )

        directory = (
            DirectoryPage.from_bytes(raw)
        )

        page_id = (
            directory.next_dir_page
        )

    return result

def command_layout(args):
    catalog = Catalog(
        args.db,
        frames=8
    )

    metadata = catalog.get_table(
        args.table
    )

    table_path = (
        Path(args.db)
        / metadata["file"]
    )

    disk = DiskManager(
        table_path
    )

    if (
        args.page < 0
        or args.page >= disk.num_pages()
    ):
        raise ValueError(
            f"Page {args.page} does not exist."
        )

    directory_ids = (
        _directory_page_ids(disk)
    )

    raw = disk.read_page(
        args.page
    )

    # Directory page
    if args.page in directory_ids:
        page = DirectoryPage.from_bytes(
            raw
        )

        print(
            f"page_id: {page.page_id}"
        )

        print(
            "page_type: directory"
        )

        print(
            f"next_dir_page: "
            f"{page.next_dir_page}"
        )

        print(
            f"entry_count: "
            f"{page.entry_count}"
        )

        for entry_no in range(
            page.entry_count
        ):

            data_page_id, free_bytes = (
                page.get_entry(entry_no)
            )

            print(
                f"entry {entry_no}: "
                f"data_page_id={data_page_id}, "
                f"free_bytes={free_bytes}"
            )

    # Data page
    else:

        page = SlottedPage.from_bytes(
            raw
        )

        print(
            f"page_id: {page.page_id}"
        )

        print(
            "page_type: data"
        )

        print(
            f"slot_count: "
            f"{page.slot_count}"
        )

        print(
            f"free_end: "
            f"{page.free_end}"
        )

        print(
            f"free_space: "
            f"{page.free_space()}"
        )

        for slot_no in range(
            page.slot_count
        ):

            offset, length = (
                page._read_slot(
                    slot_no
                )
            )

            print(
                f"slot {slot_no}: "
                f"({offset},{length})"
            )


# Trace support
class TraceDiskManager:
    """
    Synthetic disk used by the trace command.

    The trace command only needs page references;
    it does not need real table contents.
    """

    def __init__(self):

        self.reads = 0
        self.writes = 0

    def read_page(self, page_id):

        if (
            not isinstance(page_id, int)
            or page_id < 0
        ):
            raise ValueError(
                f"Invalid trace page id: {page_id}"
            )

        self.reads += 1

        return bytes(PAGE_SIZE)

    def write_page(
        self,
        page_id,
        data
    ):

        if len(data) != PAGE_SIZE:
            raise ValueError(
                "Trace page must be 4096 bytes."
            )

        self.writes += 1


def command_trace(args):
    trace_path = Path(
        args.file
    )

    if not trace_path.exists():
        raise FileNotFoundError(
            f"Trace file not found: "
            f"{trace_path}"
        )

    page_ids = []

    with trace_path.open(
        "r",
        encoding="utf-8"
    ) as file:

        for line_number, line in enumerate(
            file,
            start=1
        ):

            line = line.strip()

            if not line:
                continue

            try:
                page_id = int(line)

            except ValueError:
                raise ValueError(
                    f"Line {line_number}: "
                    "page id must be an integer."
                )

            if page_id < 0:
                raise ValueError(
                    f"Line {line_number}: "
                    "page id cannot be negative."
                )

            page_ids.append(
                page_id
            )

    disk = TraceDiskManager()

    pool = BufferPool(
        disk,
        frames=args.frames,
        policy=args.policy
    )

    # Professor specifies that fetch each page and immediately unpin clean.
    for page_id in page_ids:

        pool.fetch_page(
            page_id
        )

        pool.unpin_page(
            page_id,
            is_dirty=False
        )

    stats = pool.stats()

    result = {
        "policy": args.policy,
        "frames": args.frames,
        "hits": stats["hits"],
        "misses": stats["misses"],
        "evictions": stats["evictions"],
        "reads": stats["reads"],
        "writes": stats["writes"]
    }

    if args.json:

        print(
            json.dumps(
                result,
                separators=(",", ":")
            )
        )

    else:

        print(
            f"Policy: {args.policy}"
        )

        print(
            f"Frames: {args.frames}"
        )

        print(
            f"Hits: {stats['hits']}"
        )

        print(
            f"Misses: {stats['misses']}"
        )

        print(
            f"Evictions: {stats['evictions']}"
        )

        print(
            f"Reads: {stats['reads']}"
        )

        print(
            f"Writes: {stats['writes']}"
        )


# Argument parser
def build_parser():

    parser = argparse.ArgumentParser(
        prog="storage"
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True
    )

    # create-table
    create_parser = (
        commands.add_parser(
            "create-table"
        )
    )

    create_parser.add_argument(
        "--db",
        required=True
    )

    create_parser.add_argument(
        "--name",
        required=True
    )

    create_parser.add_argument(
        "--schema",
        required=True
    )

    create_parser.set_defaults(
        function=command_create_table
    )

    # load
    load_parser = (
        commands.add_parser(
            "load"
        )
    )

    load_parser.add_argument(
        "--db",
        required=True
    )

    load_parser.add_argument(
        "--table",
        required=True
    )

    load_parser.add_argument(
        "--file",
        required=True
    )

    load_parser.set_defaults(
        function=command_load
    )

    # scan
    scan_parser = (
        commands.add_parser(
            "scan"
        )
    )

    scan_parser.add_argument(
        "--db",
        required=True
    )

    scan_parser.add_argument(
        "--table",
        required=True
    )

    scan_parser.add_argument(
        "--frames",
        required=True,
        type=int
    )

    scan_parser.add_argument(
        "--limit",
        type=int
    )

    scan_parser.add_argument(
        "--json",
        action="store_true"
    )

    scan_parser.set_defaults(
        function=command_scan
    )

    # layout
    layout_parser = (
        commands.add_parser(
            "layout"
        )
    )

    layout_parser.add_argument(
        "--db",
        required=True
    )

    layout_parser.add_argument(
        "--table",
        required=True
    )

    layout_parser.add_argument(
        "--page",
        required=True,
        type=int
    )

    layout_parser.set_defaults(
        function=command_layout
    )

    # trace
    trace_parser = (
        commands.add_parser(
            "trace"
        )
    )

    trace_parser.add_argument(
        "--db",
        required=True
    )

    trace_parser.add_argument(
        "--file",
        required=True
    )

    trace_parser.add_argument(
        "--frames",
        required=True,
        type=int
    )

    trace_parser.add_argument(
        "--policy",
        required=True,
        choices=[
            "lru",
            "clock"
        ]
    )

    trace_parser.add_argument(
        "--json",
        action="store_true"
    )

    trace_parser.set_defaults(
        function=command_trace
    )

    return parser

# Main
def main(argv=None):

    parser = build_parser()

    args = parser.parse_args(
        argv
    )

    try:

        args.function(args)

        return 0

    except Exception as error:

        print(
            f"error: {error}",
            file=sys.stderr
        )

        return 1


if __name__ == "__main__":

    raise SystemExit(
        main()
    )