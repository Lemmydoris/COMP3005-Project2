# COMP 3005 Project 2 — Module 1 Design

## Storage Engine and Buffer Pool

### 1. Overview

Module 1 implements the storage layer of the database system. The implementation stores tables on disk using fixed-size 4096-byte pages and accesses those pages through a buffer pool.

The main components are:

- DiskManager — reads, writes, and allocates 4096-byte pages.
- SlottedPage — stores variable-length records inside data pages.
- DirectoryPage — records which data pages belong to a heap file and how much free space each page has.
- HeapFile — provides record insertion, retrieval, deletion, and scanning.
- BufferPool — manages a fixed number of memory frames using either LRU or CLOCK replacement.
- Catalog — stores table metadata in catalog.db.
- TableLoader — converts CSV rows into encoded records and inserts them into the appropriate heap file.
- storage CLI — exposes the required create table, load, scan, layout, and trace commands.

Each table is stored in its own file named <table>.db, while metadata for all tables is stored in catalog.db.

## 2. Record Format
Records do not contain a record header or NULL bitmap because NULL values are not supported.
The encoding is based entirely on the table schema.

### INT
An INT is stored using:
- 4 bytes
- signed two's-complement representation
- little-endian byte order

### VARCHAR(n)
A VARCHAR(n) is stored as:
- 2-byte unsigned length L
- followed by L UTF-8 bytes

-The implementation validates that the UTF-8 byte length does not exceed the declared maximum n, where n <= 255.

For example, for the schema: a:INT,b:VARCHAR(20),c:INT

the tuple: (42, "bob", 7)

requires 13 bytes: 2A 00 00 00 03 00 62 6F 62 07 00 00 00

## 3. Slotted Data Page Format
Every page is exactly 4096 bytes.
The data page has the following layout:

offset    size      field
------    ----      -----
0         4         page_id
4         2         slot_count
6         2         free_end
8         4         slot 0
12        4         slot 1
...                 additional slots
                    free space
free_end            record data
4095                end of page


Each slot consists of:
    - uint16 offset
    - uint16 length


The header and slot directory grow forward from the beginning of the page, while record bytes grow backward from byte 4095.

- The available free space is calculated as: free_space = free_end - (8 + 4 * slot_count)

- A new record of length `L` therefore requires: L + 4 bytes because four additional bytes are required for the new slot.

Slot numbers are never reused or renumbered so that an existing RID remains stable.

- A record ID is represented as: (page_id, slot_number)

## 4. Free-Space Strategy
- The heap file uses directory pages to track free space in its data pages.

- Each directory entry contains:
    - data_page_id
    - free_bytes

- The directory page layout is:

offset    size      field
------    ----      -----
0         4         page_id
4         4         next_dir_page
8         2         entry_count
10        6         entry 0
16        6         entry 1
...                 additional entries

- Each entry consists of:
    - uint32 data_page_id
    - uint16 free_bytes

- A directory page can hold:
    floor((4096 - 10) / 6) = 681 entries

- Page 0 of every table file is the first directory page.

### First-Fit Policy
- Insertion uses a first-fit strategy.
- For a record of length L, the heap file walks the directory pages in order and chooses the first data page where: free_bytes >= L + 4

If a suitable page is found:
1. The data page is fetched through the buffer pool.
2. The record is inserted.
3. The directory entry is updated with the page's new free-space value.
4. Both pages are unpinned.

- If no existing data page has enough space, a new data page is allocated and added to the directory.
- If the current directory page already contains 681 entries, another directory page is allocated and linked through next_dir_page.
- This strategy was chosen because it follows the required heap-file behavior while avoiding the need to scan every data page to discover its free space.


## 5. Deletion and Compaction Decision
- Compaction is not implemented in Module 1.
- When a record is deleted, its slot becomes: (0, 0)
- The original record bytes remain physically present in the page, but they are no longer accessible.
- The deleted space is not reclaimed. This means that deleting a record does not increase the amount of usable free space on the page.
- I chose not to implement optional compaction because the required implementation already supports correct record insertion, retrieval, deletion, RID stability, and scanning without it. Avoiding compaction also keeps page offsets stable and reduces unnecessary page movement.
- A scan ignores every slot whose offset is 0.

## 6. Heap File Design
A table heap file is organized as a linked collection of directory pages and data pages.

For example:

