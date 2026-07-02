from __future__ import annotations

import pytest

from databricks_to_pbi.translator.rules import (
    RuleContext,
    apply_rules,
    rule_avg,
    rule_count,
    rule_count_distinct,
    rule_count_star,
    rule_max,
    rule_min,
    rule_sum,
)

_DEFAULT_COLS = {"Sales": ["amount", "net_amount", "customer_id", "order_date"]}


def _ctx(table: str = "Sales", columns: dict[str, list[str]] | None = None) -> RuleContext:
    return RuleContext(
        table=table,
        columns_by_table=columns or _DEFAULT_COLS,
    )


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SUM(amount)", "SUM('Sales'[amount])"),
        ("sum( amount )", "SUM('Sales'[amount])"),
        ("SUM(net_amount)", "SUM('Sales'[net_amount])"),
    ],
)
def test_rule_sum(sql: str, expected: str) -> None:
    assert rule_sum(sql, _ctx()) == expected


def test_rule_avg() -> None:
    assert rule_avg("AVG(amount)", _ctx()) == "AVERAGE('Sales'[amount])"


def test_rule_min_max() -> None:
    assert rule_min("MIN(amount)", _ctx()) == "MIN('Sales'[amount])"
    assert rule_max("MAX(order_date)", _ctx()) == "MAX('Sales'[order_date])"


def test_rule_count_star() -> None:
    assert rule_count_star("COUNT(*)", _ctx()) == "COUNTROWS('Sales')"


def test_rule_count() -> None:
    assert rule_count("COUNT(customer_id)", _ctx()) == "COUNT('Sales'[customer_id])"


def test_rule_count_distinct() -> None:
    expected = "DISTINCTCOUNT('Sales'[customer_id])"
    assert rule_count_distinct("COUNT(DISTINCT customer_id)", _ctx()) == expected


def test_apply_rules_returns_first_matching_dax() -> None:
    dax, name = apply_rules("SUM(amount)", _ctx())
    assert dax == "SUM('Sales'[amount])"
    assert name == "rule_sum"


def test_apply_rules_returns_none_when_no_match() -> None:
    dax, name = apply_rules("LAG(amount, 1) OVER (ORDER BY order_date)", _ctx())
    assert dax is None
    assert name is None


def test_rule_rejects_unknown_column() -> None:
    with pytest.raises(ValueError):
        rule_sum("SUM(bogus_col)", _ctx())


def test_rule_divide_two_sums() -> None:
    # The dedicated rule_divide_sums was subsumed by rule_arithmetic_aggregates,
    # which recursively translates each side and wraps the `/` in DIVIDE.
    from databricks_to_pbi.translator.rules import rule_arithmetic_aggregates

    out = rule_arithmetic_aggregates("SUM(amount) / SUM(net_amount)", _ctx())
    assert out == "DIVIDE(SUM('Sales'[amount]), SUM('Sales'[net_amount]))"


def test_rule_sumx_product() -> None:
    # Subsumed by the generic rule_aggx_complex.
    from databricks_to_pbi.translator.rules import rule_aggx_complex

    out = rule_aggx_complex("SUM(amount * net_amount)", _ctx())
    assert out == "SUMX('Sales', 'Sales'[amount] * 'Sales'[net_amount])"


def test_apply_rules_picks_divide_over_sum_alone() -> None:
    dax, name = apply_rules("SUM(amount) / SUM(net_amount)", _ctx())
    assert name == "rule_arithmetic_aggregates"
    assert dax is not None
    assert "DIVIDE" in dax


def test_rule_calculate_case_simple_eq() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_case

    sql = "SUM(CASE WHEN status = 'shipped' THEN amount END)"
    out = rule_calculate_case(sql, _ctx(columns={"Sales": ["amount", "status"]}))
    assert out == "CALCULATE(SUM('Sales'[amount]), 'Sales'[status] = \"shipped\")"


def test_rule_calculate_case_numeric_gt() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_case

    sql = "SUM(CASE WHEN amount > 100 THEN amount END)"
    out = rule_calculate_case(sql, _ctx(columns={"Sales": ["amount"]}))
    assert out == "CALCULATE(SUM('Sales'[amount]), 'Sales'[amount] > 100)"


