# Fix for ClickHouse Tuple Alias Parsing (Issue #1690 / PR #1695)

## Summary
Fixed the ClickHouse dialect parser to allow aliased arguments inside `tuple()` function calls, which is valid syntax in ClickHouse SQL.

## Problem
ClickHouse SQL supports writing `tuple()` calls with aliased arguments:
```sql
SELECT tuple(a AS x, b AS y) FROM t
SELECT tuple(a + 1 AS x, b * 2 AS y) FROM t
SELECT tuple(a, b AS y, c) FROM t  -- mixed aliases
```

However, sqlglot's ClickHouse parser was raising `ParseError: Expecting )` when encountering the `AS` keyword inside tuple arguments.

## Root Cause
The default function argument parsing in sqlglot uses `_parse_csv(self._parse_lambda)` where `_parse_lambda()` is called without the `alias=True` parameter. This prevents the parser from recognizing aliases within function arguments.

While the `_parse_lambda()` method supports an `alias` parameter to enable alias parsing, most functions don't need it and it defaults to `False`.

## Solution
Added a custom `FUNCTION_PARSER` for the ClickHouse `TUPLE` function that explicitly allows aliases in arguments.

### Changes to `sqlglot/dialects/clickhouse.py`

**1. Added TUPLE parser to FUNCTION_PARSERS (line 70):**
```python
FUNCTION_PARSERS = {
    **parser.Parser.FUNCTION_PARSERS,
    "QUANTILE": lambda self: self._parse_quantile(),
    "TUPLE": lambda self: self._parse_tuple(),  # NEW
}
```

**2. Implemented `_parse_tuple()` method (lines 243-248):**
```python
def _parse_tuple(self) -> exp.Expression:
    """
    Parse tuple() function arguments, which allow aliases in ClickHouse.
    tuple(a AS x, b AS y) is valid in ClickHouse.
    """
    args = self._parse_csv(lambda: self._parse_lambda(alias=True))
    return self.expression(exp.Anonymous, this="tuple", expressions=args)
```

## Key Design Decisions

1. **Custom Parser Method**: Created `_parse_tuple()` as a dedicated parser for the tuple function, consistent with existing `_parse_quantile()` pattern

2. **Enable Aliases**: Uses `_parse_lambda(alias=True)` to allow `AS` keyword in arguments

3. **Anonymous Expression**: Returns `exp.Anonymous` with `this="tuple"` to preserve the function name in output (generates `tuple(...)` not `(...)`)

4. **Minimal Impact**: Only affects the ClickHouse dialect's parsing of TUPLE; no changes to other dialects or the base parser

## Testing

### New Test Cases (test_case/test_clickhouse_tuple_alias.py)
- ✅ `tuple(a AS x, b AS y)` - basic aliased arguments
- ✅ `tuple(a + 1 AS x, b * 2 AS y)` - expressions with aliases
- ✅ `tuple(a, b AS y, c)` - mixed with/without aliases
- ✅ `tuple(tuple(a AS x) AS t1, b AS y)` - nested tuples with aliases
- ✅ `tuple(a AS x)` - minimal regression test

### Existing Tests
- ✅ All 6 ClickHouse dialect tests pass
- ✅ No regressions in other dialects

### Edge Cases Verified
- ✅ Complex expressions with AS: `tuple(CAST(a AS INT) AS x)`
- ✅ Empty tuple: `tuple()`
- ✅ ORDER BY clause: `ORDER BY tuple(id)`
- ✅ Multiple nested tuples with aliases

## Result
All tests pass (11/11). The fix successfully resolves Issue #1690 while maintaining backward compatibility.

