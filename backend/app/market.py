"""Public-price and SEC-XBRL enrichment for the local research experience."""
import asyncio
import csv
from io import StringIO
from datetime import datetime, timezone
import httpx
from .config import settings

SEC_HEADERS = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}
_ticker_index: dict[str, dict] = {}
_ticker_index_loaded_at = 0.0
_sec_request_lock = asyncio.Lock()
_last_sec_request_at = 0.0


async def sec_get(client: httpx.AsyncClient, url: str):
    """Make a politely paced request to the public SEC data APIs."""
    global _last_sec_request_at
    async with _sec_request_lock:
        delay = 0.125 - (datetime.now(timezone.utc).timestamp() - _last_sec_request_at)
        if delay > 0:
            await asyncio.sleep(delay)
        response = await client.get(url, headers=SEC_HEADERS)
        _last_sec_request_at = datetime.now(timezone.utc).timestamp()
    response.raise_for_status()
    return response

async def ticker_index(client: httpx.AsyncClient):
    """Refresh the SEC-published ticker/CIK map at most once per six hours."""
    global _ticker_index, _ticker_index_loaded_at
    now = datetime.now(timezone.utc).timestamp()
    if _ticker_index and now - _ticker_index_loaded_at < 21600: return _ticker_index
    response = await sec_get(client, "https://www.sec.gov/files/company_tickers.json")
    _ticker_index = {str(item.get("ticker", "")).upper(): item for item in response.json().values() if item.get("ticker")}
    _ticker_index_loaded_at = now
    return _ticker_index

def latest_fact(facts: dict, tags: list[str], units: str = "USD"):
    for tag in tags:
        # Share counts are reported in the SEC's DEI taxonomy; most accounting
        # statements live in US-GAAP. Check both instead of silently omitting a
        # valid public fact.
        for namespace in ("us-gaap", "dei"):
            entries = facts.get("facts", {}).get(namespace, {}).get(tag, {}).get("units", {}).get(units, [])
            valid = [entry for entry in entries if entry.get("form") in {"10-K", "10-Q", "20-F", "40-F"} and entry.get("val") is not None]
            if valid:
                value = max(valid, key=lambda entry: (entry.get("end", ""), entry.get("filed", "")))
                return {"value": value["val"], "period_end": value.get("end"), "filed": value.get("filed"), "form": value.get("form"), "tag": tag}
    return None

def quarterly_series(facts: dict, tags: list[str]):
    for tag in tags:
        entries = facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD", [])
        rows = [entry for entry in entries if entry.get("form") in {"10-Q", "10-K", "20-F", "40-F"} and entry.get("val") is not None and entry.get("end")]
        # Keep the latest reported value per period end and avoid duplicate amendments.
        unique = {}
        for row in rows:
            if row.get("fp") in {"Q1", "Q2", "Q3", "FY"}: unique[row["end"]] = row
        if unique: return [{"period_end":end, "value":row["val"], "form":row.get("form")} for end,row in sorted(unique.items())[-12:]]
    return []

async def company_overview(symbol: str):
    symbol = symbol.upper().replace(".", "-")
    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
        item = (await ticker_index(client)).get(symbol)
        if not item: raise ValueError("No SEC-listed company mapping was found for this symbol")
        cik = str(item["cik_str"]).zfill(10)
        submissions, facts = await asyncio.gather(
            sec_get(client, f"https://data.sec.gov/submissions/CIK{cik}.json"),
            sec_get(client, f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"),
        )
        profile, xbrl = submissions.json(), facts.json()
    revenue_tags = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]
    income_tags = ["NetIncomeLoss", "ProfitLoss"]
    metrics = {
        "revenue": latest_fact(xbrl, revenue_tags), "net_income": latest_fact(xbrl, income_tags),
        "assets": latest_fact(xbrl, ["Assets"]), "cash": latest_fact(xbrl, ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]),
        "liabilities": latest_fact(xbrl, ["Liabilities"]), "eps_diluted": latest_fact(xbrl, ["EarningsPerShareDiluted"], "USD/shares"),
        "shares_outstanding": latest_fact(xbrl, ["EntityCommonStockSharesOutstanding"], "shares"),
    }
    return {"symbol":symbol, "company_name":profile.get("name") or item.get("title"), "cik":cik, "exchange":(profile.get("exchanges") or [None])[0], "sic":profile.get("sic"), "sic_description":profile.get("sicDescription"), "metrics":metrics, "series":{"revenue":quarterly_series(xbrl, revenue_tags), "net_income":quarterly_series(xbrl, income_tags)}, "source":"SEC EDGAR submissions and Company Facts (XBRL)", "source_updated_at":datetime.now(timezone.utc).isoformat()}

async def quote_history(symbol: str):
    symbol = symbol.upper().replace(".", "-")
    if not symbol.replace("-", "").isalpha(): raise ValueError("Invalid symbol")
    url = f"https://stooq.com/q/d/l/?s={symbol.lower()}.us&i=d"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent":"TopInvestors local app"})
        rows = []
        for row in csv.DictReader(StringIO(response.text)):
            try: rows.append({"date":row["Date"], "close":float(row["Close"])})
            except (KeyError, TypeError, ValueError): continue
        source = "Stooq free end-of-day data"
        if not rows:
            # Public no-key fallback. It is used only if Stooq has no history for a symbol.
            response = await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=5y&interval=1d", headers={"User-Agent":"Mozilla/5.0"})
            response.raise_for_status()
            result = response.json().get("chart", {}).get("result", [None])[0] or {}
            timestamps, closes = result.get("timestamp", []), result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            rows = [{"date":datetime.fromtimestamp(ts, timezone.utc).date().isoformat(), "close":float(close)} for ts, close in zip(timestamps, closes) if close is not None]
            source = "Yahoo Finance public end-of-day data"
    if not rows: raise ValueError("No free end-of-day history was returned for this symbol")
    return {"symbol":symbol, "source":source, "latest":rows[-1], "range_52_week":{"low":min(row["close"] for row in rows[-252:]), "high":max(row["close"] for row in rows[-252:])}, "history":rows}
