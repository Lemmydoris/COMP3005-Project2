# Module 2 Design

## 1. Execution Engine Structure

Module 2 implements a physical query execution engine using the iterator model.

Every physical operator follows the same interface:

```text
open()
next() -> tuple | END
close()
counters()
```

`open()` prepares the operator and performs any blocking work that is required.

`next()` returns one tuple at a time. The special `END` sentinel indicates that the operator has no more tuples.

`close()` releases resources owned by the operator, including temporary files.

`counters()` reports:

```text
tuples_out
comparisons
page_reads
page_writes
```

Operators communicate only through the iterator interface. A parent operator calls `next()` on its child or children and does not directly bypass them.

The common execution interface is implemented in:

```text
execution/base.py
```

The execution engine is organized into separate physical operator modules, including:

```text
execution/seqscan.py
execution/filter.py
execution/project.py
execution/sort.py
execution/distinct.py
execution/group_by.py
execution/union_all.py
execution/set_ops.py
execution/limit.py
execution/nested_loop_join.py
execution/sort_merge_join.py
execution/hash_join.py
execution/plan.py
execution/cli.py
```

This keeps each physical algorithm independent while using a common operator contract.

## 2. Memory Budget

The whole execution plan receives a memory budget of `B` frames from the command line.

The minimum supported budget is:

```text
B = 4
```

The implementation reuses the same plan-wide frame budget across blocking phases rather than permanently dividing the frames among all operators.

A blocking operation may use up to `B` frames while it is the active blocking phase. When that phase finishes, the same budget can be reused by the next phase.

Pipelined operators require only a small amount of working memory.

Examples include:

```text
SeqScan       -> one data page at a time
Filter        -> one tuple at a time
Project       -> one tuple at a time
UnionAll      -> one input stream at a time
Limit         -> one input stream at a time
```

The join-specific allocation rules are:

```text
Nested-loop join:
B - 2 page-equivalents for outer tuples
1 frame for the inner stream
1 remaining frame

Sort-merge join:
up to B frames during each external sort
approximately 3 frames during the merge stage

Hash join:
B - 1 output partitions
1 input frame
```

The implementation records `max_frames_held` in blocking operators so the memory rule can be checked experimentally.

The required budget experiment sorted 80 pages at `B = 4` and reported:

```text
max_frames_held = 4
```

so the implementation did not exceed the supplied frame budget.

## 3. Sequential Scan

`SeqScan` reads every live tuple from a heap file in heap order.

The implementation reads the directory metadata and then streams through the table's data pages.

Only one data page is held at a time during the tuple-producing part of the scan.

The output schema uses qualified column names such as:

```text
R.id
R.value
```

This qualification is important because joins may combine relations containing columns with the same unqualified name.

The theoretical scan cost uses the number of data pages:

```text
cost = M reads
```

The physical counter may be one read larger because the implementation also performs a real DiskManager read of the table directory page.

This difference is retained in the measurements rather than hidden.

## 4. Filter and Project

### Filter

`Filter` is fully pipelined.

For each tuple returned by its child, it evaluates the prepared condition and either returns or discards the tuple.

The filter does not perform disk I/O of its own.

Its comparison counter increases once per tuple whose condition is evaluated.

### Project

`Project` is also fully pipelined.

It resolves the requested columns during `open()` and then creates an output tuple containing only those positions.

Projection preserves duplicate tuples.

Duplicate removal is therefore performed only by the separate `Distinct` operator.

## 5. Temporary Runs

Blocking operators use temporary runs stored on disk instead of keeping unlimited Python lists in memory.

The temporary-run abstraction is implemented in:

```text
execution/temp_run.py
```

A temporary run supports:

```text
append(row)
finish()
rows()
delete()
```

Temporary pages are included in the appropriate operator's page-read and page-write counters.

Temporary files are removed after the operator finishes.

The measurement harness verified that completed plans left:

```text
temp_files_after_close = 0
```

## 6. External Merge Sort

The `Sort` operator implements external merge sort.

### Pass 0

The operator reads enough tuples to fill at most `B` page-equivalents.

That run is sorted in memory and written to a temporary run.

This repeats until all input tuples have been consumed.

The initial number of runs is approximately:

```text
R0 = ceil(N / B)
```

where `N` is the number of input pages.

### Merge Passes

Subsequent passes merge at most:

```text
B - 1
```

runs at a time.

