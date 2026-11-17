"""Read frozen primary-source observations without network access."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import math
from pathlib import Path
import re
from statistics import covariance, variance
from xml.etree import ElementTree as ET


XBRL = "{http://www.xbrl.org/2003/instance}"
INLINE = "{http://www.xbrl.org/2013/inlineXBRL}"


def frozen_bytes(path, expected_sha256):
    raw = Path(path).read_bytes()
    if sha256(raw).hexdigest() != expected_sha256:
        raise ValueError(f"Snapshot hash differs: {Path(path).name}")
    return raw


def _xbrl_number(node):
    text = "".join(node.itertext()).strip()
    format_name = node.get("format", "").split(":")[-1]
    if format_name in {"fixed-zero", "zerodash"}:
        return Decimal(0)
    if format_name not in {"", "num-dot-decimal", "numdotdecimal"}:
        raise ValueError(f"Unsupported Inline XBRL transform: {format_name}")
    try:
        value = Decimal(text.replace(",", "").replace(" ", "")).scaleb(int(node.get("scale", "0")))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid Inline XBRL number: {node.get('id')}") from exc
    if not value.is_finite() or value < 0 or node.get("sign") not in {None, "-"}:
        raise ValueError(f"Invalid Inline XBRL signed value: {node.get('id')}")
    return -value if node.get("sign") == "-" else value


class Filing:
    """Exact fact selectors for consolidated US GAAP Inline XBRL filings."""

    def __init__(self, raw, *, cik):
        if re.search(rb"<!\s*(DOCTYPE|ENTITY)\b", raw, re.IGNORECASE):
            raise ValueError("XML declarations for document types and entities are unsupported")
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ValueError("Expected well-formed Inline XBRL XHTML") from exc
        self.contexts = {}
        for node in root.iter(XBRL + "context"):
            entity = node.find(XBRL + "entity")
            period = node.find(XBRL + "period")
            identifier = entity.find(XBRL + "identifier") if entity is not None else None
            if (identifier is None or identifier.get("scheme") != "http://www.sec.gov/CIK"
                    or identifier.text != cik or period is None
                    or len(entity) != 1 or node.find(XBRL + "scenario") is not None):
                continue
            self.contexts[node.get("id")] = (
                period.findtext(XBRL + "startDate"),
                period.findtext(XBRL + "instant") or period.findtext(XBRL + "endDate"),
            )
        if not self.contexts:
            raise ValueError("No consolidated contexts for the specified SEC CIK")
        self.units = {
            node.get("id"): tuple(part.text for part in node.iter(XBRL + "measure"))
            for node in root.iter(XBRL + "unit")
        }
        self.facts = list(root.iter(INLINE + "nonFraction"))
        self.cover = {}
        for node in root.iter(INLINE + "nonNumeric"):
            if node.get("contextRef") in self.contexts:
                self.cover.setdefault(node.get("name"), set()).add(" ".join("".join(node.itertext()).split()))

    def fact(self, concept, *, end, start=None, unit="iso4217:USD"):
        matches = [
            node for node in self.facts
            if node.get("name") == concept
            and self.contexts.get(node.get("contextRef")) == (start, end)
            and self.units.get(node.get("unitRef")) == tuple(unit.split("/"))
        ]
        if not matches:
            raise ValueError(f"No consolidated {concept} for [{start}, {end}] in {unit}")
        observations = [
            (_xbrl_number(node), Decimal(node.get("decimals", "0").replace("INF", "Infinity")))
            for node in matches
        ]
        value, precision = max(observations, key=lambda item: item[1])
        for other, decimals in observations:
            tolerance = Decimal("0.5").scaleb(-int(decimals)) if decimals < precision else Decimal(0)
            if abs(value - other) > tolerance:
                raise ValueError(f"Conflicting values for {concept} at {end}; reconcile the tagged disclosures")
        return {
            "concept": concept, "start": start, "end": end, "unit": unit,
            "raw_value": str(value),
            "tags": [{"id": node.get("id"), "context": node.get("contextRef"), "decimals": node.get("decimals")} for node in matches],
        }


def nasdaq_closes(snapshot, symbol, as_of):
    data = snapshot.get("data")
    if (snapshot.get("status", {}).get("rCode") != 200
            or not isinstance(data, dict) or data.get("symbol", "").upper() != symbol.upper()):
        raise ValueError(f"Nasdaq snapshot does not identify {symbol}")
    closes = {}
    rows = data.get("tradesTable", {}).get("rows", [])
    if not rows or len(rows) != data.get("totalRecords"):
        raise ValueError(f"Nasdaq history for {symbol} is empty or truncated")
    for row in rows:
        day = datetime.strptime(row["date"], "%m/%d/%Y").date()
        price = float(row["close"].replace("$", "").replace(",", ""))
        if day in closes or day > as_of or price <= 0 or not math.isfinite(price):
            raise ValueError(f"Invalid or duplicate Nasdaq close for {symbol} on {day}")
        closes[day] = price
    if as_of not in closes:
        raise ValueError(f"Closing price missing for {symbol} on {as_of}")
    return closes


def price_return_beta(stock: dict[date, float], benchmark: dict[date, float], minimum=60):
    if stock.keys() != benchmark.keys() or len(stock) - 1 < minimum:
        raise ValueError("Beta requires matched sessions and enough returns")
    dates = sorted(stock)
    x = [benchmark[b] / benchmark[a] - 1 for a, b in zip(dates, dates[1:])]
    y = [stock[b] / stock[a] - 1 for a, b in zip(dates, dates[1:])]
    benchmark_variance = variance(x)
    if not benchmark_variance:
        raise ValueError("Benchmark returns have zero variance")
    return {
        "beta": covariance(x, y) / benchmark_variance,
        "observations": len(x),
        "first_close": dates[0].isoformat(), "last_close": dates[-1].isoformat(),
        "method": "OLS with intercept, matched daily close-to-close price returns",
    }
