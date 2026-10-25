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

    def test_non_finite_fiscal_values_are_rejected(self):
        for row in (0, 4):
            for value in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(row=row, value=value):
                    facts = self.fiscal_facts(40)
                    facts["value"] = facts["value"].astype(float)
                    facts.loc[row, "value"] = value
                    with self.assertRaisesRegex(ValueError, "Fiscal-year reconciliation failed"):
                        dataset.check_quarters_add_up(facts)

    def test_zero_fiscal_year_requires_zero_quarter_total(self):
        facts = self.fiscal_facts(-60)
        facts.loc[4, "value"] = 0
        dataset.check_quarters_add_up(facts)
        facts.loc[3, "value"] = -50
        with self.assertRaisesRegex(ValueError, "Fiscal-year reconciliation failed"):
            dataset.check_quarters_add_up(facts)

    def test_negative_fiscal_year_uses_relative_absolute_difference(self):
        facts = self.fiscal_facts(40)
        facts["value"] *= -1
        dataset.check_quarters_add_up(facts)
        facts.loc[3, "value"] = -50
        with self.assertRaisesRegex(ValueError, "Fiscal-year reconciliation failed"):
            dataset.check_quarters_add_up(facts)

    def test_incomplete_fiscal_year_is_still_skipped(self):
        dataset.check_quarters_add_up(self.fiscal_facts(40).drop(index=2))

    def test_fiscal_tolerance_remains_half_a_percent(self):
        dataset.check_quarters_add_up(self.fiscal_facts(40.5))
        with self.assertRaisesRegex(ValueError, "Fiscal-year reconciliation failed"):
            dataset.check_quarters_add_up(self.fiscal_facts(40.6))

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

    def check_tsmc_values(self, reported, reference):
        with tempfile.TemporaryDirectory() as folder:
            sec = Path(folder) / "sec.csv"
            manual = Path(folder) / "manual.csv"
            sec.write_text(
                "ticker,currency,metric,end,filed,value\n"
                f"TSM,TWD,operating_income,2022-12-31,2023-04-01,{reference}\n"
            )
            manual.write_text(
                "ticker,metric,period,value,unit_multiplier,source\n"
                f"TSM,operating_income,FY2022,{reported},1,SEC 20-F\n"
            )
            with patch.object(dataset, "SEC_FILE", sec), patch.object(dataset, "MANUAL_FILE", manual):
                dataset.check_tsmc_against_sec()

    def test_non_finite_tsmc_values_are_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            for reported, reference in ((value, 100), (100, value)):
                with self.subTest(reported=reported, reference=reference):
                    with self.assertRaisesRegex(ValueError, "TSMC reconciliation failed"):
                        self.check_tsmc_values(reported, reference)

    def test_negative_tsmc_reference_uses_absolute_difference(self):
        self.check_tsmc_values(-100, -100)
        self.check_tsmc_values(-100.4, -100)
        with self.assertRaisesRegex(ValueError, "TSMC reconciliation failed"):
            self.check_tsmc_values(-101, -100)
        with self.assertRaisesRegex(ValueError, "TSMC reconciliation failed"):
            self.check_tsmc_values(120, -100)

    def test_zero_tsmc_reference_requires_zero_reported_value(self):
        self.check_tsmc_values(0, 0)
        for value in (-1, 1):
            with self.subTest(reported=value):
                with self.assertRaisesRegex(ValueError, "TSMC reconciliation failed"):
                    self.check_tsmc_values(value, 0)

    def test_tsmc_tolerance_remains_half_a_percent(self):
        self.check_tsmc_values(100.5, 100)
        self.check_tsmc_values(-100.5, -100)
        with self.assertRaisesRegex(ValueError, "TSMC reconciliation failed"):
            self.check_tsmc_values(100.6, 100)


if __name__ == "__main__":
    unittest.main()