One frame-equivalent is reserved for output.

The number of passes is:

```text
1 + ceil(
    log(ceil(N / B))
    /
    log(B - 1)
)
```

The final pass is streamed to the parent instead of writing another complete final temporary run.

### Carrying an Unmerged Run

When a merge pass contains a final run that does not have enough partners to form a merge group, the implementation carries that run forward unchanged.

It does not unnecessarily read and rewrite the run.

For example, if a pass has:

```text
run A
run B
run C
```

and only two runs can be merged at once, the implementation merges A and B and carries C forward.

This can make measured I/O slightly smaller than the simplified full-pass cost formula.

The project specification explicitly allows this strategy as long as it is documented.

### Memory Measurement

The sort maintains:

```text
passes
max_frames_held
```

for experimental verification.

In the required `N = 20 × B` experiment:

```text
N = 80
B = 4
passes = 4
max_frames_held = 4
```

## 7. Distinct

`Distinct` supports two physical strategies:

```text
sort
hash
```

### Sort Distinct

The input is sorted and adjacent equal tuples are suppressed.

The operator therefore uses the external sort implementation and inherits its spill behavior.

### Hash Distinct

The hash strategy maintains seen tuples while they fit within its memory allocation.

When the input becomes too large, tuples are partitioned into disk-backed temporary runs and duplicate removal is performed partition by partition.

This avoids storing the complete relation in a Python set without regard for `B`.

## 8. Group By

`GroupBy` supports:

```text
sort
hash
```

The supported aggregates are:

```text
COUNT
SUM
AVG
MIN
MAX
```

`SUM` and `AVG` require integer input.

`AVG` produces a real-valued result.

The implementation handles two empty-input cases separately.

With grouping columns and an empty relation:

```text
0 output rows
```

With no grouping columns and:

```text
COUNT(*)
```

the result is:

```text
0
```

A global non-COUNT aggregate over an empty input is treated as an error because the result is undefined by the project specification.

## 9. Block Nested-Loop Join

The nested-loop implementation is a block nested-loop join.

It accepts general join conditions, including inequality conditions.

### Memory Layout

For a plan with `B` frames:

```text
B - 2 pages -> outer block
1 page       -> inner stream
1 page       -> remaining working/output space
```

Outer tuples are packed into page-equivalent blocks based on their encoded tuple sizes.

For each outer block, the right input is scanned from the beginning.

### Comparison Counter

Every left/right tuple pair is tested exactly once.

Therefore:

```text
comparisons = |R| × |S|
```

The comparison count does not depend on:

```text
B
number of matches
join predicate selectivity
```

### Rescan Counter Preservation

A right child is reopened for every new outer block.

Since `open()` normally resets an operator's counters, repeated rescans originally risked losing the counters from earlier inner passes.

The implementation preserves the counters from the complete right subtree before reopening it and restores them afterward.

This makes repeated inner reads cumulative.

For the regression test:

```text
700 left tuples
10 right tuples
B = 4
```

the result is:

```text
comparisons = 7000
Rbig reads  = 4
Ssmall reads = 4
total reads = 8
```

The regression suite now permanently checks this behavior.

## 10. Sort-Merge Join

Sort-merge join accepts equality conditions only.

Both inputs are sorted using the external sort implementation.

The merge phase then advances the sorted inputs according to their join keys.

### Duplicate Key Runs

Duplicate join keys require every matching combination to be returned.

For example:

```text
R = [1, 2, 2, 3]
S = [2, 2, 4]
```

must produce:

```text
2 × 2 = 4 matching rows
```

The implementation preserves this cross-product behavior.

### Large Equal-Key Runs

An equal-key run is not assumed to fit entirely in memory.

The repeated inner-key run can be materialized in a temporary run so it can be replayed for each matching tuple from the other side.

This allows duplicate runs larger than the available memory budget to complete without storing the full run in an unrestricted Python list.

The temporary run is deleted during cleanup.

## 11. Grace Hash Join

Hash join implements a Grace-style equality join.

The left input is the build side.

For a memory budget `B`, the partition phase creates:

```text
P = B - 1
```

partitions.

Both inputs are partitioned according to the first hash function.

Matching keys therefore enter the same partition number.

For each partition pair, the operator normally:

```text
builds an in-memory hash table on the left partition
scans the right partition
probes the hash table
emits matching combinations
```

