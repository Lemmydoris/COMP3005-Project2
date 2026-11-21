# REPORT_M4.md — Module 4 Query Optimizer

## 1. Experimental setup

The companion dataset and workload were not provided. Following the instructor clarification, I created my own data and workload and documented the assumptions used for all measurements.

All measurements in Sections 2–4 use the database directory:

```text
m4_report_db
```

with a memory budget of:

```text
B = 32 frames
```

Actual I/O is measured as:

```text
actual I/O = page_reads + page_writes
```

### Main workload schema

The workload uses four relations:

```text
Customers(cust_id, region, segment, age)
Orders(order_id, cust_id, product_id, amount)
Products(product_id, supplier_id, category, price)
Suppliers(supplier_id, region)
```

The generated relation sizes were:

| Relation | Tuples |
|---|---:|
| Customers | 5,000 |
| Orders | 20,000 |
| Products | 2,000 |
| Suppliers | 200 |

IDs were generated deterministically. Join columns were generated so that the foreign-key-style joins used by the workload have matching values. Categorical and numeric values were generated deterministically so equality and range predicates have repeatable results.

`Customers.region` and `Customers.segment` were intentionally correlated. This provides a simple example of the weakness of estimating conjunctions by multiplying independent single-column selectivities.

The measured base-table page counts visible in the optimizer/executor were approximately:

| Relation | Data pages |
|---|---:|
| Customers | 26 |
| Orders | 100 |
| Products | 11 |
| Suppliers | 2 |

### Twenty-query workload

The workload deliberately mixes single-table filters, range predicates, two-, three-, and four-relation joins, a comma join, grouping, sorting, and limiting.

| Query | Main operation |
|---|---|
| q01 | Customers filtered by `region = 1` |
| q02 | Products filtered by `price > 500` |
| q03 | Customers filtered by correlated `region = 1 AND segment = 1` |
| q04 | Customers filtered by `region = 1 AND segment = 2` |
| q05 | Customers–Orders join with customer-region filter |
| q06 | Customers–Orders join with correlated region/segment filters |
| q07 | Orders–Products join with product-category filter |
| q08 | Products–Suppliers join with supplier-region filter |
| q09 | Customers–Orders–Products join with region/category filtering |
| q10 | Orders–Products–Suppliers join with category/region filtering |
| q11 | Four-relation join with correlated customer predicates |
| q12 | Four-relation join with customer-region and product-category filters |
| q13 | Products/Suppliers comma join with equality predicate and supplier filter |
| q14 | Customers–Orders join with region and amount range filter |
| q15 | Orders–Products join with amount and price range filters |
| q16 | Four-relation join with customer-region filter |
| q17 | Products filtered by category and price |
| q18 | Customers grouped by region after an age predicate |
| q19 | Customers–Orders join grouped by region with amount predicate |
| q20 | Orders filtered, sorted by amount descending, then limited |

The logical plans for these queries were retained under `m4_logical/`.

---

## 2. Estimation quality

For every optimized plan, estimated cardinality was compared with the executor's actual `tuples_out` value at every recorded node. The generated file:

```text
m4_results/estimation_nodes.csv
```

contains the complete node-level measurements.

Q-error was computed as the larger cardinality divided by the smaller cardinality. For a zero-cardinality case, the denominator was clamped to 1 so that division by zero did not occur.

Across the twenty-query workload:

```text
queries measured = 20
plan nodes measured = 228
median q-error = 1.0
worst q-error = 400,000,000
worst node = q12 root project
```

The median of 1.0 means that at least half of the measured nodes were estimated exactly or effectively exactly. The largest errors occurred when the optimizer predicted a large intermediate or final result but the actual result was empty.

### Worst q-error observed in each query

| Query | Worst q-error |
|---|---:|
| q01 | 1.0 |
| q02 | 1.0020 |
| q03 | 6.6667 |
| q04 | 50.0 |
| q05 | 500.0 |
| q06 | 50.0 |
| q07 | 400.0 |
| q08 | 20.0 |
| q09 | 20,000,000 |
| q10 | 800.0 |
| q11 | 200,000 |
| q12 | 400,000,000 |
| q13 | 20.0 |
| q14 | 3,268.1373 |
| q15 | 1,768.1471 |
| q16 | 2,000,000 |
| q17 | 1.0025 |
| q18 | 5.2 |
| q19 | 1,093.4886 |
| q20 | 509.25 |

