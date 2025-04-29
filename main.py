import os
import asyncio
import random
import pandas as pd
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import FileResponse

# --- FastAPI app setup ---
app = FastAPI()

# --- Scraper Config ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/112.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.01.722.58",
]

PROXIES = [None]  # Add proxies if needed

class ScrapeRequest(BaseModel):
    base_url: str = "https://clutch.co/agencies/digital-marketing"
    total_pages: int = 3
    headless: bool = True

async def scrape_clutch(url: str, headless: bool, ua: str | None, proxy: str | None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context_kwargs = {}
        if proxy:
            context_kwargs["proxy"] = {"server": proxy}
        context = await browser.new_context(**context_kwargs)
        
        if ua:
            await context.set_extra_http_headers({"User-Agent": ua})
        
        page = await context.new_page()
        await page.goto(url, timeout=120_000)
        await page.wait_for_load_state("networkidle", timeout=60_000)
        await page.wait_for_selector("a.provider__title-link.directory_profile", timeout=60_000)

        names = await page.eval_on_selector_all(
            "a.provider__title-link.directory_profile",
            "els => els.map(el => el.textContent.trim())"
        )

        websites = await page.evaluate("""
        () => {
          const selector = "a.provider__cta-link.sg-button-v2.sg-button-v2--primary.website-link__item.website-link__item--non-ppc";
          return Array.from(document.querySelectorAll(selector)).map(el => {
            const href = el.getAttribute("href");
            let dest = null;
            try {
              const params = new URL(href, location.origin).searchParams;
              dest = params.get("u") ? decodeURIComponent(params.get("u")) : null;
            } catch {}
            return { destination_url: dest };
          });
        }
        """)

        locations = await page.eval_on_selector_all(
            ".provider__highlights-item.sg-tooltip-v2.location",
            "els => els.map(el => el.textContent.trim())"
        )

        await browser.close()
        return names, websites, locations

async def run_scraper(base_url: str, total_pages: int, headless: bool):
    print(f"Starting to scrape {total_pages} page(s) from {base_url}")
    all_rows = []

    for page_num in range(1, total_pages + 1):
        await asyncio.sleep(random.uniform(1, 3))  # Rate limiting
        paged_url = f"{base_url}?page={page_num}"
        ua = random.choice(USER_AGENTS)
        proxy = random.choice(PROXIES)

        names, websites, locations = await scrape_clutch(
            paged_url,
            headless,
            ua,
            proxy
        )

        for i, name in enumerate(names):
            raw_url = websites[i]["destination_url"] if i < len(websites) else None
            website = f"{urlparse(raw_url).scheme}://{urlparse(raw_url).netloc}" if raw_url else None
            location = locations[i] if i < len(locations) else None

            all_rows.append({
                "S.No": len(all_rows) + 1,
                "Company Name": name,
                "Website": website,
                "Location": location
            })

    df = pd.DataFrame(all_rows)
    output_file = "clutch_companies.csv"
    df.to_csv(output_file, index=False, encoding="utf-8-sig")
    print(f"\nScraping completed! {len(df)} records saved to {output_file}")

# --- FastAPI Endpoints ---

@app.get("/")
async def root():
    return {"message": "Clutch Scraper is live!"}

@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    await run_scraper(request.base_url, request.total_pages, request.headless)
    return {"status": "Scraping complete", "output_file": "clutch_companies.csv"}

@app.get("/download")
async def download_file():
    file_path = "clutch_companies.csv"
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type='application/octet-stream', filename="clutch_companies.csv")
    return {"message": "File not found!"}