def test_rule_calculate_filter() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    sql = "SUM(amount) FILTER (WHERE status = 'shipped')"
    out = rule_calculate_filter(sql, _ctx(columns={"Sales": ["amount", "status"]}))
    assert out == "CALCULATE(SUM('Sales'[amount]), 'Sales'[status] = \"shipped\")"


def test_apply_rules_picks_calculate_when_case_present() -> None:
    dax, name = apply_rules(
        "SUM(CASE WHEN status = 'shipped' THEN amount END)",
        _ctx(columns={"Sales": ["amount", "status"]}),
    )
    assert name == "rule_calculate_case"
    assert dax is not None
    assert "CALCULATE" in dax


def test_calculate_case_in_clause() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_case

    sql = "SUM(CASE WHEN status IN ('shipped','delivered') THEN amount END)"
    out = rule_calculate_case(sql, _ctx(columns={"Sales": ["amount", "status"]}))
    assert out == 'CALCULATE(SUM(\'Sales\'[amount]), \'Sales\'[status] IN {"shipped", "delivered"})'


def test_calculate_case_else_branch() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_case_else

    sql = "SUM(CASE WHEN status = 'shipped' THEN amount ELSE 0 END)"
    out = rule_calculate_case_else(sql, _ctx(columns={"Sales": ["amount", "status"]}))
    assert out == 'CALCULATE(SUM(\'Sales\'[amount]), \'Sales\'[status] = "shipped")'


# ---------------------------------------------------------------------------
# Tests for the rules added to support production metric views (TPC-H model).
# ---------------------------------------------------------------------------


def test_count_distinct_with_dotted_column_ref() -> None:
    from databricks_to_pbi.translator.rules import rule_count_distinct

    out = rule_count_distinct(
        "COUNT(DISTINCT orders.o_orderkey)",
        _ctx(columns={"lineitem": ["l_quantity"]}, table="lineitem"),
    )
    assert out == "DISTINCTCOUNT('orders'[o_orderkey])"


def test_sum_with_dotted_column_ref() -> None:
    from databricks_to_pbi.translator.rules import rule_sum

    out = rule_sum(
        "SUM(orders.total_amount)",
        _ctx(columns={"lineitem": ["l_quantity"]}, table="lineitem"),
    )
    assert out == "SUM('orders'[total_amount])"


def test_sum_arithmetic_one_minus() -> None:
    # Subsumed by rule_aggx_complex (handles any non-bare expression inside SUM).
    from databricks_to_pbi.translator.rules import rule_aggx_complex

    out = rule_aggx_complex(
        "SUM(l_extendedprice * (1 - l_discount))",
        _ctx(columns={"lineitem": ["l_extendedprice", "l_discount"]}, table="lineitem"),
    )
    assert out == (
        "SUMX('lineitem', 'lineitem'[l_extendedprice] * (1 - 'lineitem'[l_discount]))"
    )


def test_sum_arithmetic_one_minus_times() -> None:
    from databricks_to_pbi.translator.rules import rule_aggx_complex

    out = rule_aggx_complex(
        "SUM(l_extendedprice * (1 - l_discount) * l_tax)",
        _ctx(
            columns={"lineitem": ["l_extendedprice", "l_discount", "l_tax"]},
            table="lineitem",
        ),
    )
    assert out == (
        "SUMX('lineitem', 'lineitem'[l_extendedprice] * "
        "(1 - 'lineitem'[l_discount]) * 'lineitem'[l_tax])"
    )


def test_measure_ref() -> None:
    from databricks_to_pbi.translator.rules import rule_measure_ref

    assert rule_measure_ref("MEASURE(total_sales)", _ctx()) == "[total_sales]"


def test_measure_arithmetic_subtract() -> None:
    # Subsumed by the generic arithmetic rule: each MEASURE() side translates
    # to [name] via rule_measure_ref, then joined with the operator.
    from databricks_to_pbi.translator.rules import rule_arithmetic_aggregates

    out = rule_arithmetic_aggregates(
        "MEASURE(total_sales) - MEASURE(total_discount_amount)", _ctx(),
    )
    assert out == "[total_sales] - [total_discount_amount]"


