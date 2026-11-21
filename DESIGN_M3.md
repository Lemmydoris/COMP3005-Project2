# Module 3 Design

## 1. Overview

Module 3 implements a SQL front end that converts SQL text into a logical query plan.

The pipeline is:

```text
SQL text
    |
    v
hand-written lexer
    |
    v
hand-written parser
    |
    v
SQL AST
    |
    v
semantic analysis against catalog
    |
    v
resolved semantic representation
    |
    v
logical-plan JSON
```

Module 3 does not choose physical algorithms.

In particular, a logical join remains:

```text
join
```

and never becomes:

```text
nested_loop_join
sort_merge_join
hash_join
```

Those decisions belong to Module 4.

The implementation is contained in the `sql_frontend` package:

```text
sql_frontend/
    __init__.py
    lexer.py
    ast.py
    parser.py
    semantic.py
    translator.py
    cli.py
```

---

## 2. Lexer

The SQL lexer is hand written.

It tracks:

```text
token kind
token value
line
column
```

Keywords are case-insensitive while identifiers preserve their case.

The scanner supports:

```text
identifiers
signed integers
single-quoted strings
escaped single quotes
comparison operators
punctuation
-- line comments
semicolon-separated statements
```

Comparison operators use maximal munch so that:

```text
<=
>=
<>
```

are recognized as individual tokens.

Lexical failures use the common error format:

```text
error: lexical: <message> at line L, column C
```

---

## 3. Parser and AST

The parser is a hand-written recursive-descent parser.

Parsing produces dataclass-based AST nodes rather than immediately constructing a logical plan.

Important AST nodes include:

```text
SelectQuery
SetQuery
TableRef
FromCross
FromJoin
ColumnRef
AggregateCall
Comparison
LogicalCondition
NotCondition
CreateTable
InsertStatement
```

Keeping parsing separate from semantic analysis is important because a syntactically valid SQL statement can still contain:

```text
unknown tables
unknown columns
ambiguous columns
type errors
invalid aggregate use
incompatible set inputs
```

The parser also encodes boolean precedence structurally.

Among boolean operators:

```text
NOT > AND > OR
```

Set operators have equal precedence and are left associative.

---

## 4. Scope Construction

Semantic analysis begins by constructing a scope from the `FROM` clause.

Each base-table reference contributes one scope entry.

Without an alias:

```sql
FROM Emp
```

the scope entry is named:

```text
Emp
```

With an alias:

```sql
FROM Emp e
```

the scope entry is named:

```text
e
```

and its columns become:

```text
e.eid
e.name
e.age
...
```

A table alias therefore replaces the base table name inside that scope.

For a self join:

```sql
FROM Emp e
JOIN Emp m ON e.mgr = m.eid
```

the scope contains two independent entries:

```text
e
m
```

The logical plan contains two scans of `Emp`, each under a separate `rename`.

Two scope entries are not permitted to have the same visible name.

Therefore:

```sql
FROM Emp, Emp
```

is rejected as a duplicate scope/alias error.

---

## 5. Subquery Scope

A subquery in `FROM` must have an alias.

For example:

```sql
FROM (
    SELECT did, COUNT(*) AS n
    FROM Emp
    GROUP BY did
) AS t
```

The inner query is analyzed independently.

Its output schema becomes the columns exposed by the outer scope entry `t`.

The outer query can therefore reference:

```text
t.did
t.n
```

but it cannot directly access columns that were not produced by the subquery.

The translator constructs the subquery's logical plan first and then places:

```text
rename t
```

above it.

---

## 6. Column Resolution

All column references are resolved during semantic analysis.

### Qualified reference

For:

```text
t.c
```

the analyzer first checks that `t` is a visible scope entry.

It then checks that `c` exists in that entry.

Failure of the first check reports an unknown table or alias.

Failure of the second reports an unknown column in that entry.

### Unqualified reference

For:

```text
c
```

all current scope entries are searched.

Exactly one match is required.

Zero matches produce an unknown-column error.

More than one match produces an ambiguity error that names all candidates.

For example:

```sql
SELECT did
FROM Emp, Dept
```

is rejected if both tables contain `did`, with candidates such as:

```text
Emp.did
Dept.did
```

After semantic analysis, source-column references are represented by fully qualified plan names.

---

## 7. SELECT * Expansion

`SELECT *` is expanded during semantic analysis.

Columns are expanded in:

```text
FROM order
then
schema order
```

For:

```sql
SELECT *
FROM Emp e, Dept d
```

the result begins with all `e` columns followed by all `d` columns.

Shared column names are not ambiguous during star expansion because every generated reference is explicitly qualified.

For example:

```text
e.city
d.city
```

can both appear.

---

## 8. ORDER BY Resolution

`ORDER BY` resolution uses two steps.

First, an unqualified name is checked against explicit output aliases in the select list.

If it does not match an output alias, it is resolved against the `FROM` scope.

This permits:

```sql
SELECT name
FROM Emp
ORDER BY age
```

even though `age` is not part of the select list.

For an aggregating query, an `ORDER BY` source column must still obey the grouping rules unless it resolves to an output alias.

Ordinary select aliases are preserved in semantic output metadata for output-schema and `ORDER BY` resolution. The available Module 3 handout defines the logical `project` node using resolved column names and does not provide a separate ordinary-column alias JSON field, so the translator does not invent an additional unrecognized logical-plan field.

Aggregate aliases are different because the `group_by` logical node explicitly contains the aggregate output name.

---

## 9. Type Rules

The semantic analyzer checks comparison types before logical-plan translation.

Comparisons require matching types.

Therefore:

```sql
WHERE age > '30'
```

is rejected when `age` is `INT`, because the comparison is:

```text
INT versus VARCHAR
```

Set operations require:

```text
same number of columns
same type in each position
```

The left input supplies the output column names.

Aggregate typing is:

```text
COUNT -> INT

SUM(INT) -> INT

AVG(INT) -> REAL

MIN(INT) -> INT
MIN(VARCHAR) -> VARCHAR

MAX(INT) -> INT
MAX(VARCHAR) -> VARCHAR
```

`SUM` and `AVG` reject non-INT input.

---

## 10. Aggregation Rules

A query is considered aggregating when either:

```text
GROUP BY is present
```

or an aggregate appears in the select list.

In an aggregating query, every non-aggregate selected source column must appear in `GROUP BY`.

Thus:

```sql
SELECT did, name, COUNT(*)
FROM Emp
GROUP BY did
```

is rejected because `name` is neither grouped nor aggregated.

`HAVING` operates after grouping.

It may use grouping columns and aggregates.

`WHERE` operates before grouping, so an aggregate inside `WHERE` is always rejected.

For example:

```sql
WHERE COUNT(*) > 1
```

is an aggregate semantic error.

A global aggregate is represented by a `group_by` node with no keys.

For:

```sql
SELECT COUNT(*)
FROM Emp
```

the logical grouping has:

```text
keys = []
```

This represents one global group.

Module 2 already implements the required empty-input behavior for global `COUNT(*)`, producing one row whose count is zero.

---

## 11. Aggregate Output Names

An explicit SQL alias is used when supplied.

For example:

```sql
COUNT(*) AS n
```

produces the aggregate output:

```text
n
```

If no alias is supplied, the implementation generates a deterministic name.

The naming rule is:

```text
lowercase_function + "_" + normalized_argument
```

`*` becomes:

```text
star
```

and a qualified column replaces the dot with an underscore.

Examples:

```text
COUNT(*)
    -> count_star

AVG(Emp.salary)
    -> avg_Emp_salary

SUM(Emp.age)
    -> sum_Emp_age
```

This rule is deterministic, readable, and stable across repeated compilations.

---

## 12. Bag Semantics

SQL uses bag semantics rather than the set semantics of the earlier relational-algebra project.

The translator therefore makes duplicate elimination explicit.

### Scan

A scan preserves duplicate rows.

### Project

Projection preserves duplicates.

Dropping columns does not automatically introduce a `distinct`.

For example:

```sql
SELECT city FROM Emp
```

produces only a `project`, not a `distinct`.

### SELECT DISTINCT

For:

```sql
SELECT DISTINCT city
FROM Emp
```

the translator produces:

```text
distinct
    project
        scan
```

