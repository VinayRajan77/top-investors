"""Public SEC Form 13F importer. No paid financial-data provider is used."""
import asyncio
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

async def sec_get(client, url):
    # Globally space every request across parallel investors below SEC's 10/s cap.
    global _last_request
    async with _rate_lock:
        now = asyncio.get_running_loop().time()
        await asyncio.sleep(max(0, .125 - (now - _last_request)))
        _last_request = asyncio.get_running_loop().time()
    response = await client.get(url, headers=HEADERS, timeout=30)
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
    """Return five recent original 13F reports, including archived submission files."""
    submission = (await sec_get(client, f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json")).json()
    groups = [submission.get("filings", {}).get("recent", {})]
    for archive in submission.get("filings", {}).get("files", []):
        archived = (await sec_get(client, f"https://data.sec.gov/submissions/{archive['name']}")).json()
        groups.append(archived.get("filings", {}).get("recent", archived))
    records = []
    for group in groups:
        for i, form in enumerate(group.get("form", [])):
            if form == "13F-HR": records.append({"accession":group["accessionNumber"][i], "date":date.fromisoformat(group["filingDate"][i])})
    return sorted({item["accession"]:item for item in records}.values(), key=lambda item:item["date"], reverse=True)[:5]

async def information_table(client, cik, accession):
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}"
    files = (await sec_get(client, f"{base}/index.json")).json().get("directory", {}).get("item", [])
    names = [file["name"] for file in files]
    candidates = [name for name in names if "infotable" in name.lower() or "informationtable" in name.lower()]
    candidates += [name for name in names if name.lower().endswith(".xml") and name not in candidates]
    for filename in candidates:
        contents = (await sec_get(client, f"{base}/{filename}")).text
        if "infoTable" in contents or "informationTable" in contents: return contents
    return None

def reported_value(raw_value, filing_date):
    # Modern 13F XML reports dollars. Legacy reports before 2023 used thousands.
    return raw_value * 1000 if filing_date.year < 2023 else raw_value

async def import_filing(client, investor, record, ticker_by_name):
    xml = await information_table(client, investor.cik, record["accession"])
    if not xml: return False
    grouped = {}
    for node in ET.fromstring(xml).iter():
        if local_name(node.tag) != "infoTable": continue
        company, cusip = text_of(node,"nameOfIssuer"), text_of(node,"cusip")
        shares = float(text_of(node,"sshPrnamt") or 0)
        value = reported_value(float(text_of(node,"value") or 0), record["date"])
        if company and value:
            key = cusip or company  # Combine split reporting-manager rows.
            old = grouped.get(key, (company, cusip, 0, 0))
            grouped[key] = (company, cusip, old[2] + shares, old[3] + value)
    if not grouped: return False
    total = sum(row[3] for row in grouped.values())
    with SessionLocal() as db:
        if db.scalar(select(PortfolioSnapshot).where(PortfolioSnapshot.source_accession_number == record["accession"])): return True
        snapshot = PortfolioSnapshot(investor_id=investor.id, filing_date=record["date"], quarter=f"{record['date'].year} Q{(record['date'].month-1)//3+1}", total_value=total, source_accession_number=record["accession"])
        db.add(snapshot); db.flush()
        for company, cusip, shares, value in grouped.values():
            ticker = CUSIP_TICKERS.get(cusip) or ticker_by_name.get(normalize_issuer(company))
            # 13F contains quarter-end market value, not trade execution price.
            # Retain an explicit filing-price proxy only where shares are reported.
            filing_price = value / shares if shares else None
            db.add(Holding(snapshot_id=snapshot.id, ticker=ticker, cusip=cusip or None, company_name=company, shares=shares, market_value=value, estimated_purchase_price=filing_price, pct_of_portfolio=value / total * 100))
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
        semaphore = asyncio.Semaphore(3)
        async def refresh_investor(investor):
            try:
                async with semaphore:
                    for record in await filing_records(client, investor.cik): await import_filing(client, investor, record, titles)
                    calculate_performance(investor.id)
            except Exception as exc: print(f"SEC refresh failed for {investor.slug}: {exc}")
        await asyncio.gather(*(refresh_investor(investor) for investor in investors))
