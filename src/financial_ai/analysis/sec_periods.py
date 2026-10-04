"""Conservative annual USD facts mapping; never mix periods or guess missing tags."""

from datetime import date
from typing import Any

from financial_ai.analysis.fundamentals import FinancialPeriod, StatementValue

TAGS = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "gross_profit": ("GrossProfit",),
    "net_income": ("NetIncomeLoss",),
    "operating_income": ("OperatingIncomeLoss",),
    "equity": ("StockholdersEquity",),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "stock_compensation": ("ShareBasedCompensation",),
}


def financial_periods(facts):
    annual = [f for f in facts if f["unit"] == "USD" and f["form"] in {"10-K", "10-K/A"}]
    duration = [
        f
        for f in annual
        if f.get("period_start")
        and 330
        <= (date.fromisoformat(f["period_end"]) - date.fromisoformat(f["period_start"])).days
        <= 380
    ]
    ends = sorted({f["period_end"] for f in duration if f["tag"] in TAGS["revenue"]})[-3:]
    periods = []
    for end in ends:
        fields: dict[str, Any] = {}
        for name, tags in TAGS.items():
            pool = (
                annual if name in {"equity", "current_assets", "current_liabilities"} else duration
            )
            # Instant balance-sheet facts must not be duration observations.
            matches = [
                f
                for f in pool
                if f["period_end"] == end
                and f["tag"] in tags
                and (pool is duration or not f.get("period_start"))
            ]
            if matches:
                preferred = min(tags.index(f["tag"]) for f in matches)
                chosen = max(
                    (f for f in matches if tags.index(f["tag"]) == preferred),
                    key=lambda f: f["filed_at"],
                )
                fields[name] = StatementValue(float(chosen["value"]), "usd")
        periods.append(FinancialPeriod(end, **fields))
    return periods
