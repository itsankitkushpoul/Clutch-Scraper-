import os
import subprocess
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

# Ensure Playwright Chromimum is installed (runs on startup)
subprocess.run(["playwright", "install", "chromium"], check=True)

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

async def scrape_page(url: str, headless: bool, ua: str | None, proxy: str | None):
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
        await page.wait_for_selector("a.provider__title-link.directory_profile")

        # 1) Company Names
        names = await page.eval_on_selector_all(
            "a.provider__title-link.directory_profile",
            "els => els.map(el => el.textContent.trim())"
        )

        # 2) Clutch Profile URLs (optional)
        profile_urls = await page.eval_on_selector_all(
            "a.provider__title-link.directory_profile",
            "els => els.map(el => el.href)"
        )

        # 3) Actual Company Websites
        site_data = await page.evaluate("""
        () => {
          const selector = "a.provider__cta-link.sg-button-v2.sg-button-v2--primary.website-link__item.website-link__item--non-ppc";
          return Array.from(document.querySelectorAll(selector)).map(el => {
            const href = el.getAttribute("href") || "";
            try {
              const params = new URL(href, location.origin).searchParams;
              const u = params.get("u");
              return u ? decodeURIComponent(u) : null;
            } catch {
              return null;
            }
          });
        }
        """)

        # 4) Locations
        locations = await page.eval_on_selector_all(
            ".provider__highlights-item.sg-tooltip-v2.location",
            "els => els.map(el => el.textContent.trim())"
        )

        await browser.close()
        return names, site_data, locations

async def run_scraper(base_url: str, total_pages: int, headless: bool):
    rows = []
    for i in tqdm(range(1, total_pages + 1), desc="Pages"):
        await asyncio.sleep(random.uniform(1, 3))
        page_url = f"{base_url}?page={i}"
        ua = random.choice(USER_AGENTS)
        proxy = random.choice(PROXIES)
        names, websites, locs = await scrape_page(page_url, headless, ua, proxy)

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
    out = "clutch_companies.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return len(df), out

# --- FastAPI Endpoints ---
@app.get("/")
async def root():
    return {"message": "Clutch scraper is live!"}

@app.post("/scrape")
async def scrape(request: ScrapeRequest):
    try:
        count, filename = await run_scraper(
            request.base_url,
            request.total_pages,
            request.headless
        )
        return {"status": "Scraping complete", "records": count, "output_file": filename}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download")
async def download_file():
    file_path = "clutch_companies.csv"
    if os.path.exists(file_path):
        return FileResponse(
            file_path,
            media_type='application/octet-stream',
            filename=file_path
        )
    raise HTTPException(status_code=404, detail="File not found")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
