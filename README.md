# Top Investors

A local, SEC-only portfolio explorer inspired by the useful interaction patterns of investor-tracking sites. It uses public Form 13F data only—no paid market-data API.

## Run it

1. Copy the sample configuration if you want to customize it: `Copy-Item backend/.env.example backend/.env`.
2. Start the data services and API: `docker-compose up -d --build`.
3. In a second terminal, start the website: `cd frontend`, `npm install`, then `npm run dev`.
4. Open `http://localhost:3000/investors`.

The backend seeds the curated investor list immediately and begins its first 13F pull at startup. An initial refresh can take a few minutes because SEC requests are deliberately kept below the 10 requests/second limit. To manually start a refresh:

```powershell
curl.exe -X POST http://localhost:8000/api/admin/refresh -H "X-Admin-Token: change-me"
```

Change `ADMIN_REFRESH_TOKEN` before exposing the service beyond your machine. The frontend URL is controlled by `frontend/.env.local` (`NEXT_PUBLIC_API_URL`).

## Publish the API with Render

This repository includes a `render.yaml` Blueprint that deploys the API, a Render
Postgres database, and a Render Key Value cache together. It keeps database
credentials and the administrator token out of Git.

1. Push this project to GitHub, then in Render choose **New → Blueprint** and
   select the repository.
2. Render reads `render.yaml`. Enter a meaningful contact address for
   `SEC_USER_AGENT` and set `CORS_ORIGINS` to your Vercel site URL, for example
   `https://topinvestors.vercel.app`. Add `http://localhost:3000` too if you
   want local development to keep working.
3. After deployment, open `https://<your-render-service>.onrender.com/api/health`.
   A successful response means the API is ready.
4. In the Vercel project for `frontend`, set `NEXT_PUBLIC_API_URL` to that
   Render URL and redeploy the frontend.

The included Free plans are appropriate for a preview. Render's free Postgres
database expires after 30 days and does not include backups, so use a paid
database before relying on this as a production service.

## Important data notes

- A 13F reports long U.S. equity holdings quarterly; it does not represent a complete fund portfolio, true short activity, cash, or real-time prices.
- “Portfolio change” compares total disclosed value to the previous filing. It is an approximation, **not** a true time-weighted return.
- SEC's free `company_tickers.json` does not provide a reliable CUSIP-to-ticker map. The importer retains the reported CUSIP rather than inventing a ticker.
- Purchase prices are not present in Form 13F, so the UI explicitly leaves them unavailable. A future free, verified historical-price integration could estimate them.
- Holdings with a verified symbol open a security page with a free, delayed end-of-day chart and the tracked investors currently holding it. It is intentionally not presented as real-time market data.