### Correlation example already visible in the workload

For q03, the optimizer estimated:

```text
75 rows
```

while execution returned:

```text
500 rows
```

giving:

```text
q-error = 500 / 75 = 6.67
```

The two predicates are on `Customers.region` and `Customers.segment`. The estimator multiplies the two selectivities:

```text
sel(p AND q) = sel(p) * sel(q)
```

which assumes statistical independence. The generated columns are correlated, so that assumption is false.

The much larger q-errors in queries such as q09 and q12 also show that errors in intermediate cardinality can compound through joins. q12 is the most extreme because a plan node was estimated at 400,000,000 rows while the actual result was empty.

---

## 3. Does optimization pay?

The optimized plan was compared with an unoptimized baseline for every query.

The baseline used:

```text
written join order
fixed nested-loop join algorithm
no logical predicate pushdown
no projection pushdown
```

Both plans were executed with the same database and `B = 32`, and actual I/O was measured as page reads plus page writes.

| Query | Optimized I/O | Unoptimized I/O | Baseline / optimized |
|---|---:|---:|---:|
| q01 | 26 | 26 | 1.000 |
| q02 | 11 | 11 | 1.000 |
| q03 | 26 | 26 | 1.000 |
| q04 | 26 | 26 | 1.000 |
| q05 | 126 | 126 | 1.000 |
| q06 | 126 | 126 | 1.000 |
| q07 | 111 | 144 | 1.297 |
| q08 | 13 | 13 | 1.000 |
| q09 | 137 | 192 | 1.401 |
| q10 | 113 | 156 | 1.381 |
| q11 | 172 | 210 | 1.221 |
| q12 | 170 | 210 | 1.235 |
| q13 | 13 | 13 | 1.000 |
| q14 | 126 | 126 | 1.000 |
| q15 | 111 | 144 | 1.297 |
| q16 | 161 | 210 | 1.304 |
| q17 | 11 | 11 | 1.000 |
| q18 | 26 | 26 | 1.000 |
| q19 | 162 | 234 | 1.444 |
| q20 | 100 | 100 | 1.000 |

Totals:

```text
total optimized I/O   = 1,767
total baseline I/O    = 2,130
I/O saved             = 363 pages
overall reduction     = 17.0%
per-query ratio range = 1.000x to 1.444x
```

The largest improvement was q19, where the baseline used 234 page I/Os and the optimized plan used 162, a ratio of about 1.44x.

Several single-table or already-simple queries had a ratio of exactly 1.0. This is expected: when there is no meaningful join-order or pushdown decision to improve, optimization may produce the same amount of physical I/O.

The optimizer was also separately verified to react to memory size. On the R/S test case:

```text
B = 32 -> nested_loop_join, estimated cost 30
B = 4  -> hash_join, estimated cost 90
```

Therefore physical algorithm selection is cost-based rather than fixed.

---

## 4. Which rewrite rule mattered?

The workload was rerun with one logical rewrite rule disabled at a time.

For Rules 3–7, a faster equivalent measurement procedure was used: if disabling a rule produced exactly the same physical plan as the normal optimizer, the already-measured I/O of that identical plan was reused. Changed plans were executed normally. Rules 1 and 2 were measured by executing the complete workload.

| Rule disabled | Description | All rules I/O | Disabled-rule I/O | Difference |
|---|---|---:|---:|---:|
| 1 | Split conjunctions | 1,767 | 1,806 | +39 |
| 2 | Selection pushdown | 1,767 | 1,828 | +61 |
| 3 | Cross/select to join | 1,767 | 1,767 | 0 |
| 4 | Push through rename/union | 1,767 | 1,767 | 0 |
| 5 | Push below group_by | 1,767 | 1,767 | 0 |
| 6 | Projection pushdown | 1,767 | 1,916 | +149 |
| 7 | Cleanup | 1,767 | 1,767 | 0 |

