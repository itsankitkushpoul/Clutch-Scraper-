import os
import asyncio
import random
import traceback
import pandas as pd
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from tqdm import tqdm
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# --- Configuration ---
HEADLESS = True
USE_AGENT = True
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/112.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.01.722.58",
]
PROXIES = [None]

# --- FastAPI setup ---
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://clutch-agency-explorer.lovable.app", "https://bf2aeaa9-1c53-465a-85da-704004dcf688.lovableproject.com", "https://f82eae5a-65eb-4b3f-a5ee-97376a3ab8a0.lovableproject.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScrapeRequest(BaseModel):
    base_url: str = "https://clutch.co/agencies/digital-marketing"
    total_pages: int = 3
    headless: bool = HEADLESS

async def scrape_clutch(url: str, headless: bool, ua: str | None, proxy: str | None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context_kwargs = {}
        if ua:
            context_kwargs['user_agent'] = ua
        if proxy:
            context_kwargs['proxy'] = {'server': proxy}
        context = await browser.new_context(**context_kwargs)

        # Fallback headers/proxy (second-script style)
        if proxy:
            await context.set_proxy({"server": proxy})
        if ua:
            await context.set_extra_http_headers({"User-Agent": ua})

        page = await context.new_page()

        await page.goto(url, timeout=120_000)
        await page.wait_for_load_state("networkidle", timeout=60_000)
        await page.wait_for_selector("a.provider__title-link.directory_profile", timeout=60_000)

        # Company Names
        names = await page.eval_on_selector_all(
            "a.provider__title-link.directory_profile",
            "els => els.map(el => el.textContent.trim())"
        )

        # Website Data
        websites = await page.evaluate('''
        () => {
          const selector = "a.provider__cta-link.sg-button-v2.sg-button-v2--primary.website-link__item.website-link__item--non-ppc";
          return Array.from(document.querySelectorAll(selector)).map(el => {
            const href = el.getAttribute("href") || '';
            let dest = null;
            try {
              const params = new URL(href, location.origin).searchParams;
              dest = params.get("u") ? decodeURIComponent(params.get("u")) : null;
            } catch {}
            return { destination_url: dest };
          });
        }
        ''')

        # Location Extraction
        locations = await page.eval_on_selector_all(
            ".provider__highlights-item.sg-tooltip-v2.location",
            "els => els.map(el => el.textContent.trim())"
        )

        await browser.close()
        return names, websites, locations

async def run_scraper(base_url: str, total_pages: int, headless: bool):
    all_data = []

    for page_num in tqdm(range(1, total_pages + 1), desc="Scraping pages", unit="page"):
        await asyncio.sleep(random.uniform(1, 3))
        page_url = f"{base_url}?page={page_num}"
        ua = random.choice(USER_AGENTS) if USE_AGENT else None
        proxy = random.choice(PROXIES)

        try:
            names, websites, locations = await scrape_clutch(page_url, headless, ua, proxy)
        except Exception as e:
            print(f"Error on page {page_num}: {e}")
            continue

        for idx, name in enumerate(names):
            raw = websites[idx]["destination_url"] if idx < len(websites) else None
            site = None
            if raw:
                parsed = urlparse(raw)
                site = f"{parsed.scheme}://{parsed.netloc}"
            loc = locations[idx] if idx < len(locations) else None
            all_data.append({
                "S.No": len(all_data) + 1,
                "Company": name,
                "Website": site,
                "Location": loc
            })

    df = pd.DataFrame(all_data)
    out_file = "clutch_companies.csv"
    df.to_csv(out_file, index=False, encoding="utf-8-sig")
    print(f"Scraping complete: {len(df)} records saved to {out_file}")
    return len(df), out_file

@app.get("/")
async def root():
    return {"status": "alive"}

@app.post("/scrape")
async def scrape_endpoint(req: ScrapeRequest):
    try:
        count, filename = await run_scraper(req.base_url, req.total_pages, req.headless)
        return {"status": "success", "records": count, "file": filename}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download")
async def download():
    path = "clutch_companies.csv"
    if os.path.exists(path):
        return FileResponse(path, filename=path)
    raise HTTPException(status_code=404, detail="Not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
