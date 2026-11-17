"""Independent checks for the sector valuation routes and identifier inputs."""

from datetime import date, datetime
import unittest

from equity_workbench.equity_models import _reit_path, evaluate_equity
from equity_workbench.lseg_analysis import check_market_identity, market_observation, net_investment
from equity_workbench.lseg_workspace import valuation_route


class DirectEquityTests(unittest.TestCase):
    def test_missing_historical_lease_assets_stay_unavailable(self):
        opening = {"gross_finance_lease_assets": None, "noncurrent_finance_lease_debt": 30}
        ending = {"gross_finance_lease_assets": 60, "noncurrent_finance_lease_debt": 50,
                  "revenue": 400, "ebit": 90, "cfo": 85, "cash_capex": 20, "stock_comp": 4, "interest": 6}
        self.assertIsNone(net_investment([ending], opening, .2)["net_investment_rate"])
        opening["gross_finance_lease_assets"] = 40
        self.assertAlmostEqual(net_investment([ending], opening, .2)["lease_asset_growth_proxy"], 20)

    def test_reit_dividend_cash_flows_agree_with_growing_perpetuity(self):
        dates = [date(2026, 12, 31), date(2027, 12, 31)]
        plan = {"estimates": [{"dps": 3, "profit_or_ffo": 4}, {"dps": 3.06, "profit_or_ffo": 4.08}]}
        result = _reit_path({"market_price": 50}, plan, .08, .02, 0, date(2025, 12, 31), dates)
        self.assertAlmostEqual(result["value_per_share"], 50)
        self.assertAlmostEqual(result["implied_terminal_dividend_growth"], .02)
        self.assertEqual(result["forward_price_to_ffo"], 12.5)

    def test_residual_income_at_fair_book_when_roe_equals_equity_cost(self):
        annual = [{"period_end": f"{year}-12-31", "book": 100, "earnings": 10} for year in range(2022, 2026)]
        case = {"method": "residual_income", "valuation_date": "2025-12-31",
                "valuation_shares": 10, "market_price": 10}
        plan = {
            "method": "residual_income", "cost_of_equity": .1, "terminal_growth": .025,
            "annual": annual, "quarterly": [annual[-1]],
            "estimates": [
                {"period_end": "2026-12-31", "dps": 1, "profit_or_ffo": 10},
                {"period_end": "2027-12-31", "dps": 1, "profit_or_ffo": 10},
            ],
        }
        result = evaluate_equity(case, plan)
        self.assertAlmostEqual(result["value_per_share"], 10, places=3)
        self.assertAlmostEqual(result["scenarios"]["base"]["dividend_equivalent_value"], 100, places=2)
        self.assertGreater(result["scenarios"]["upside"]["value_per_share"], result["value_per_share"])

    def test_market_units_and_research_route(self):
        row = {
            "Instrument": "DEMO.L", "TR.PRIMARYRIC": "DEMO.L", "TR.INSTRUMENTTYPE": "Ordinary Shares",
            "TR.ISIN": "GB0000000000", "TR.TRBCECONOMICSECTOR": "Financials",
            "TR.EXCHANGENAME": "London Stock Exchange", "TR.PRICECLOSE": 550,
            "TR.PRICECLOSE.CURRENCY": "GBp", "TR.PRICECLOSE.DATE": "2026-02-13",
            "TR.COMPANYMARKETCAP": 550e6, "TR.ISSUEMARKETCAP": 550e6,
            "TR.COMPANYMARKETCAP.CURRENCY": "GBP", "TR.ISSUEMARKETCAP.CURRENCY": "GBP",
            "TR.COMPANYMARKETCAP.DATE": "2026-02-13", "TR.ISSUEMARKETCAP.DATE": "2026-02-13",
        }
        identity = check_market_identity("DEMO.L", [row], "GB0000000000")
        self.assertEqual(valuation_route(identity), "residual_income")
        _, close, currency, price = market_observation(identity, datetime.fromisoformat("2026-02-14T15:00:00Z"))
        self.assertEqual(currency, "GBP")
        self.assertEqual(price, 5.5)
        self.assertEqual(close.hour, 16)
        with self.assertRaisesRegex(ValueError, "identifier mismatch"):
            check_market_identity("DEMO.L", [row], "GB1111111111")
