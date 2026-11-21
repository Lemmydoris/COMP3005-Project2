# DESIGN_M4.md — Module 4 Query Optimizer

## 1. Overview

Module 4 accepts a logical relational-algebra plan from Module 3 and produces a physical plan that can be executed directly by the Module 2 executor. The optimizer applies logical rewrites first, estimates cardinalities and page counts from catalog statistics, enumerates connected join orders with dynamic programming, and chooses physical operators using the Module 2 page-I/O cost formulas.

The command-line interface is:

```text
opt analyze  --db DIR --table R [--buckets 20]
opt plan     --db DIR --logical q.json --frames 32 --json
opt explain  --db DIR --logical q.json --frames 32
opt dp-table --db DIR --logical q.json --frames 32
```

An additional `--rewrite` flag is supported by `opt explain` so that the logical plan can be shown before and after rewriting without changing the normal explain format.

## 2. Statistics and catalog layout

`ANALYZE` computes table statistics exactly and stores them in the Module 1 catalog.

For each table the statistics dictionary contains:

- `n_tuples`: number of live tuples.
- `n_pages`: number of data pages, excluding directory pages.
- `width`: average record width in bytes.
- `columns`: per-column statistics.

For each column, the stored information is:

- `ndv`: number of distinct values.
- `min`: minimum value.
- `max`: maximum value.
- `hist`: an equi-depth histogram.

A histogram bucket stores its value range, tuple count, and number of distinct values in that bucket. The default number of buckets is 20 and can be changed with `--buckets`.

Because histogram state can be larger than one catalog record, large statistics are serialized and stored as internal statistics-chunk records inside `catalog.db`. `Catalog.get_table()` reconstructs the newest complete statistics version and exposes it as the normal `entry["statistics"]` dictionary.

Running `ANALYZE` twice on an unchanged table is deterministic. In testing, the two serialized visible statistics dictionaries compared equal.

### No-statistics fallback

Planning does not require ANALYZE to have been run. If the statistics dictionary is missing or empty, the planner falls back to catalog metadata:

- rows: catalog `num_tuples`
- pages: catalog `num_pages`
- width: derived from the declared schema

Declared-width defaults are 4 bytes for `INT`, 8 for `REAL`, `2 + declared_length` for `VARCHAR(n)`, 10 for a VARCHAR without a usable declared length, and 8 bytes as the final generic fallback.

Selectivity fallback constants are:

```text
DEFAULT_EQUALITY_SELECTIVITY = 0.10
DEFAULT_RANGE_SELECTIVITY    = 1/3
DEFAULT_JOIN_SELECTIVITY     = 0.10
```

A no-statistics plan was tested successfully and was accepted unedited by the Module 2 executor.

## 3. Selectivity and cardinality estimation

Selectivity is a fraction from 0 to 1.

### Equality with a literal

For `c = v`, if a histogram bucket contains `v`:

```text
sel(c = v) = count(bucket) / (n_tuples * ndv(bucket))
```

If no usable histogram is available but a column NDV is available:

```text
sel(c = v) = 1 / ndv(c)
```

If neither statistic is usable, the implemented equality fallback is `0.10`.

### Range predicates

For `c < v`, `c <= v`, `c > v`, and `c >= v`, the estimator sums complete histogram buckets on the selected side and uses a linear fraction of the bucket containing the boundary value.

If usable range statistics are unavailable, the implemented fallback is:

```text
1/3
```

### Not equal

```text
sel(c <> v) = 1 - sel(c = v)
```

The same complement rule is used for `!=`.

### Boolean predicates

```text
sel(p AND q) = sel(p) * sel(q)

sel(p OR q)  = sel(p) + sel(q) - sel(p) * sel(q)

sel(NOT p)   = 1 - sel(p)
```

The AND formula assumes independence. This assumption is intentionally examined in the Module 4 report using correlated columns.

### Equality joins

When both join-key NDVs are known:

```text
rows(R join S)
    = rows(R) * rows(S)
      / max(ndv(R.a), ndv(S.b))
```

If the required NDVs are unavailable, the join-selectivity fallback is `0.10`.

For other join predicates, the conservative default join selectivity is also `0.10`.

### Output pages

Estimated output pages are derived from estimated rows and row width using the 4096-byte page size:

```text
pages = ceil(rows * width / 4096)
```

## 4. Logical rewrite rules

Rewrites are applied before costing.

### Rule 1 — split conjunctions

```text
select[p AND q](X)
```

becomes stacked selections.

Precondition: none; the transformation is always safe.

### Rule 2 — push select below join or cross

A selection is pushed to one input of a join/cross if its predicate references columns from that side only.

Precondition: every column referenced by the predicate belongs to only one side.

### Rule 3 — convert cross plus equality select to join

A selection above a cross is converted to a join when the predicate references both sides and is an equality predicate.

This is the rewrite that makes a comma join equivalent to the same `JOIN ... ON` query.

