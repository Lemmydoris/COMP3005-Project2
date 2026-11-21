# Design Log

## September 29, 2026

### Grammar and Language Design

I started by defining the grammar before writing the parser. I chose recursive descent parsing and divided the relational operators into separate precedence levels. Also I decided that `times` and `join` have higher precedence than `intersect`, while `union` and `minus` have the lowest precedence and associate to the left.

One problem I had while using AI assistance was Markdown formatting in `GRAMMAR.md`. Some code blocks were opened but not closed correctly, causing later headings such as Sections 4 and 5 to appear as code instead of Markdown headings. I found the problem by noticing that the headings were no longer highlighted normally in the editor. I fixed it by closing each code fence with three backticks and removing unnecessary escape characters.

### Tokenizer
I implemented the tokenizer manually without regular expressions. I tested it with the required difficult inputs, including queries with no whitespace, `>=`, negative numbers, commas and parentheses inside quoted strings, doubled quotes in `O''Brien`, and an unterminated string.

The tokenizer originally treated all words, including words such as `union`, as identifiers. Instead of changing this immediately, I kept that design intentionally and moved keyword interpretation into the parser. This allows a query such as `select[union=3](R)` to treat `union` as an attribute when the grammar expects an attribute.

### Parser
I implemented a recursive descent parser based directly on the grammar. The parser uses separate functions for union/minus, intersection, product/join, unary expressions, conditions, and operands. This avoids the direct left recursion in the naive grammar.

I verified the precedence rules by printing the parse tree for `A union B minus C`. The tree grouped the expression as `(A union B) minus C`, which matched the rule documented in `GRAMMAR.md`.

## September 30, 2026

### Relational Operators and Error Handling

I implemented selection, projection, rename, Cartesian product, theta join, union, intersection, and difference. I also created separate error categories for lexical, syntax, name, schema, and type errors.

One AI-assisted draft was incomplete when I first assembled `operators.py`. The evaluator referred to functions such as `select_table`, `project_table`, `rename_table`, `times_table`, and `join_table`, but those function definitions were missing from my copy. I found the problem by reviewing the file before running it and added the missing relational-operator section.

Another incomplete part of the initial testing was the incompatible-union case. The first manual semantic tests covered joins, projection, type errors, duplicate projection attributes, and empty results, but did not directly test a union between incompatible schemas. I added `R_union` and `S_union` with different attribute names and verified that the engine produced a `SchemaError`.

### Required Test Suite

I created a `tests/test_required.py` test suite containing all 25 required cases. Running the file directly caused `ModuleNotFoundError: No module named 'tokenizer'` because Python started from the `tests` directory. I instead ran the suite from the project root with:

`python -m unittest discover -s tests -v`

All 25 tests passed.

### Relation Loader and Command-Line Interface

I added a relation loader that reads the required relation-definition syntax and converts it into in-memory relations. I also created `ra.py` as the command-line entry point. The program can print a parse tree using `--tree` or execute a query using a data file supplied with `--data`.

I tested a real join between `Employees` and `Dept`. With three employee tuples and two department tuples, the nested-loop join performed exactly six comparisons.

### Performance Study

I created a data generator for relations `R(a,b)` and `S(b,c)` and added counters for selection examinations and join comparisons.

The first join measurements were:

| n | m | Comparisons | Wall Time (s) | Output Tuples |
|---:|---:|---:|---:|---:|
| 1000 | 1000 | 1,000,000 | 2.234465 | 1,000 |
| 2000 | 2000 | 4,000,000 | 7.900435 | 2,000 |
| 4000 | 4000 | 16,000,000 | 30.882528 | 4,000 |
| 8000 | 8000 | 64,000,000 | 121.743664 | 8,000 |

The comparison count is matching `n × m` exactly so far. When both relation sizes double, the number of comparisons becomes four times larger. The full join benchmark was completed through 64,000 tuples per relation. The largest experiment performed 4,096,000,000 tuple pair comparisons and took 7,719.363992 seconds. The final log-log slope was 1.9705, which is close to the quadratic growth expected from the nested-loop implementation.

## Project 2 preparation refactor — 2026-11-11