```text
R.db

Page 0
└── DirectoryPage
    ├── entry 0 -> Page 1
    ├── entry 1 -> Page 2
    └── ...

Page 1
└── SlottedPage containing records

Page 2
└── SlottedPage containing records
```

The heap file supports four primary operations.

### Insert

```text
insert(record) -> (page_id, slot_no)
```

The directory is searched using first fit. If no existing page has enough space, a new data page is allocated.

### Get

```text
get(rid) -> record
```

The requested data page is fetched through the buffer pool, the slot is read, and the page is unpinned.

Attempting to read a deleted or invalid RID produces an error that identifies the RID.

### Delete

```text
delete(rid)
```

The slot is changed to `(0, 0)`. The directory's free-space value is updated, although without compaction the deleted record bytes do not become reusable.

### Scan

```text
scan() -> iterator of (rid, record)
```

Scanning is implemented as a generator instead of reading the entire relation into memory.

At most:

```text
1 directory page
+
1 data page
=
2 pinned pages
```

are needed at any instant during a scan.

The data page is unpinned before moving to the next data page.

This allows relations substantially larger than the buffer pool to be scanned without loading the entire table into memory.

---

## 7. Buffer Pool Design

The buffer pool contains exactly `B` frames.

Each frame stores:

- page ID
- page bytes
- pin count
- dirty flag
- CLOCK reference bit

The page table maps:

```text
page_id -> frame index
```

### Fetch

If a requested page is already resident:

```text
pin_count += 1
```

and the access is counted as a hit.

If it is not resident, an unpinned frame is selected.

If a dirty victim must be replaced, it is written to disk first.

The requested page is then read from disk and pinned.

A miss is counted only when a disk read actually occurs.

If every frame is pinned, the operation fails with:

```text
no unpinned frame available
```

and no page is evicted.

### Unpin

Unpinning decreases the frame's pin count.

If `is_dirty=True`, the frame remains marked dirty.

Attempting to unpin a page whose pin count is already zero is an error.

### New Page

`new_page()` creates a new 4096-byte zero-filled page.

The new page is:

- resident in the buffer pool
- pinned
- dirty

Creating a new page does not require reading it from disk.

### Flush

`flush_all()` writes every dirty resident page to disk and clears the dirty flags.

---

## 8. Replacement Policies

Two replacement policies are supported.

### LRU

LRU maintains frames in order of most recent access.

Every hit or successful miss moves the frame to the most recently used position.

When replacement is necessary, the least recently used unpinned frame is selected.

For the required trace:

```text
B = 3

1 2 3 1 4 2
```

the implementation produces:

```text
hits       = 1
misses     = 5
evictions  = 2
```

### CLOCK

CLOCK uses:

- a circular collection of frames
- one reference bit per frame
- a CLOCK hand

Every successful access sets the reference bit to 1.

When choosing a victim, pinned frames are skipped and unpinned frames with reference bit 1 receive a second chance by having their reference bit cleared.

For the same required trace:

```text
1 2 3 1 4 2
```

the implementation produces:

```text
hits       = 2
misses     = 4
evictions  = 1
```

Both results are covered by automated tests.

---

## 9. Disk I/O Counters

The buffer pool maintains deterministic counters:

```text
hits
misses
evictions
reads
writes
```

The rules used are:

- A hit occurs when `fetch_page` finds the page already resident.
- A miss occurs only if the fetch requires a disk read.
- An eviction occurs when a miss replaces an existing resident page.
- A read corresponds to one disk-manager read operation.
- A write corresponds to one disk-manager write operation.

The initial misses that occupy previously empty frames are not counted as evictions.

Repeated scans of the same database using fresh buffer pools produce identical counters.

---

## 10. Catalog Design

The catalog is stored in:

```text
catalog.db
```

and is itself accessed through a normal buffer pool and heap file.

I chose an **append-only catalog design**.

Each metadata entry is serialized as compact UTF-8 JSON and stored as a catalog heap-file record.

A table entry contains:

```text
{
    "name": table name,
    "schema": ordered column definitions,
    "file": table data filename,
    "num_pages": current page count,
    "num_tuples": current live tuple count,
    "statistics": {}
}
```

For example:

```text
{
    "name": "R",
    "schema": [
        ["a", "INT"],
        ["b", "VARCHAR", 20],
        ["c", "INT"]
    ],
    "file": "R.db",
    "num_pages": 2,
    "num_tuples": 2,
    "statistics": {}
}
```

