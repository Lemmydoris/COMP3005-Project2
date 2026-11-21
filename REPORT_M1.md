# Module 1 Report

## 1. Capacity Measurement

The purpose of this experiment was to compare the theoretical number of records that fit on one 4096-byte data page with the number actually observed in the storage engine.

For a fixed-length record of length `L`, the capacity formula is:

```text id="2rvm5s"
floor(4088 / (L + 4))
```

The additional four bytes are required for the slot entry associated with each record.

| Schema | Record Size | Space per Record Including Slot | Computed Capacity | Measured Capacity |
|---|---:|---:|---:|---:|
| `a:INT,b:INT,c:INT` | 12 bytes | 16 bytes | 255 | 255 |
| `a:INT,b:VARCHAR(10),c:INT` using a 10-byte string | 20 bytes | 24 bytes | 170 | 170 |
| `a:INT,b:VARCHAR(200),c:INT` using a 200-byte string | 210 bytes | 214 bytes | 19 | 19 |

### All-INT Schema

The schema was:

```text id="v5ct7g"
a:INT,b:INT,c:INT
```

Each record contains three 4-byte integers:

```text id="pecoy9"
4 + 4 + 4 = 12 bytes
```

Including the four-byte slot:

```text id="y6oqkr"
12 + 4 = 16 bytes
```

Therefore:

```text id="blxqsq"
floor(4088 / 16)
= 255 records
```

The experiment loaded 260 records. Data page 1 contained 255 records and had only 8 bytes of usable free space remaining. The remaining five records were placed on page 2.

Therefore:

```text id="dgnbsf"
Computed capacity = 255
Measured capacity = 255
```

### Short VARCHAR Schema

The schema was:

```text id="tb6jd2"
a:INT,b:VARCHAR(10),c:INT
```

Every VARCHAR value used in the experiment contained exactly 10 single-byte UTF-8 characters.

The encoded record size was therefore:

```text id="na0f3j"
INT                 = 4
VARCHAR length      = 2
VARCHAR data        = 10
INT                 = 4
                     ----
record size         = 20 bytes
```

Including the four-byte slot:

```text id="mnfnzm"
20 + 4 = 24 bytes
```

Therefore:

```text id="p1ssgx"
floor(4088 / 24)
= 170 records
```

The experiment loaded 175 records. Page 1 contained 170 records with 8 bytes of usable free space remaining, and the other five records were stored on page 2.

Therefore:

```text id="e87d48"
Computed capacity = 170
Measured capacity = 170
```

### VARCHAR(200) Schema

The schema was:

```text id="y6ztqb"
a:INT,b:VARCHAR(200),c:INT
```

Each test value contained exactly 200 single-byte UTF-8 characters.

The encoded record size was:

```text id="luz2ki"
INT                 = 4
VARCHAR length      = 2
VARCHAR data        = 200
INT                 = 4
                     -----
record size         = 210 bytes
```

Including the slot:

```text id="q0g53u"
210 + 4 = 214 bytes
```

Therefore:

```text id="rvjxzg"
floor(4088 / 214)
= 19 records
```

The experiment loaded 25 records. Page 1 contained 19 records and had 22 bytes of usable free space remaining. This was not enough for another 214-byte record-and-slot combination, so the remaining six records were placed on page 2.

Therefore:
id="0rw2cc"
Computed capacity = 19
Measured capacity = 19

### Interpretation

There was no difference between the theoretical and measured capacities for any of the three schemas.

This occurred because the experiment deliberately used fixed-length test values. The INT-only schema was naturally fixed length, while the VARCHAR experiments used strings whose actual lengths were always exactly 10 and 200 bytes respectively. As a result, every record within each experiment had the same encoded size.

The remaining free space on the full first pages was also consistent with the calculations:

```text id="d67rn6"
All INT:
4088 - (255 × 16) = 8 bytes

VARCHAR(10):
4088 - (170 × 24) = 8 bytes

VARCHAR(200):
4088 - (19 × 214) = 22 bytes
```

In all three cases, the remaining space was smaller than the amount required for one additional record and its four-byte slot. The measured results therefore exactly confirm the slotted-page capacity formula used by the implementation.

## 2. Replacement Policy Measurement

The purpose of this experiment was to compare the LRU and CLOCK buffer replacement policies under different workloads and buffer sizes.

Because the companion trace files were not available, I created five documented traces representing different access patterns:

- Trace 1: a four-page working set (`0–3`) repeated 50 times.
- Trace 2: a sequential cycle over 20 pages repeated 10 times.
- Trace 3: a sequential cycle over 80 pages repeated 10 times.
- Trace 4: two frequently accessed hot pages mixed with unique cold pages.
- Trace 5: a phased workload that alternates between two 32-page working sets.

Each trace was run under both LRU and CLOCK using:

```text
B = 4, 16, 64, 256
```

The hit rate was calculated as:

```text
hit rate = hits / (hits + misses)
```

### LRU Results