def test_divide_nullif_measures() -> None:
    # Renamed rule (still has the NULLIF-aware shortcut to skip emitting NULLIF;
    # DAX DIVIDE already handles zero denominator).
    from databricks_to_pbi.translator.rules import rule_divide_nullif

    out = rule_divide_nullif(
        "MEASURE(total_sales) / NULLIF(MEASURE(total_orders), 0)", _ctx(),
    )
    assert out == "DIVIDE([total_sales], [total_orders])"


def test_avg_datediff_swaps_arg_order_and_adds_unit() -> None:
    from databricks_to_pbi.translator.rules import rule_avg_datediff

    out = rule_avg_datediff(
        "AVG(DATEDIFF(l_receiptdate, l_shipdate))",
        _ctx(
            columns={"lineitem": ["l_receiptdate", "l_shipdate"]}, table="lineitem"
        ),
    )
    # SQL DATEDIFF(end, start); DAX DATEDIFF(start, end, unit)
    assert out == (
        "AVERAGEX('lineitem', DATEDIFF('lineitem'[l_shipdate], "
        "'lineitem'[l_receiptdate], DAY))"
    )


def test_filter_product_with_in_clause() -> None:
    """rule_calculate_filter is now generic — it recurses into the inner
    aggregate (here ``SUM(a * (1-b))`` → SUMX) and wraps in CALCULATE."""
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    out = rule_calculate_filter(
        "SUM(l_extendedprice * (1 - l_discount)) "
        "FILTER (WHERE orders.o_orderpriority IN ('1-URGENT', '2-HIGH'))",
        _ctx(
            columns={"lineitem": ["l_extendedprice", "l_discount"]},
            table="lineitem",
        ),
    )
    assert out == (
        "CALCULATE(SUMX('lineitem', 'lineitem'[l_extendedprice] * "
        "(1 - 'lineitem'[l_discount])), "
        "'orders'[o_orderpriority] IN {\"1-URGENT\", \"2-HIGH\"})"
    )


def test_filter_count_star() -> None:
    """COUNT(*) FILTER (WHERE …) now works via the generic FILTER rule."""
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    out = rule_calculate_filter(
        "COUNT(*) FILTER (WHERE amount < 10)",
        _ctx(columns={"orders": ["amount"]}, table="orders"),
    )
    assert out == "CALCULATE(COUNTROWS('orders'), 'orders'[amount] < 10)"


def test_filter_count_distinct_with_dotted_column() -> None:
    """COUNT(DISTINCT col) FILTER also composes for free."""
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    out = rule_calculate_filter(
        "COUNT(DISTINCT orders.customer_id) FILTER (WHERE status = 'active')",
        _ctx(columns={"lineitem": ["status"]}, table="lineitem"),
    )
    assert out == (
        "CALCULATE(DISTINCTCOUNT('orders'[customer_id]), "
        '\'lineitem\'[status] = "active")'
    )


def test_filter_avg_with_inequality() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    out = rule_calculate_filter(
        "AVG(amount) FILTER (WHERE region != 'US')",
        _ctx(columns={"orders": ["amount", "region"]}, table="orders"),
    )
    assert out == (
        'CALCULATE(AVERAGE(\'orders\'[amount]), \'orders\'[region] <> "US")'
    )


def test_filter_simple_eq_string() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE status = 'shipped')",
        _ctx(columns={"Sales": ["amount", "status"]}),
    )
    assert out == 'CALCULATE(SUM(\'Sales\'[amount]), \'Sales\'[status] = "shipped")'


# ---------------------------------------------------------------------------
# Tier 1 condition expansion: inequality, NULL, NOT IN, LIKE, AND/OR.
# ---------------------------------------------------------------------------


def test_condition_inequality_operators() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    ctx = _ctx(columns={"Sales": ["amount", "qty"]})
    out = rule_calculate_filter("SUM(amount) FILTER (WHERE qty >= 100)", ctx)
    assert out == "CALCULATE(SUM('Sales'[amount]), 'Sales'[qty] >= 100)"
    out = rule_calculate_filter("SUM(amount) FILTER (WHERE qty <= 1000)", ctx)
    assert out == "CALCULATE(SUM('Sales'[amount]), 'Sales'[qty] <= 1000)"
    out = rule_calculate_filter("SUM(amount) FILTER (WHERE qty < 0)", ctx)
    assert out == "CALCULATE(SUM('Sales'[amount]), 'Sales'[qty] < 0)"


