import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';

const api = (process.env.SNAPSHOT_API_URL || 'https://topinvestors-api.onrender.com').replace(/\/$/, '');
const output = resolve('data/published-snapshot.json');
const categories = ['popular', 'performance', 'growth', 'value', 'short_sellers', 'long_term'];
const featuredStockLimit = 80;

async function get(path) {
  const response = await fetch(`${api}${path}`);
  if (!response.ok) throw new Error(`${path}: ${response.status} ${response.statusText}`);
  return response.json();
}

async function limited(items, worker, limit = 4) {
  const results = [];
  let cursor = 0;
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) results.push(await worker(items[cursor++]));
  }));
  return results;
}

console.log(`Creating a publishable snapshot from ${api}…`);
const listPairs = await Promise.all(categories.map(async category => [category, await get(`/api/investors?sort=${category}&limit=100`)]));
const lists = Object.fromEntries(listPairs.map(([category, result]) => [category, result.items]));
const managerSlugs = [...new Set(Object.values(lists).flat().map(item => item.slug))];
const detailPairs = await limited(managerSlugs, async slug => [slug, await get(`/api/investors/${slug}`)], 3);
const investors = Object.fromEntries(detailPairs);

const stockScore = new Map();
for (const investor of Object.values(investors)) for (const holding of investor.holdings || []) if (holding.ticker) stockScore.set(holding.ticker, (stockScore.get(holding.ticker) || 0) + (holding.market_value || 0));
const symbols = [...stockScore.entries()].sort((a, b) => b[1] - a[1]).slice(0, featuredStockLimit).map(([symbol]) => symbol);
const stockPairs = await limited(symbols, async symbol => {
  try { return [symbol, { stock: await get(`/api/stocks/${encodeURIComponent(symbol)}`) }]; }
  catch (error) { console.warn(`Skipping ${symbol}: ${error.message}`); return [symbol, null]; }
}, 3);
const stocks = Object.fromEntries(stockPairs.filter(([, value]) => value));
const snapshot = { generated_at: new Date().toISOString(), source: 'Public SEC Form 13F and free end-of-day market data.', lists, investors, stocks };
await mkdir(dirname(output), { recursive: true });
await writeFile(output, `${JSON.stringify(snapshot)}\n`);
console.log(`Saved ${managerSlugs.length} investor profiles and ${Object.keys(stocks).length} featured stock charts to ${output}.`);
