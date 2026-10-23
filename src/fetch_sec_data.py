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

# Each metric can be reported under different XBRL tags, so we keep all candidates
METRIC_CONCEPTS = {
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


def download_company_facts(cik):
    """Download the full XBRL fact file for one company."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    facts = response.json()
    return facts


def extract_rows(ticker, facts):
    """Turn the nested JSON into flat rows for the metrics we need."""
    rows = []
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for metric, concepts in METRIC_CONCEPTS.items():
        for concept in concepts:
            usd_values = us_gaap.get(concept, {}).get("units", {}).get("USD", [])
            for item in usd_values:
                is_report = item.get("form", "").startswith(("10-K", "10-Q"))
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
                            "form": item["form"],
                            "filed": item["filed"],
                        }
                    )
    return rows


def main():
    companies = pd.read_csv(COMPANY_FILE)
    sec_companies = companies[companies["source"] == "sec"]

    all_rows = []
    for _, company in sec_companies.iterrows():
        facts = download_company_facts(company["cik"])
        rows = extract_rows(company["ticker"], facts)
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
