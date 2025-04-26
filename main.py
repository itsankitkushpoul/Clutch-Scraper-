import os
import asyncio
import random
import pandas as pd
from urllib.parse import urlparse
from tqdm import tqdm
from playwright.async_api import async_playwright
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import FileResponse

# --- FastAPI app setup ---
app = FastAPI()

# --- Scraper Config ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)…",
    # add more if you want
]

PROXIES = [None]  # add as needed

class ScrapeRequest(BaseModel):
    base_url: str = "https://clutch.co/agencies/digital-marketing"
    total_pages: int = 3
    headless: bool = True

async def scrape_page(url, headless, ua, proxy):
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
        await page.wait_for_load_state("networkidle")

        names = await page.eval_on_selector_all(
            "a.provider__title-link.directory_profile",
            "els => els.map(el => el.textContent.trim())"
        )
        data = await page.evaluate("""() => { /* your eval logic here */ }""")
        locations = await page.eval_on_selector_all(
            ".provider__highlights-item.sg-tooltip-v2.location",
            "els => els.map(el => el.textContent.trim())"
        )
        await browser.close()
        return names, data, locations

async def run_scraper(base_url, total_pages, headless):
    print(f"Scraping {total_pages} pages from {base_url}")
    rows = []
    for i in tqdm(range(1, total_pages + 1), desc="Pages"):
        await asyncio.sleep(random.uniform(1, 3))
        url = f"{base_url}?page={i}"
        ua = random.choice(USER_AGENTS)
        proxy = random.choice(PROXIES)
        names, websites, locs = await scrape_page(url, headless, ua, proxy)
        for idx, name in enumerate(names):
            raw = websites[idx].get("destination_url") if idx < len(websites) else None
            site = f"{urlparse(raw).scheme}://{urlparse(raw).netloc}" if raw else None
            loc = locs[idx] if idx < len(locs) else None
            rows.append({
                "S.No": len(rows)+1, "Company": name,
                "Website": site, "Location": loc
            })
    df = pd.DataFrame(rows)
    out = "clutch_companies.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"Saved {len(df)} records to {out}")

# --- FastAPI Endpoints ---

@app.get("/")
async def root():
    return {"message": "Clutch scraper is live!"}

@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    await run_scraper(request.base_url, request.total_pages, request.headless)
    return {"status": "Scraping complete", "output_file": "clutch_companies.csv"}

@app.get("/download")
async def download_file():
    file_path = "clutch_companies.csv"  # Path to your CSV file
    if os.path.exists(file_path):
        return FileResponse(file_path, media_type='application/octet-stream', filename="clutch_companies.csv")
    return {"message": "File not found!"}