def test_condition_not_equal_string() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    ctx = _ctx(columns={"Sales": ["amount", "status"]})
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE status != 'cancelled')", ctx
    )
    assert out == 'CALCULATE(SUM(\'Sales\'[amount]), \'Sales\'[status] <> "cancelled")'
    # SQL also allows <>
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE status <> 'cancelled')", ctx
    )
    assert out == 'CALCULATE(SUM(\'Sales\'[amount]), \'Sales\'[status] <> "cancelled")'


def test_condition_is_null_is_not_null() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    ctx = _ctx(columns={"Sales": ["amount", "customer_id"]})
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE customer_id IS NULL)", ctx
    )
    assert out == "CALCULATE(SUM('Sales'[amount]), ISBLANK('Sales'[customer_id]))"
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE customer_id IS NOT NULL)", ctx
    )
    assert out == (
        "CALCULATE(SUM('Sales'[amount]), NOT(ISBLANK('Sales'[customer_id])))"
    )


def test_condition_not_in() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    ctx = _ctx(columns={"Sales": ["amount", "status"]})
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE status NOT IN ('cancelled', 'refunded'))", ctx
    )
    assert out == (
        'CALCULATE(SUM(\'Sales\'[amount]), '
        'NOT(\'Sales\'[status] IN {"cancelled", "refunded"}))'
    )


def test_condition_like_prefix_suffix_contains_exact() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    ctx = _ctx(columns={"Sales": ["amount", "email"]})
    # Prefix: 'pat%' → STARTSWITH
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE email LIKE 'admin%')", ctx
    )
    assert out == 'CALCULATE(SUM(\'Sales\'[amount]), STARTSWITH(\'Sales\'[email], "admin"))'
    # Suffix: '%pat' → ENDSWITH
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE email LIKE '%@databricks.com')", ctx
    )
    assert out == (
        'CALCULATE(SUM(\'Sales\'[amount]), '
        'ENDSWITH(\'Sales\'[email], "@databricks.com"))'
    )
    # Contains: '%pat%' → CONTAINSSTRING
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE email LIKE '%internal%')", ctx
    )
    assert out == (
        'CALCULATE(SUM(\'Sales\'[amount]), '
        'CONTAINSSTRING(\'Sales\'[email], "internal"))'
    )
    # No wildcards: equality
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE email LIKE 'a@b.com')", ctx
    )
    assert out == 'CALCULATE(SUM(\'Sales\'[amount]), \'Sales\'[email] = "a@b.com")'


def test_condition_and_composition() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    ctx = _ctx(columns={"Sales": ["amount", "status", "region"]})
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE status = 'shipped' AND region = 'US')", ctx
    )
    assert out == (
        'CALCULATE(SUM(\'Sales\'[amount]), '
        '(\'Sales\'[status] = "shipped") && (\'Sales\'[region] = "US"))'
    )


def test_condition_or_composition() -> None:
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    ctx = _ctx(columns={"Sales": ["amount", "priority", "is_vip"]})
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE priority = 'high' OR is_vip > 0)", ctx
    )
    assert out == (
        'CALCULATE(SUM(\'Sales\'[amount]), '
        '(\'Sales\'[priority] = "high") || (\'Sales\'[is_vip] > 0))'
    )


def test_condition_and_or_precedence_with_parens() -> None:
    """``a AND (b OR c)`` should parenthesise the OR sub-expression."""
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    ctx = _ctx(columns={"Sales": ["amount", "a", "b", "c"]})
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE a > 0 AND (b > 0 OR c > 0))", ctx
    )
    assert out == (
        'CALCULATE(SUM(\'Sales\'[amount]), '
        '(\'Sales\'[a] > 0) && '
        '((\'Sales\'[b] > 0) || (\'Sales\'[c] > 0)))'
    )


def test_condition_dotted_column_inequality() -> None:
    """A dotted column reference in any of the new operators still emits the
    cross-table form."""
    from databricks_to_pbi.translator.rules import rule_calculate_filter

    ctx = _ctx(columns={"lineitem": ["amount"]}, table="lineitem")
    out = rule_calculate_filter(
        "SUM(amount) FILTER (WHERE orders.priority != 'low')", ctx
    )
    assert out == (
        'CALCULATE(SUM(\'lineitem\'[amount]), \'orders\'[priority] <> "low")'
    )