### Interpretation

Rule 6, projection pushdown, had the largest effect. Disabling it increased workload I/O by 149 pages. The largest visible increases occurred on the wider multi-relation queries, including q11, q12, q16, and q19. Keeping unnecessary columns through joins increases intermediate tuple width and therefore the number of pages that later physical operators must process.

Rule 2, selection pushdown, was the next most useful rule, increasing total I/O by 61 pages when disabled. Rule 1 also mattered because splitting a conjunction allows individual one-sided predicates to be pushed independently.

Rules 3, 4, 5, and 7 had no total page-I/O effect on this particular workload. This does not mean the rules are useless. For example, Rule 3 changed q13 from the comma-join representation, but both physical alternatives happened to use 13 actual page I/Os. Rule 7 is primarily a cleanup rule, so an unchanged I/O total is expected.

---

## 5. Where the optimizer breaks

A separate controlled database, `m4_break_db`, was created so that the failure case could be measured without modifying the main workload.

The important relation contained:

```text
CorrCustomers(id, region, segment, p1, ..., p7)
```

with 5,000 rows. `region` had ten values and `segment` was generated as:

```text
segment = region
```

for every row. The two columns are therefore perfectly correlated.

A second relation, `CorrProbe`, contained 500 rows and was joined on `id`. Seven `VARCHAR(255)` padding columns were included in each relation so the choice of physical join algorithm had a visible page-I/O effect.

The critical predicate was:

```text
c.region = 1 AND c.segment = 1
```

Each individual predicate selects 10% of the table:

```text
sel(region = 1)  = 0.10
sel(segment = 1) = 0.10
```

The optimizer assumes independence, so it estimates:

```text
5,000 * 0.10 * 0.10 = 50 rows
```

The actual result is:

```text
500 rows
```

because whenever `region = 1`, `segment = 1` as well.

Therefore:

```text
estimated rows = 50
actual rows    = 500
q-error        = 10.0
```

### Plan consequence

Because it believed the filtered input contained only 50 rows, the optimizer selected a nested-loop join.

Actual execution costs were:

| Plan | Reads | Writes | Total I/O |
|---|---:|---:|---:|
| Optimizer-chosen nested-loop join | 4,763 | 0 | 4,763 |
| Equivalent hash-join alternative | 3,273 | 518 | 3,791 |

The hash join saved:

```text
4,763 - 3,791 = 972 page I/Os
```

or approximately 20.4% of the chosen plan's I/O.

The final join returned 50 rows because only 50 of the 500 filtered customer IDs matched IDs present in the 500-row probe relation. The important estimation error occurs before that join: the filtered customer relation contains 500 rows, not the estimated 50.

### Failed assumption

The failed assumption was:

```text
region and segment are statistically independent
```

Single-column histograms and NDVs cannot represent this dependency.

A statistic that would prevent this error is a multi-column statistic for:

```text
(region, segment)
```

such as a joint frequency distribution, multi-column histogram, or another extended statistic that records their dependency. Such a statistic would allow the optimizer to estimate the conjunction directly instead of multiplying two independent selectivities.

This experiment shows that a locally reasonable selectivity formula can make the optimizer choose a physically worse plan when its statistical assumptions do not hold.

---

## 6. Dynamic-programming evidence

### Section 5.1 reproduction

For the three-relation worked example with `B = 32`, the implementation produced:

```text
Subset                  Best plan considered                                                  Cost
--------------------------------------------------------------------------------------------------------
{A}                     scan A                                                                100
{B'}                    scan B'                                                               10
{C}                     scan C                                                                400
{A,B'}                  {B'} outer, nested_loop_join with A inner, condition A.x = B'.x       110
{A,C}                   no predicate, skipped                                                 -
{B',C}                  {B'} outer, nested_loop_join with C inner, condition B'.y = C.y       410
{A,B',C}                {A,B'} outer, nested_loop_join with C inner, condition B'.y = C.y     530
                        alternative, {B',C} outer, nested_loop_join with A inner              650
```

The winning cost is 530.

