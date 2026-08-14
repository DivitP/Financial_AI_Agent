"""SEC submissions and company-facts normalization; callers supply HTTP payloads."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import json
from typing import Any, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from financial_ai.data.http import HttpRequest, SharedHttpClient


SUPPORTED_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "8-K", "8-K/A", "4", "4/A"}


class SecCompany(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ticker: str
    cik: str = Field(pattern=r"^\d{10}$")
    name: str


class SecFilingMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    accession_number: str
    cik: str = Field(pattern=r"^\d{10}$")
    form: str
    filed_at: datetime
    accepted_at: datetime | None = None
    report_date: str | None = None
    primary_document: str
    url: str


class SecXbrlFact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    instrument_id: UUID
    accession_number: str
    taxonomy: str
    tag: str
    statement: str
    unit: str
    value: Decimal
    period_start: str | None = None
    period_end: str
    filed_at: datetime
    accepted_at: datetime | None = None
    form: str
    frame: str | None = None

    @property
    def identity(self) -> tuple[str, str, str, str, str]:
        """Includes accession/filing identity so restatements are never overwritten."""

        return (self.accession_number, self.taxonomy, self.tag, self.unit, self.period_end)


class SecFilingCollector:
    def __init__(self, http: SharedHttpClient | None = None) -> None:
        self.http = http

    def companies(
        self, ticker_payload: list[Mapping[str, Any]] | Mapping[str, Mapping[str, Any]]
    ) -> dict[str, SecCompany]:
        records = ticker_payload.values() if isinstance(ticker_payload, Mapping) else ticker_payload
        return {
            str(item["ticker"]).upper(): SecCompany(
                ticker=str(item["ticker"]).upper(),
                cik=f"{int(item['cik_str']):010d}",
                name=str(item["title"]),
            )
            for item in records
        }

    def collect_filings(self, ticker: str) -> list[SecFilingMetadata]:
        """Fetch SEC submissions through the shared client; no key is required."""

        if self.http is None:
            raise RuntimeError(
                "SEC collector requires a configured SharedHttpClient for live collection"
            )
        companies = self.companies(
            _json_object(
                self.http.fetch(
                    HttpRequest("sec", "https://www.sec.gov/files/company_tickers.json")
                )
            )
        )
        company = companies.get(ticker.upper())
        if company is None:
            return []
        submissions = _json_object(
            self.http.fetch(
                HttpRequest("sec", f"https://data.sec.gov/submissions/CIK{company.cik}.json")
            )
        )
        return self.filings(company.cik, submissions)

    def collect_xbrl_facts(
        self,
        instrument_id: UUID,
        cik: str,
        accepted_by_accession: Mapping[str, datetime] | None = None,
    ) -> list[SecXbrlFact]:
        if self.http is None:
            raise RuntimeError(
                "SEC collector requires a configured SharedHttpClient for live collection"
            )
        payload = _json_object(
            self.http.fetch(
                HttpRequest("sec", f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
            )
        )
        return self.xbrl_facts(instrument_id, payload, accepted_by_accession)

    def filings(self, cik: str, submissions: Mapping[str, Any]) -> list[SecFilingMetadata]:
        recent = submissions.get("filings", {}).get("recent", submissions.get("recent", {}))
        accepted = dict(
            zip(
                recent.get("accessionNumber", []),
                recent.get("acceptanceDateTime", []),
                strict=False,
            )
        )
        records: list[SecFilingMetadata] = []
        for index, form in enumerate(recent.get("form", [])):
            if form not in SUPPORTED_FORMS:
                continue
            accession = str(recent["accessionNumber"][index])
            primary_document = str(recent.get("primaryDocument", [""])[index])
            filed_at = _date_to_datetime(str(recent["filingDate"][index]))
            records.append(
                SecFilingMetadata(
                    accession_number=accession,
                    cik=cik,
                    form=form,
                    filed_at=filed_at,
                    accepted_at=_accepted(accepted.get(accession)),
                    report_date=_at(recent, "reportDate", index),
                    primary_document=primary_document,
                    url=sec_document_url(cik, accession, primary_document),
                )
            )
        return records

    def xbrl_facts(
        self,
        instrument_id: UUID,
        company_facts: Mapping[str, Any],
        accepted_by_accession: Mapping[str, datetime] | None = None,
    ) -> list[SecXbrlFact]:
        facts: list[SecXbrlFact] = []
        for taxonomy, concepts in company_facts.get("facts", {}).items():
            for tag, concept in concepts.items():
                statement = _statement_for_tag(tag)
                if statement is None:
                    continue
                for unit, entries in concept.get("units", {}).items():
                    for entry in entries:
                        if entry.get("form") not in {"10-K", "10-K/A", "10-Q", "10-Q/A"}:
                            continue
                        accession = str(entry["accn"])
                        facts.append(
                            SecXbrlFact(
                                instrument_id=instrument_id,
                                accession_number=accession,
                                taxonomy=taxonomy,
                                tag=tag,
                                statement=statement,
                                unit=unit,
                                value=Decimal(str(entry["val"])),
                                period_start=entry.get("start"),
                                period_end=str(entry["end"]),
                                filed_at=_date_to_datetime(str(entry["filed"])),
                                accepted_at=(accepted_by_accession or {}).get(accession),
                                form=str(entry["form"]),
                                frame=entry.get("frame"),
                            )
                        )
        return facts


def sec_document_url(cik: str, accession_number: str, primary_document: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_number.replace('-', '')}/{primary_document}"


def _statement_for_tag(tag: str) -> str | None:
    if tag in {"Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "NetIncomeLoss"}:
        return "income_statement"
    if tag in {"Assets", "Liabilities", "StockholdersEquity"}:
        return "balance_sheet"
    if tag in {
        "NetCashProvidedByUsedInOperatingActivities",
        "PaymentsToAcquirePropertyPlantAndEquipment",
    }:
        return "cash_flow_statement"
    return None


def _date_to_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=UTC)


def _accepted(value: str | None) -> datetime | None:
    return _date_to_datetime(value) if value else None


def _at(values: Mapping[str, Any], key: str, index: int) -> str | None:
    items = values.get(key, [])
    return str(items[index]) if index < len(items) and items[index] else None


def _json_object(response) -> Mapping[str, Any]:
    payload = json.loads(response.body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("SEC response must be a JSON object")
    return payload
