# Clutch.co Scraper

Deploys a Playwright-based scraper that extracts company names, websites, and locations.

## Environment Variables

- `BASE_URL` – Clutch listing base URL  
- `TOTAL_PAGES` – Number of pages to scrape  
- `HEADLESS` – `"true"` or `"false"`

## Deploying to Railway

1. Push this repo to GitHub.
2. In Railway, create a new Project > Deploy from GitHub, and select this repo.
3. Under Variables, set:
   - `BASE_URL`
   - `TOTAL_PAGES`
   - `HEADLESS`
4. Trigger a deploy.

Your CSV will be written to the container’s filesystem; for persistence, you can attach a Volume or push results to an external store (S3, database, etc.).
