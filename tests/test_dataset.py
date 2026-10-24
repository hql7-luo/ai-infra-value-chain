"""Financial reconciliation must stop publication when inputs conflict."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import build_dataset as dataset


class DatasetChecks(unittest.TestCase):
    def fiscal_facts(self, last_quarter):
        rows = [
            ("2022-01-01", "2022-03-31", 10),
            ("2022-04-01", "2022-06-30", 20),
            ("2022-07-01", "2022-09-30", 30),
            ("2022-10-01", "2022-12-31", last_quarter),
            ("2022-01-01", "2022-12-31", 100),
        ]
        frame = pd.DataFrame(rows, columns=["start", "end", "value"])
        frame["ticker"] = "EXAMPLE"
        frame["metric"] = "revenue"
        frame["start"] = pd.to_datetime(frame["start"])
        frame["end"] = pd.to_datetime(frame["end"])
        frame["days"] = (frame["end"] - frame["start"]).dt.days + 1
        return frame

    def test_matching_fiscal_year_passes(self):
        dataset.check_quarters_add_up(self.fiscal_facts(40))

    def test_conflicting_fiscal_year_stops_pipeline(self):
        with self.assertRaisesRegex(ValueError, "Fiscal-year reconciliation failed"):
            dataset.check_quarters_add_up(self.fiscal_facts(50))

    def test_two_fiscal_quarters_in_one_calendar_quarter_are_rejected(self):
        facts = self.fiscal_facts(40).iloc[:2].copy()
        facts["end"] = pd.to_datetime(["2022-03-31", "2022-04-30"])
        facts["days"] = 90
        with self.assertRaisesRegex(ValueError, "Multiple fiscal quarters"):
            dataset.build_quarterly_table(facts)

    def test_missing_tsmc_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            sec = Path(folder) / "sec.csv"
            manual = Path(folder) / "manual.csv"
            sec.write_text("ticker,currency,metric,end,filed,value\nTSM,TWD,revenue,2021-12-31,2022-04-01,100\n")
            manual.write_text("ticker,metric,period,value,unit_multiplier,source\nTSM,revenue,FY2022,100,1,SEC 20-F\n")
            with patch.object(dataset, "SEC_FILE", sec), patch.object(dataset, "MANUAL_FILE", manual):
                with self.assertRaisesRegex(ValueError, "TSMC reconciliation failed"):
                    dataset.check_tsmc_against_sec()


if __name__ == "__main__":
    unittest.main()
