import asyncio, json
from contextlib import asynccontextmanager
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from sqlalchemy import delete, desc, select, text
from sqlalchemy.orm import Session
from .config import settings
from .models import AppState, Base, Holding, Investor, PerformanceCache, PortfolioSnapshot, SessionLocal, engine
from .market import company_overview, quote_history
from .scraper import refresh_all, seed_investors

cache = Redis.from_url(settings.redis_url, decode_responses=True)
scheduler = AsyncIOScheduler()
refresh_state = {"running": False, "last_started": None, "last_finished": None, "last_error": None, "last_import": None}
def db_session():
    db = SessionLocal()
    try: yield db
    finally: db.close()
def money(v): return float(v or 0)
async def run_refresh():
    """Run one import at a time and invalidate every derived card afterwards."""
    if refresh_state["running"]: return False
    refresh_state.update(running=True, last_started=datetime.utcnow().isoformat(), last_error=None)
    try:
        refresh_state["last_import"] = await refresh_all()
        cache.flushdb()
    except Exception as exc:
        refresh_state["last_error"] = str(exc)
        raise
    finally:
        refresh_state.update(running=False, last_finished=datetime.utcnow().isoformat())
    return True
def investor_card(db, investor):
    snapshot = db.scalar(select(PortfolioSnapshot).where(PortfolioSnapshot.investor_id == investor.id).order_by(desc(PortfolioSnapshot.filing_date)))
    perf = db.get(PerformanceCache, {"investor_id": investor.id, "period": "one_year_disclosed_value_change"})
    holdings = [] if not snapshot else db.scalars(select(Holding).where(Holding.snapshot_id == snapshot.id).order_by(desc(Holding.market_value)).limit(3)).all()
    return {"slug":investor.slug,"name":investor.name,"fund_name":investor.fund_name,"categories":investor.category,
      "performance": None if not perf else perf.return_pct,"total_value":0 if not snapshot else money(snapshot.total_value),
      "holdings":[{"ticker":h.ticker,"company_name":h.company_name} for h in holdings], "holding_count":0 if not snapshot else len(snapshot.holdings),
      "filing_date": None if not snapshot else snapshot.filing_date.isoformat(), "data_status":"available" if snapshot else "not_imported"}
def migrate_import_data():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE holdings ADD COLUMN IF NOT EXISTS cusip VARCHAR(20)"))
    with SessionLocal() as db:
        version = db.get(AppState, "sec_import_format")
        if not version or version.value != "3":
            # Version 1 multiplied modern SEC values by 1,000 and stored invalid data.
            db.execute(delete(Holding)); db.execute(delete(PortfolioSnapshot)); db.execute(delete(PerformanceCache))
            db.merge(AppState(key="sec_import_format", value="3")); db.commit()
@asynccontextmanager
async def lifespan(app):
    migrate_import_data(); seed_investors()
    # Ensure the frontend never receives cached cards from a prior import format.
    cache.flushdb()
    scheduler.add_job(run_refresh, "interval", hours=24, id="sec-refresh", replace_existing=True); scheduler.start()
    asyncio.create_task(run_refresh())
    yield
    scheduler.shutdown(wait=False)
app = FastAPI(title="Top Investors", lifespan=lifespan)
# The web app runs separately on localhost:3000 during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
@app.get("/api/health")
def health(db: Session = Depends(db_session)):
    return {"status":"ok", "refresh": refresh_state, "investor_count": len(db.scalars(select(Investor)).all()), "snapshot_count": len(db.scalars(select(PortfolioSnapshot)).all())}
@app.get("/api/investors")
def investors(sort: str = Query("popular"), limit: int = Query(50, le=100), db: Session = Depends(db_session)):
    key=f"investors:{sort}:{limit}"; saved=cache.get(key)
    if saved: return json.loads(saved)
    items=[investor_card(db, i) for i in db.scalars(select(Investor)).all()]
    category={"growth":"growth","value":"value","short_sellers":"short_seller","long_term":"long_term"}.get(sort)
    if category: items=[i for i in items if category in i["categories"]]
    if sort == "performance":
        # A collection named Best performance must not quietly rank managers
        # without the required reporting history.
        items=[item for item in items if item["performance"] is not None]
        items.sort(key=lambda x: x["performance"], reverse=True)
    else: items.sort(key=lambda x:x["total_value"], reverse=True)
    data={"items":items[:limit],"sort":sort,"refreshing":refresh_state["running"]}; cache.setex(key,60,json.dumps(data)); return data
