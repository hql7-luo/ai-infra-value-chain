"""
Step 2: turn raw reported numbers into one clean, calendar-aligned dataset.

Why this step is needed:
- US companies report year-to-date numbers (6, 9, 12 months), not every single quarter.
- Fiscal years end in different months (NVIDIA in January, Microsoft in June, ...).
So we (1) rebuild every standalone quarter, (2) map each fiscal quarter to the calendar
quarter where most of it falls, and (3) add four quarters to get calendar years and TTM.

Inputs:  data/raw/sec_facts.csv          (from fetch_sec_data.py)
         data/manual/sec_gap_fills.csv   (a few quarters missing from SEC XBRL)
         data/manual/manual_reported.csv (TSMC, Innolight, Eoptolink, local currency)
         data/manual/fx_rates.csv
Outputs: data/processed/quarterly.csv    (US-listed companies, one row per calendar quarter)
         data/processed/periods.csv      (all companies, CY2022-CY2025 and TTM, USD billions)
"""
import math
import os

import pandas as pd

SEC_FILE = "data/raw/sec_facts.csv"
GAP_FILE = "data/manual/sec_gap_fills.csv"
MANUAL_FILE = "data/manual/manual_reported.csv"
FX_FILE = "data/manual/fx_rates.csv"
COMPANY_FILE = "config/companies.csv"
QUARTERLY_OUT = "data/processed/quarterly.csv"
PERIODS_OUT = "data/processed/periods.csv"

LATEST_QUARTER = "2026Q2"  # latest calendar quarter reported by every company
TTM_LABEL = "TTM 2Q26"
CALENDAR_YEARS = [2022, 2023, 2024, 2025]
METRICS = ["revenue", "gross_profit", "operating_income", "capex", "operating_cash_flow"]

# When a company used two tags for the same item, prefer the one listed first
TAG_PREFERENCE = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "CostOfRevenue",
    "CostOfGoodsAndServicesSold",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PaymentsToAcquireProductiveAssets",
]


# ---------- 1. One value per reported period ----------

def load_us_facts():
    """Read SEC facts for US filers (in USD) and add the manual gap fills."""
    companies = pd.read_csv(COMPANY_FILE)
    us_tickers = companies.loc[companies["source"] == "sec", "ticker"]

    facts = pd.read_csv(SEC_FILE)
    facts = facts[facts["ticker"].isin(us_tickers) & (facts["currency"] == "USD")]

    gaps = pd.read_csv(GAP_FILE)
    gaps["concept"] = "manual_gap_fill"
    gaps["filed"] = "2000-01-01"
    facts = pd.concat([facts, gaps], ignore_index=True)

    for column in ["start", "end", "filed"]:
        facts[column] = pd.to_datetime(facts[column])
    facts["days"] = (facts["end"] - facts["start"]).dt.days + 1
    facts = remove_tagging_errors(facts)
    return facts


def remove_tagging_errors(facts):
    """
    Drop a 3-month fact that repeats the full-year value for the same end date.
    (Example: Oracle tagged its FY2022 revenue on a 3-month period ending 2022-05-31.)
    """
    yearly = facts[facts["days"].apply(is_year_length)][["ticker", "metric", "end", "value"]]
    yearly = yearly.drop_duplicates().assign(repeats_year=True)
    facts = facts.merge(yearly, on=["ticker", "metric", "end", "value"], how="left")
    is_error = facts["days"].apply(is_quarter_length) & (facts["repeats_year"] == True)
    if is_error.any():
        print(f"Removed {is_error.sum()} 3-month facts that repeat a full-year value")
    facts = facts[~is_error].drop(columns="repeats_year")
    return facts


