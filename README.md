# Top Investors

An investment-research experience for exploring institutional conviction through
public SEC Form 13F disclosures.

**Live demo:** [top-investorsweb.vercel.app](https://top-investorsweb.vercel.app/investors)

## Highlights

- Discover notable investment managers and their latest reported portfolios.
- Compare holdings between filings to surface new, increased, reduced, and
  unchanged positions.
- Explore security pages with interactive multi-year price charts and disclosed
  institutional activity.
- Review portfolio-history trends and carefully labelled disclosed-value change.
- Search investors, funds, tickers, and reported issuers from one interface.

## Data and methodology

Top Investors treats 13F data as what it is: a delayed, long-only disclosure
snapshot—not a real-time trading feed, audited fund return, or complete picture
of a manager's portfolio. Public SEC data is paired with delayed end-of-day
market history and clear source notes throughout the experience.

Reported position values are interpreted using the SEC's 13F convention of
reporting values in thousands of dollars. Options are kept distinct from
common-share positions, and portfolio history keeps the latest filing for each
reported period rather than treating amendments as separate quarters.

## Technical focus

Built with Next.js, TypeScript, FastAPI, PostgreSQL, Redis-compatible caching,
and GitHub Actions. The public experience is served from a versioned data
snapshot, so visitors do not wait for the research API to wake up.

## Data disclaimer

Form 13F reports certain U.S. equity holdings quarterly. It does not disclose
short positions, cash, most derivatives, transaction execution prices, or a
manager's complete portfolio. Figures in this project are for research and
educational use only, not investment advice.
