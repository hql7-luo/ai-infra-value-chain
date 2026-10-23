"""
Step 3: answer the question "where does the profit from AI infrastructure land?"

Input:   data/processed/periods.csv    (from build_dataset.py, USD billions)
         data/processed/quarterly.csv
Outputs: outputs/company_summary.csv   one row per company, CY2022 vs latest TTM
         outputs/layer_summary.csv     same numbers added up by value-chain layer
         outputs/profit_share_by_year.csv  each layer's share of supplier operating profit
         outputs/cloud_capex.csv       cloud platforms: capex vs operating cash flow
         outputs/cloud_capex_quarterly.csv
         outputs/key_numbers.json      the numbers quoted in the README

Main idea: revenue is double counted along a supply chain (NVIDIA's sales include
TSMC's wafers, Dell's sales include NVIDIA's GPUs). Operating profit is not, because
each company's profit is only what it keeps for itself. So "who makes the money" is
measured with operating profit, and growth with revenue.
"""
import json
import os

import pandas as pd

PERIODS_FILE = "data/processed/periods.csv"
QUARTERLY_FILE = "data/processed/quarterly.csv"
OUTPUT_DIR = "outputs"

BASE = "CY2022"        # before ChatGPT (launched Nov 30, 2022) changed AI spending
LATEST = "TTM 2Q26"    # trailing twelve months, Jul 2025 - Jun 2026 (calendar-aligned)
PERIOD_ORDER = ["CY2022", "CY2023", "CY2024", "CY2025", "TTM 2Q26"]
CLOUD_LAYER = "Cloud & AI platforms"
CHINA_OPTICAL = ["300308.SZ", "300502.SZ"]


def safe_divide(top, bottom):
    """Divide two columns; return NaN (not an error) where the bottom is 0."""
    result = top / bottom.where(bottom != 0)
    return result


def compare_base_and_latest(table, group_columns):
    """Put CY2022 and the latest TTM side by side and add growth and margin columns."""
    numbers = ["revenue", "gross_profit", "operating_income", "capex"]
    base = table[table["period"] == BASE].groupby(group_columns)[numbers].sum(min_count=1)
    latest = table[table["period"] == LATEST].groupby(group_columns)[numbers].sum(min_count=1)

    summary = pd.DataFrame(index=latest.index)
    summary["revenue_2022"] = base["revenue"]
    summary["revenue_ttm"] = latest["revenue"]
    summary["revenue_multiple"] = safe_divide(latest["revenue"], base["revenue"])
    summary["gross_margin_2022"] = safe_divide(base["gross_profit"], base["revenue"])
    summary["gross_margin_ttm"] = safe_divide(latest["gross_profit"], latest["revenue"])
    summary["operating_income_2022"] = base["operating_income"]
    summary["operating_income_ttm"] = latest["operating_income"]
    summary["operating_margin_2022"] = safe_divide(base["operating_income"], base["revenue"])
    summary["operating_margin_ttm"] = safe_divide(latest["operating_income"], latest["revenue"])
    summary["new_revenue"] = latest["revenue"] - base["revenue"]
    summary["new_operating_income"] = latest["operating_income"] - base["operating_income"]
    # of every extra dollar of revenue since 2022, how many cents became operating profit
    summary["profit_per_new_revenue_dollar"] = safe_divide(
        summary["new_operating_income"], summary["new_revenue"])
    summary["capex_to_revenue_ttm"] = safe_divide(latest["capex"], latest["revenue"])
    return summary


def build_company_summary(periods):
    info = periods[["ticker", "company", "layer", "layer_order"]].drop_duplicates()
    summary = compare_base_and_latest(periods, ["ticker"]).reset_index()
    summary = info.merge(summary, on="ticker")
    suppliers = summary["layer"] != CLOUD_LAYER
    total_new_profit = summary.loc[suppliers, "new_operating_income"].sum()
    summary["share_of_supplier_new_profit"] = summary["new_operating_income"].where(suppliers) / total_new_profit
    summary = summary.sort_values(["layer_order", "new_operating_income"], ascending=[True, False])
    return summary


