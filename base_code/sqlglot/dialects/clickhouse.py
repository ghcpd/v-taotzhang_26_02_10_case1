from __future__ import annotations

import typing as t

from sqlglot import exp, generator, parser, tokens
from sqlglot.dialects.dialect import (
    Dialect,
    inline_array_sql,
    no_pivot_sql,
    rename_func,
    var_map_sql,
)
from sqlglot.errors import ParseError
from sqlglot.parser import parse_var_map
from sqlglot.tokens import Token, TokenType


def _lower_func(sql: str) -> str:
    index = sql.index("(")
    return sql[:index].lower() + sql[index:]


class ClickHouse(Dialect):
    normalize_functions = None
    null_ordering = "nulls_are_last"

    class Tokenizer(tokens.Tokenizer):
        COMMENTS = ["--", "#", "#!", ("/*", "*/")]
        IDENTIFIERS = ['"', "`"]
        BIT_STRINGS = [("0b", "")]
        HEX_STRINGS = [("0x", ""), ("0X", "")]

        KEYWORDS = {
            **tokens.Tokenizer.KEYWORDS,
            "ASOF": TokenType.ASOF,
            "ATTACH": TokenType.COMMAND,
            "DATETIME64": TokenType.DATETIME64,
            "FINAL": TokenType.FINAL,
            "FLOAT32": TokenType.FLOAT,
            "FLOAT64": TokenType.DOUBLE,
            "GLOBAL": TokenType.GLOBAL,
            "INT128": TokenType.INT128,
            "INT16": TokenType.SMALLINT,
            "INT256": TokenType.INT256,
            "INT32": TokenType.INT,
            "INT64": TokenType.BIGINT,
            "INT8": TokenType.TINYINT,
            "MAP": TokenType.MAP,
            "TUPLE": TokenType.STRUCT,
            "UINT128": TokenType.UINT128,
            "UINT16": TokenType.USMALLINT,
            "UINT256": TokenType.UINT256,
            "UINT32": TokenType.UINT,
            "UINT64": TokenType.UBIGINT,
            "UINT8": TokenType.UTINYINT,
        }

    class Parser(parser.Parser):
        FUNCTIONS = {
            **parser.Parser.FUNCTIONS,
            "ANY": exp.AnyValue.from_arg_list,
            "MAP": parse_var_map,
            "MATCH": exp.RegexpLike.from_arg_list,
            "UNIQ": exp.ApproxDistinct.from_arg_list,
        }

        FUNCTION_PARSERS = {
            **parser.Parser.FUNCTION_PARSERS,
            "QUANTILE": lambda self: self._parse_quantile(),
        }

        FUNCTION_PARSERS.pop("MATCH")

        NO_PAREN_FUNCTION_PARSERS = parser.Parser.NO_PAREN_FUNCTION_PARSERS.copy()
        NO_PAREN_FUNCTION_PARSERS.pop(TokenType.ANY)

        RANGE_PARSERS = {
            **parser.Parser.RANGE_PARSERS,
            TokenType.GLOBAL: lambda self, this: self._match(TokenType.IN)
            and self._parse_in(this, is_global=True),
        }

        # The PLACEHOLDER entry is popped because 1) it doesn't affect Clickhouse (it corresponds to
        # the postgres-specific JSONBContains parser) and 2) it makes parsing the ternary op simpler.
        COLUMN_OPERATORS = parser.Parser.COLUMN_OPERATORS.copy()
        COLUMN_OPERATORS.pop(TokenType.PLACEHOLDER)

        JOIN_KINDS = {
            *parser.Parser.JOIN_KINDS,
            TokenType.ANY,
            TokenType.ASOF,
            TokenType.ANTI,
            TokenType.SEMI,
        }

        TABLE_ALIAS_TOKENS = {*parser.Parser.TABLE_ALIAS_TOKENS} - {
            TokenType.ANY,
            TokenType.ASOF,
            TokenType.SEMI,
            TokenType.ANTI,
            TokenType.SETTINGS,
            TokenType.FORMAT,
        }

        LOG_DEFAULTS_TO_LN = True

        QUERY_MODIFIER_PARSERS = {
            **parser.Parser.QUERY_MODIFIER_PARSERS,
            "settings": lambda self: self._parse_csv(self._parse_conjunction)
            if self._match(TokenType.SETTINGS)
            else None,
            "format": lambda self: self._parse_id_var() if self._match(TokenType.FORMAT) else None,
        }

        def _parse_conjunction(self) -> t.Optional[exp.Expression]:
            this = super()._parse_conjunction()

            if self._match(TokenType.PLACEHOLDER):
                return self.expression(
                    exp.If,
                    this=this,
                    true=self._parse_conjunction(),
                    false=self._match(TokenType.COLON) and self._parse_conjunction(),
                )

            return this

        def _parse_placeholder(self) -> t.Optional[exp.Expression]:
            """
            Parse a placeholder expression like SELECT {abc: UInt32} or FROM {table: Identifier}
            https://clickhouse.com/docs/en/sql-reference/syntax#defining-and-using-query-parameters
            """
            if not self._match(TokenType.L_BRACE):
                return None

            this = self._parse_id_var()
            self._match(TokenType.COLON)
            kind = self._parse_types(check_func=False) or (
                self._match_text_seq("IDENTIFIER") and "Identifier"
            )

            if not kind:
                self.raise_error("Expecting a placeholder type or 'Identifier' for tables")
            elif not self._match(TokenType.R_BRACE):
                self.raise_error("Expecting }")

            return self.expression(exp.Placeholder, this=this, kind=kind)

        def _parse_in(
            self, this: t.Optional[exp.Expression], is_global: bool = False
        ) -> exp.Expression:
            this = super()._parse_in(this)
            this.set("is_global", is_global)
            return this

        def _parse_table(
            self, schema: bool = False, alias_tokens: t.Optional[t.Collection[TokenType]] = None
        ) -> t.Optional[exp.Expression]:
            this = super()._parse_table(schema=schema, alias_tokens=alias_tokens)

            if self._match(TokenType.FINAL):
                this = self.expression(exp.Final, this=this)

            return this

        def _parse_position(self, haystack_first: bool = False) -> exp.Expression:
            return super()._parse_position(haystack_first=True)

        # https://clickhouse.com/docs/en/sql-reference/statements/select/with/
        def _parse_cte(self) -> exp.Expression:
            index = self._index
            try:
                # WITH <identifier> AS <subquery expression>
                return super()._parse_cte()
            except ParseError:
                # WITH <expression> AS <identifier>
                self._retreat(index)
                statement = self._parse_statement()

                if statement and isinstance(statement.this, exp.Alias):
                    self.raise_error("Expected CTE to have alias")

                return self.expression(exp.CTE, this=statement, alias=statement and statement.this)

        def _parse_join_side_and_kind(
            self,
        ) -> t.Tuple[t.Optional[Token], t.Optional[Token], t.Optional[Token]]:
            is_global = self._match(TokenType.GLOBAL) and self._prev
            kind_pre = self._match_set(self.JOIN_KINDS, advance=False) and self._prev
            if kind_pre:
                kind = self._match_set(self.JOIN_KINDS) and self._prev
                side = self._match_set(self.JOIN_SIDES) and self._prev
                return is_global, side, kind
            return (
                is_global,
                self._match_set(self.JOIN_SIDES) and self._prev,
                self._match_set(self.JOIN_KINDS) and self._prev,
            )

        def _parse_join(self, skip_join_token: bool = False) -> t.Optional[exp.Expression]:
            join = super()._parse_join(skip_join_token)

            if join:
                join.set("global", join.args.pop("natural", None))
            return join

        def _parse_function(
            self, functions: t.Optional[t.Dict[str, t.Callable]] = None, anonymous: bool = False
        ) -> t.Optional[exp.Expression]:
            # Override to allow aliases inside tuple() arguments, which is valid in ClickHouse.
            # The base implementation doesn't permit aliases within function arguments (alias=False
            # passed to _parse_lambda), so we special-case "tuple" here.
            if self._curr and self._curr.text.upper() == "TUPLE":
                # Adapted from sqlglot.parser.Parser._parse_function
                token_type = self._curr.token_type

                if not self._next or self._next.token_type != TokenType.L_PAREN:
                    if token_type in self.NO_PAREN_FUNCTIONS:
                        self._advance()
                        return self.expression(self.NO_PAREN_FUNCTIONS[token_type])
                    return None

                if token_type not in self.FUNC_TOKENS:
                    return None

                this = self._curr.text
                upper = this.upper()
                self._advance(2)

                parser = self.FUNCTION_PARSERS.get(upper)

                if parser and not anonymous:
                    this = parser(self)
                else:
                    subquery_predicate = self.SUBQUERY_PREDICATES.get(token_type)

                    if subquery_predicate and self._curr.token_type in (TokenType.SELECT, TokenType.WITH):
                        this = self.expression(subquery_predicate, this=self._parse_select())
                        self._match_r_paren()
                        return this

                    if functions is None:
                        functions = self.FUNCTIONS

                    # Use alias=True to allow expressions like 'a AS x' inside tuple
                    args = self._parse_csv(lambda: self._parse_lambda(alias=True))

                    if upper in functions and not anonymous:
                        this = functions[upper](args)
                        self.validate_expression(this, args)
                    else:
                        this = self.expression(exp.Anonymous, this=this, expressions=args)

                self._match_r_paren(this)
                return self._parse_window(this)

            # Fallback to default behavior for other functions
            return super()._parse_function(functions, anonymous)

        def _parse_func_params(
            self, this: t.Optional[exp.Func] = None
        ) -> t.Optional[t.List[t.Optional[exp.Expression]]]:
            if self._match_pair(TokenType.R_PAREN, TokenType.L_PAREN):
                return self._parse_csv(self._parse_lambda)
            if self._match(TokenType.L_PAREN):
                params = self._parse_csv(self._parse_lambda)
                self._match_r_paren(this)
                return params
            return None

        def _parse_quantile(self) -> exp.Quantile:
            this = self._parse_lambda()
            params = self._parse_func_params()
            if params:
                return self.expression(exp.Quantile, this=params[0], quantile=this)
            return self.expression(exp.Quantile, this=this, quantile=exp.Literal.number(0.5))

        def _parse_wrapped_id_vars(
            self, optional: bool = False
        ) -> t.List[t.Optional[exp.Expression]]:
            return super()._parse_wrapped_id_vars(optional=True)

    class Generator(generator.Generator):
        STRUCT_DELIMITER = ("(", ")")

        TYPE_MAPPING = {
            **generator.Generator.TYPE_MAPPING,
            exp.DataType.Type.ARRAY: "Array",
            exp.DataType.Type.BIGINT: "Int64",
            exp.DataType.Type.DATETIME64: "DateTime64",
            exp.DataType.Type.DOUBLE: "Float64",
            exp.DataType.Type.FLOAT: "Float32",
            exp.DataType.Type.INT: "Int32",
            exp.DataType.Type.INT128: "Int128",
            exp.DataType.Type.INT256: "Int256",
            exp.DataType.Type.MAP: "Map",
            exp.DataType.Type.NULLABLE: "Nullable",
            exp.DataType.Type.SMALLINT: "Int16",
            exp.DataType.Type.STRUCT: "Tuple",
            exp.DataType.Type.TINYINT: "Int8",
            exp.DataType.Type.UBIGINT: "UInt64",
            exp.DataType.Type.UINT: "UInt32",
            exp.DataType.Type.UINT128: "UInt128",
            exp.DataType.Type.UINT256: "UInt256",
            exp.DataType.Type.USMALLINT: "UInt16",
            exp.DataType.Type.UTINYINT: "UInt8",
        }

        TRANSFORMS = {
            **generator.Generator.TRANSFORMS,
            exp.AnyValue: rename_func("any"),
            exp.ApproxDistinct: rename_func("uniq"),
            exp.Array: inline_array_sql,
            exp.CastToStrType: rename_func("CAST"),
            exp.Final: lambda self, e: f"{self.sql(e, 'this')} FINAL",
            exp.Map: lambda self, e: _lower_func(var_map_sql(self, e)),
            exp.PartitionedByProperty: lambda self, e: f"PARTITION BY {self.sql(e, 'this')}",
            exp.Pivot: no_pivot_sql,
            exp.Quantile: lambda self, e: self.func("quantile", e.args.get("quantile"))
            + f"({self.sql(e, 'this')})",
            exp.RegexpLike: lambda self, e: f"match({self.format_args(e.this, e.expression)})",
            exp.StrPosition: lambda self, e: f"position({self.format_args(e.this, e.args.get('substr'), e.args.get('position'))})",
            exp.VarMap: lambda self, e: _lower_func(var_map_sql(self, e)),
        }

        PROPERTIES_LOCATION = {
            **generator.Generator.PROPERTIES_LOCATION,
            exp.VolatileProperty: exp.Properties.Location.UNSUPPORTED,
            exp.PartitionedByProperty: exp.Properties.Location.POST_SCHEMA,
        }

        JOIN_HINTS = False
        TABLE_HINTS = False
        EXPLICIT_UNION = True
        GROUPINGS_SEP = ""

        def cte_sql(self, expression: exp.CTE) -> str:
            if isinstance(expression.this, exp.Alias):
                return self.sql(expression, "this")

            return super().cte_sql(expression)

        def after_limit_modifiers(self, expression: exp.Expression) -> t.List[str]:
            return super().after_limit_modifiers(expression) + [
                self.seg("SETTINGS ") + self.expressions(expression, key="settings", flat=True)
                if expression.args.get("settings")
                else "",
                self.seg("FORMAT ") + self.sql(expression, "format")
                if expression.args.get("format")
                else "",
            ]

        def parameterizedagg_sql(self, expression: exp.Anonymous) -> str:
            params = self.expressions(expression, "params", flat=True)
            return self.func(expression.name, *expression.expressions) + f"({params})"

        def placeholder_sql(self, expression: exp.Placeholder) -> str:
            return f"{{{expression.name}: {self.sql(expression, 'kind')}}}"