The ordinary theoretical cost is:

```text
3(M + N)
```

consisting of:

```text
2(M + N) for partitioning
+
(M + N) for probing
```

### Partition Overflow

The implementation does not silently construct a hash table larger than the memory budget.

If a left partition is larger than:

```text
B - 1 pages
```

the implementation falls back to block nested-loop join for that partition pair.

The hash join records:

```text
partition_sizes
overflow_fallbacks
max_frames_held
```

This fallback was exercised by both the B=4 experiments and the 40-percent-skew experiment.

For example, with:

```text
B = 16
```

the skew test produced a partition containing:

```text
18 left pages
18 right pages
```

Since:

```text
B - 1 = 15
```

the 18-page build partition did not fit.

The implementation therefore used one BNL overflow fallback rather than violating the memory budget.

## 12. Set Operators

The execution engine implements:

```text
union_all
union
intersect
except
```

### Union All

`UnionAll` is pipelined.

It returns every tuple from the left child and then every tuple from the right child.

Duplicates are preserved.

### Union

`Union` applies set semantics and removes duplicate tuples.

### Intersect

`Intersect` returns a tuple once if it appears on both sides.

### Except

`Except` returns a tuple once if it appears on the left and not on the right.

Set operators require positionally compatible schemas.

Column types must match, while the result uses the left input's column names.

## 13. Limit

`Limit` is fully pipelined.

It stops pulling from its child once the requested number of tuples has been returned.

This is important because it prevents unnecessary work below the limit.

The operator performs no disk I/O or comparisons of its own.

## 14. Plan Construction

Physical JSON plans are converted into executable operator trees by:

```text
execution/plan.py
```

The builder validates the fields permitted for each operator.

Unexpected fields, missing children, invalid sort directions, and unknown operator names are rejected.

References to unknown tables or columns are rejected when the relevant operator opens.

The supported physical operators include:

```text
seqscan
filter
project
distinct
sort
group_by
nested_loop_join
sort_merge_join
hash_join
union_all
union
intersect
except
limit
```

## 15. Command-Line Interface

The execution engine is exposed through:

```text
exec run
exec trace
```

The required form is:

```text
exec run   --db DIR --plan plan.json --frames B --json
exec trace --db DIR --plan plan.json --frames B
```

`exec run` returns the result schema, rows, and total counters.

`exec trace` prints one line for each plan node in tree order, including:

```text
tuples_out
comparisons
reads
writes
```

For example:

```text
nested_loop_join (...) tuples_out=10 comparisons=7000 reads=0 writes=0
  seqscan Rbig         tuples_out=700 comparisons=0 reads=4 writes=0
  seqscan Ssmall       tuples_out=20 comparisons=0 reads=4 writes=0
```

The right scan shows 20 output tuples because its 10 tuples were scanned twice.

## 16. Counter Design

Every operator owns its own counters.

`tuples_out` counts tuples actually returned by that operator.

`comparisons` counts conditions or key comparisons performed by that operator.

`page_reads` and `page_writes` count real page operations attributed to the operator, including temporary-run I/O.

The root execution summary combines the counters from the plan tree while using the root's tuple count as the final output count.

The implementation intentionally retains physical metadata reads such as directory-page reads.

Therefore, measured physical I/O can be slightly larger than formulas that define `M` and `N` using only data pages.

Those differences are reported and explained rather than removed from the counters.

## 17. Resource Cleanup

Every operator's `close()` method releases its resources.

Temporary-run operators explicitly delete the files they created.

The measurement harness checks the temporary directory after each completed plan.

All reported experiments ended with:

```text
temp_files_after_close = 0
```

This confirms that temporary runs were not left behind after the plans completed.

## 18. Testing

The execution engine has unit tests for individual physical operators, plan construction, the CLI, and cross-operator behavior.

Important regression cases include:

```text
duplicate sort-merge keys produce four rows
all three joins return the same bag
BNL comparisons equal |R| × |S|
BNL inner rescan counters accumulate
hash overflow uses BNL fallback
external sort uses temporary files
sort never exceeds B frames
limit stops pulling its child
empty inputs complete cleanly
temporary files are cleaned up
```

After the BNL counter regression test was added, the complete project test suite contained:

```text
207 tests
```

with:

```text
207 passing
0 failing
```

The design therefore supports both the required tuple semantics and the measured memory and I/O behavior used in the Module 2 report.