# ---------------------------------------------------------------------------
# Tier 2: arithmetic on aggregates + COALESCE/IFNULL
# ---------------------------------------------------------------------------


def test_arithmetic_subtract_two_sums() -> None:
    """SUM(revenue) - SUM(cost) → SUM('t'[revenue]) - SUM('t'[cost])."""
    from databricks_to_pbi.translator.rules import apply_rules

    dax, name = apply_rules(
        "SUM(revenue) - SUM(cost)",
        _ctx(columns={"Sales": ["revenue", "cost"]}),
    )
    assert name == "rule_arithmetic_aggregates"
    assert dax == "SUM('Sales'[revenue]) - SUM('Sales'[cost])"


def test_arithmetic_weighted_average_via_sumx() -> None:
    """SUM(a * b) / SUM(b) → DIVIDE(SUMX(...), SUM(...))."""
    from databricks_to_pbi.translator.rules import apply_rules

    dax, _ = apply_rules(
        "SUM(price * qty) / SUM(qty)",
        _ctx(columns={"Sales": ["price", "qty"]}),
    )
    assert dax == "DIVIDE(SUMX('Sales', 'Sales'[price] * 'Sales'[qty]), SUM('Sales'[qty]))"


def test_arithmetic_discounted_ratio() -> None:
    """SUM(a * (1 - b)) / SUM(c)."""
    from databricks_to_pbi.translator.rules import apply_rules

    dax, _ = apply_rules(
        "SUM(list * (1 - discount)) / SUM(list)",
        _ctx(columns={"Sales": ["list", "discount"]}),
    )
    assert dax == (
        "DIVIDE(SUMX('Sales', 'Sales'[list] * (1 - 'Sales'[discount])), "
        "SUM('Sales'[list]))"
    )


def test_arithmetic_left_associative_chain() -> None:
    """SUM(a) - SUM(b) - SUM(c) splits at the RIGHTMOST `-` (left-associative)."""
    from databricks_to_pbi.translator.rules import apply_rules

    dax, _ = apply_rules(
        "SUM(a) - SUM(b) - SUM(c)",
        _ctx(columns={"Sales": ["a", "b", "c"]}),
    )
    # Expect ((SUM(a) - SUM(b)) - SUM(c))
    assert dax == "SUM('Sales'[a]) - SUM('Sales'[b]) - SUM('Sales'[c])"


def test_arithmetic_precedence_plus_then_star() -> None:
    """`+` is lower precedence than `*` → split on `+` first."""
    from databricks_to_pbi.translator.rules import apply_rules

    dax, _ = apply_rules(
        "SUM(a) + SUM(b) * SUM(c)",
        _ctx(columns={"Sales": ["a", "b", "c"]}),
    )
    # left = SUM(a); right = SUM(b) * SUM(c) — note multiplication group
    assert dax == "SUM('Sales'[a]) + SUM('Sales'[b]) * SUM('Sales'[c])"


def test_divide_nullif_generic_with_arithmetic_numerator() -> None:
    """SUM(returned) / NULLIF(SUM(total), 0) — the generic NULLIF rule handles it."""
    from databricks_to_pbi.translator.rules import rule_divide_nullif

    out = rule_divide_nullif(
        "SUM(returned) / NULLIF(SUM(total), 0)",
        _ctx(columns={"Sales": ["returned", "total"]}),
    )
    assert out == "DIVIDE(SUM('Sales'[returned]), SUM('Sales'[total]))"


def test_coalesce_two_sums_and_zero() -> None:
    from databricks_to_pbi.translator.rules import rule_coalesce

    out = rule_coalesce(
        "COALESCE(SUM(amount), 0)",
        _ctx(columns={"Sales": ["amount"]}),
    )
    assert out == "COALESCE(SUM('Sales'[amount]), 0)"


def test_coalesce_with_chained_sums() -> None:
    from databricks_to_pbi.translator.rules import rule_coalesce

    out = rule_coalesce(
        "COALESCE(SUM(primary_amount), SUM(fallback_amount), 0)",
        _ctx(columns={"Sales": ["primary_amount", "fallback_amount"]}),
    )
    assert out == (
        "COALESCE(SUM('Sales'[primary_amount]), SUM('Sales'[fallback_amount]), 0)"
    )