def pick_one_value_per_period(facts):
    """
    Later filings repeat old numbers, and a company may switch tags.
    Keep one value per period: the tag the company used most recently,
    then the preferred tag, then the latest filing.
    """
    facts = facts.copy()
    latest_end = facts.groupby(["ticker", "metric", "concept"])["end"].transform("max")
    facts["tag_last_used"] = latest_end
    facts["tag_rank"] = facts["concept"].apply(
        lambda tag: TAG_PREFERENCE.index(tag) if tag in TAG_PREFERENCE else 99
    )
    facts = facts.sort_values(
        ["ticker", "metric", "start", "end", "tag_last_used", "tag_rank", "filed"],
        ascending=[True, True, True, True, False, True, False],
    )
    unique_facts = facts.drop_duplicates(["ticker", "metric", "start", "end"], keep="first")
    return unique_facts


# ---------- 2. Rebuild standalone quarters ----------

def is_quarter_length(days):
    """A fiscal quarter is 13 or 14 weeks long."""
    return 80 <= days <= 100


def is_year_length(days):
    return 350 <= days <= 380


def to_calendar_quarter(end_date):
    """Map a fiscal period to the calendar quarter where most of its last quarter falls."""
    middle_of_last_quarter = end_date - pd.Timedelta(days=45)
    calendar_quarter = f"{middle_of_last_quarter.year}Q{(middle_of_last_quarter.month - 1) // 3 + 1}"
    return calendar_quarter


def rebuild_quarters(facts):
    """
    For one company and one metric, return {quarter end date: quarter value}.
    Use the reported 3-month value when it exists; otherwise take the difference
    between two year-to-date values with the same start (e.g. Q4 = 12 months - 9 months).
    """
    quarters = {}
    for _, row in facts.iterrows():
        if is_quarter_length(row["days"]):
            quarters[row["end"]] = row["value"]

    for _, same_start in facts.groupby("start"):
        same_start = same_start.sort_values("end")
        previous = None
        for _, row in same_start.iterrows():
            if previous is not None:
                gap_days = (row["end"] - previous["end"]).days
                if is_quarter_length(gap_days) and row["end"] not in quarters:
                    quarters[row["end"]] = row["value"] - previous["value"]
            previous = row
    return quarters


def reconciliation_gap(reported, reference):
    """Relative absolute difference, rejecting non-finite values and zero mismatches."""
    if not math.isfinite(reported) or not math.isfinite(reference):
        return float("inf")
    if reference == 0:
        return 0.0 if reported == 0 else float("inf")
    return abs(reported - reference) / abs(reference)


def check_quarters_add_up(unique_facts):
    """Data check: the four rebuilt quarters of each fiscal year should add up to the reported year."""
    checked, problems = 0, []
    for (ticker, metric), facts in unique_facts.groupby(["ticker", "metric"]):
        quarters = rebuild_quarters(facts)
        for _, year in facts[facts["days"].apply(is_year_length)].iterrows():
            inside = [value for end, value in quarters.items() if year["start"] < end <= year["end"]]
            if len(inside) == 4:
                checked += 1
                difference = reconciliation_gap(sum(inside), year["value"])
                if difference > 0.005:
                    problems.append(f"{ticker} {metric} {year['end'].date()}: {difference:.1%}")
    print(f"Quarter check: {checked} fiscal years compared, {len(problems)} off by more than 0.5%")
    for problem in problems:
        print("  ", problem)
    if problems:
        raise ValueError(f"Fiscal-year reconciliation failed for {len(problems)} values")


def build_quarterly_table(unique_facts):
    rows = []
    for (ticker, metric), facts in unique_facts.groupby(["ticker", "metric"]):
        for end_date, value in rebuild_quarters(facts).items():
            rows.append({
                "ticker": ticker,
                "metric": metric,
                "fiscal_quarter_end": end_date.date(),
                "calendar_quarter": to_calendar_quarter(end_date),
                "value": value,
            })
    long_table = pd.DataFrame(rows)

    duplicates = long_table.duplicated(["ticker", "metric", "calendar_quarter"], keep=False)
    if duplicates.any():
        raise ValueError(
            "Multiple fiscal quarters map to one calendar quarter:\n"
            + long_table[duplicates].to_string(index=False)
        )

    quarterly = long_table.pivot_table(
        index=["ticker", "calendar_quarter"], columns="metric", values="value", aggfunc="last"
    ).reset_index()
    fiscal_end = long_table.groupby(["ticker", "calendar_quarter"])["fiscal_quarter_end"].max()
    quarterly = quarterly.join(fiscal_end, on=["ticker", "calendar_quarter"])
    return quarterly


