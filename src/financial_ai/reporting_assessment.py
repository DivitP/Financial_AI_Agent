"""Readable assessment with calculation inputs and exact source references."""

from __future__ import annotations

import html

from financial_ai.analysis.research_assessment import assess, measure, ValuationAssumptions
from financial_ai.providers.financial_history import Fact
from financial_ai.providers.legacy_live import finite


def render_assessment(history, quote, profile, artifacts, assumptions=None, *, now=None):
    from financial_ai.reporting_legacy import text

    assumptions = assumptions or ValuationAssumptions()
    assessment = assess(history, quote, profile, assumptions, now=now)
    references: dict[tuple, tuple[int, Fact]] = {}

    def cite(facts):
        links = []
        for fact in facts:
            key = (fact.evidence_id, fact.locator, fact.start, fact.end, fact.accession)
            if key not in references:
                references[key] = (len(references) + 1, fact)
            number = references[key][0]
            link = f"[{number}]({fact.url})"
            if link not in links:
                links.append(link)
        return " ".join(links)

    def amount(value, unit=None):
        if value is None:
            return "Unavailable"
        currency = unit or history.currency
        magnitude = abs(value)
        divisor, suffix = (
            (1e12, "T")
            if magnitude >= 1e12
            else (1e9, "B")
            if magnitude >= 1e9
            else (1e6, "M")
            if magnitude >= 1e6
            else (1, "")
        )
        return f"{currency} {value / divisor:,.2f}{suffix}"

    lines = [
        f"### Business trajectory: {assessment.trajectory}",
        "",
        f"**Comparison:** {assessment.comparison}. Financial source: **{text(history.provider)}**. "
        "This describes observed business performance, not a buy/sell rating.",
        "",
    ]
    if history.issuer_id:
        lines += [
            f"Issuer resolved: **{text(history.issuer)}**, SEC CIK `{history.issuer_id}`. "
            "Financials are consolidated at issuer level; the requested share-class quote is retained.",
            "",
        ]
    for title, insights in (
        ("What supports the thesis", assessment.positive),
        ("What challenges the thesis", assessment.negative),
        ("What explains the numbers", assessment.observations),
    ):
        lines += [f"### {title}", ""]
        if not insights:
            lines += ["No supported conclusion from the comparable records collected.", ""]
        else:
            lines += [f"- {text(item.text)} {cite(item.facts)}" for item in insights]
            lines.append("")

    def trends(windows, title):
        if not windows:
            return [f"### {title}", "", "Comparable periods unavailable.", ""]
        output = [
            f"### {title}",
            "",
            "Values retain their reporting currency; M = million, B = billion, T = trillion. "
            "FCF is calculated as operating cash flow minus the magnitude of capital expenditure.",
            "",
            "| Metric | " + " | ".join(f"{w.kind} {w.end}" for w in windows) + " |",
            "| --- | " + " | ".join("---:" for _ in windows) + " |",
        ]
        for key, label in (
            ("revenue", "Revenue"),
            ("operating_margin", "Operating margin"),
            ("net_income", "Net income"),
            ("ocf", "Operating cash flow"),
            ("capex", "Capital expenditure (magnitude)"),
            ("fcf", "Free cash flow (calculated)"),
            ("fcf_margin", "Free cash flow / revenue"),
            ("sbc_revenue", "Stock compensation / revenue"),
            ("shares", "Weighted-average diluted shares"),
        ):
            cells = []
            for window in windows:
                value = measure(window, key)
                if value is None:
                    cells.append("Unavailable")
                    continue
                shown = (
                    f"{value.value:.1%}"
                    if value.unit == "fraction"
                    else amount(
                        abs(value.value) if key == "capex" else value.value,
                        "shares" if key == "shares" else None,
                    )
                )
                cells.append(f"{shown} {cite(value.facts)}")
            output.append(f"| {label} | " + " | ".join(cells) + " |")
        output += [
            "",
            "Period starts: "
            + "; ".join(f"{w.end}: {w.start or 'not supplied'}" for w in windows)
            + ". "
            "Filing dates and original observation units are retained in the evidence details.",
            "",
        ]
        return output

    lines += trends(history.annual, "Business performance across reporting periods")
    if history.interim:
        lines += trends(history.interim, "Latest year-to-date comparison")
    balances = history.interim or history.annual
    if balances:
        latest = balances[-1]
        lines += [
            f"### Balance-sheet context as of {latest.end}",
            "",
            "| Reported balance | Value |",
            "| --- | ---: |",
        ]
        for key, label in (
            ("cash", "Cash and equivalents"),
            ("debt_noncurrent", "Noncurrent debt"),
            ("assets", "Total assets"),
            ("liabilities", "Total liabilities"),
        ):
            value = measure(latest, key)
            lines += [
                f"| {label} | "
                + (f"{amount(value.value)} {cite(value.facts)}" if value else "Unavailable")
                + " |"
            ]
        lines += [
            "",
            "Cash excludes marketable securities; noncurrent debt is not total debt. "
            "These balances do not establish net cash or refinancing capacity without complete debt maturities and liquidity data.",
            "",
        ]
    basis = assessment.basis
    if basis:
        lines += [
            "### What the market valuation implies",
            "",
            f"**Financial baseline:** {basis.kind} ending {basis.end}. "
            + (
                "TTM = last full fiscal year + current YTD − prior matching YTD. "
                if basis.kind == "TTM"
                else ""
            )
            + "These are reported earnings, not normalized earnings or analyst consensus.",
            "",
        ]
    market_refs = ""
    if assessment.market_cap is not None:
        market = assessment.market_source
        q = quote.data[0] if quote.data else {}
        source_name = "quote" if finite(q.get("marketCap"), positive=True) else "profile"
        fact = Fact(
            assessment.market_cap,
            history.currency,
            "observation time not supplied",
            None,
            None,
            market["url"],
            artifacts[source_name],
            "marketCap",
        )
        market_refs = cite((fact,))
        lines += [
            f"Provider-reported issuer market capitalization: **{amount(assessment.market_cap)}** {market_refs}. "
            f"Market-cap source retrieved {market['retrieved_at']}; its observation time is not guaranteed by the dated quote.",
            "",
        ]
    if assessment.valuation:
        lines += ["| Calculated valuation | Value |", "| --- | ---: |"]
        labels = {
            "price_to_earnings": "Market cap / reported net income",
            "price_to_sales": "Market cap / revenue",
            "price_to_fcf": "Market cap / free cash flow",
            "fcf_yield": "Free cash flow / market cap",
        }
        for name, value in assessment.valuation.items():
            shown = f"{value.value:.1%}" if value.unit == "fraction" else f"{value.value:.2f}x"
            lines += [f"| {labels[name]} | {shown} {cite(value.facts)} {market_refs} |"]
        lines += [
            "",
            "A multiple alone does not establish cheapness. Peer-relative and historical valuation "
            "comparisons have not been established from like-for-like data.",
            "",
        ]
    if assessment.implied_growth is not None:
        earnings = assessment.metrics["basis_net_income"]
        inputs = cite(earnings.facts) + " " + market_refs
        lines += [
            f"**Expectations hurdle:** to reach **{assumptions.target_equity_growth_pct:g}% annual issuer equity-value growth** "
            f"over **{assumptions.years} years**, with an exit P/E of **{assumptions.exit_multiple:g}x**, "
            f"reported net income would need to grow approximately **{assessment.implied_growth:.1%} annually**. {inputs}",
            "",
            "This is a reverse calculation from your assumptions, not a forecast or a required personal return. "
            "It excludes dividends and changes in share count, debt structure, accounting quality and class-specific rights.",
            "",
            "### Bear / base / bull: transparent illustrations",
            "",
            "**Assumptions, not probabilities or price targets.** Base earnings growth is "
            f"{assumptions.earnings_growth_pct:g}% per year; bear/bull vary it by −10/+10 percentage points. "
            "Exit P/E varies by −5/+5 turns around the selected base multiple. "
            "No assumption is calibrated to this issuer's historical valuation. "
            "You can change the base assumptions above and regenerate the report.",
            "",
            "| Illustration | Earnings growth / year | Exit P/E | Terminal issuer equity value | Change vs snapshot cap | Annualized value change |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for scenario in assessment.scenarios:
            lines += [
                f"| {scenario['name']} | {scenario['growth']:.1%} | {scenario['multiple']:.1f}x | "
                f"{amount(scenario['terminal'])} | {scenario['change']:+.1%} | {scenario['annualized']:+.1%} |"
            ]
        lines += [
            "",
            f"All scenario calculations use the same earnings and market-cap evidence: {inputs}.",
            "",
            "### Sensitivity: separate growth from valuation",
            "",
            "Terminal issuer equity values, holding other assumptions constant:",
            "",
            f"| Annual earnings growth | Exit {assumptions.exit_multiple - 5:g}x | Exit {assumptions.exit_multiple:g}x | Exit {assumptions.exit_multiple + 5:g}x |",
            "| --- | ---: | ---: | ---: |",
        ]
        for row in assessment.sensitivity:
            lines += [
                f"| {row['growth']:.1%} | " + " | ".join(amount(v) for v in row["values"]) + " |"
            ]
        lines += [
            "",
            f"Calculated inputs: {inputs}. Changes in valuation can offset earnings growth.",
            "",
        ]
    elif not assessment.scenarios:
        lines += [
            "Scenario valuation is unavailable for this coverage/asset/baseline. No terminal values have been fabricated.",
            "",
        ]
    lines += ["### What would change this assessment", ""]
    lines += [f"- {text(item.text)} {cite(item.facts)}" for item in assessment.monitor]
    lines += [
        "- Check management's next reported guidance and actual segment results in the original filing. "
        "No management guidance or future earnings date has been verified by this report.",
        "",
    ]
    if history.filings:
        lines += ["### Recent original filings", ""]
        lines += [
            f"- [{text(f['form'])}, filed {text(f['filed'])}]({f['url']})" for f in history.filings
        ]
        lines.append("")
    lines += ["### Evidence coverage and model limits", ""]
    lines += [f"- {text(note)}" for note in dict.fromkeys(history.notices + assessment.limitations)]
    lines += [
        "- Business trajectory is a rule-based description of comparable revenue, operating margin and cash-flow changes. "
        "It is not a calibrated prediction. Operating cash flow and capex do not capture every economic cost or financing obligation.",
        "",
    ]
    if references:
        lines += ["<details><summary>Evidence and calculation inputs</summary><ol>"]
        for number, fact in references.values():
            lines += [
                f'<li><a href="{html.escape(fact.url, quote=True)}">[{number}] {html.escape(fact.locator)}</a>: '
                f"{fact.value:,.4f} {html.escape(fact.unit)}; period {html.escape(fact.start or 'instant/start unavailable')} "
                f"to {html.escape(fact.end)}; filed {html.escape(fact.filed or 'unavailable')}; "
                f"accession {html.escape(fact.accession or 'not supplied')}; evidence "
                f"<code>{html.escape(fact.evidence_id)}</code>.</li>"
            ]
        lines += ["</ol></details>"]
    return "\n".join(lines)