### Rule 4 — push select through rename and union

A selection can move below a rename after its column names are rewritten through the alias. For `union` and `union_all`, the selection is pushed into both branches.

### Rule 5 — push select below group_by

A selection can move below a grouping operator only when it references grouping columns alone.

A predicate on an aggregate result must remain above the grouping operator.

### Rule 6 — projection pushdown

The optimizer inserts projections below operators so each branch keeps only columns required by its ancestors plus columns needed by the operator itself.

A column still referenced by a predicate, grouping key, join condition, sort key, or output projection must never be dropped.

### Rule 7 — cleanup

The optimizer removes projections that drop nothing and collapses adjacent selections. This does not change semantics but makes the rewritten plan and explain output easier to read.

## 5. Rewrite worked example

The required comma-join example is:

```sql
SELECT e.name
FROM Emp e, Dept d
WHERE e.did = d.did
  AND e.age > 60
  AND d.budget > 1000;
```

The intended rewrite behavior is:

```text
before                              after
project [e.name]                    project [e.name]
  select e.did=d.did                  join e.did=d.did
    select e.age>60                     project [e.name,e.did]
      select d.budget>1000                select e.age>60
        cross                               rename e (scan Emp)
          rename e (scan Emp)             project [d.did]
          rename d (scan Dept)              select d.budget>1000
                                              rename d (scan Dept)
```

The rewrite test suite includes the professor's worked example and currently passes.

## 6. Cost model

Cost is measured as page I/O: reads plus writes. CPU cost is ignored. `M` and `N` are estimated input page counts and `B` is the number of available frames.

```text
seqscan                M

filter                  0
project                 0
limit                   0

sort                    2*M*(passes - 1) + M
passes                  1 + ceil(log(ceil(M/B)) / log(B-1))

nested_loop_join        M + ceil(M/(B-2))*N

sort_merge_join         sort(M) + sort(N) + M + N

hash_join               3*(M + N)
```

`distinct` and `group_by` use the cost of the sort or hash-partitioning strategy selected for that operator.

These formulas are intentionally kept consistent with Module 2 because the report compares predicted optimizer cost with executor I/O.

## 7. Join enumeration

Connected joins are enumerated using dynamic programming over left-deep trees, in the Selinger style, for up to six relations.

For every base relation:

```text
best[{r}] = cheapest access path for r
```

Then for subset sizes 2 through n:

```text
best[S] =
    minimum over each possible added base relation r
    and each legal join algorithm
    of best[S - {r}] joined with best[{r}]
```

Pairings with no join predicate between the existing left subset and the new relation are skipped when a connected alternative exists.

For equality joins, the enumerator considers:

- block nested-loop join
- sort-merge join
- hash join

For non-equality joins, block nested-loop join is the legal general-purpose join.

### Why left-deep trees

A left-deep tree requires the right input of every join to be a base relation. This gives up bushy plans in which both inputs can themselves be joins. The restriction reduces the search space substantially and allows the outer side of a join sequence to pipeline naturally into the next join. For the project limit of up to six relations, dynamic programming over left-deep alternatives provides a manageable, deterministic search.

## 8. DP worked example and arithmetic note

For the professor's Section 5.1 example with 32 frames:

```text
A   = 100 pages, 5,000 rows
B'  = 10 pages,    500 rows
C   = 400 pages, 20,000 rows

A.x = B'.x  -> 1,000 rows, 20 pages
B'.y = C.y  -> 2,000 rows, 40 pages
```

The implementation reproduces the key DP entries:

```text
{A}          scan A                                              100
{B'}         scan B'                                              10
{C}          scan C                                              400
{A,B'}       B' outer, BNL with A inner                         110
{A,C}        no predicate, skipped                                -
{B',C}       B' outer, BNL with C inner                         410
{A,B',C}     {A,B'} outer, BNL with C inner                     530
```

The handout prints `550` for the alternative that starts from `{B',C}` and then joins A. Applying the handout's own BNL formula to a 40-page outer with 32 frames gives:

```text
incremental = 40 + ceil(40/30)*100
            = 40 + 2*100
            = 240

total       = 410 + 240
            = 650
```

The implementation preserves the stated cost formula, so it reports 650 for that alternative while still reproducing the required winning cost of 530.

## 9. Verified integration checks

The following checks were performed successfully:

- Full test suite: 349 tests passing.
- Section 5.1 join-order tests: 9 tests passing.
- Physical plans emitted by `opt plan` run unedited in Module 2.
- Equivalent comma join and `JOIN ... ON` queries produce identical physical JSON.
- With the test R/S statistics, 32 frames selects nested-loop join while 4 frames selects hash join.
- Running ANALYZE twice on an unchanged table produces identical visible statistics.
- Planning with no ANALYZE statistics still produces a valid executable physical plan.
- `opt explain --rewrite` displays before-rewrite logical plan, after-rewrite logical plan, and the final physical plan.