- Split the parse-tree node definitions into `ra_tree.py` so tokenizer, parser, tree, and operators can be imported independently.
- Added JSON round-trip helpers for every Bonus Project 1 tree node.
- Exposed the condition parser as `parse_condition_text()` for reuse by later modules.
- Added a data-source contract (`get_relation(name)`) so the evaluator no longer owns a raw in-memory relation dictionary.
- Switched base tuples, projection, product, and join to preserve duplicates for Project 2 bag semantics.
- Bonus 1 required test 23 changed meaning: projection formerly removed duplicate `DID` values; Project 2 requires projection to preserve them. The expected result is now `D1, D2, D1`.
- Kept the remaining Bonus 1 behavior and tests unchanged.

### AI-assistance note
The first project-planning pass assumed the companion traces/JSON schemas/workloads mentioned in the module documents would be downloadable. The course discussion clarification from the instructor states they will not be posted and students must create their own test inputs. We corrected the plan before coding module-specific test data. This is a project-wide clarification, not counted as one of the required per-module AI failure examples.

# Module 1 — Storage Engine and Buffer Pool

## AI Use and Design Corrections

I used ChatGPT as a development assistant while implementing and testing Module 1. I did not accept its suggestions without testing them against the project specification. The following are examples where an AI suggestion or AI-assisted change was incorrect or incomplete and had to be detected and corrected.

### Entry 1 — Buffer Pool Miss Counter Was Incremented Too Early

**Area:** `storage/buffer.py`

During implementation of `fetch_page`, the AI-assisted version initially incremented the buffer pool's `misses` counter as soon as a requested page was found not to be resident.

This was not fully consistent with the project's definition of a miss. According to the required counter semantics, a miss represents a fetch that actually requires a disk read.

The problematic sequence was conceptually:

```text
page not resident
-> increment misses
-> try to obtain a frame
-> possibly fail because every frame is pinned
```

This meant that a failed fetch caused by having no unpinned frame could incorrectly increase the miss counter even though no disk read occurred.

I discovered this while auditing the implementation against the exact counter definitions and the pinned-frame failure requirement.

I corrected `fetch_page` so that the miss counter is incremented only after an available frame has been found and immediately before the actual disk read.

The corrected behavior is:

```text
page not resident
-> find an available frame
-> fail without changing miss count if none exists
-> perform disk read
-> increment miss count
```

This also keeps repeated commands deterministic and makes the reported counters correspond to actual I/O.

---

### Entry 2 — Test Placement Accidentally Nested the CLOCK Test

**Area:** `tests/test_buffer.py`

While adding tests with AI guidance, the CLOCK trace test was initially placed at the wrong indentation level and became nested inside another test instead of being a separate test method.

The test runner therefore executed fewer tests than expected. The unexpected test count was the clue that the test had not been discovered independently.

After examining `test_buffer.py`, I corrected the indentation so that:

```text
test_professor_clock_trace
```

was a separate method of `BufferPoolTests`.

After the correction, the CLOCK test appeared independently in the unittest output and verified the required result for:

```text
B = 3
trace = 1 2 3 1 4 2
```

with:

```text
hits = 2
misses = 4
evictions = 1
```

This incident showed that a test passing as part of another method is not sufficient; the test discovery output itself must also be checked.

---

### Entry 3 — New-Page Test Was Also Accidentally Nested

**Area:** `tests/test_buffer.py`

A similar test-structure problem occurred when the AI-assisted `new_page()` test was added.

The new-page test was accidentally inserted inside the CLOCK test rather than becoming an independent unittest method.

This produced a misleading failure involving an expected zero value and also caused the total number of discovered tests to be lower than expected.

I fixed the indentation and separated the test into its own method:

```text
test_new_page_is_zero_filled_pinned_and_dirty
```

The independent test then verified that a newly allocated page is:

```text
4096 bytes
zero-filled
pin_count = 1
dirty = true
```

and does not require a disk read merely to initialize its zero-filled contents.

The final unittest output now lists this test separately.

---

### Entry 4 — AI Test Expected the Wrong Exception Class

**Area:** `tests/test_buffer.py`

When adding a hardening test for the required error on unpinning a page whose pin count is already zero, the AI-assisted test initially expected:

```python
RuntimeError
```

However, the existing implementation raised:

```python
ValueError
```

The unittest run produced an error even though the buffer pool was correctly rejecting the invalid unpin operation.

I checked the Module 1 specification again. The requirement states that unpinning a page at pin count zero must produce an error, but it does not require a specific Python exception class.

Therefore, changing the implementation simply to satisfy the AI-generated test would have been unnecessary and could have introduced inconsistency.

Instead, I corrected the test to verify the behavior actually required by the specification:

```python
with self.assertRaisesRegex(
    ValueError,
    "pin count 0"
):
    pool.unpin_page(
        0,
        is_dirty=False
    )
```

After this correction, the complete test suite reported:

```text
Ran 74 tests

OK
```

This was an example where the implementation was correct and the AI-generated test assumption was wrong.

---

## Module 1 Verification

After correcting the issues above, I reran the complete automated test suite.

The final result was:

```text
Ran 74 tests in 1.677s

OK
```

Additional manual measurements were also performed for:

- record capacity
- LRU and CLOCK replacement
- large sequential scans
- deterministic buffer counters
- a real byte-level page layout

These checks were used to validate AI-assisted implementation decisions against the actual project specification rather than assuming that generated code or tests were correct.

# Module 3 — SQL Front End

## Decision: Separate SQL front end package

I implemented Module 3 in a new `sql_frontend` package instead of modifying the Bonus Project 1 `tokenizer.py` and `parser.py`.

This keeps the old relational-algebra implementation stable and prevents Module 3 changes from breaking earlier tests.

The SQL front end has separate lexer, AST, parser, semantic-analysis, translation, and CLI layers.

## Decision: Hand-written scanner and parser

The SQL scanner and parser are hand written.

I did not use regular expressions or a parser generator.

The parser first creates an AST and does not perform catalog lookup or optimization while parsing.

This keeps syntax errors separate from semantic errors.

## Decision: Permit base-table aliases without AS

The grammar sketch shows base-table aliases with `AS`, but required examples use forms such as:

```sql
FROM Emp e
```

The parser therefore accepts both:

```sql
FROM Emp e
```

and:

```sql
FROM Emp AS e
```

Subqueries in `FROM` continue to require an explicit alias.

## Decision: Allow aggregates in condition syntax and reject them semantically when necessary

The required HAVING examples contain conditions such as:

```sql
HAVING COUNT(*) > 5
```

Therefore the parser permits aggregate expressions as condition operands.

The semantic phase determines whether the location is legal.

An aggregate in `HAVING` can be valid.

An aggregate in `WHERE` is rejected because WHERE is evaluated before grouping.

## Decision: Resolve every source column before translation

Semantic analysis constructs a scope from the FROM clause and resolves every column before logical-plan generation.

Unqualified columns must match exactly one scope entry.

Ambiguous references name their candidates.

`SELECT *` expands in FROM order and schema order.

Resolved source columns carry qualified logical names such as:

```text
Emp.age
e.name
d.title
```

This prevents the translator and later optimizer from having to repeat name resolution.

## Decision: Preserve SQL bag semantics

Projection does not remove duplicates.

A `distinct` logical node is emitted only when SQL requires duplicate elimination.

`SELECT DISTINCT` emits a distinct above project.

`UNION ALL` preserves duplicates.

`UNION`, `INTERSECT`, and `EXCEPT` use set semantics.

A grouping query does not receive a redundant distinct because `GROUP BY` already produces one row per group.

## Decision: Deterministic aggregate names

An aggregate uses its SQL `AS` alias when supplied.

Otherwise I generate a deterministic name from the function and argument.

Examples:

```text
COUNT(*) -> count_star
AVG(Emp.salary) -> avg_Emp_salary
```

Qualified-column dots are replaced by underscores in generated aggregate names.

## Decision: Preserve written predicate placement in Module 3

The logical translator performs no optimization.

A comma in FROM produces a `cross`, while the WHERE condition remains in a `select` node above it.

`JOIN ... ON` produces a logical `join` with the ON condition attached.

Even when the two forms are semantically equivalent, Module 3 intentionally produces different plans.

Recognizing and rewriting that equivalence is deferred to Module 4.

## Decision: Canonical logical-plan order

Select blocks are translated in this order from bottom to top:

```text
FROM
WHERE
GROUP BY
HAVING
PROJECT
DISTINCT
ORDER BY
LIMIT
```

Set operations combine complete blocks and are left associative.

No logical plan contains a physical algorithm name.

## Decision: ORDER BY name resolution

`ORDER BY` first checks explicit output aliases and then checks the FROM scope.

This allows a query to sort by a source column that is not present in the select list.

The semantic representation retains output alias information so aliases can participate in name resolution.

The available Module 3 handout does not define an additional ordinary-column alias field for the logical `project` JSON node, so I did not invent an unsupported field.

## Decision: Common error format

Lexical, syntax, name, ambiguity, type, aggregate, and schema errors use:

```text
error: <category>: <message> at line L, column C
```

The CLI reports the first error and does not expose Python stack traces.

## Verification checkpoint

The dedicated Module 3 required-case suite passes all 15 professor-required cases.

The complete project suite after Module 3 contains:

```text
281 passing tests
0 failures
```# Module 4 entries for DESIGN_LOG.md

Append the following entries to the existing `DESIGN_LOG.md`.

## Module 4 — Statistics storage

**Decision:** Store optimizer statistics in the existing Module 1 catalog and expose them through `entry["statistics"]`.

**Reason:** The optimizer needs persistent statistics that survive process restarts and are available to both the CLI and planner.

**Implementation detail:** Histogram data can exceed one catalog record, so large statistics are serialized into internal statistics-chunk records in `catalog.db`. `Catalog.get_table()` reconstructs the newest complete statistics version.

## Module 4 — Missing statistics

**Decision:** Planning continues when `ANALYZE` has not been run.

**Fallbacks:** Base rows/pages come from catalog metadata, row width comes from the declared schema, equality selectivity defaults to `0.10`, range selectivity to `1/3`, and generic join selectivity to `0.10`.

## Module 4 — Rewrite before costing

**Decision:** Apply logical rewrites before cardinality estimation and physical join selection.

**Reason:** Predicate and projection pushdown change intermediate cardinality/width, while cross-plus-equality conversion allows comma joins and explicit joins to share the same physical-planning path.

## Module 4 — Join enumeration

**Decision:** Use dynamic programming over connected left-deep trees for up to six relations.

**Reason:** Left-deep enumeration gives a manageable search space and supports pipelined execution while still exploring join order and physical join algorithm.

**Tradeoff:** Bushy trees can sometimes be cheaper, but they are intentionally outside the selected search space.

## Module 4 — Cost unit

**Decision:** Use page I/O as the optimizer cost unit and ignore CPU.

**Reason:** This matches Module 2 and allows predicted optimizer cost to be compared directly with executor reads and writes.

## Module 4 — EXPLAIN rewrite view

**Decision:** Keep normal `opt explain` output stable and provide an optional `--rewrite` view.

**Reason:** The required physical explain format remains unchanged while the before/after logical trees can still be shown for the report.

## Module 4 — DP table presentation

**Decision:** `dp-table` prints the retained best candidate for every subset, marks disconnected subsets as `no predicate, skipped`, and prints a competing complete-subset plan.

## Module 4 — Section 5.1 arithmetic discrepancy

**Observation:** The worked handout prints 550 for the `{B',C}`-then-A alternative, but the stated BNL formula with `B=32` gives 650.

**Decision:** Preserve the stated BNL formula instead of special-casing the example.

**Verified result:** The winning plan still costs 530, so the discrepancy does not change the optimizer's selected plan.

## Module 4 — Report workload

**Decision:** Use a deterministic four-table workload created locally after the instructor clarified that companion files would not be posted.

**Reason:** Deterministic generation makes the twenty-query measurements reproducible and allows the report to document the exact assumptions used.

## Module 4 — Correlation failure experiment

**Decision:** Use a separate controlled database with perfectly correlated `region` and `segment` columns to test the optimizer's independence assumption.

**Result:** The optimizer estimated 50 rows where 500 existed, chose nested-loop join, and incurred 4,763 page I/Os. An equivalent hash join used 3,791 I/Os.

**Lesson:** Single-column statistics are insufficient for strongly correlated predicates; a joint or multi-column statistic would prevent this error.