When metadata changes, such as after loading records, a newer metadata version is appended.

When the catalog is read, records are processed in heap order and the newest entry for each table becomes authoritative.

This avoids in-place variable-length catalog record updates.

The empty `statistics` object is reserved for the statistics required by Module 4.

---

## 11. CSV Loading

The loader reads CSV files with:

- no header
- one record per line
- comma-separated fields
- standard double-quoted CSV fields

For example:

```text
42,bob,7
43,"amy,lee",9
```

The second row still contains three fields because `"amy,lee"` is quoted.

Each field is validated according to the table schema.

An invalid `INT` reports the line and column.

A `VARCHAR` longer than its declared maximum reports the line and column.

A record larger than the maximum storable page record size reports the table and row.

Loading stops when an invalid row is encountered.

Records successfully inserted before the invalid row remain stored. Transaction rollback is not implemented in Module 1.

After loading, the catalog is updated with the table's new:

```text
num_pages
num_tuples
```

---

## 12. Command-Line Interface

The storage engine exposes the required commands:

```text
storage create-table --db DIR --name R --schema "a:INT,b:VARCHAR(20),c:INT"

storage load --db DIR --table R --file r.csv

storage scan --db DIR --table R --frames 8 --json

storage layout --db DIR --table R --page 3

storage trace --db DIR --file trace.txt --frames 16 --policy lru|clock --json
```

The implementation can currently be invoked using:

```text
python -m storage
```

The `scan --json` result contains:

```text
table
schema
rows
stats
```

The trace result contains:

```text
policy
frames
hits
misses
evictions
reads
writes
```

---

## 13. Byte-Level Example from an Actual Database Page
- To verify the page design against an actual file generated by my implementation, I created a table with the schema: a:INT,b:VARCHAR(20),c:INT
and loaded the following CSV row: 42,bob,7
- I then inspected page 1 of the generated R.db file using: "python -m storage layout --db m1_design_demo --table R --page 1" 

The implementation produced:
page_id: 1
page_type: data
slot_count: 1
free_end: 4083
free_space: 4071
slot 0: (4083,13)

The record (42, "bob", 7) is encoded as 13 bytes: 2A 00 00 00 03 00 62 6F 62 07 00 00 00

The corresponding real page layout is therefore:

Byte
Offset
0    ┌──────────────────────────────┐
     │ page_id = 1                  │ 4 bytes
4    ├──────────────────────────────┤
     │ slot_count = 1               │ 2 bytes
6    ├──────────────────────────────┤
     │ free_end = 4083              │ 2 bytes
8    ├──────────────────────────────┤
     │ slot 0 offset = 4083         │ 2 bytes
10   │ slot 0 length = 13           │ 2 bytes
12   ├──────────────────────────────┤
     │                              │
     │                              │
     │         FREE SPACE           │
     │         4071 bytes           │
     │                              │
     │                              │
4083 ├──────────────────────────────┤
     │ 2A 00 00 00                  │ a = 42
4087 │ 03 00 62 6F 62               │ b = "bob"
4092 │ 07 00 00 00                  │ c = 7
4095 └──────────────────────────────┘

This confirms that the implementation matches the required slotted-page structure: the header and slot directory grow forward from the beginning of the page, while record data grows backward from the end of the page.

For this page:
free_space
= free_end - (8 + 4 × slot_count)
= 4083 - (8 + 4 × 1)
= 4083 - 12
= 4071 bytes

The values reported by the implemented layout command therefore agree exactly with the expected byte-level calculation.

## 14. Testing

The implementation currently passes 74 automated tests.

These tests include:

- the required slotted-page worked example
- exact record encoding
- LRU replacement
- CLOCK replacement
- pinned-page eviction failure
- unpin-at-zero error
- disk persistence
- directory page serialization
- heap insertion and retrieval
- deletion
- empty scan after deleting every record
- 240-record page-capacity test
- scanning a table 20 times larger than the buffer budget
- maximum of two pages pinned during scanning
- catalog persistence
- CSV loading
- quoted commas
- invalid "INT" handling
- oversized "VARCHAR" handling
- oversized records
- deterministic scan counters
- command-line JSON output
- required trace behavior

At the end of Module 1 implementation:

Ran 74 tests
OK

This test suite is used to verify both correctness and the deterministic behavior required for later measurement experiments.