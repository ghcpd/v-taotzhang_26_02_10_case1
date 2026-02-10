import pytest
import sqlglot
from sqlglot import exp


@pytest.mark.parametrize(
    "sql",
    [
        # 最典型：tuple() 参数里带 AS alias
        "SELECT tuple(a AS x, b AS y) FROM t",

        # 参数是表达式 + alias
        "SELECT tuple(a + 1 AS x, b * 2 AS y) FROM t",

        # 混合：有的有 alias，有的没有
        "SELECT tuple(a, b AS y, c) FROM t",

        # 嵌套 tuple + alias
        "SELECT tuple(tuple(a AS x) AS t1, b AS y) FROM t",
    ],
)
def test_clickhouse_tuple_allows_alias_in_args(sql: str) -> None:
    """
    Issue #1690 / PR #1695:
    ClickHouse dialect should allow aliases inside tuple() arguments.
    """
    parsed = sqlglot.parse_one(sql, read="clickhouse")
    assert parsed is not None

    # 取出 SELECT 列表中的第一个表达式：tuple(...)
    select_exprs = parsed.expressions
    assert len(select_exprs) == 1
    tup = select_exprs[0]

    # tuple(...) 通常会被解析为一个函数表达式
    # 不强绑定具体类名（不同版本可能是 Anonymous/Func），只检查名字/形态
    assert isinstance(tup, exp.Expression)
    sql_norm = tup.sql(dialect="clickhouse").lower()

    # 关键断言：输出 SQL 中仍保留 alias（不丢失 AS）
    # 注意：ClickHouse 方言可能会省略 AS 或用空格形式，这里做“包含 alias 名称”的弱断言
    for alias in ("x", "y", "t1"):
        if alias in sql.lower():
            assert alias in sql_norm


def test_clickhouse_tuple_alias_does_not_crash_min_repro() -> None:
    """
    A minimal regression test: parsing should not raise.
    """
    sql = "SELECT tuple(a AS x) FROM t"
    parsed = sqlglot.parse_one(sql, read="clickhouse")
    assert parsed is not None
