# ClickHouse Tuple Alias Parsing Fix

## Summary

This update addresses parsing issues in the ClickHouse dialect of sqlglot where valid `tuple()` calls containing aliased arguments (e.g., `a AS x`) would error or produce incorrect ASTs. The change ensures these cases parse correctly while maintaining existing behavior for other dialects.

## What Was Changed

- Added custom logic in `ClickHouse.Parser._parse_function` to specially handle `tuple()` function calls.
- The custom parser consumes aliases within tuple arguments and constructs `Alias` expressions accordingly.
- This ensures that alias tokens inside `tuple()` are properly parsed and do not trigger syntax errors.

## Why This Fix

The default parser raised `ParseError: Expecting )` when encountering an `AS` alias inside tuple arguments due to alias tokens not being consumed correctly. This change explicitly handles such aliases, preventing the parse error and aligning sqlglot behavior with ClickHouse's real syntax.

## Testing

Existing tests were run, including the new `test_clickhouse_tuple_alias.py`, and all now pass. The fix was confirmed by running:

```bash
pytest -q test_case/test_clickhouse_tuple_alias.py
```

No changes were made to tests or other dialects.

---

This README provides context and justification for the changes made to the ClickHouse dialect parser.