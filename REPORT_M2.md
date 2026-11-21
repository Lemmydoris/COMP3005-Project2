# Module 2 Report

## 1. Join Cost Against Formula

The purpose of the first experiment was to compare the measured page I/O of the three physical join algorithms with their theoretical formulas.

The three joins were:

```text
block nested-loop join
sort-merge join
Grace hash join
```

The experiments used:

```text
B = 4, 16, 64, 256
```

and three equal-sized relation pairs:

```text
8 data pages per relation
32 data pages per relation
80 data pages per relation
```

The test records were deliberately made large enough that one tuple occupied one data page. This made the input relation sizes directly measurable.

Each table also contained one directory page.

Therefore, for example:

```text
8 data pages -> 9 physical file pages
32 data pages -> 33 physical file pages
80 data pages -> 81 physical file pages
```

The theoretical formulas use only the data-page counts `M` and `N`.

The measured counters report actual DiskManager activity, including directory-page accesses and temporary-file activity.

### Theoretical Formulas

For block nested-loop join:

```text
M + ceil(M / (B - 2)) × N
```

For sort:

```text
sort(M) = 2M(passes - 1) + M
```

where:

```text
passes =
1 + ceil(
    log(ceil(M / B))
    /
    log(B - 1)
)
```

For sort-merge join:

```text
sort(M) + sort(N) + M + N
```

For Grace hash join:

```text
3(M + N)
```

### Measured Results

| Size per Relation | B | Join | Reads | Writes | Measured I/O | Formula | Gap |
|---:|---:|---|---:|---:|---:|---:|---:|
| 8 | 4 | Nested loop | 45 | 0 | 45 | 40 | +5 |
| 8 | 4 | Sort merge | 42 | 24 | 66 | 64 | +2 |
| 8 | 4 | Hash | 38 | 16 | 54 | 48 | +6 |
| 8 | 16 | Nested loop | 18 | 0 | 18 | 16 | +2 |
| 8 | 16 | Sort merge | 26 | 8 | 34 | 32 | +2 |
| 8 | 16 | Hash | 34 | 16 | 50 | 48 | +2 |
| 8 | 64 | Nested loop | 18 | 0 | 18 | 16 | +2 |
| 8 | 64 | Sort merge | 26 | 8 | 34 | 32 | +2 |
| 8 | 64 | Hash | 34 | 16 | 50 | 48 | +2 |
| 8 | 256 | Nested loop | 18 | 0 | 18 | 16 | +2 |
| 8 | 256 | Sort merge | 26 | 8 | 34 | 32 | +2 |
| 8 | 256 | Hash | 34 | 16 | 50 | 48 | +2 |
| 32 | 4 | Nested loop | 561 | 0 | 561 | 544 | +17 |
| 32 | 4 | Sort merge | 226 | 160 | 386 | 384 | +2 |
| 32 | 4 | Hash | 289 | 64 | 353 | 192 | +161 |
| 32 | 16 | Nested loop | 132 | 0 | 132 | 128 | +4 |
| 32 | 16 | Sort merge | 162 | 96 | 258 | 256 | +2 |
| 32 | 16 | Hash | 130 | 64 | 194 | 192 | +2 |
| 32 | 64 | Nested loop | 66 | 0 | 66 | 64 | +2 |
| 32 | 64 | Sort merge | 98 | 32 | 130 | 128 | +2 |
| 32 | 64 | Hash | 130 | 64 | 194 | 192 | +2 |
| 32 | 256 | Nested loop | 66 | 0 | 66 | 64 | +2 |
| 32 | 256 | Sort merge | 98 | 32 | 130 | 128 | +2 |
| 32 | 256 | Hash | 130 | 64 | 194 | 192 | +2 |
| 80 | 4 | Nested loop | 3321 | 0 | 3321 | 3280 | +41 |
| 80 | 4 | Sort merge | 706 | 544 | 1250 | 1280 | -30 |
| 80 | 4 | Hash | 1352 | 160 | 1512 | 480 | +1032 |
| 80 | 16 | Nested loop | 567 | 0 | 567 | 560 | +7 |
| 80 | 16 | Sort merge | 402 | 240 | 642 | 640 | +2 |
| 80 | 16 | Hash | 322 | 160 | 482 | 480 | +2 |
| 80 | 64 | Nested loop | 243 | 0 | 243 | 240 | +3 |
| 80 | 64 | Sort merge | 402 | 240 | 642 | 640 | +2 |
| 80 | 64 | Hash | 322 | 160 | 482 | 480 | +2 |
| 80 | 256 | Nested loop | 162 | 0 | 162 | 160 | +2 |
| 80 | 256 | Sort merge | 242 | 80 | 322 | 320 | +2 |
| 80 | 256 | Hash | 322 | 160 | 482 | 480 | +2 |

