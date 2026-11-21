# COMP 3005 Bonus Project 1
## Relational Algebra Engine

This project implements a small relational algebra engine in Python. It includes a hand-written tokenizer, recursive descent parser, parse-tree printer, relational algebra evaluator, relation-definition loader, error handling, test suite, data generator, and performance instrumentation.

The implementation does not use regular expressions, parser generators, `eval`, `exec`, pandas, NumPy, or an embedded SQL engine.

## Requirements

- Python 3.11 or later
- No external packages are required for the core engine

## Project Structure

- `tokenizer.py` - hand-written character-by-character tokenizer
- `parser.py` - recursive descent parser and parse-tree definitions
- `operators.py` - relational algebra operators and evaluation
- `relation_loader.py` - loads relation definitions from files
- `ra.py` - command-line interface
- `generator.py` - generates benchmark relation data
- `benchmark.py` - runs join performance experiments
- `GRAMMAR.md` - EBNF grammar, precedence, ambiguity demonstration, and parsing strategy
- `DESIGN_LOG.md` - dated development diary
- `REPORT.md` - performance study
- `sample.ra` - example relation definitions
- `tests/test_required.py` - required test cases

## Supported Relational Algebra Operators

The engine supports the following operators:

### Unary Operators

```text
select[condition](expression)
project[attribute-list](expression)
rename[new-relation-name](expression)
```

### Binary Operators

```text
expression union expression
expression intersect expression
expression minus expression
expression times expression
expression join[condition] expression
```

The join operator is a theta join and is evaluated using a nested-loop implementation.

## Conditions

Conditions support:

```text
=
!=
<
<=
>
>=
```

Conditions may contain attribute names, qualified attribute names, numbers, strings, parentheses, and the logical operators:

```text
not
and
or
```

The precedence of logical operators is:

1. `not`
2. `and`
3. `or`

## Relation Definition Format

Relations may be stored in a file using this format:

```text
Employees (EID, Name, Age, DID) = {
    E1, John, 32, D1
    E2, Alice, 28, D2
    E3, Bob, 29, D1
}
```

Strings containing spaces, commas, parentheses, or quote characters must be enclosed in single quotes.

Two consecutive single quotes inside a quoted string represent one literal quote. For example:

```text
'O''Brien'
```

represents:

```text
O'Brien
```

Lines beginning with `//` are comments.

## Running the Program

### Print a Parse Tree

Use the `--tree` option:

```bash
python ra.py --tree "project[Name](select[Age>30](Employees))"
```

Example output:

```text
Project(attrs=[Name])
└── Select
    ├── Gt
    │   ├── Attr(Age)
    │   └── Num(30)
    └── Relation(Employees)
```

The tree is printed without executing the query.

### Execute a Query

Provide a relation-definition file using `--data`:

```bash
python ra.py --data sample.ra "project[Name](Employees)"
```

Example:

```bash
python ra.py --data sample.ra "project[Name](select[Age>30](Employees))"
```

A join can be executed with:

```bash
python ra.py --data sample.ra "Employees join[Employees.DID=Dept.DID] Dept"
```

## Rename and Self Joins

A self join requires two distinguishable copies of the same relation.

For example, this query uses `rename`:

```text
rename[E2](Emp) join[Emp.MgrID=E2.EID] Emp
```

Without `rename`, both copies would have attributes such as:

```text
Emp.EID
Emp.MgrID
```

The engine would not be able to distinguish which copy of `Emp` an attribute refers to, and qualified output attribute names would collide.

Renaming one copy to `E2` gives distinct names such as:

```text
E2.EID
Emp.EID
```

which makes the self join expressible.

## Set Semantics

Relations are treated as sets.

Duplicate tuples in relation input are removed using the engine's own tuple-equality implementation.

Projection also removes duplicate output tuples.

For example, if the `DID` values are:

```text
D1
D2
D1
```

then:

```text
project[DID](Employees)
```

returns:

```text
D1
D2
```

## Error Handling

The engine reports errors without displaying a stack trace to the command-line user.

Supported error categories include:

- lexical errors
- syntax errors
- name errors
- schema errors
- type errors

Example:

```text
select[Age>'30'](Employees)
```

produces a type error because `Age` is numeric while `'30'` is a string.

## Running the Required Tests

From the project root, run:

```bash
python -m unittest discover -s tests -v
```

The test suite includes all 25 required cases from the project specification.

At the time of writing, all 25 required tests pass.

Do not run `tests/test_required.py` directly from the `tests` directory because the project modules are located in the parent directory.

## Data Generator

Run:

```bash
python generator.py
```

This creates generated relation data for:

```text
R(a, b)
S(b, c)
```

The generator supports configurable relation sizes and match rates.

## Performance Benchmark

Run:

```bash
python benchmark.py
```

The benchmark executes:

```text
R join[R.b=S.b] S
```

at multiple relation sizes.

The join implementation increments its comparison counter once for every pair of tuples whose join condition is evaluated.

The selection implementation separately increments its counter once for every tuple whose selection condition is evaluated.

Benchmark results are written to:

```text
benchmark_results.csv
```

## Known Limitations

This component intentionally has several limitations consistent with the project specification:

- All relations are stored entirely in memory.
- Null values and three-valued logic are not supported.
- Query optimization and algebraic rewriting are not implemented.
- Joins use nested loops rather than hash join or sort-merge join.
- Indexes are not implemented.
- The parse tree is executed exactly as written.
- Very large nested-loop joins are slow because every pair of tuples is examined.

These limitations are intentional for this stage of the DBMS project.

## Project Demonstration Video
- https://youtu.be/V6ZkemAHmAI