| Trace | Frames B | Hits | Misses | Evictions | Reads | Hit Rate |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 4 | 196 | 4 | 0 | 4 | 0.9800 |
| 1 | 16 | 196 | 4 | 0 | 4 | 0.9800 |
| 1 | 64 | 196 | 4 | 0 | 4 | 0.9800 |
| 1 | 256 | 196 | 4 | 0 | 4 | 0.9800 |
| 2 | 4 | 0 | 200 | 196 | 200 | 0.0000 |
| 2 | 16 | 0 | 200 | 184 | 200 | 0.0000 |
| 2 | 64 | 180 | 20 | 0 | 20 | 0.9000 |
| 2 | 256 | 180 | 20 | 0 | 20 | 0.9000 |
| 3 | 4 | 0 | 800 | 796 | 800 | 0.0000 |
| 3 | 16 | 0 | 800 | 784 | 800 | 0.0000 |
| 3 | 64 | 0 | 800 | 736 | 800 | 0.0000 |
| 3 | 256 | 720 | 80 | 0 | 80 | 0.9000 |
| 4 | 4 | 398 | 102 | 98 | 102 | 0.7960 |
| 4 | 16 | 398 | 102 | 86 | 102 | 0.7960 |
| 4 | 64 | 398 | 102 | 38 | 102 | 0.7960 |
| 4 | 256 | 398 | 102 | 0 | 102 | 0.7960 |
| 5 | 4 | 0 | 480 | 476 | 480 | 0.0000 |
| 5 | 16 | 0 | 480 | 464 | 480 | 0.0000 |
| 5 | 64 | 416 | 64 | 0 | 64 | 0.8667 |
| 5 | 256 | 416 | 64 | 0 | 64 | 0.8667 |

### CLOCK Results

| Trace | Frames B | Hits | Misses | Evictions | Reads | Hit Rate |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 4 | 196 | 4 | 0 | 4 | 0.9800 |
| 1 | 16 | 196 | 4 | 0 | 4 | 0.9800 |
| 1 | 64 | 196 | 4 | 0 | 4 | 0.9800 |
| 1 | 256 | 196 | 4 | 0 | 4 | 0.9800 |
| 2 | 4 | 0 | 200 | 196 | 200 | 0.0000 |
| 2 | 16 | 0 | 200 | 184 | 200 | 0.0000 |
| 2 | 64 | 180 | 20 | 0 | 20 | 0.9000 |
| 2 | 256 | 180 | 20 | 0 | 20 | 0.9000 |
| 3 | 4 | 0 | 800 | 796 | 800 | 0.0000 |
| 3 | 16 | 0 | 800 | 784 | 800 | 0.0000 |
| 3 | 64 | 0 | 800 | 736 | 800 | 0.0000 |
| 3 | 256 | 720 | 80 | 0 | 80 | 0.9000 |
| 4 | 4 | 396 | 104 | 100 | 104 | 0.7920 |
| 4 | 16 | 396 | 104 | 88 | 104 | 0.7920 |
| 4 | 64 | 396 | 104 | 40 | 104 | 0.7920 |
| 4 | 256 | 398 | 102 | 0 | 102 | 0.7960 |
| 5 | 4 | 0 | 480 | 476 | 480 | 0.0000 |
| 5 | 16 | 0 | 480 | 464 | 480 | 0.0000 |
| 5 | 64 | 416 | 64 | 0 | 64 | 0.8667 |
| 5 | 256 | 416 | 64 | 0 | 64 | 0.8667 |

### Trace 1 — Small Working Set

Trace 1 repeatedly accesses only four pages.

With `B = 4`, the entire working set fits in the buffer. Both policies therefore incur four compulsory misses when the pages are first loaded and then hit on all remaining 196 references.

Increasing the buffer beyond four frames provides no additional benefit because all four pages already fit.

Both policies achieved:

```text
hit rate = 196 / 200
         = 0.98
```

### Trace 2 — Twenty-Page Cycle

Trace 2 cycles over twenty pages.

At `B = 4` and `B = 16`, the buffer is smaller than the complete working set, and both policies produce zero hits.

Once the buffer reaches `B = 64`, all twenty pages fit. There are twenty compulsory misses during the first pass followed by 180 hits.

Therefore:

```text
hit rate = 180 / 200
         = 0.90
```

Increasing the buffer from 64 to 256 produces no further improvement because the entire working set already fits at 64 frames.

### Trace 3 — Eighty-Page Sequential Scan Repeated Ten Times

Trace 3 consists of pages `0–79` accessed sequentially ten times.

The important result for LRU at:

```text
B = 64
```

was:

```text
hits       = 0
misses     = 800
evictions  = 736
reads      = 800
hit rate   = 0
```

Although 64 pages fit in the buffer, the working set contains 80 pages. By the time the scan returns to page 0 on the next pass, the sequential accesses have already caused the pages that will be needed next to be evicted.

This creates sequential-scan thrashing: every access becomes a miss even though the buffer can store most of the relation.

At `B = 256`, all 80 pages fit in memory. The first traversal therefore causes 80 compulsory misses, while the remaining nine traversals produce:

```text
9 × 80 = 720 hits
```

giving:

```text
hit rate = 720 / 800
         = 0.90
```

CLOCK showed the same behavior on this workload.

### Trace 4 — Hot and Cold Pages

Trace 4 repeatedly accesses pages 0 and 1 while mixing them with unique cold pages.

This workload produced the only measurable difference between LRU and CLOCK.

For `B = 4`, LRU achieved:

```text
398 hits
102 misses
hit rate = 0.796
```

while CLOCK achieved:

```text
396 hits
104 misses
hit rate = 0.792
```

The same small difference occurred at `B = 16` and `B = 64`.

LRU's exact recency tracking allowed it to retain the frequently reused pages slightly more effectively, while CLOCK's second-chance approximation occasionally replaced a page that was reused soon afterward.

At `B = 256`, the buffer was large enough to avoid this distinction and both policies produced the same result.

### Trace 5 — Phased Working Sets

Trace 5 alternates between two working sets of 32 pages.

At `B = 4` and `B = 16`, neither working set fits, so both policies produce zero hits.

At `B = 64`, all 64 unique pages can remain resident. Only the first access to each page is a miss:

```text
64 misses
416 hits
```

giving:

```text
hit rate = 416 / 480
         ≈ 0.8667
```

Increasing the buffer to 256 provides no further improvement.

### Comparison of LRU and CLOCK

Overall, the two policies produced nearly identical behavior.

They had exactly the same hit rate on Traces 1, 2, 3, and 5 for every tested buffer size.

The only difference occurred on Trace 4, where LRU achieved a hit rate of:

```text
0.796
```

compared with:

```text
0.792
```

for CLOCK at `B = 4`, `16`, and `64`.

The difference is only:

```text
0.796 - 0.792 = 0.004
```

or 0.4 percentage points.

### Policy I Would Ship

Based on these measurements, I would ship **LRU**.

Both policies performed equally on nearly all of the tested workloads, but LRU performed slightly better on the hot/cold workload in Trace 4 and never performed worse than CLOCK in these experiments.

LRU also gives a straightforward interpretation of replacement decisions because it explicitly removes the least recently used unpinned page. Although CLOCK can reduce the bookkeeping required for exact recency tracking, that implementation advantage did not produce a measurable hit-rate benefit in these experiments.

For this implementation and these workloads, LRU therefore provides the best measured behavior, although the difference between the two policies is small.\

## 3. Scan Cost Measurement

The final experiment measured the page-read cost of scanning a table containing approximately 500 data pages using three different buffer-pool sizes.

The experiment used a table named `Scan500` with 15 `VARCHAR(255)` columns. Every field contained exactly 255 single-byte characters.

Each field therefore required:

```text
2 bytes for the VARCHAR length
+ 255 bytes of data
= 257 bytes
```

With 15 fields, each record required:

```text
15 × 257
= 3855 bytes
```

Including the four-byte slot entry:

```text
3855 + 4
= 3859 bytes
```

Because two such records cannot fit in one 4096-byte page, each data page contained exactly one record.

The experiment loaded 500 rows, producing 500 data pages. The table also required one directory page, so a complete scan needed to access 501 pages.

The layout command confirmed that both the first and last data pages contained one record.

Example:

```text
page_id: 1
page_type: data
slot_count: 1
free_end: 241
free_space: 229
slot 0: (241,3855)
```

Page 500 produced the same data-page structure.

### Measured Results

| Buffer Frames B | Hits | Misses | Evictions | Reads | Writes |
|---:|---:|---:|---:|---:|---:|
| 2 | 0 | 501 | 499 | 501 | 0 |
| 8 | 0 | 501 | 493 | 501 | 0 |
| 64 | 0 | 501 | 437 | 501 | 0 |

### Interpretation

The number of page reads remained constant at:

```text
501 reads
```

for all three buffer sizes.

This is the expected result. The table contains 500 data pages plus one directory page:

```text
500 + 1 = 501 pages
```

The scan performs one sequential pass through the table. Each data page is visited once and then the scan moves forward to the next page. There is therefore no opportunity to reuse a data page during the same scan.

This also explains why the number of hits remained zero at every buffer size. A larger buffer can retain more pages after they have been read, but those pages are not referenced again during this sequential scan.

Increasing the buffer size therefore reduced only the number of evictions:

```text
B = 2   -> 499 evictions
B = 8   -> 493 evictions
B = 64  -> 437 evictions
```

The number of disk reads did not change.

This result demonstrates that the scan is streaming through the heap file rather than loading the entire relation into memory. The scan cost grows with the number of pages in the relation and does not incorrectly decrease as the memory budget increases.

### Overall Module 1 Measurement Result

All three Module 1 measurement experiments behaved as expected:

- The measured record capacities exactly matched the page-layout calculations.
- LRU and CLOCK produced deterministic replacement behavior across the tested traces, with LRU slightly outperforming CLOCK on the hot/cold workload.
- A 500-data-page sequential scan required 501 reads regardless of whether the buffer contained 2, 8, or 64 frames.

These measurements support the correctness of the page layout, buffer replacement, and heap-scan implementations.