### Block Nested-Loop Join Differences

The block nested-loop formula counts data pages:

```text
M + ceil(M / (B - 2)) × N
```

The implementation also performs a physical read of the directory page whenever a relation scan is opened.

This explains the positive gaps.

For example, with:

```text
M = 32
N = 32
B = 4
```

the number of outer blocks is:

```text
ceil(32 / (4 - 2))
= ceil(32 / 2)
= 16
```

The theoretical data-page cost is:

```text
32 + 16 × 32
= 544
```

The implementation performs:

```text
1 directory read for the outer scan
+
16 directory reads for the 16 inner rescans
= 17 additional reads
```

Therefore:

```text
544 + 17
= 561
```

which exactly equals the measured result.

The same pattern appears for the other BNL experiments.

At `M = N = 80` and `B = 4`:

```text
outer blocks =
ceil(80 / 2)
= 40
```

so the additional directory cost is:

```text
1 + 40 = 41
```

The formula predicts:

```text
3280
```

and the implementation measures:

```text
3280 + 41
= 3321
```

Again, the gap is explained exactly.

### Sort-Merge Differences

Most sort-merge measurements are:

```text
formula + 2
```

because each base relation contributes one physical directory-page read.

For example:

```text
M = N = 32
B = 16
```

produced:

```text
formula = 256
measured = 258
```

The two extra I/Os correspond to the two base-table directory pages.

The unusual result occurred for:

```text
M = N = 80
B = 4
```

where:

```text
formula = 1280
measured = 1250
gap = -30
```

The difference is caused by the implementation's external-sort merge policy.

When a merge pass contains a final run that has no partners, the implementation carries that run forward unchanged instead of reading and rewriting it.

This is a permitted external-sort strategy.

For an 80-page sort at `B = 4`, this optimization saves 16 page operations relative to the simplified full-pass formula.

The physical directory-page scan adds one read.

Therefore, for each sorted input:

```text
-16 + 1
= -15
```

Sort-merge performs two such sorts:

```text
2 × -15
= -30
```

which exactly explains:

```text
1280 - 30
= 1250
```

### Hash Join Differences

At larger values of `B`, the hash join is almost exactly:

```text
formula + 2
```

because the two base-table directory pages are physically read.

At `B = 4`, however, Grace-hash partitions can exceed the available build-side memory.

The implementation uses:

```text
P = B - 1
  = 3 partitions
```

and falls back to BNL when a left partition is larger than:

```text
B - 1 = 3 pages
```

#### 8-Page Relations

The three build partitions contained:

```text
2 pages
2 pages
4 pages
```

Only the four-page partition overflowed.

Ordinary hash probing of the overflowing pair would cost:

```text
4 + 4 = 8
```

but BNL costs:

```text
4 + ceil(4 / 2) × 4
= 4 + 8
= 12
```

The fallback therefore adds:

```text
12 - 8
= 4
```

page operations.

Including the two base-relation directory reads:

```text
4 + 2
= 6
```

which exactly matches the measured gap:

```text
54 - 48
= 6
```

#### 32-Page Relations

The build partitions were:

```text
13 pages
7 pages
12 pages
```

All three exceeded three pages and therefore used the BNL fallback.

The extra costs over ordinary probing were:

```text
13-page partition:
BNL = 13 + ceil(13 / 2) × 13
    = 104

normal probe = 26

extra = 78
```

```text
7-page partition:
BNL = 7 + ceil(7 / 2) × 7
    = 35

normal probe = 14

extra = 21
```

```text
12-page partition:
BNL = 12 + ceil(12 / 2) × 12
    = 84

normal probe = 24

extra = 60
```

Therefore:

```text
78 + 21 + 60
= 159
```

Adding the two directory reads gives:

```text
159 + 2
= 161
```

The measured difference was exactly:

```text
353 - 192
= 161
```

#### 80-Page Relations

The three build partitions contained:

```text
26 pages
23 pages
31 pages
```

All three overflowed.

The extra BNL costs were:

```text
26-page partition:
364 - 52 = 312

23-page partition:
299 - 46 = 253

31-page partition:
527 - 62 = 465
```

Total overflow cost:

```text
312 + 253 + 465
= 1030
```

Adding two directory reads:

```text
1030 + 2
= 1032
```

The measured gap was:

```text
1512 - 480
= 1032
```

Therefore, even the largest hash-join difference is completely explained by the documented overflow policy.

### Join Cost Interpretation

The theoretical formulas accurately predicted the basic behavior of all three algorithms.

The remaining differences came from real implementation details that the simplified formulas do not represent:

```text
directory-page reads
hash-partition overflow handling
external-sort run carrying
```

The measurements therefore demonstrate both agreement with the formulas and the effect of physical implementation choices.

## 2. Sort Pass Measurement