def test_ifnull_maps_to_coalesce() -> None:
    """IFNULL(<agg>, default) is a synonym of COALESCE in SQL — same output."""
    from databricks_to_pbi.translator.rules import rule_coalesce

    out = rule_coalesce(
        "IFNULL(AVG(score), 0)",
        _ctx(columns={"Sales": ["score"]}),
    )
    assert out == "COALESCE(AVERAGE('Sales'[score]), 0)"


# ---------------------------------------------------------------------------
# Tier 3: multi-WHEN CASE + math wrappers + generic SUMX/AVGX/MINX/MAXX
# ---------------------------------------------------------------------------


def test_multi_when_case_with_arithmetic_then_values() -> None:
    """SUM(CASE WHEN ... THEN expr WHEN ... THEN expr ELSE expr END)
    → SUMX('t', SWITCH(TRUE(), cond1, expr1, cond2, expr2, else_expr))."""
    from databricks_to_pbi.translator.rules import rule_case_multi_when

    sql = (
        "SUM(CASE "
        "WHEN region = 'US' THEN amount * 1.1 "
        "WHEN region = 'EU' THEN amount * 0.95 "
        "ELSE amount END)"
    )
    out = rule_case_multi_when(
        sql, _ctx(columns={"Sales": ["amount", "region"]}),
    )
    assert out == (
        "SUMX('Sales', SWITCH(TRUE(), "
        "'Sales'[region] = \"US\", 'Sales'[amount] * 1.1, "
        "'Sales'[region] = \"EU\", 'Sales'[amount] * 0.95, "
        "'Sales'[amount]))"
    )


def test_multi_when_case_no_else() -> None:
    from databricks_to_pbi.translator.rules import rule_case_multi_when

    sql = (
        "AVG(CASE "
        "WHEN tier = 'gold' THEN score * 2 "
        "WHEN tier = 'silver' THEN score END)"
    )
    out = rule_case_multi_when(
        sql, _ctx(columns={"Sales": ["score", "tier"]}),
    )
    assert out == (
        "AVERAGEX('Sales', SWITCH(TRUE(), "
        "'Sales'[tier] = \"gold\", 'Sales'[score] * 2, "
        "'Sales'[tier] = \"silver\", 'Sales'[score]))"
    )


def test_sum_round_amount() -> None:
    """SUM(ROUND(amount, 2)) — math wrapper inside SUM via rule_aggx_complex."""
    from databricks_to_pbi.translator.rules import rule_aggx_complex

    out = rule_aggx_complex(
        "SUM(ROUND(amount, 2))", _ctx(columns={"Sales": ["amount"]}),
    )
    assert out == "SUMX('Sales', ROUND('Sales'[amount], 2))"


def test_sum_abs_net_amount() -> None:
    from databricks_to_pbi.translator.rules import rule_aggx_complex

    out = rule_aggx_complex(
        "SUM(ABS(net_amount))", _ctx(columns={"Sales": ["net_amount"]}),
    )
    assert out == "SUMX('Sales', ABS('Sales'[net_amount]))"


def test_avg_greatest_two_args() -> None:
    """GREATEST(a, b) → MAX(a, b) in DAX (2-arg form)."""
    from databricks_to_pbi.translator.rules import rule_aggx_complex

    out = rule_aggx_complex(
        "AVG(GREATEST(0, score))", _ctx(columns={"Sales": ["score"]}),
    )
    assert out == "AVERAGEX('Sales', MAX(0, 'Sales'[score]))"


def test_sum_ceil_adds_significance() -> None:
    """SQL CEIL(x) → DAX CEILING(x, 1) — needs the significance arg."""
    from databricks_to_pbi.translator.rules import rule_aggx_complex

    out = rule_aggx_complex(
        "SUM(CEIL(amount))", _ctx(columns={"Sales": ["amount"]}),
    )
    assert out == "SUMX('Sales', CEILING('Sales'[amount], 1))"


