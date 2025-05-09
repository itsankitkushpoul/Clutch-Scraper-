import os
import json
import asyncio
import random
import logging
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl, conint

from playwright.async_api import async_playwright, Playwright, Browser
from playwright_stealth import stealth_async

# -----------------------
# Logging
# -----------------------
logging.basicConfig(level=logging.INFO)

# -----------------------
# Config from env
# -----------------------
def getenv_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")

HEADLESS    = getenv_bool("HEADLESS", True)
USE_AGENT   = getenv_bool("USE_AGENT", True)
ENABLE_CORS = getenv_bool("ENABLE_CORS", True)

# JSON-encoded lists in env:
USER_AGENTS = json.loads(os.getenv("USER_AGENTS", json.dumps([
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)..."
])))
PROXIES     = json.loads(os.getenv("PROXIES", json.dumps([None])))

# Batch size for concurrency
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "5"))

# -----------------------
# FastAPI setup
# -----------------------
app = FastAPI(title="Clutch Scraper API")

if ENABLE_CORS:
    frontend_domains = [
        "https://e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovableproject.com",
        "https://id-preview--e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovable.app",
        "https://clutch-agency-explorer-ui.lovable.app",
        "https://preview--clutch-agency-explorer-ui.lovable.app"
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=frontend_domains,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logging.info(f"CORS enabled for: {frontend_domains}")

@app.get("/health")
def health():
    return {"status": "ok"}

class ScrapeRequest(BaseModel):
    base_url: HttpUrl
    total_pages: conint(gt=0, le=50) = 3

# -----------------------
# Global Playwright objects
# -----------------------
playwright: Playwright = None
browser: Browser = None

@app.on_event("startup")
async def startup():
    global playwright, browser
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=HEADLESS)
    logging.info("Browser launched")

@app.on_event("shutdown")
async def shutdown():
    await browser.close()
    await playwright.stop()
    logging.info("Browser closed")

# -----------------------
# Scraping logic
# -----------------------
async def scrape_page(url: str) -> list:
    ua    = random.choice(USER_AGENTS) if USE_AGENT else None
    proxy = random.choice(PROXIES)

    context = await browser.new_context(
        proxy={"server": proxy} if proxy else None,
        user_agent=ua
    )
    page = await context.new_page()

    await stealth_async(page)

    for attempt in range(1, 5):
        try:
            await page.goto(url, timeout=120_000)
            break
        except Exception as e:
            wait = 2 ** attempt + random.random()
            logging.warning(f"[{url}] goto failed (attempt {attempt}), waiting {wait:.1f}s: {e}")
            await asyncio.sleep(wait)
    else:
        logging.error(f"[{url}] giving up after retries")
        await context.close()
        return []

    await page.wait_for_load_state("networkidle")

    results = []

    names = await page.eval_on_selector_all(
        'a.provider__title-link.directory_profile',
        'els => els.map(el => el.textContent.trim())'
    )
    raw_links = await page.evaluate("""() => {
        const sel = "a.provider__cta-link.sg-button-v2.sg-button-v2--primary.website-link__item.website-link__item--non-ppc";
        return Array.from(document.querySelectorAll(sel)).map(el => {
            const href = el.getAttribute("href");
            try {
                const p = new URL(href, location.origin).searchParams;
                return p.get("u") ? decodeURIComponent(p.get("u")) : null;
            } catch {
                return null;
            }
        });
    }""")
    locations = await page.eval_on_selector_all(
        '.provider__highlights-item.sg-tooltip-v2.location',
        'els => els.map(el => el.textContent.trim())'
    )

    for i, name in enumerate(names):
        raw = raw_links[i] if i < len(raw_links) else None
        site = f"{urlparse(raw).scheme}://{urlparse(raw).netloc}" if raw else None
        loc  = locations[i] if i < len(locations) else None
        results.append({
            "company":  name,
            "website":  site,
            "location": loc,
            "featured": False
        })

    fnames = await page.eval_on_selector_all(
        'a.provider__title-link.ppc-website-link',
        'els => els.map(el => el.textContent.trim())'
    )
    fraws = await page.evaluate("""() => {
        const sel = "a.provider__cta-link.ppc_position--link";
        return Array.from(document.querySelectorAll(sel)).map(el => {
            const href = el.getAttribute("href");
            try {
                const p = new URL(href, location.origin).searchParams;
                return p.get("u") ? decodeURIComponent(p.get("u")) : null;
            } catch {
                return null;
            }
        });
    }""")
    flocs = await page.eval_on_selector_all(
        'div.provider__highlights-item.sg-tooltip-v2.location',
        'els => els.map(el => el.textContent.trim())'
    )

    for i, name in enumerate(fnames):
        raw = fraws[i] if i < len(fraws) else None
        site = f"{urlparse(raw).scheme}://{urlparse(raw).netloc}" if raw else None
        loc  = flocs[i] if i < len(flocs) else None
        results.append({
            "company":  name,
            "website":  site,
            "location": loc,
            "featured": True
        })

    await page.close()
    await context.close()

    await asyncio.sleep(random.uniform(2, 5))

    return results

# -----------------------
# Endpoint with batching
# -----------------------
@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    all_results = []
    pages = list(range(1, req.total_pages + 1))

    for i in range(0, len(pages), BATCH_SIZE):
        batch = pages[i : i + BATCH_SIZE]
        tasks = [
            scrape_page(f"{req.base_url}?page={p}") for p in batch
        ]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in batch_results:
            if isinstance(res, list):
                all_results.extend(res)

        if i + BATCH_SIZE < len(pages):
            pause = random.uniform(10, 20)
            logging.info(f"Batch {i//BATCH_SIZE + 1} completed; sleeping {pause:.1f} seconds before next batch")
            await asyncio.sleep(pause)

    if not all_results:
        raise HTTPException(status_code=204, detail="No data scraped.")

    return {"count": len(all_results), "data": all_results}
