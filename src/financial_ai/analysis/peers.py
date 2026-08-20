"""Configurable peer-universe construction and comparable-company percentiles."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PeerCompany:
    symbol: str
    name: str
    sector: str
    industry: str
    metrics: dict[str, float]


@dataclass(frozen=True)
class PeerUniverse:
    selection_rule: str
    default_symbols: tuple[str, ...]
    add_symbols: tuple[str, ...] = ()
    remove_symbols: tuple[str, ...] = ()

    def symbols(self) -> tuple[str, ...]:
        removed = {symbol.upper() for symbol in self.remove_symbols}
        ordered = [*self.default_symbols, *self.add_symbols]
        return tuple(
            dict.fromkeys(symbol.upper() for symbol in ordered if symbol.upper() not in removed)
        )


@dataclass(frozen=True)
class ComparableResult:
    symbol: str
    metric: str
    value: float | None
    percentile: float | None
    peer_count: int


def compare_company(
    target: PeerCompany, peers: list[PeerCompany], metrics: tuple[str, ...]
) -> list[ComparableResult]:
    """Percentile is the share of valid peer observations at or below the target."""
    results: list[ComparableResult] = []
    for metric in metrics:
        value = target.metrics.get(metric)
        values = sorted(peer.metrics[metric] for peer in peers if metric in peer.metrics)
        percentile = (
            sum(candidate <= value for candidate in values) / len(values)
            if value is not None and values
            else None
        )
        results.append(ComparableResult(target.symbol, metric, value, percentile, len(values)))
    return results