The handout's alternative value is 550, but applying the stated block nested-loop formula to the 40-page outer relation requires two passes over the 100-page inner relation, producing 650. The implementation keeps the stated formula rather than special-casing the printed example. The winning plan is unchanged.

### Full four-relation DP table

The required four-relation query joins:

```text
Customers
Orders
Products
Suppliers
```

with predicates:

```text
Customers.cust_id = Orders.cust_id
Orders.product_id = Products.product_id
Products.supplier_id = Suppliers.supplier_id
```

The complete `dp-table` output with `B = 32` was:

```text
Subset                              Best plan considered                                               Cost
----------------------------------------------------------------------------------------------------------------
{Customers}                         scan Customers                                                     25
{Orders}                            scan Orders                                                        99
{Products}                          scan Products                                                      10
{Suppliers}                         scan Suppliers                                                     1

{Customers,Orders}                  {Customers} outer, nested_loop_join with Orders inner,
                                    condition Customers.cust_id = Orders.cust_id                       124

{Customers,Products}                no predicate, skipped                                              -
{Customers,Suppliers}               no predicate, skipped                                              -

{Orders,Products}                   {Products} outer, nested_loop_join with Orders inner,
                                    condition Orders.product_id = Products.product_id                  109

{Orders,Suppliers}                  no predicate, skipped                                              -

{Products,Suppliers}                {Suppliers} outer, nested_loop_join with Products inner,
                                    condition Products.supplier_id = Suppliers.supplier_id             11

{Customers,Orders,Products}         {Customers,Orders} outer, nested_loop_join with Products inner,
                                    condition Orders.product_id = Products.product_id                  341

{Customers,Orders,Suppliers}        no predicate, skipped                                              -
{Customers,Products,Suppliers}      no predicate, skipped                                              -

{Orders,Products,Suppliers}         {Products,Suppliers} outer, nested_loop_join with Orders inner,
                                    condition Orders.product_id = Products.product_id                  124

{Customers,Orders,Products,Suppliers}
                                    {Orders,Products,Suppliers} outer,
                                    nested_loop_join with Customers inner,
                                    condition Customers.cust_id = Orders.cust_id                       539

                                    alternative:
                                    {Customers,Orders,Products} outer,
                                    nested_loop_join with Suppliers inner,
                                    condition Products.supplier_id = Suppliers.supplier_id             584
```

The optimizer therefore retained the connected left-deep plan with estimated cost 539 instead of the competing complete-subset plan costing 584.

Disconnected subsets such as `{Customers,Products}` were skipped because no join predicate connects the two relations.

---

## 7. Functional checklist evidence

The following Module 4 behaviors were verified during implementation and testing:

- The Section 3 rewrite example reproduces.
- Rule 1 splits conjunctions.
- Rule 2 pushes one-sided selections.
- Rule 3 converts a cross plus an equality predicate into a join.
- Rule 4 pushes selections through rename/union when safe.
- Rule 5 only pushes grouping-column predicates below `group_by`.
- Rule 6 preserves every column still required by a predicate, join, grouping, sort, or final output.
- Rule 7 removes no-op projections and collapses adjacent selections.
- The Section 5.1 DP winner is 530.
- Dynamic programming uses connected left-deep join enumeration.
- Comma joins and equivalent `JOIN ... ON` queries produce the same physical plan.
- Changing the memory budget can change the selected physical join algorithm.
- Running `ANALYZE` twice on unchanged data produces identical visible statistics.
- Planning without ANALYZE still produces a valid physical plan using fallback metadata and selectivity constants.
- Physical plans produced by the optimizer are accepted directly by the Module 2 executor.

---

## 8. Measurement artifacts

The following generated files preserve the measurements used in this report:

```text
m4_results/estimation_nodes.csv
m4_results/optimized_io.csv
m4_results/optimization_payoff.csv
m4_results/rewrite_ablation.csv
m4_dp4.json
m4_break_logical.json
m4_break_chosen.json
m4_break_hash.json
```

The workload logical plans are stored under:

```text
m4_logical/
```

These files make the reported values reproducible from the same database and workload.