The second experiment compared the measured number of external-sort passes with:

```text
1 + ceil(
    log(ceil(N / B))
    /
    log(B - 1)
)
```

Six combinations of `N` and `B` were tested.

One required case used:

```text
N = 20 × B
```

Specifically:

```text
N = 80
B = 4
```

### Results

| N Data Pages | B | Measured Passes | Formula Passes | Difference | Max Frames |
|---:|---:|---:|---:|---:|---:|
| 8 | 4 | 2 | 2 | 0 | 4 |
| 16 | 4 | 3 | 3 | 0 | 4 |
| 32 | 4 | 3 | 3 | 0 | 4 |
| 32 | 8 | 2 | 2 | 0 | 8 |
| 64 | 8 | 3 | 3 | 0 | 8 |
| 80 | 4 | 4 | 4 | 0 | 4 |

Every measured pass count matched the theoretical formula exactly.

### Example: N = 80, B = 4

Initial runs:

```text
ceil(80 / 4)
= 20 runs
```

Merge fan-in:

```text
B - 1
= 3
```

The pass sequence is therefore:

```text
Pass 0:
20 initial runs

Pass 1:
ceil(20 / 3)
= 7 runs

Pass 2:
ceil(7 / 3)
= 3 runs

Pass 3:
ceil(3 / 3)
= 1 final stream
```

Total:

```text
4 passes
```

which matches the measured result.

The experiment also showed:

```text
max_frames_held = 4
```

so the sort respected the memory budget even on an input twenty times larger than `B`.

## 3. Join Crossover

The third experiment measured when the cheapest join algorithm changes.

Two crossover experiments were performed.

The first fixed the relation size and varied `B`.

The second fixed `B` and varied the relation size.

The generated plots are:

```text
m2_measurements/crossover_vary_B.svg
m2_measurements/crossover_vary_size.svg
```

### Fixed Relations, Varying B

Both relations contained:

```text
64 data pages
```

The results were:

| B | Nested Loop | Sort Merge | Hash | Cheapest |
|---:|---:|---:|---:|---|
| 4 | 2145 | 1010 | 1037 | Sort merge |
| 8 | 780 | 738 | 447 | Hash |
| 16 | 390 | 514 | 386 | Hash |
| 32 | 260 | 514 | 386 | Nested loop |
| 64 | 195 | 258 | 386 | Nested loop |
| 128 | 130 | 258 | 386 | Nested loop |
| 256 | 130 | 258 | 386 | Nested loop |

There were two ranking changes.

The first occurred between:

```text
B = 4
and
B = 8
```

At `B = 4`, sort merge was cheapest.

At `B = 8`, hash join became cheapest.

The reason is that very small `B` values produce very small Grace-hash partitions. Overflow becomes more likely and triggers the more expensive BNL fallback.

Once more memory becomes available, the partitions fit and Grace hash join approaches its expected linear I/O cost.

The second crossover occurred between:

```text
B = 16
and
B = 32
```

At `B = 16`:

```text
Hash = 386
BNL  = 390
```

so hash was slightly cheaper.

At `B = 32`:

```text
BNL  = 260
Hash = 386
```

so BNL became clearly cheaper.

The reason is the term:

```text
ceil(M / (B - 2))
```

in the nested-loop formula.

As `B` increases, more outer pages fit in each block and the number of full scans of the inner relation falls sharply.

Hash join does not receive the same reduction because its ordinary Grace cost remains approximately:

```text
3(M + N)
```

### Fixed B, Varying Relation Size

The second experiment fixed:

```text
B = 16
```

and varied both relation sizes equally.

| Pages per Relation | Nested Loop | Sort Merge | Hash | Cheapest |
|---:|---:|---:|---:|---|
| 4 | 10 | 18 | 26 | Nested loop |
| 8 | 18 | 34 | 50 | Nested loop |
| 16 | 51 | 66 | 98 | Nested loop |
| 32 | 132 | 258 | 194 | Nested loop |
| 64 | 390 | 514 | 386 | Hash |
| 80 | 567 | 642 | 482 | Hash |

The crossover occurred between:

```text
32 pages
and
64 pages
```

At 32 pages:

```text
BNL  = 132
Hash = 194
```

so BNL was cheaper.

At 64 pages:

```text
BNL  = 390
Hash = 386
```

so hash became cheaper by only four page operations.

As the relations grow while `B` stays fixed, the number of BNL outer blocks increases.

This causes repeated scans of the inner relation.

Hash join grows more nearly linearly as long as its partitions remain within memory.

Therefore, the crossover demonstrates that there is no universally cheapest join algorithm.

The best choice depends on both:

```text
relation size
available memory
```

## 4. Hash Join Under Skew

The fourth experiment tested Grace hash join with a deliberately skewed key distribution.

