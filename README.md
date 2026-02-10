# Fix for ClickHouse tuple() alias parsing

## Problem
ClickHouse SQL allows `tuple()` function calls where arguments can have aliases, like `tuple(a AS x, b AS y)`. However, SQLGlot's ClickHouse parser was not handling this correctly, causing parsing failures or incorrect AST generation.

## Root Cause
- `TUPLE` is tokenized as `STRUCT` token type in ClickHouse.
- `STRUCT` has a special parser `_parse_struct` that allows aliases in arguments.
- However, the parser looks up function parsers by the function name (uppercased), so `TUPLE` was not found in `FUNCTION_PARSERS`, causing it to fall back to generic function parsing which doesn't allow aliases.

## Solution
1. Added `"TUPLE": lambda self: self._parse_struct()` to `FUNCTION_PARSERS` in the ClickHouse parser to ensure `tuple()` uses the same parsing logic as `struct()`.

2. Added `exp.Struct: lambda self, e: self.func("tuple", *e.expressions)` to `TRANSFORMS` in the ClickHouse generator to output `tuple()` instead of `struct()` in generated SQL.

## Changes Made
- Modified `sqlglot/dialects/clickhouse.py`:
  - Added TUPLE to FUNCTION_PARSERS
  - Added Struct transform to output "tuple" instead of "struct"

## Testing
- All existing ClickHouse tests pass
- New tests for tuple() with aliases now pass
- The fix preserves aliases in the generated SQL output