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

        # Company names
        names = await page.eval_on_selector_all(
            "a.provider__title-link.directory_profile",
            "els => els.map(el => el.textContent.trim())"
        )

        # Real company websites (CLEANED version)
        websites = await page.evaluate("""
        () => {
            const selector = "a.provider__cta-link.sg-button-v2.sg-button-v2--primary.website-link__item.website-link__item--non-ppc";
            return Array.from(document.querySelectorAll(selector)).map(el => {
                const href = el.getAttribute("href");
                if (!href) return null;
                try {
                    const url = new URL(href, location.origin);
                    const destParam = url.searchParams.get("u");
                    if (destParam) {
                        const cleanUrl = new URL(decodeURIComponent(destParam));
                        return cleanUrl.origin;  // Only scheme + domain (https://example.com)
                    }
                } catch (e) {
                    return null;
                }
                return null;
            });
        }
        """)

        # Locations
        locations = await page.eval_on_selector_all(
            ".provider__highlights-item.sg-tooltip-v2.location",
            "els => els.map(el => el.textContent.trim())"
        )

        await browser.close()
        return names, websites, locations

async def run_scraper(base_url, total_pages, headless):
    print(f"Scraping {total_pages} pages from {base_url}")
    rows = []
    for i in tqdm(range(1, total_pages + 1), desc="Pages"):
        await asyncio.sleep(random.uniform(1, 3))  # random delay
        url = f"{base_url}?page={i}"
        ua = random.choice(USER_AGENTS)
        proxy = random.choice(PROXIES)
        names, websites, locs = await scrape_page(url, headless, ua, proxy)
        for idx, name in enumerate(names):
            site = websites[idx] if idx < len(websites) else None
            loc = locs[idx] if idx < len(locs) else None
            rows.append({
                "S.No": len(rows) + 1,
                "Company": name,
                "Website": site,
                "Location": loc
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