Both input relations contained:

```text
40 rows
40 data pages
```

The skewed dataset assigned the same join-key value to:

```text
16 rows
```

on each side.

Therefore:

```text
16 / 40
= 0.40
= 40%
```

The experiment used:

```text
B = 16
P = B - 1
  = 15 partitions
```

A uniform dataset of the same size was also measured for comparison.

### Uniform Case

The uniform case produced:

```text
tuples_out = 40
comparisons = 40
page_reads = 162
page_writes = 80
overflow_fallbacks = 0
max_frames_held = 16
```

Total I/O:

```text
162 + 80
= 242
```

The largest uniform partitions contained only a few pages each, so no overflow handling was required.

### Skewed Case

The skewed case produced:

```text
tuples_out = 280
comparisons = 346
page_reads = 180
page_writes = 80
overflow_fallbacks = 1
max_frames_held = 16
```

Total I/O:

```text
180 + 80
= 260
```

The heavily skewed key was concentrated into partition 11.

That partition contained:

```text
18 left tuples
18 right tuples
18 left pages
18 right pages
```

The hash build limit was:

```text
B - 1
= 15 pages
```

Since:

```text
18 > 15
```

the partition could not be safely built as an in-memory hash table.

The implementation therefore used its documented BNL fallback on that one partition pair.

### Cost of Skew

The uniform case cost:

```text
242 I/O
```

while the skewed case cost:

```text
260 I/O
```

The increase was:

```text
260 - 242
= 18 page operations
```

Percentage increase:

```text
18 / 242 × 100
≈ 7.44%
```

The skew also caused a much larger output.

The repeated key alone contributes:

```text
16 × 16
= 256
```

matching tuple combinations.

The remaining unique matching keys contribute another 24 rows:

```text
256 + 24
= 280
```

which exactly matches:

```text
tuples_out = 280
```

This experiment demonstrates why Grace hash join must explicitly handle skew rather than assuming every partition will fit in memory.

## 5. Memory Budget Experiment

The final required experiment tested whether external sort could process a relation of:

```text
20 × B pages
```

with:

```text
B = 4
```

Therefore the input contained:

```text
20 × 4
= 80 data pages
```

### Result

The measured values were:

| Measurement | Result |
|---|---:|
| B | 4 |
| Input data pages | 80 |
| Input equals 20 × B | Yes |
| Sort completed | Yes |
| Rows returned | 80 |
| Passes | 4 |
| Maximum frames held | 4 |
| Within memory budget | Yes |
| Page reads | 313 |
| Page writes | 232 |
| Total I/O | 545 |
| Temporary files after close | 0 |

The sort therefore successfully processed an input twenty times larger than the available memory.

The largest number of frames held at once was:

```text
4
```

which is exactly the supplied memory budget.

This value is known because the `Sort` operator records:

```text
max_frames_held
```

while run generation and merge phases execute.

After the plan completed:

```text
temp_files_after_close = 0
```

which confirms that the external runs were cleaned up.

## 6. Correctness and Regression Testing

In addition to the measurement experiments, the execution engine was tested using the complete automated suite.

After adding a permanent regression test for cumulative BNL inner-scan counters, the result was:

```text
Ran 207 tests
OK
```

Important tested behaviors include:

```text
all three joins return the same bag
duplicate sort-merge keys produce four output rows
BNL reports exactly |R| × |S| comparisons
BNL works with multiple outer blocks at B = 4
BNL rescan counters accumulate
hash join handles partition overflow
sort respects B
empty inputs return cleanly
temporary files are removed
limit stops pulling its child
set operators preserve their required semantics
```

The dedicated nested-loop suite contained:

```text
11 tests
```

and all 11 passed.

## 7. Overall Module 2 Measurement Result

The Module 2 experiments behaved consistently with the physical algorithms and the documented implementation decisions.

The main findings were:

- All six measured external-sort pass counts matched the theoretical pass formula exactly.
- A sort of `20 × B` pages completed successfully at `B = 4` without exceeding four frames.
- Block nested-loop I/O fell sharply as the memory budget increased.
- Grace hash join performed well when its build partitions fit, but small-memory and skewed cases caused documented BNL overflow fallbacks.
- Sort merge was competitive at very small memory budgets.
- The cheapest join changed as both relation size and buffer size changed.
- Differences between theoretical and measured I/O were explainable by physical directory reads, hash overflow handling, and the external-sort run-carry strategy.
- The 40-percent-skew dataset caused one partition overflow and increased hash-join I/O by approximately 7.44 percent.
- Every measurement plan cleaned up its temporary files.
- The complete automated suite finished with 207 passing tests.

These results support the correctness of the iterator execution engine, external-memory algorithms, memory-budget enforcement, join implementations, counter accounting, and temporary-resource cleanup.