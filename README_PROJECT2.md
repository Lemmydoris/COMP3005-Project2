# COMP 3005 Bonus Project 2 — Working DBMS

This directory starts from the submitted Bonus Project 1 engine and applies the required preparation refactor before Module 1.

## Run regression tests

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Current checkpoint

- Bonus Project 1 regression suite adapted for Project 2 bag projection semantics.
- Tokenizer, parser, tree, and operators are separate importable layers.
- Condition parser exposed independently.
- Tree JSON round-trip implemented.
- Relation access detached behind `get_relation(name)`.
- Module 1 implementation is next.
