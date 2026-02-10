# ClickHouse Tuple Alias Parsing Fix

This change addresses an issue in the ClickHouse dialect of `sqlglot` where
`tuple()` calls failed to parse correctly when their arguments included
aliased expressions (e.g., `a AS x` or `a + 1 AS x`).

## Problem

In sqlglot's core parser, function arguments are parsed with
`alias=False`, meaning aliased expressions inside function calls were not
recognized. ClickHouse allows aliases inside `tuple()` arguments, which led to
parsing errors or incorrect ASTs.

## Solution

The ClickHouse dialect overrides the `_parse_function` method to add special
handling for the `tuple` function. This override uses `alias=True` when
parsing tuple arguments, allowing aliased expressions to be correctly
recognized and preserved in the AST. The rest of the function parsing logic is
left unchanged for all other functions.

No other dialects or behaviors are modified.

## Verification

Existing tests, including new ones targeting this behavior, pass when run
against the updated parser. The minimal test suite specific to this issue can
be executed with:

```bash
pytest -q test_case/test_clickhouse_tuple_alias.py -q
```

All tests succeed, confirming the fix.

---

This README provides context about the change and should help future
contributors understand the rationale behind the parser modification.