# ClickHouse Tuple Alias Fix

## Problem
ClickHouse SQL supports aliased arguments inside `tuple()` function calls, such as:
```sql
SELECT tuple(a AS x, b AS y) FROM t
SELECT tuple(a + 1 AS x, b * 2 AS y) FROM t
SELECT tuple(a, b AS y, c) FROM t  -- mixed aliases
```

However, sqlglot's ClickHouse dialect was failing to parse these valid queries, raising a `ParseError: Expecting )` when encountering the `AS` keyword inside tuple arguments.

## Root Cause
The standard function argument parsing in sqlglot uses `_parse_csv(self._parse_lambda)` where `_parse_lambda(alias=False)` by default. This prevents aliases from being recognized in function arguments for most functions.

The `_parse_lambda()` method accepts an `alias` parameter that enables alias parsing, but it defaults to `False`. For ClickHouse's `tuple()` function, we need aliases to be allowed.

## Solution
Added a custom `FUNCTION_PARSER` for the `TUPLE` function in the ClickHouse dialect that:

1. Uses `_parse_lambda(alias=True)` to allow aliases in the arguments
2. Collects all arguments as expressions
3. Returns an Anonymous function expression with `this="tuple"` to preserve the function name in output

### Changes Made
**File: `sqlglot/dialects/clickhouse.py`**

1. Added `"TUPLE": lambda self: self._parse_tuple()` to the `FUNCTION_PARSERS` dictionary

2. Implemented the `_parse_tuple()` method:
```python
def _parse_tuple(self) -> exp.Expression:
    """
    Parse tuple() function arguments, which allow aliases in ClickHouse.
    tuple(a AS x, b AS y) is valid in ClickHouse.
    """
    args = self._parse_csv(lambda: self._parse_lambda(alias=True))
    return self.expression(exp.Anonymous, this="tuple", expressions=args)
```

## Impact
- ✅ Fixes parsing of valid ClickHouse `tuple()` calls with aliased arguments
- ✅ Preserves function name in output (generates `tuple(...)` not `(...)`)
- ✅ Does not affect other dialects (only custom to ClickHouse)
- ✅ All existing tests pass
- ✅ Minimal change: only 2 lines added to FUNCTION_PARSERS, 8 lines for the method

## Testing
All tests pass including:
- 5 new test cases for tuple with aliases
- 6 existing ClickHouse dialect tests
- No regressions in other dialects