def build_layer_summary(periods):
    suppliers = periods[periods["layer"] != CLOUD_LAYER]
    summary = compare_base_and_latest(suppliers, ["layer_order", "layer"]).reset_index()
    summary["share_of_supplier_new_profit"] = (
        summary["new_operating_income"] / summary["new_operating_income"].sum())
    summary["companies"] = summary["layer"].map(
        suppliers.groupby("layer")["ticker"].apply(lambda tickers: ", ".join(sorted(set(tickers)))))
    summary = summary.sort_values("layer_order")
    return summary


def build_optical_split(periods):
    """Optical layer split into China module makers vs US-listed component makers."""
    optical = periods[periods["layer"] == "Optical"].copy()
    optical["group"] = optical["ticker"].apply(
        lambda ticker: "China modules (Innolight, Eoptolink)" if ticker in CHINA_OPTICAL
        else "US-listed (Lumentum, Coherent, Fabrinet)")
    split = compare_base_and_latest(optical, ["group"]).reset_index()
    return split


def build_profit_share_by_year(periods):
    """Each supplier layer's share of total supplier operating profit, year by year."""
    suppliers = periods[periods["layer"] != CLOUD_LAYER]
    profit = suppliers.pivot_table(index="layer", columns="period",
                                   values="operating_income", aggfunc="sum")
    share = (profit / profit.sum()).reindex(columns=PERIOD_ORDER)
    order = suppliers.drop_duplicates("layer").set_index("layer")["layer_order"]
    share = share.loc[order.sort_values().index]
    return share


def build_cloud_capex(periods):
    """Who pays: capex of the five cloud platforms vs the cash their businesses generate."""
    cloud = periods[periods["layer"] == CLOUD_LAYER]
    totals = cloud.groupby("period")[["revenue", "operating_income", "capex", "operating_cash_flow"]].sum()
    totals = totals.reindex(PERIOD_ORDER)
    totals["capex_to_operating_cash_flow"] = totals["capex"] / totals["operating_cash_flow"]
    totals["capex_to_revenue"] = totals["capex"] / totals["revenue"]
    totals["cash_left_after_capex"] = totals["operating_cash_flow"] - totals["capex"]
    by_company = cloud.pivot_table(index="period", columns="ticker", values="capex").reindex(PERIOD_ORDER)
    by_company.columns = [f"capex_{ticker}" for ticker in by_company.columns]
    return totals.join(by_company)


def build_cloud_capex_quarterly(quarterly):
    """Quarterly capex by cloud platform, 2022Q1 to 2026Q2."""
    cloud = quarterly[(quarterly["layer"] == CLOUD_LAYER) & (quarterly["calendar_quarter"] <= "2026Q2")]
    capex = cloud.pivot_table(index="calendar_quarter", columns="ticker", values="capex")
    cash = cloud.groupby("calendar_quarter")["operating_cash_flow"].sum()
    capex["total_capex"] = capex.sum(axis=1)
    capex["operating_cash_flow"] = cash
    # use four-quarter sums so one lumpy quarter does not swing the ratio
    capex["capex_to_ocf_4q"] = (capex["total_capex"].rolling(4).sum()
                                / capex["operating_cash_flow"].rolling(4).sum())
    capex = capex[capex.index >= "2022Q1"]
    return capex