def fill_missing_metrics(table):
    """Some companies do not tag gross profit or operating income; rebuild them."""
    table = table.copy()
    for column in ["gross_profit", "cost_of_revenue", "operating_income",
                   "operating_expenses", "costs_and_expenses"]:
        if column not in table.columns:
            table[column] = float("nan")

    # gross profit = revenue - cost of revenue
    gross_profit_rebuilt = table["revenue"] - table["cost_of_revenue"]
    table["gross_profit"] = table["gross_profit"].fillna(gross_profit_rebuilt)

    # operating income = gross profit - operating expenses, or revenue - total costs and expenses
    from_opex = table["gross_profit"] - table["operating_expenses"]
    from_total_costs = table["revenue"] - table["costs_and_expenses"]
    table["operating_income"] = table["operating_income"].fillna(from_opex).fillna(from_total_costs)
    return table


# ---------- 3. Calendar years and TTM for US filers ----------

def four_quarters_ending(last_quarter):
    """e.g. 2026Q2 -> ['2026Q2', '2026Q1', '2025Q4', '2025Q3']"""
    year, quarter = int(last_quarter[:4]), int(last_quarter[-1])
    quarters = []
    for _ in range(4):
        quarters.append(f"{year}Q{quarter}")
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
    return quarters


def annual_value(unique_facts, ticker, metric, last_quarter):
    """Backup: a reported 12-month value whose last quarter maps to last_quarter."""
    candidates = unique_facts[
        (unique_facts["ticker"] == ticker)
        & (unique_facts["metric"] == metric)
        & unique_facts["days"].apply(is_year_length)
    ]
    match = candidates[candidates["end"].apply(to_calendar_quarter) == last_quarter]
    value = match["value"].iloc[0] if len(match) > 0 else float("nan")
    return value


def sum_four_quarters(quarterly, unique_facts, last_quarter, label):
    """Add four calendar quarters per company. If a quarter is missing, use a 12-month value."""
    needed = four_quarters_ending(last_quarter)
    window = quarterly[quarterly["calendar_quarter"].isin(needed)]
    rows = []
    for ticker, group in window.groupby("ticker"):
        row = {"ticker": ticker, "period": label}
        for metric in METRICS:
            values = group[metric]
            if len(group) == 4 and values.notna().all():
                row[metric] = values.sum()
            else:
                row[metric] = annual_value(unique_facts, ticker, metric, last_quarter)
        rows.append(row)
    return pd.DataFrame(rows)


def build_us_periods(quarterly, unique_facts):
    tables = [sum_four_quarters(quarterly, unique_facts, f"{year}Q4", f"CY{year}")
              for year in CALENDAR_YEARS]
    tables.append(sum_four_quarters(quarterly, unique_facts, LATEST_QUARTER, TTM_LABEL))
    return pd.concat(tables, ignore_index=True)


# ---------- 4. Manually collected companies (TSMC, Innolight, Eoptolink) ----------

def build_manual_periods():
    """
    The manual file holds full-year (FY) and first-half (H1) numbers in local currency.
    Each value is converted with the average exchange rate of its own period, then
    TTM to June 2026 = FY2025 - H1 2025 + H1 2026.
    These companies use calendar fiscal years, so FY2024 = CY2024.
    """
    manual = pd.read_csv(MANUAL_FILE)
    fx = pd.read_csv(FX_FILE)
    manual = manual.merge(fx[["currency", "period", "local_per_usd"]], on=["currency", "period"], how="left")
    manual["value_usd"] = manual["value"] * manual["unit_multiplier"] / manual["local_per_usd"]

    wide = manual.pivot_table(index=["ticker", "period"], columns="metric", values="value_usd").reset_index()
    wide = fill_missing_metrics(wide)

    rows = []
    for ticker, group in wide.groupby("ticker"):
        by_period = group.set_index("period")
        for year in CALENDAR_YEARS:
            row = {"ticker": ticker, "period": f"CY{year}"}
            for metric in METRICS:
                row[metric] = by_period.loc[f"FY{year}", metric]
            rows.append(row)
        row = {"ticker": ticker, "period": TTM_LABEL}
        for metric in METRICS:
            row[metric] = (by_period.loc["FY2025", metric] - by_period.loc["H1_2025", metric]
                           + by_period.loc["H1_2026", metric])
        rows.append(row)
    return pd.DataFrame(rows)


