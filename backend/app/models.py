from datetime import datetime
from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, create_engine
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from .config import settings

class Base(DeclarativeBase): pass
class Investor(Base):
    __tablename__ = "investors"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    fund_name: Mapped[str] = mapped_column(String(180))
    cik: Mapped[str] = mapped_column(String(10))
    category: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    snapshots: Mapped[list["PortfolioSnapshot"]] = relationship(back_populates="investor", cascade="all, delete-orphan")
class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    investor_id: Mapped[int] = mapped_column(ForeignKey("investors.id"), index=True)
    filing_date: Mapped[datetime] = mapped_column(Date)
    quarter: Mapped[str] = mapped_column(String(8))
    total_value: Mapped[float] = mapped_column(Numeric(20, 2))
    source_accession_number: Mapped[str] = mapped_column(String(30), unique=True)
    investor: Mapped[Investor] = relationship(back_populates="snapshots")
    holdings: Mapped[list["Holding"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")
class Holding(Base):
    __tablename__ = "holdings"
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("portfolio_snapshots.id"), index=True)
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cusip: Mapped[str | None] = mapped_column(String(20), nullable=True)
    company_name: Mapped[str] = mapped_column(Text)
    shares: Mapped[float] = mapped_column(Numeric(22, 2))
    market_value: Mapped[float] = mapped_column(Numeric(20, 2))
    estimated_purchase_price: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    pct_of_portfolio: Mapped[float] = mapped_column(Float)
    snapshot: Mapped[PortfolioSnapshot] = relationship(back_populates="holdings")
class PerformanceCache(Base):
    __tablename__ = "performance_cache"
    investor_id: Mapped[int] = mapped_column(ForeignKey("investors.id"), primary_key=True)
    # The descriptive annual-comparison key is longer than 20 characters.
    period: Mapped[str] = mapped_column(String(64), primary_key=True)
    return_pct: Mapped[float] = mapped_column(Float)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
class AppState(Base):
    __tablename__ = "app_state"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(128))
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