@app.get("/api/investors/{slug}")
def investor_detail(slug: str, db: Session = Depends(db_session)):
    investor=db.scalar(select(Investor).where(Investor.slug==slug))
    if not investor: raise HTTPException(404,"Investor not found")
    result=investor_card(db, investor)
    snapshots = db.scalars(select(PortfolioSnapshot).where(PortfolioSnapshot.investor_id==investor.id).order_by(desc(PortfolioSnapshot.filing_date))).all()
    snapshot = snapshots[0] if snapshots else None
    previous = snapshots[1] if len(snapshots) > 1 else None
    old = {} if not previous else {holding.cusip or holding.company_name: holding for holding in db.scalars(select(Holding).where(Holding.snapshot_id == previous.id)).all()}
    def activity(holding):
        prior = old.get(holding.cusip or holding.company_name)
        if not previous: return {"action":"first_observed", "shares":money(holding.shares)}
        if not prior: return {"action":"new", "shares":money(holding.shares)}
        delta = money(holding.shares) - money(prior.shares)
        return {"action":"increased" if delta > 0 else "reduced" if delta < 0 else "held", "shares":abs(delta)}
    result["holdings"]=[] if not snapshot else [{"ticker":h.ticker,"cusip":h.cusip,"company_name":h.company_name,"shares":money(h.shares),"market_value":money(h.market_value),"pct_of_portfolio":h.pct_of_portfolio,"estimated_purchase_price":None if h.estimated_purchase_price is None else money(h.estimated_purchase_price),"last_transaction":activity(h)} for h in db.scalars(select(Holding).where(Holding.snapshot_id==snapshot.id).order_by(desc(Holding.market_value))).all()]
    result["history"]=[{"filing_date":s.filing_date.isoformat(),"total_value":money(s.total_value),"holding_count":len(s.holdings)} for s in reversed(snapshots)]
    return result
@app.get("/api/search")
def search(q: str = Query(min_length=2, max_length=60), db: Session = Depends(db_session)):
    term = q.strip().lower()
    managers = [{"type":"investor","slug":item.slug,"name":item.name,"subtitle":item.fund_name} for item in db.scalars(select(Investor)).all() if term in item.name.lower() or term in item.fund_name.lower()]
    stocks = {}
    for holding in db.scalars(select(Holding).where(Holding.ticker.is_not(None))).all():
        if term in holding.ticker.lower() or term in holding.company_name.lower():
            stocks[holding.ticker] = {"type":"stock","symbol":holding.ticker,"name":holding.company_name,"subtitle":"Open free price chart"}
    return {"items": (managers + list(stocks.values()))[:12]}
@app.get("/api/stocks/{symbol}")
async def stock(symbol: str):
    try: return await quote_history(symbol)
    except ValueError as exc: raise HTTPException(404, str(exc))
    except Exception: raise HTTPException(502, "Free market-data source is temporarily unavailable")
@app.get("/api/stocks/{symbol}/overview")
async def stock_overview(symbol: str):
    symbol = symbol.upper()
    key = f"stock-overview:{symbol}"
    cached = cache.get(key)
    if cached:
        return json.loads(cached)
    try:
        overview = await company_overview(symbol)
        # Company Facts update on SEC filing cadence, not every page view.
        cache.setex(key, 21600, json.dumps(overview))
        return overview
    except ValueError as exc: raise HTTPException(404, str(exc))
    except Exception: raise HTTPException(502, "SEC company data is temporarily unavailable")
@app.get("/api/stocks/{symbol}/holders")
def stock_holders(symbol: str, db: Session = Depends(db_session)):
    symbol = symbol.upper()
    investors = db.scalars(select(Investor)).all()
    items, exits = [], []
    for investor in investors:
        snapshots = db.scalars(select(PortfolioSnapshot).where(PortfolioSnapshot.investor_id == investor.id).order_by(desc(PortfolioSnapshot.filing_date)).limit(2)).all()
        if not snapshots: continue
        latest = db.scalar(select(Holding).where(Holding.snapshot_id == snapshots[0].id, Holding.ticker == symbol))
        previous = None if len(snapshots) < 2 else db.scalar(select(Holding).where(Holding.snapshot_id == snapshots[1].id, Holding.ticker == symbol))
        if not latest and not previous: continue
        current_shares, old_shares = float(latest.shares) if latest else 0, float(previous.shares) if previous else 0
        delta = current_shares - old_shares
        action = "first_observed" if previous is None else ("increased" if delta > 0 else "reduced" if delta < 0 else "held")
        position = latest or previous
        record={"slug":investor.slug,"name":investor.name,"fund_name":investor.fund_name,"market_value":money(latest.market_value) if latest else 0,"pct_of_portfolio":latest.pct_of_portfolio if latest else 0,"filing_date":snapshots[0].filing_date.isoformat(),"transaction":{"action":action if latest else "exited", "shares":abs(delta),"event_date":snapshots[0].filing_date.isoformat(),"price_proxy":None if position.estimated_purchase_price is None else money(position.estimated_purchase_price)}}
        (items if latest else exits).append(record)
    return {"items": sorted(items, key=lambda item:item["market_value"], reverse=True), "exits": sorted(exits, key=lambda item:item["filing_date"], reverse=True)}
@app.post("/api/admin/refresh")
async def refresh(x_admin_token: str = Header(default="")):
    if x_admin_token != settings.admin_refresh_token: raise HTTPException(401,"Invalid admin token")
    if refresh_state["running"]: return {"status":"refresh already running"}
    cache.flushdb(); asyncio.create_task(run_refresh()); return {"status":"refresh started"}
