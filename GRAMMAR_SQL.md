# Module 3 SQL Grammar

## 1. Lexical Rules

The SQL front end uses a hand-written scanner. It does not use regular expressions, a parser generator, or `eval`.

Keywords are case-insensitive. For example:

```text
SELECT
select
SeLeCt
```

all produce the same keyword token.

Identifiers are case-sensitive. Therefore:

```text
Emp
emp
```

are different identifiers.

An identifier begins with a letter or underscore and may then contain letters, digits, or underscores.

String literals use single quotes.

Two adjacent single quotes inside a string represent one literal single quote.

Example:

```sql
'O''Brien'
```

has the value:

```text
O'Brien
```

Integer literals may optionally be signed:

```text
10
-10
+10
```

Comparison operators use maximal munch:

```text
=
<>
<
<=
>
>=
```

For example, `<=` is one token rather than `<` followed by `=`.

SQL comments begin with:

```text
--
```

and continue to the end of the line.

Statements are separated by semicolons.

The implementation permits multiple statements in one input file.

---

## 2. EBNF

```text
program        ::= statement
                   { ";" statement }
                   [ ";" ]

statement      ::= create
                 | insert
                 | query

create         ::= CREATE TABLE ident
                   "("
                   coldef
                   { "," coldef }
                   ")"

coldef         ::= ident INT
                 | ident VARCHAR
                   "(" int ")"

insert         ::= INSERT INTO ident
                   VALUES
                   "("
                   literal
                   { "," literal }
                   ")"

query          ::= select_block
                   { setop select_block }

setop          ::= UNION [ ALL ]
                 | INTERSECT
                 | EXCEPT

select_block   ::= SELECT
                   [ DISTINCT ]
                   select_list
                   FROM
                   from_source
                   [ WHERE condition ]
                   [
                       GROUP BY col_list
                       [ HAVING condition ]
                   ]
                   [ ORDER BY sort_list ]
                   [ LIMIT int ]
                 | "(" query ")"

select_list    ::= "*"
                 | select_item
                   { "," select_item }

select_item    ::= (
                       column
                     | aggregate
                   )
                   [ AS ident ]

aggregate      ::= (
                       COUNT
                     | SUM
                     | AVG
                     | MIN
                     | MAX
                   )
                   "("
                   (
                       column
                     | "*"
                   )
                   ")"

from_source    ::= table_ref
                   {
                       "," table_ref
                     | JOIN table_ref
                       ON condition
                   }

table_ref      ::= ident
                   [ [ AS ] ident ]
                 | "(" query ")"
                   AS ident

col_list       ::= column
                   { "," column }

sort_list      ::= sort_item
                   { "," sort_item }

sort_item      ::= column
                   [ ASC | DESC ]

condition      ::= or_condition

or_condition   ::= and_condition
                   { OR and_condition }

and_condition  ::= not_condition
                   { AND not_condition }

not_condition  ::= NOT not_condition
                 | condition_primary

condition_primary
                ::= comparison
                  | "(" condition ")"

comparison     ::= operand
                   comparison_operator
                   operand

comparison_operator
                ::= "="
                  | "<>"
                  | "<"
                  | "<="
                  | ">"
                  | ">="

operand        ::= column
                 | aggregate
                 | int
                 | string

column         ::= ident
                 | ident "." ident

literal        ::= int
                 | string
```

---

## 3. Boolean Precedence

Comparisons form the atomic conditions.

Among the boolean operators, precedence from tightest to loosest is:

```text
NOT
AND
OR
```

For example:

```sql
NOT a = 1 AND b = 2 OR c = 3
```

is interpreted as:

```text
((NOT (a = 1)) AND (b = 2)) OR (c = 3)
```

Parentheses override the normal precedence.

The recursive grammar structure enforces this precedence directly:

```text
or_condition
    -> and_condition
        -> not_condition
            -> condition_primary
```

---

## 4. Set-Operator Associativity

The set operators:

```text
UNION
UNION ALL
INTERSECT
EXCEPT
```

have the same precedence and are left associative.

Therefore:

```text
A UNION B EXCEPT C
```

means:

```text
(A UNION B) EXCEPT C
```

The parser constructs this associativity directly from:

```text
query ::= select_block { setop select_block }
```

---

## 5. Grammar Differences from the Handout Sketch

### 5.1 Base-table aliases may omit AS

The handout grammar sketch shows:

```text
ident [ AS ident ]
```

but required examples use SQL such as:

```sql
FROM Emp e
```

The implementation therefore accepts both:

```sql
FROM Emp e
```

and:

```sql
FROM Emp AS e
```

A subquery in `FROM` still requires the explicit form:

```sql
FROM (SELECT ...) AS t
```

because the alias is required to create its outer scope entry.

### 5.2 Aggregates are accepted syntactically in conditions

The handout's simplified operand production lists columns and literals, but required SQL includes:

```sql
HAVING COUNT(*) > 5
```

The parser therefore permits an aggregate as a condition operand.

Whether the aggregate is legal is decided during semantic analysis.

Thus:

```sql
HAVING COUNT(*) > 5
```

may be valid, while:

```sql
WHERE COUNT(*) > 5
```

parses successfully and is then rejected with an aggregate semantic error.

This keeps syntax recognition separate from semantic legality.

### 5.3 FROM is represented as one left-to-right chain

The implementation represents comma references and explicit joins using one left-to-right `from_source` production.

This preserves the exact order and form in which the SQL was written.

A comma becomes a logical cross product.

An explicit `JOIN ... ON` becomes a logical join carrying its condition.

No attempt is made in Module 3 to recognize equivalent comma and explicit join forms. That is an optimizer responsibility in Module 4.

### 5.4 Extra semicolon separators are tolerated

The parser tolerates harmless additional semicolons between statements.

This does not change the meaning of any valid input and allows multi-statement files to be handled cleanly.