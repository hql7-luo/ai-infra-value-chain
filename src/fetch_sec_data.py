"""
Step 1: download reported financial facts from SEC EDGAR.

Source: SEC XBRL "companyfacts" API (free, no key needed)
        https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
Input:  config/companies.csv
Output: data/raw/sec_facts.csv  (one row per reported fact, nothing calculated yet)
"""
import os
import time

import pandas as pd
import requests

COMPANY_FILE = "config/companies.csv"
OUTPUT_FILE = "data/raw/sec_facts.csv"
START_DATE = "2021-01-01"  # keep facts that end on or after this date

# SEC asks every script to identify itself with a name and an email address
USER_AGENT = os.environ.get(
    "SEC_USER_AGENT", "ai-infra-value-chain research project haoqi.luo23@hoosac.org"
)

# US filers (10-K / 10-Q, US GAAP). One metric can use different tags, so keep all candidates.
US_GAAP_CONCEPTS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ],
    "gross_profit": ["GrossProfit"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold"],
    "operating_income": ["OperatingIncomeLoss"],
    # backups, used only when a company stops tagging operating income directly
    "operating_expenses": ["OperatingExpenses"],
    "costs_and_expenses": ["CostsAndExpenses"],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
}

# Foreign filers such as TSMC (20-F, IFRS, annual only, local currency)
IFRS_CONCEPTS = {
    "revenue": ["Revenue", "RevenueFromContractsWithCustomers"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["ProfitLossFromOperatingActivities"],
    "capex": [
        "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "PurchaseOfPropertyPlantAndEquipment",
    ],
    "operating_cash_flow": ["CashFlowsFromUsedInOperatingActivities"],
}


def download_company_facts(cik):
    """Download the full XBRL fact file for one company."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    facts = response.json()
    return facts


def extract_rows(ticker, facts, taxonomy, concept_map):
    """Turn the nested JSON into flat rows for the metrics we need."""
    rows = []
    tagged_facts = facts.get("facts", {}).get(taxonomy, {})
    for metric, concepts in concept_map.items():
        for concept in concepts:
            units = tagged_facts.get(concept, {}).get("units", {})
            for currency, items in units.items():
                for item in items:
                    is_report = item.get("form", "").startswith(("10-K", "10-Q", "20-F"))
                    is_recent = item.get("end", "") >= START_DATE
                    if is_report and is_recent and "start" in item:
                        rows.append(
                            {
                                "ticker": ticker,
                                "metric": metric,
                                "concept": concept,
                                "start": item["start"],
                                "end": item["end"],
                                "value": item["val"],
                                "currency": currency,
                                "form": item["form"],
                                "filed": item["filed"],
                            }
                        )
    return rows


def main():
    companies = pd.read_csv(COMPANY_FILE)
    sec_companies = companies[companies["cik"].notna()]

    all_rows = []
    for _, company in sec_companies.iterrows():
        facts = download_company_facts(company["cik"])
        if company["source"] == "sec":
            rows = extract_rows(company["ticker"], facts, "us-gaap", US_GAAP_CONCEPTS)
        else:
            rows = extract_rows(company["ticker"], facts, "ifrs-full", IFRS_CONCEPTS)
        all_rows.extend(rows)
        print(f"{company['ticker']:6} {facts.get('entityName', '')[:40]:40} {len(rows):5} facts")
        time.sleep(0.2)  # stay well below SEC's 10 requests per second limit

    result = pd.DataFrame(all_rows)
    result = result.sort_values(["ticker", "metric", "concept", "end", "start", "filed"])
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    result.to_csv(OUTPUT_FILE, index=False)
    print(f"Saved {len(result):,} rows to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
