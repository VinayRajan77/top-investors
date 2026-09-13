import { NextRequest } from 'next/server';
import snapshot from '../../../data/published-snapshot.json';

export const dynamic = 'force-dynamic';

const liveApi = (process.env.SNAPSHOT_LIVE_API_URL || 'https://topinvestors-api.onrender.com').replace(/\/$/, '');
const data = snapshot as unknown as { generated_at: string | null; lists: Record<string, any[]>; investors: Record<string, any>; stocks: Record<string, { stock: any }> };
const response = (body: unknown, status = 200) => Response.json(body, { status, headers: { 'Cache-Control': 'public, max-age=300, s-maxage=3600, stale-while-revalidate=86400' } });

function holders(symbol: string) {
  const items: any[] = [], exits: any[] = [];
  for (const investor of Object.values(data.investors)) {
    const holding = investor.holdings?.find((item: any) => item.ticker === symbol);
    if (!holding) continue;
    const transaction = holding.last_transaction || { action: 'held', shares: 0 };
    items.push({ slug: investor.slug, name: investor.name, fund_name: investor.fund_name, market_value: holding.market_value || 0, pct_of_portfolio: holding.pct_of_portfolio || 0, filing_date: investor.filing_date, transaction: { ...transaction, event_date: investor.filing_date, price_proxy: holding.estimated_purchase_price || null } });
  }
  return { items: items.sort((a, b) => b.market_value - a.market_value), exits };
}

async function live(path: string, request: NextRequest) {
  const target = new URL(`/api/${path}`, liveApi);
  target.search = request.nextUrl.search;
  const upstream = await fetch(target, { cache: 'no-store' });
  const text = await upstream.text();
  return new Response(text, { status: upstream.status, headers: { 'content-type': upstream.headers.get('content-type') || 'application/json' } });
}

export async function GET(request: NextRequest, { params }: { params: { path: string[] } }) {
  const path = params.path;
  if (path[0] === 'investors' && path.length === 1) {
    const sort = request.nextUrl.searchParams.get('sort') || 'popular';
    return response({ items: data.lists[sort] || [], sort, refreshing: false, generated_at: data.generated_at });
  }
  if (path[0] === 'investors' && path[1] && path.length === 2) return data.investors[path[1]] ? response(data.investors[path[1]]) : response({ detail: 'Investor not in the published snapshot.' }, 404);
  if (path[0] === 'search') {
    const query = (request.nextUrl.searchParams.get('q') || '').trim().toLowerCase();
    const managers = Object.values(data.investors).filter(investor => investor.name.toLowerCase().includes(query) || investor.fund_name.toLowerCase().includes(query)).map(investor => ({ type: 'investor', slug: investor.slug, name: investor.name, subtitle: investor.fund_name }));
    const stocks = new Map<string, any>();
    for (const investor of Object.values(data.investors)) for (const holding of investor.holdings || []) if (holding.ticker && (holding.ticker.toLowerCase().includes(query) || holding.company_name.toLowerCase().includes(query))) stocks.set(holding.ticker, { type: 'stock', symbol: holding.ticker, name: holding.company_name, subtitle: 'Open published price chart' });
    return response({ items: [...managers, ...Array.from(stocks.values())].slice(0, 12) });
  }
  if (path[0] === 'stocks' && path[1]) {
    const symbol = path[1].toUpperCase();
    if (path[2] === 'holders') return response(holders(symbol));
    if (path.length === 2 && data.stocks[symbol]?.stock) return response(data.stocks[symbol].stock);
  }
  // A seldom-used security not included in the compact published snapshot can
  // still use the research API; core directory and investor routes never wait
  // on this fallback.
  return live(path.join('/'), request);
}
