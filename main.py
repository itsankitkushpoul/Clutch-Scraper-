import os
import asyncio
import random
import traceback
import pandas as pd
from urllib.parse import urlparse
from tqdm import tqdm
from playwright.async_api import async_playwright
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse

# --- FastAPI app setup ---
app = FastAPI()

# --- Scraper Config ---
# A wider set of realistic user agents to reduce bot detection
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.5845.140 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:116.0) Gecko/20100101 Firefox/116.0"
]
PROXIES = [None]  # Add proxy strings if needed

class ScrapeRequest(BaseModel):
    base_url: str = "https://clutch.co/agencies/digital-marketing"
    total_pages: int = 3
    headless: bool = True

async def scrape_page(url: str, headless: bool, ua: str | None, proxy: str | None):
    """
    Scrape one Clutch listing page and return:
      - names: list of company names
      - websites: list of actual website URLs or None
      - locations: list of location strings
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx_args = {}
        if ua:
            ctx_args['user_agent'] = ua
        if proxy:
            ctx_args['proxy'] = {'server': proxy}
        context = await browser.new_context(**ctx_args)
        page = await context.new_page()

        await page.goto(url, timeout=120_000)
        await page.wait_for_load_state("networkidle")

        # 1) Company Names
        names = await page.eval_on_selector_all(
            "a.provider__title-link.directory_profile",
            "els => els.map(el => el.textContent.trim())"
        )

        # 2) Actual Company Websites
        site_data = await page.evaluate("""
        () => {
          const selector = "a.provider__cta-link.sg-button-v2.sg-button-v2--primary.website-link__item.website-link__item--non-ppc";
          return Array.from(document.querySelectorAll(selector)).map(el => {
            const href = el.getAttribute('href') || '';
            try {
              const params = new URL(href, location.origin).searchParams;
              const u = params.get('u');
              return u ? decodeURIComponent(u) : null;
            } catch {
              return null;
            }
          });
        }
        """)

        # 3) Locations
        locations = await page.eval_on_selector_all(
            ".provider__highlights-item.sg-tooltip-v2.location",
            "els => els.map(el => el.textContent.trim())"
        )

        await browser.close()
        return names, site_data, locations

async def run_scraper(base_url: str, total_pages: int, headless: bool):
    rows = []
    for page_num in tqdm(range(1, total_pages + 1), desc="Pages", unit="page"):
        await asyncio.sleep(random.uniform(1, 3))  # polite rate limit
        page_url = f"{base_url}?page={page_num}"
        ua = random.choice(USER_AGENTS)
        proxy = random.choice(PROXIES)

        try:
            names, websites, locs = await scrape_page(page_url, headless, ua, proxy)
        except Exception as e:
            print(f"Error scraping page {page_num}: {e}")
            continue

        # Debug counts
        print(f"Page {page_num}: found {len(names)} companies, {len(websites)} website links, {len(locs)} locations")

        for idx, name in enumerate(names):
            raw_site = websites[idx] if idx < len(websites) else None
            site = None
            if raw_site:
                parsed = urlparse(raw_site)
                site = f"{parsed.scheme}://{parsed.netloc}"
            loc = locs[idx] if idx < len(locs) else None
            rows.append({
                "S.No": len(rows) + 1,
                "Company": name,
                "Website": site,
                "Location": loc
            })

    df = pd.DataFrame(rows)
    out_file = "clutch_companies.csv"
    df.to_csv(out_file, index=False, encoding="utf-8-sig")
    print(f"Total records scraped: {len(df)}")
    return len(df), out_file

# --- FastAPI Endpoints ---
@app.get("/")
async def root():
    return {"message": "Clutch scraper is live!"}

@app.post("/scrape")
async def scraper_endpoint(request: ScrapeRequest):
    try:
        count, filename = await run_scraper(request.base_url, request.total_pages, request.headless)
        return {"status": "complete", "records": count, "file": filename}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download")
async def download_file():
    file_path = "clutch_companies.csv"
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type="application/octet-stream", filename=file_path)
    raise HTTPException(status_code=404, detail="File not found")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
