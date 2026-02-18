"""
metrics.py

Computes key financial metrics (GAAP + IFRS expansions) from Balance, Income, and Cash Flow statements.
Handles intangible assets, goodwill, lease liabilities, net debt, intangible/goodwill ratios,
free cash flow, EBIT, EBITDA, net margin, etc.

Uses 'synonyms_utils.compute_capex_single_period' for safer fallback when explicit 'capital_expenditures' is absent.
"""

import numpy as np
import pandas as pd
from edgar_analytics.synonyms import SYNONYMS
from edgar_analytics.synonyms_utils import (
    compute_capex_single_period,
    find_synonym_value,
    flip_sign_if_negative_expense,
)

from apps.common.src.logging import get_logger

logger = get_logger(__name__)


def compute_ratios_and_metrics(
    balance_df: pd.DataFrame, income_df: pd.DataFrame, cash_df: pd.DataFrame
) -> dict:
    """
    Compute key financial ratios from the provided DataFrames (Balance, Income, Cash Flow).
    Includes expanded IFRS/GAAP coverage:
      - Net Income, Revenue, Margins
      - Free Cash Flow (OpCF - CapEx)
      - Operating Income, EBITDA
      - IFRS expansions: intangible ratio, goodwill ratio, net debt, net debt/EBITDA, lease liabilities, etc.

    :param balance_df: Balance sheet data as a DataFrame
    :param income_df: Income statement data as a DataFrame
    :param cash_df:   Cash flow statement data as a DataFrame
    :return: A dictionary of computed metrics and alerts.
    """
    metrics = {}

    # ========== INCOME STATEMENT ==========
    logger.info("Processing Income Statement...")
    revenue = find_synonym_value(income_df, SYNONYMS["revenue"], 0.0, "INC->Revenue")

    logger.info("Revenue found: %s", revenue)
    cost_rev = find_synonym_value(income_df, SYNONYMS["cost_of_revenue"], 0.0, "INC->CostOfRev")
    logger.info("Cost of Revenue found: %s", cost_rev)
    gross_profit = find_synonym_value(
        income_df, SYNONYMS["gross_profit"], np.nan, "INC->GrossProfit"
    )
    op_exp = find_synonym_value(income_df, SYNONYMS["operating_expenses"], 0.0, "INC->OpEx")
    net_income = find_synonym_value(income_df, SYNONYMS["net_income"], 0.0, "INC->NetIncome")

    # Flip sign if negative expenses
    cost_rev = flip_sign_if_negative_expense(cost_rev, "cost_of_revenue")
    op_exp = flip_sign_if_negative_expense(op_exp, "operating_expenses")

    if pd.isna(gross_profit) and revenue != 0.0:
        gross_profit = revenue - cost_rev

    metrics["Revenue"] = revenue
    metrics["Gross Profit"] = 0.0 if pd.isna(gross_profit) else gross_profit
    metrics["Gross Margin %"] = (gross_profit / revenue * 100.0) if revenue else 0.0

    # Approx Operating Income
    operating_income_approx = gross_profit - op_exp
    metrics["Operating Margin %"] = (
        ((operating_income_approx / revenue) * 100.0) if revenue else 0.0
    )
    metrics["Operating Expenses"] = op_exp
    metrics["Net Income"] = net_income
    metrics["Net Margin %"] = ((net_income / revenue) * 100.0) if revenue else 0.0

    # ========== BALANCE SHEET ==========
    curr_assets = find_synonym_value(balance_df, SYNONYMS["current_assets"], 0.0, "BS->CurrAssets")
    curr_liabs = find_synonym_value(
        balance_df, SYNONYMS["current_liabilities"], 0.0, "BS->CurrLiab"
    )
    total_assets = find_synonym_value(balance_df, SYNONYMS["total_assets"], 0.0, "BS->TotalAssets")
    total_liabs = find_synonym_value(
        balance_df, SYNONYMS["total_liabilities"], 0.0, "BS->TotalLiab"
    )
    total_equity = find_synonym_value(balance_df, SYNONYMS["total_equity"], 0.0, "BS->TotalEquity")

    metrics["Current Ratio"] = (curr_assets / curr_liabs) if curr_liabs else 0.0
    metrics["Debt-to-Equity"] = (total_liabs / total_equity) if total_equity else 0.0
    metrics["Equity Ratio %"] = ((total_equity / total_assets) * 100.0) if total_assets else 0.0

    # ========== CASH FLOW STATEMENT ==========
    # Operating CF
    op_cf = find_synonym_value(cash_df, SYNONYMS["cash_flow_operating"], 0.0, "CF->OpCF")

    # CapEx using new consolidated logic
    capex_val = compute_capex_single_period(cash_df, debug_label="CF->CapExSingle")

    free_cf = op_cf - capex_val
    metrics["Cash from Operations"] = op_cf
    metrics["Free Cash Flow"] = free_cf

    # ========== DEPRECIATION, ETC. ==========
    dep_amort = find_synonym_value(
        income_df, SYNONYMS["depreciation_amortization"], 0.0, "INC->DepAmort"
    )
    dep_amort = flip_sign_if_negative_expense(dep_amort, "depreciation_amortization")
    cost_rev, dep_amort = adjust_for_dep_in_cogs(income_df, cost_rev, dep_amort)

    metrics["CostOfRev"] = cost_rev
    metrics["OpEx"] = op_exp

    operating_income_approx = gross_profit - op_exp
    metrics["EBIT (approx)"] = operating_income_approx
    metrics["EBITDA (approx)"] = operating_income_approx + dep_amort

    # ========== ROE / ROA ==========
    metrics["ROE %"] = ((net_income / total_equity) * 100.0) if total_equity else 0.0
    metrics["ROA %"] = ((net_income / total_assets) * 100.0) if total_assets else 0.0

    # ========== IFRS/GAAP EXPANSIONS ==========
    intangible_val = find_synonym_value(
        balance_df, SYNONYMS["intangible_assets"], 0.0, "BS->Intangibles"
    )
    goodwill_val = find_synonym_value(balance_df, SYNONYMS["goodwill"], 0.0, "BS->Goodwill")
    oper_lease_val = find_synonym_value(
        balance_df, SYNONYMS["operating_lease_liabilities"], 0.0, "BS->OperLeaseLiab"
    )
    fin_lease_val = find_synonym_value(
        balance_df, SYNONYMS["finance_lease_liabilities"], 0.0, "BS->FinLeaseLiab"
    )
    short_debt_val = find_synonym_value(
        balance_df, SYNONYMS["short_term_debt"], 0.0, "BS->ShortTermDebt"
    )
    long_debt_val = find_synonym_value(
        balance_df, SYNONYMS["long_term_debt"], 0.0, "BS->LongTermDebt"
    )
    cash_equiv_val = find_synonym_value(balance_df, SYNONYMS["cash_equivalents"], 0.0, "BS->CashEq")

    if total_assets > 0:
        metrics["Intangible Ratio %"] = (intangible_val / total_assets) * 100.0
        metrics["Goodwill Ratio %"] = (goodwill_val / total_assets) * 100.0
    else:
        metrics["Intangible Ratio %"] = 0.0
        metrics["Goodwill Ratio %"] = 0.0

    net_intangibles = intangible_val + goodwill_val
    tangible_equity = total_equity - net_intangibles
    metrics["Tangible Equity"] = max(tangible_equity, 0.0)

    total_leases = oper_lease_val + fin_lease_val
    gross_debt = short_debt_val + long_debt_val + total_leases
    net_debt = gross_debt - cash_equiv_val
    metrics["Net Debt"] = net_debt

    ebitda_approx = metrics["EBITDA (approx)"]
    metrics["Net Debt/EBITDA"] = (net_debt / ebitda_approx) if ebitda_approx != 0 else 0.0
    metrics["Lease Liabilities Ratio %"] = (
        ((total_leases / total_assets) * 100.0) if total_assets else 0.0
    )

    # ========== INTEREST EXPENSE / TAX EXPENSE / STANDARD EBIT & EBITDA ==========
    interest_exp = find_synonym_value(
        income_df, SYNONYMS["interest_expense"], 0.0, "INC->InterestExpense"
    )
    interest_exp = flip_sign_if_negative_expense(interest_exp, "interest_expense")
    metrics["Interest Expense"] = interest_exp

    income_tax_val = find_synonym_value(
        income_df, SYNONYMS["income_tax_expense"], 0.0, "INC->TaxExpense"
    )
    if income_tax_val < 0.0:
        income_tax_val = abs(income_tax_val)
    metrics["Income Tax Expense"] = income_tax_val

    ebit_standard = net_income + interest_exp + income_tax_val
    metrics["EBIT (standard)"] = ebit_standard
    metrics["EBITDA (standard)"] = ebit_standard + dep_amort
    metrics["Interest Coverage"] = (ebit_standard / interest_exp) if interest_exp != 0.0 else 0.0

    # # ========== ALERTS ==========
    # alerts = []
    # if metrics["Net Margin %"] < ALERTS_CONFIG["NEGATIVE_MARGIN"]:
    #     alerts.append(f"Net margin below {ALERTS_CONFIG['NEGATIVE_MARGIN']}% (negative)")
    # if metrics["Debt-to-Equity"] > ALERTS_CONFIG["HIGH_LEVERAGE"]:
    #     alerts.append(f"Debt-to-Equity above {ALERTS_CONFIG['HIGH_LEVERAGE']} (high leverage)")
    # if 0.0 < metrics["ROE %"] < ALERTS_CONFIG["LOW_ROE"]:
    #     alerts.append(f"ROE < {ALERTS_CONFIG['LOW_ROE']}%")
    # if 0.0 < metrics["ROA %"] < ALERTS_CONFIG["LOW_ROA"]:
    #     alerts.append(f"ROA < {ALERTS_CONFIG['LOW_ROA']}%")
    # if metrics["Net Debt"] > 0 and metrics["Net Debt/EBITDA"] > 3.5:
    #     alerts.append("Net Debt/EBITDA above 3.5 (heavy leverage).")
    # if metrics["Interest Coverage"] != 0.0 and metrics["Interest Coverage"] < 2.0:
    #     alerts.append("Interest coverage below 2.0 => potential default risk.")

    # metrics["Alerts"] = alerts
    return metrics


def adjust_for_dep_in_cogs(
    income_df: pd.DataFrame, cost_of_revenue: float, dep_amort: float
) -> tuple[float, float]:
    """
    If there's a separate 'Depreciation in cost of sales' row, remove it from cost_of_revenue
    (already flipped to positive) and add it to total Dep/Amort. Avoids double counting.

    :param income_df: Income statement DataFrame
    :param cost_of_revenue: cost_of_revenue float (already sign-flipped if negative)
    :param dep_amort: total depreciation & amortization previously found
    :return: (adjusted_cost_of_revenue, adjusted_dep_amort)
    """
    dep_in_cogs = find_synonym_value(
        income_df, SYNONYMS.get("depreciation_in_cost_of_sales", []), 0.0, "INC->DepInCOGS"
    )
    if dep_in_cogs != 0.0:
        cost_of_revenue -= dep_in_cogs
        dep_amort += dep_in_cogs

    return cost_of_revenue, dep_amort
