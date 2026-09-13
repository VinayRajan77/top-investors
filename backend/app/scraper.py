"""Public SEC Form 13F importer. No paid financial-data provider is used."""
import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
import httpx
from sqlalchemy import desc, select
from .config import settings
from .models import Holding, Investor, PerformanceCache, PortfolioSnapshot, SessionLocal
from .seeds import SEED_INVESTORS

HEADERS = {"User-Agent": settings.sec_user_agent, "Accept-Encoding": "gzip, deflate"}
# SEC's free company_tickers.json does not provide CUSIPs. Unknown CUSIPs remain
# unlinked rather than being guessed; these are convenient verified common symbols.
CUSIP_TICKERS = {"037833100":"AAPL", "023135106":"AMZN", "02079K305":"GOOGL", "02079K107":"GOOG", "025816109":"AXP", "060505104":"BAC", "191216100":"KO", "594918104":"MSFT", "67066G104":"NVDA", "88160R101":"TSLA", "30303M102":"META", "478160104":"JNJ", "931142103":"WMT", "084670702":"BRK.B"}
_rate_lock = asyncio.Lock()
_last_request = 0.0
SEC_REQUEST_INTERVAL_SECONDS = 1.0
SEC_RETRY_ATTEMPTS = 5

async def sec_get(client, url):
    """Fetch SEC data slowly and back off when a shared cloud IP is throttled."""
    global _last_request
    async with _rate_lock:
        for attempt in range(SEC_RETRY_ATTEMPTS):
            now = asyncio.get_running_loop().time()
            await asyncio.sleep(max(0, SEC_REQUEST_INTERVAL_SECONDS - (now - _last_request)))
            response = await client.get(url, headers=HEADERS, timeout=30)
            _last_request = asyncio.get_running_loop().time()
            if response.status_code != 429:
                response.raise_for_status()
                return response
            retry_after = response.headers.get("Retry-After")
            try:
                delay = max(15.0, float(retry_after or 0))
            except ValueError:
                delay = 15.0
            print(f"SEC rate limit reached; retrying in {delay:.0f}s (attempt {attempt + 1}/{SEC_RETRY_ATTEMPTS}).")
            await asyncio.sleep(delay)
        response.raise_for_status()
        return response

def seed_investors():
    with SessionLocal() as db:
        for slug, name, fund, cik, categories in SEED_INVESTORS:
            item = db.scalar(select(Investor).where(Investor.slug == slug))
            if not item: db.add(Investor(slug=slug, name=name, fund_name=fund, cik=cik, category=categories))
            else: item.name, item.fund_name, item.cik, item.category = name, fund, cik, categories
        db.commit()

def local_name(tag): return tag.rsplit("}", 1)[-1]
def normalize_issuer(name):
    return "".join(character for character in name.upper() if character.isalnum())
def text_of(node, tag):
    for child in node.iter():
        if local_name(child.tag) == tag: return (child.text or "").strip()
    return ""