The `distinct` is above the projection because duplicate elimination applies to the projected rows.

### GROUP BY

`GROUP BY` already produces one row per distinct group.

Therefore a redundant `DISTINCT` is not emitted above a grouping query.

### UNION ALL

`UNION ALL` preserves duplicates and translates directly to:

```text
union_all
```

### UNION

`UNION` uses set semantics and translates to:

```text
union
```

which removes duplicates.

### INTERSECT and EXCEPT

`INTERSECT` and `EXCEPT` also use set semantics and are represented by their corresponding logical operators.

This keeps duplicate elimination only where SQL actually requires it.

---

## 13. Logical Translation Order

A select block is translated bottom to top in the following canonical order:

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

Set operations are then placed between complete select blocks.

Module 3 performs no optimization.

In particular, predicates are not pushed downward.

For:

```sql
SELECT e.name, d.title
FROM Emp e
JOIN Dept d ON e.did = d.did
WHERE d.budget > 1000
```

the WHERE predicate remains above the join even though it refers only to `d`.

Predicate pushdown belongs to Module 4.

---

## 14. Comma Joins and Explicit Joins

The SQL forms:

```sql
FROM Emp e, Dept d
WHERE e.did = d.did
```

and:

```sql
FROM Emp e
JOIN Dept d ON e.did = d.did
```

are semantically related but deliberately produce different Module 3 plans.

The comma form becomes:

```text
select e.did = d.did
    cross
        rename e
            scan Emp
        rename d
            scan Dept
```

The explicit form becomes:

```text
join e.did = d.did
    rename e
        scan Emp
    rename d
        scan Dept
```

Module 3 preserves where the user wrote the predicate.

Recognizing these two forms as equivalent is a rewrite for Module 4.

The same rule is tested on a four-table chain.

---

## 15. Set Operations

Set operators are translated between complete query blocks.

Supported logical operators are:

```text
union
union_all
intersect
except
```

They are left associative.

Therefore:

```text
A UNION B EXCEPT C
```

becomes logically equivalent to:

```text
except(
    union(A, B),
    C
)
```

`UNION` and `UNION ALL` deliberately produce different plan nodes even when their input queries are identical.

---

## 16. Error Handling

Errors use the common format:

```text
error: <category>: <message> at line L, column C
```

The supported categories are:

```text
lexical
syntax
name
ambiguity
type
aggregate
schema
```

The front end reports the first error and stops.

No stack trace is shown through the `sql` CLI.

Important distinctions include:

```text
unknown table
versus
unknown column
```

and:

```text
unknown column
versus
ambiguous column
```

These differences are preserved in the error messages.

---

## 17. Command-Line Interface

Module 3 exposes:

```text
sql parse
sql compile
sql check
```

### Parse

```text
sql parse --query "SELECT ..." --explain
```

does not require a catalog.

It prints the parsed AST as an indented tree.

### Compile

```text
sql compile --db DIR --file q.sql --json
```

parses and semantically analyzes the SQL against the catalog and emits logical-plan JSON for query statements.

### Check

```text
sql check --db DIR --file q.sql
```

performs parsing and semantic checking.

A successful check is silent and returns exit code 0.

An error is printed and returns exit code 1.

---

## 18. Verification

Module 3 has tests for:

```text
lexer behavior
parser behavior
semantic analysis
logical-plan translation
CLI behavior
all fifteen required Module 3 cases
```

The dedicated required-case suite contains:

```text
15 tests
```

and all fifteen pass.

After adding the Module 3 required-case suite, the complete project test suite contains:

```text
281 tests
```

with:

```text
281 passing
0 failing
```

The required tests include:

```text
self join with two aliases
three-table SELECT * expansion
ambiguous unqualified column
UNION versus UNION ALL
WHERE and HAVING placement
non-grouped selected column
aggregate in WHERE
FROM subquery with alias
ORDER BY non-selected column
INT/VARCHAR comparison error
unknown table versus unknown column
duplicate scope name
global COUNT(*)
incompatible UNION
four-table comma versus JOIN ON plans
```

The resulting Module 3 logical plans contain no physical join algorithm names, preserve SQL predicate placement, and use qualified source-column references after semantic resolution.