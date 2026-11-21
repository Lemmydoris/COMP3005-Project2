# Relational Algebra Engine Grammar

## 1. EBNF Grammar
expr ::= union_expr

union_expr ::= intersect_expr { ("union" | "minus") intersect_expr }

intersect_expr ::= product_expr { "intersect" product_expr }

product_expr ::= unary_expr { ("times" unary_expr) | ("join" "[" condition "]" unary_expr) }

unary_expr ::= "select" "[" condition "]" "(" expr ")"
            | "project" "[" attribute_list "]" "(" expr ")"
            | "rename" "[" IDENT "]" "(" expr ")"
            | primary_expr

primary_expr ::= IDENT| "(" expr ")"

attribute_list ::= attribute { "," attribute }

attribute ::= [ IDENT "." ] IDENT

condition ::= or_condition

or_condition ::= and_condition { "or" and_condition }

and_condition ::= not_condition { "and" not_condition }

not_condition ::= "not" not_condition
                | condition_primary

condition_primary ::= comparison
                | "(" condition ")"

comparison ::= operand comparison_op operand

comparison_op ::= "=" | "!=" | "<" | "<=" | ">" | ">="

operand ::= NUMBER | STRING | attribute

relation_definition ::= IDENT "(" attribute_name_list ")" "=" "{" tuple_list "}"

attribute_name_list ::= IDENT { "," IDENT }

tuple_list ::= tuple { tuple }

tuple ::= value { "," value }

value ::= NUMBER | STRING | IDENT

IDENT ::= LETTER { LETTER | DIGIT | "_" }

NUMBER ::= [ "-" ] DIGIT { DIGIT } [ "." DIGIT { DIGIT } ]

STRING ::= "'" { STRING_CHAR | "''" } "'"

LETTER ::= "A"..."Z" | "a"..."z" | "_"

DIGIT ::= "0"..."9"

## 2. Precedence and Associativity

The grammar uses separate precedence levels to remove ambiguity. Operators at a higher precedence level bind more tightly than operators at a lower level.

| Precedence | Operators | Associativity | Grammar Rule |
|---|---|---|---|
| Highest | `select`, `project`, `rename`, `( )` | N/A | `unary_expr`, `primary_expr` |
| 3 | `times`, `join` | Left | `product_expr` |
| 2 | `intersect` | Left | `intersect_expr` |
| Lowest | `union`, `minus` | Left | `union_expr` |

For conditions, `not` has the highest precedence, followed by `and`, and then `or`. Parentheses may be used to override the normal precedence rules.

| Precedence | Condition Operator | Associativity |
|---|---|---|
| Highest | `not` | Right |
| 2 | `and` | Left |
| Lowest | `or` | Left |

## 3. Ambiguity Demonstration

Consider the deliberately ambiguous grammar:

```ebnf
Expr ::= Expr "union" Expr
    | Expr "minus" Expr
    | "(" Expr ")"
    | IDENT
```
For input:
A union B minus C
two different parse trees are possible.

### Tree 1
``` text
This interpretation is:
(A union B) minus C
          minus
         /     \
      union     C
      /   \
     A     B
```
This tree means that A union B is evaluated first, and then C is subtracted from the result.

### Tree 2
``` text
This interpretation is:
A union (B minus C)
        union
       /     \
      A      minus
             /   \
            B     C
```
### Example that shows Different Results
Consider three union-compatible relations with the same schema (x):
A = {1}
B = {2}
C = {1}
For the first parse tree:
(A union B) minus C
First:
A union B = {1, 2}
Then:
{1, 2} minus {1} = {2}
So the result is:
{2}

For the second parse tree:
A union (B minus C)
First:
B minus C = {2}
Then:
A union {2} = {1, 2}
So the result is:
{1, 2}

The two parse trees produce different results. This shows that the naive grammar is ambiguous.
In my grammar, union and minus have the same precedence and are left-associative. 
Therefore:
A union B minus C is parsed as: (A union B) minus C
The stratified union_expr rule enforces this grouping without using left recursion.

## 4. Parsing Strategy Justification 

I use a recursive descent parser because the language is small, the grammar is written by hand, and each grammar rule can be represented by a parsing function.

For example, the parser can have separate functions for expressions, union-level expressions, product-level expressions, unary expressions, conditions, comparisons, and operands. These functions call one another according to the structure of the grammar.

A straightforward recursive descent parser cannot handle direct left recursion. For example:
```ebnf
Expr ::= Expr "union" Expr
```
## 5. Sources

The following sources were used while designing the grammar and parser:
- Robert Nystrom, *Crafting Interpreters*, especially the chapters on scanning and parsing.
- Wikipedia articles on EBNF, recursive descent parsing, maximal munch, and operator precedence.
- COMP 3005 course materials and the Bonus Project 1 specification.
- AI assistance was used to explain grammar concepts, suggest possible EBNF structures, and review design decisions.
AI suggestions were not accepted automatically. They were checked against the project specification and the grammar rules. Some suggestions were incomplete or needed correction, especially around precedence, keyword handling, Markdown formatting, and making sure the grammar matched the exact required syntax.