def collect_key_numbers(company, layer, optical, cloud):
    """The handful of numbers the README quotes, so the text can be checked against data."""
    chips = layer.set_index("layer").loc["AI chips"]
    nvidia = company.set_index("ticker").loc["NVDA"]
    servers = layer.set_index("layer").loc["Servers & systems"]
    memory = layer.set_index("layer").loc["Memory & storage"]
    numbers = {
        "period_base": BASE,
        "period_latest": LATEST,
        "supplier_new_operating_income_busd": layer["new_operating_income"].sum(),
        "supplier_new_revenue_busd": layer["new_revenue"].sum(),
        "ai_chips_share_of_new_profit": chips["share_of_supplier_new_profit"],
        "nvidia_share_of_new_profit": nvidia["share_of_supplier_new_profit"],
        "nvidia_new_operating_income_busd": nvidia["new_operating_income"],
        "nvidia_operating_margin_ttm": nvidia["operating_margin_ttm"],
        "memory_profit_per_new_revenue_dollar": memory["profit_per_new_revenue_dollar"],
        "memory_operating_margin_2022": memory["operating_margin_2022"],
        "memory_operating_margin_ttm": memory["operating_margin_ttm"],
        "servers_new_revenue_busd": servers["new_revenue"],
        "servers_new_operating_income_busd": servers["new_operating_income"],
        "servers_profit_per_new_revenue_dollar": servers["profit_per_new_revenue_dollar"],
        "optical_split": optical.set_index("group")[
            ["new_revenue", "new_operating_income", "profit_per_new_revenue_dollar",
             "operating_margin_ttm"]].to_dict(orient="index"),
        "cloud_capex_2022_busd": cloud.loc[BASE, "capex"],
        "cloud_capex_ttm_busd": cloud.loc[LATEST, "capex"],
        "cloud_capex_to_ocf_2022": cloud.loc[BASE, "capex_to_operating_cash_flow"],
        "cloud_capex_to_ocf_ttm": cloud.loc[LATEST, "capex_to_operating_cash_flow"],
        "cloud_cash_left_after_capex_2022_busd": cloud.loc[BASE, "cash_left_after_capex"],
        "cloud_cash_left_after_capex_ttm_busd": cloud.loc[LATEST, "cash_left_after_capex"],
    }
    return numbers


def main():
    periods = pd.read_csv(PERIODS_FILE)
    quarterly = pd.read_csv(QUARTERLY_FILE)

    company = build_company_summary(periods)
    layer = build_layer_summary(periods)
    optical = build_optical_split(periods)
    profit_share = build_profit_share_by_year(periods)
    cloud = build_cloud_capex(periods)
    cloud_quarterly = build_cloud_capex_quarterly(quarterly)
    key_numbers = collect_key_numbers(company, layer, optical, cloud)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    company.to_csv(f"{OUTPUT_DIR}/company_summary.csv", index=False, float_format="%.6f")
    layer.to_csv(f"{OUTPUT_DIR}/layer_summary.csv", index=False, float_format="%.6f")
    optical.to_csv(f"{OUTPUT_DIR}/optical_split.csv", index=False, float_format="%.6f")
    profit_share.to_csv(f"{OUTPUT_DIR}/profit_share_by_year.csv", float_format="%.6f")
    cloud.to_csv(f"{OUTPUT_DIR}/cloud_capex.csv", float_format="%.6f")
    cloud_quarterly.to_csv(f"{OUTPUT_DIR}/cloud_capex_quarterly.csv", float_format="%.6f")
    with open(f"{OUTPUT_DIR}/key_numbers.json", "w") as file:
        json.dump(key_numbers, file, indent=2, default=float)

    # Short printout for a quick read in the terminal / GitHub Actions log
    columns = ["layer", "new_revenue", "new_operating_income", "share_of_supplier_new_profit",
               "profit_per_new_revenue_dollar", "operating_margin_2022", "operating_margin_ttm"]
    print(layer[columns].round(3).to_string(index=False))
    print(f"\nCloud capex {BASE}: ${key_numbers['cloud_capex_2022_busd']:.0f}B "
          f"-> {LATEST}: ${key_numbers['cloud_capex_ttm_busd']:.0f}B "
          f"({key_numbers['cloud_capex_to_ocf_ttm']:.0%} of operating cash flow)")


if __name__ == "__main__":
    main()