def check_tsmc_against_sec():
    """Data check: TSMC numbers typed from reports should match the 20-F XBRL facts."""
    sec = pd.read_csv(SEC_FILE)
    sec = sec[(sec["ticker"] == "TSM") & (sec["currency"] == "TWD")]
    sec = sec.sort_values("filed").drop_duplicates(["metric", "end"], keep="last")
    sec["period"] = "FY" + sec["end"].str[:4]

    manual = pd.read_csv(MANUAL_FILE)
    manual = manual[(manual["ticker"] == "TSM") & (manual["source"].str.contains("20-F"))]
    manual["reported"] = manual["value"] * manual["unit_multiplier"]

    sec = sec.rename(columns={"value": "sec_value"})
    merged = manual.merge(sec[["metric", "period", "sec_value"]], on=["metric", "period"], how="left")
    gap = pd.Series(
        [reconciliation_gap(reported, reference)
         for reported, reference in zip(merged["reported"], merged["sec_value"])],
        index=merged.index, dtype=float,
    )
    print(f"TSMC check vs SEC 20-F: {len(merged)} values, largest difference {gap.max():.4%}")
    if merged.empty or (gap > 0.005).any():
        raise ValueError("TSMC reconciliation failed: non-finite value, missing reference or difference above 0.5%")


# ---------- Main ----------

def main():
    companies = pd.read_csv(COMPANY_FILE)
    company_info = companies[["ticker", "company", "layer", "layer_order"]]

    # US filers: quarterly table and calendar periods
    unique_facts = pick_one_value_per_period(load_us_facts())
    check_quarters_add_up(unique_facts)
    quarterly = fill_missing_metrics(build_quarterly_table(unique_facts))
    quarterly = quarterly[quarterly["calendar_quarter"] >= "2021Q1"]
    us_periods = build_us_periods(quarterly, unique_facts)

    # Manually collected companies
    check_tsmc_against_sec()
    manual_periods = build_manual_periods()

    periods = pd.concat([us_periods, manual_periods], ignore_index=True)
    periods = periods.merge(company_info, on="ticker", how="left")
    periods[METRICS] = periods[METRICS] / 1e9  # USD billions
    periods = periods[["ticker", "company", "layer", "layer_order", "period"] + METRICS]
    periods = periods.sort_values(["layer_order", "ticker", "period"])

    quarterly = quarterly.merge(company_info, on="ticker", how="left")
    quarterly[METRICS] = quarterly[METRICS] / 1e9
    quarterly = quarterly[["ticker", "company", "layer", "calendar_quarter", "fiscal_quarter_end"] + METRICS]
    quarterly = quarterly.sort_values(["ticker", "calendar_quarter"])

    # Report gaps so nothing is silently missing
    missing = periods[periods[METRICS].isna().any(axis=1)]
    if len(missing) > 0:
        print("Rows with missing values (OK only for metrics a company does not report):")
        print(missing[["ticker", "period"] + METRICS].to_string(index=False))

    os.makedirs(os.path.dirname(PERIODS_OUT), exist_ok=True)
    quarterly.to_csv(QUARTERLY_OUT, index=False, float_format="%.4f")
    periods.to_csv(PERIODS_OUT, index=False, float_format="%.4f")
    print(f"Saved {len(quarterly)} quarterly rows and {len(periods)} period rows (USD billions)")


if __name__ == "__main__":
    main()