async def filing_records(client, cik):
    """Return the latest filing for each of five reported periods.

    SEC submissions list amendments beside the original report. Keeping every
    accession turns one quarter into several fake portfolio-history points, so
    we retain the newest filing for each report period instead.
    """
    submission = (await sec_get(client, f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json")).json()
    groups = [submission.get("filings", {}).get("recent", {})]
    for archive in submission.get("filings", {}).get("files", []):
        archived = (await sec_get(client, f"https://data.sec.gov/submissions/{archive['name']}")).json()
        groups.append(archived.get("filings", {}).get("recent", archived))
    records = []
    for group in groups:
        for i, form in enumerate(group.get("form", [])):
            if form.startswith("13F-HR"):
                filed = date.fromisoformat(group["filingDate"][i])
                report_date = group.get("reportDate", [None] * len(group["form"]))[i] or group["filingDate"][i]
                records.append({"accession":group["accessionNumber"][i], "filed":filed, "date":date.fromisoformat(report_date), "form":form})
    newest_by_period = {}
    for record in records:
        previous = newest_by_period.get(record["date"])
        if not previous or record["filed"] > previous["filed"]:
            newest_by_period[record["date"]] = record
    return sorted(newest_by_period.values(), key=lambda item:item["date"], reverse=True)[:5]

async def filing_files(client, cik, accession):
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
    files = (await sec_get(client, f"{base}/index.json")).json().get("directory", {}).get("item", [])
    return base, [file["name"] for file in files]

async def information_table(client, base, names):
    candidates = [name for name in names if "infotable" in name.lower() or "informationtable" in name.lower()]
    candidates += [name for name in names if name.lower().endswith(".xml") and name not in candidates]
    for filename in candidates:
        contents = (await sec_get(client, f"{base}/{filename}")).text
        if "infoTable" in contents or "informationTable" in contents: return contents
    return None

def summary_value_thousands(document):
    """Read Form 13F's authoritative summary total, which is in thousands."""
    try:
        root = ET.fromstring(document)
        for node in root.iter():
            if local_name(node.tag).lower() in {"tablevaluetotal", "informationtablevaluetotal"}:
                return float((node.text or "").replace(",", "").strip())
    except ET.ParseError:
        pass
    match = re.search(r"<tableValueTotal[^>]*>\s*([\d,.]+)", document, flags=re.I)
    return float(match.group(1).replace(",", "")) if match else None

async def filing_summary_total(client, base, names):
    primary = [name for name in names if name.lower().endswith((".xml", ".html", ".htm")) and "infotable" not in name.lower() and "informationtable" not in name.lower()]
    for filename in primary:
        total = summary_value_thousands((await sec_get(client, f"{base}/{filename}")).text)
        if total is not None:
            return total * 1000
    return None

def select_value_multiplier(raw_total, summary_total):
    """Normalize only when the filing total proves which scale is correct.

    Standard EDGAR 13F XML uses thousands. The additional candidates make the
    importer safe for a non-standard archived table without silently guessing.
    """
    if not summary_total or not raw_total:
        return 1000
    candidates = (1, 1000, 1_000_000)
    multiplier = min(candidates, key=lambda value: abs(raw_total * value - summary_total))
    discrepancy = abs(raw_total * multiplier - summary_total) / summary_total
    if discrepancy > 0.02:
        raise ValueError(f"Information-table total does not reconcile to the 13F summary ({discrepancy:.2%} difference).")
    return multiplier

async def import_filing(client, investor, record, ticker_by_name):
    # Most scheduled runs find no new 13F. Check the accession before touching
    # an archive document so the daily health check remains light on EDGAR.
    with SessionLocal() as db:
        existing = db.scalar(select(PortfolioSnapshot).where(PortfolioSnapshot.source_accession_number == record["accession"]))
        if existing:
            return True
    base, names = await filing_files(client, investor.cik, record["accession"])
    xml = await information_table(client, base, names)
    if not xml: return False
    summary_total = await filing_summary_total(client, base, names)
    grouped = {}
    for node in ET.fromstring(xml).iter():
        if local_name(node.tag) != "infoTable": continue
        company, cusip = text_of(node,"nameOfIssuer"), text_of(node,"cusip")
        shares = float(text_of(node,"sshPrnamt") or 0)
        value = float(text_of(node,"value") or 0)
        put_call = text_of(node, "putCall").upper() or None
        security_type = "option" if put_call in {"PUT", "CALL"} else "equity"
        if company and value:
            # Do not merge option contracts into the common-share position.
            key = (cusip or company, security_type, put_call)
            old = grouped.get(key, (company, cusip, security_type, put_call, 0, 0))
            grouped[key] = (company, cusip, security_type, put_call, old[4] + shares, old[5] + value)
    if not grouped: return False
    raw_total = sum(row[5] for row in grouped.values())
    multiplier = select_value_multiplier(raw_total, summary_total)
    total = raw_total * multiplier
    with SessionLocal() as db:
        snapshot = PortfolioSnapshot(investor_id=investor.id, filing_date=record["date"], quarter=f"{record['date'].year} Q{(record['date'].month-1)//3+1}", total_value=total, source_accession_number=record["accession"])
        db.add(snapshot); db.flush()
        for company, cusip, security_type, put_call, shares, raw_value in grouped.values():
            value = raw_value * multiplier
            ticker = CUSIP_TICKERS.get(cusip) or ticker_by_name.get(normalize_issuer(company))
            # 13F contains quarter-end market value, not trade execution price.
            # Retain an explicit filing-price proxy only where shares are reported.
            filing_price = value / shares if shares else None
            db.add(Holding(snapshot_id=snapshot.id, ticker=ticker, cusip=cusip or None, company_name=company, security_type=security_type, put_call=put_call, shares=shares, market_value=value, estimated_purchase_price=filing_price, pct_of_portfolio=value / total * 100))
        db.commit()
    return True

def calculate_performance(investor_id):
    with SessionLocal() as db:
        snapshots = db.scalars(select(PortfolioSnapshot).where(PortfolioSnapshot.investor_id == investor_id).order_by(desc(PortfolioSnapshot.filing_date))).all()
        if not snapshots: return
        # A "one-year" comparison is only meaningful when the reporting history
        # actually reaches back roughly a year. Do not substitute a random
        # quarter-over-quarter value and call it performance.
        latest = snapshots[0]
        target = latest.filing_date - timedelta(days=330)
        baseline = next((snapshot for snapshot in snapshots[1:] if snapshot.filing_date <= target), None)
        item = db.get(PerformanceCache, {"investor_id":investor_id,"period":"one_year_disclosed_value_change"})
        if not baseline or not float(baseline.total_value):
            if item: db.delete(item); db.commit()
            return
        # Approximation only: disclosed value change is not a true fund return.
        pct = (float(latest.total_value) / float(baseline.total_value) - 1) * 100
        if item: item.return_pct, item.calculated_at = pct, datetime.utcnow()
        else: db.add(PerformanceCache(investor_id=investor_id, period="one_year_disclosed_value_change", return_pct=pct))
        db.commit()

async def refresh_all():
    seed_investors()
    with SessionLocal() as db: investors = db.scalars(select(Investor)).all()
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # SEC's free catalogue lacks CUSIPs. Exact issuer-name matching augments
        # the curated CUSIP map; ambiguous names intentionally remain unlinked.
        try:
            catalogue = (await sec_get(client, "https://www.sec.gov/files/company_tickers.json")).json()
        except Exception as exc:
            # A catalogue outage must not stop valid 13F imports using CUSIP map.
            print(f"Ticker catalogue unavailable: {exc}")
            catalogue = {}
        titles = {}
        duplicates = set()
        for record in catalogue.values():
            key = normalize_issuer(record.get("title", ""))
            if key in titles: duplicates.add(key)
            else: titles[key] = record.get("ticker")
        titles = {key:value for key,value in titles.items() if key not in duplicates}
        # A sequential initial import is deliberate: shared cloud IP addresses
        # can be throttled even below the SEC's published request ceiling.
        semaphore = asyncio.Semaphore(1)
        async def refresh_investor(investor):
            try:
                async with semaphore:
                    records = await filing_records(client, investor.cik)
                    imported = 0
                    for record in records:
                        imported += int(bool(await import_filing(client, investor, record, titles)))
                    calculate_performance(investor.id)
                    return {"slug": investor.slug, "filings_found": len(records), "filings_imported": imported, "error": None}
            except Exception as exc:
                print(f"SEC refresh failed for {investor.slug}: {exc}")
                return {"slug": investor.slug, "filings_found": 0, "filings_imported": 0, "error": str(exc)}
        results = await asyncio.gather(*(refresh_investor(investor) for investor in investors))
    summary = {
        "managers_checked": len(results),
        "filings_found": sum(result["filings_found"] for result in results),
        "filings_imported": sum(result["filings_imported"] for result in results),
        "failures": [{"slug": result["slug"], "error": result["error"]} for result in results if result["error"]],
    }
    if not summary["filings_found"]:
        raise RuntimeError("The SEC importer found no 13F filing records; inspect the service logs for manager-level errors.")
    return summary