def test_sum_floor_adds_significance() -> None:
    from databricks_to_pbi.translator.rules import rule_aggx_complex

    out = rule_aggx_complex(
        "SUM(FLOOR(amount))", _ctx(columns={"Sales": ["amount"]}),
    )
    assert out == "SUMX('Sales', FLOOR('Sales'[amount], 1))"


def test_aggx_complex_skips_when_not_whole_expression() -> None:
    """The aggregate must wrap the entire SQL, not just the first term."""
    from databricks_to_pbi.translator.rules import rule_aggx_complex

    out = rule_aggx_complex(
        "SUM(amount) - LAG(SUM(amount), 1) OVER ()", _ctx(),
    )
    assert out is None


# ---------------------------------------------------------------------------
# Level of Detail (LOD) — AI/BI dashboard fixed + coarser patterns
# ---------------------------------------------------------------------------


def test_lod_over_all_rows() -> None:
    """SUM(amount) OVER () → CALCULATE(SUM(...), ALL('t'))."""
    from databricks_to_pbi.translator.rules import rule_lod_over

    out = rule_lod_over("SUM(amount) OVER ()", _ctx())
    assert out == "CALCULATE(SUM('Sales'[amount]), ALL('Sales'))"


def test_lod_over_partition_single_column() -> None:
    """SUM(amount) OVER (PARTITION BY region)
    → CALCULATE(SUM(...), ALLEXCEPT('t', 't'[region]))."""
    from databricks_to_pbi.translator.rules import rule_lod_over

    out = rule_lod_over(
        "SUM(amount) OVER (PARTITION BY region)",
        _ctx(columns={"Sales": ["amount", "region"]}),
    )
    assert out == (
        "CALCULATE(SUM('Sales'[amount]), ALLEXCEPT('Sales', 'Sales'[region]))"
    )


def test_lod_over_partition_multiple_columns() -> None:
    from databricks_to_pbi.translator.rules import rule_lod_over

    out = rule_lod_over(
        "SUM(amount) OVER (PARTITION BY region, product)",
        _ctx(columns={"Sales": ["amount", "region", "product"]}),
    )
    assert out == (
        "CALCULATE(SUM('Sales'[amount]), "
        "ALLEXCEPT('Sales', 'Sales'[region], 'Sales'[product]))"
    )


def test_lod_over_with_complex_inner_aggregate() -> None:
    """The inner side recurses through the rule engine."""
    from databricks_to_pbi.translator.rules import rule_lod_over

    out = rule_lod_over(
        "SUM(amount * qty) OVER (PARTITION BY region)",
        _ctx(columns={"Sales": ["amount", "qty", "region"]}),
    )
    assert out == (
        "CALCULATE(SUMX('Sales', 'Sales'[amount] * 'Sales'[qty]), "
        "ALLEXCEPT('Sales', 'Sales'[region]))"
    )


def test_lod_over_count_distinct() -> None:
    from databricks_to_pbi.translator.rules import rule_lod_over

    out = rule_lod_over(
        "COUNT(DISTINCT customer_id) OVER (PARTITION BY region)",
        _ctx(columns={"Sales": ["customer_id", "region"]}),
    )
    assert out == (
        "CALCULATE(DISTINCTCOUNT('Sales'[customer_id]), "
        "ALLEXCEPT('Sales', 'Sales'[region]))"
    )


def test_lod_over_count_star() -> None:
    from databricks_to_pbi.translator.rules import rule_lod_over

    out = rule_lod_over(
        "COUNT(*) OVER (PARTITION BY region)",
        _ctx(columns={"Sales": ["region"]}),
    )
    assert out == (
        "CALCULATE(COUNTROWS('Sales'), ALLEXCEPT('Sales', 'Sales'[region]))"
    )


def test_lod_over_dotted_partition_column() -> None:
    from databricks_to_pbi.translator.rules import rule_lod_over

    out = rule_lod_over(
        "SUM(amount) OVER (PARTITION BY orders.region)",
        _ctx(columns={"Sales": ["amount"]}),
    )
    assert out == (
        "CALCULATE(SUM('Sales'[amount]), ALLEXCEPT('Sales', 'orders'[region]))"
    )


def test_lod_aggregate_over_except_single_column() -> None:
    """SUM(Sales) AGGREGATE OVER (PARTITION BY * EXCEPT (Region))
    → CALCULATE(SUM(...), ALL('t'[Region]))."""
    from databricks_to_pbi.translator.rules import rule_lod_aggregate_over_except

    out = rule_lod_aggregate_over_except(
        "SUM(amount) AGGREGATE OVER (PARTITION BY * EXCEPT (region))",
        _ctx(columns={"Sales": ["amount", "region"]}),
    )
    assert out == "CALCULATE(SUM('Sales'[amount]), ALL('Sales'[region]))"


def test_lod_aggregate_over_except_multiple_columns() -> None:
    from databricks_to_pbi.translator.rules import rule_lod_aggregate_over_except

    out = rule_lod_aggregate_over_except(
        "SUM(amount) AGGREGATE OVER (PARTITION BY * EXCEPT (region, product))",
        _ctx(columns={"Sales": ["amount", "region", "product"]}),
    )
    assert out == (
        "CALCULATE(SUM('Sales'[amount]), "
        "ALL('Sales'[region]), ALL('Sales'[product]))"
    )


def test_lod_aggregate_over_except_with_complex_inner() -> None:
    """Inner side can be any aggregate the engine knows."""
    from databricks_to_pbi.translator.rules import rule_lod_aggregate_over_except

    out = rule_lod_aggregate_over_except(
        "SUM(price * qty) AGGREGATE OVER (PARTITION BY * EXCEPT (region))",
        _ctx(columns={"Sales": ["price", "qty", "region"]}),
    )
    assert out == (
        "CALCULATE(SUMX('Sales', 'Sales'[price] * 'Sales'[qty]), "
        "ALL('Sales'[region]))"
    )


def test_lod_over_does_not_consume_aggregate_over() -> None:
    """Coarser-LOD `AGGREGATE OVER (...)` form must NOT be eaten by rule_lod_over —
    its sibling rule has the more specific match."""
    from databricks_to_pbi.translator.rules import rule_lod_over

    out = rule_lod_over(
        "SUM(amount) AGGREGATE OVER (PARTITION BY * EXCEPT (region))",
        _ctx(columns={"Sales": ["amount", "region"]}),
    )
    assert out is None


def test_apply_rules_routes_lod_over() -> None:
    """The full rule pipeline picks the right LOD rule based on the marker."""
    dax_fixed, name_fixed = apply_rules(
        "SUM(amount) OVER (PARTITION BY region)",
        _ctx(columns={"Sales": ["amount", "region"]}),
    )
    assert name_fixed == "rule_lod_over"
    assert "ALLEXCEPT" in (dax_fixed or "")

    dax_coarser, name_coarser = apply_rules(
        "SUM(amount) AGGREGATE OVER (PARTITION BY * EXCEPT (region))",
        _ctx(columns={"Sales": ["amount", "region"]}),
    )
    assert name_coarser == "rule_lod_aggregate_over_except"
    assert "ALL(" in (dax_coarser or "")


def test_tpch_pbi_mv_known_measures_still_translate_via_rules() -> None:
    # Regression lock: the non-window measures in tpch_pbi_mv must keep
    # translating deterministically (so window work doesn't regress them).
    cols = {"lineitem": ["l_extendedprice", "l_discount", "l_quantity", "l_tax",
                         "l_returnflag", "l_shipmode", "l_orderkey"]}
    ctx = RuleContext(table="lineitem", columns_by_table=cols)
    cases = {
        "SUM(l_extendedprice * (1 - l_discount))":
            "SUMX('lineitem', 'lineitem'[l_extendedprice] * (1 - 'lineitem'[l_discount]))",
        "MEASURE(total_sales) - MEASURE(total_discount_amount)":
            "[total_sales] - [total_discount_amount]",
        "MEASURE(total_sales) / NULLIF(MEASURE(total_orders), 0)":
            "DIVIDE([total_sales], [total_orders])",
        "SUM(l_extendedprice * (1 - l_discount)) FILTER (WHERE l_returnflag = 'R')":
            "CALCULATE(SUMX('lineitem', 'lineitem'[l_extendedprice] * "
            "(1 - 'lineitem'[l_discount])), 'lineitem'[l_returnflag] = \"R\")",
    }
    for sql, expected in cases.items():
        dax, rule = apply_rules(sql, ctx)
        assert dax == expected, f"{sql} -> {dax!r} via {rule}"
