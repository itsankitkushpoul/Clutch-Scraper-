from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
from urllib.parse import urlparse
import asyncio
import random
import logging
from typing import List, Dict, Optional

# ---------- Configuration ----------
HEADLESS = True
USE_AGENT = True
ENABLE_CORS = True
MAX_RETRIES = 3
PAGE_LOAD_TIMEOUT = 120_000
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/14.0.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/88.0.4324.96 Safari/537.36"
]
PROXIES = [None]  # Add actual proxy URLs here if needed

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)

# ---------- Request Model ----------
class ScrapeRequest(BaseModel):
    base_url: HttpUrl
    total_pages: conint(gt=0, le=20) = 3

# ---------- FastAPI App ----------
app = FastAPI(title="Clutch Scraper API")

# ---------- CORS ----------
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

# ---------- Health Check ----------
@app.get("/health")
async def health():
    return {"status": "ok"}

# ---------- Scraping Logic ----------
async def scrape_page(url: str) -> List[Dict]:
    ua = random.choice(USER_AGENTS) if USE_AGENT else None
    proxy = random.choice(PROXIES)

    logging.info(f"Scraping: {url} | Proxy: {proxy} | UA: {ua}")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=HEADLESS)
            context = await browser.new_context(proxy={"server": proxy} if proxy else None)

            if ua:
                await context.set_extra_http_headers({'User-Agent': ua})

            try:
                page = await context.new_page()

                for attempt in range(1, MAX_RETRIES + 1):
                    try:
                        await page.goto(url, timeout=PAGE_LOAD_TIMEOUT)
                        break
                    except Exception as e:
                        logging.warning(f"Retry {attempt}/{MAX_RETRIES} for {url}. Error: {e}")
                        await asyncio.sleep(2 ** attempt)
                else:
                    logging.error(f"Failed to load {url} after {MAX_RETRIES} attempts.")
                    return []

                await page.wait_for_load_state('networkidle')

                results = []

                # Regular listings
                names = await page.eval_on_selector_all(
                    'a.provider__title-link.directory_profile',
                    'els => els.map(el => el.textContent.trim())'
                )
                raw_links = await page.evaluate("""
                    () => {
                        const selector = "a.provider__cta-link.sg-button-v2.sg-button-v2--primary.website-link__item.website-link__item--non-ppc";
                        return Array.from(document.querySelectorAll(selector)).map(el => {
                            const href = el.getAttribute("href");
                            try {
                                const params = new URL(href, location.origin).searchParams;
                                return params.get("u") ? decodeURIComponent(params.get("u")) : null;
                            } catch {
                                return null;
                            }
                        });
                    }
                """)
                locations = await page.eval_on_selector_all(
                    '.provider__highlights-item.sg-tooltip-v2.location',
                    'els => els.map(el => el.textContent.trim())'
                )

                for i, name in enumerate(names):
                    raw = raw_links[i] if i < len(raw_links) else None
                    website = f"{urlparse(raw).scheme}://{urlparse(raw).netloc}" if raw else None
                    loc = locations[i] if i < len(locations) else None
                    results.append({
                        'company': name,
                        'website': website,
                        'location': loc,
                        'featured': False,
                        'source_page': url
                    })

                # Featured listings
                featured_names = await page.eval_on_selector_all(
                    'a.provider__title-link.ppc-website-link',
                    'els => els.map(el => el.textContent.trim())'
                )
                featured_raw_links = await page.evaluate("""
                    () => {
                        const selector = "a.provider__cta-link.ppc_position--link";
                        return Array.from(document.querySelectorAll(selector)).map(el => {
                            const href = el.getAttribute("href");
                            try {
                                const params = new URL(href, location.origin).searchParams;
                                return params.get("u") ? decodeURIComponent(params.get("u")) : null;
                            } catch {
                                return null;
                            }
                        });
                    }
                """)
                featured_locs = await page.eval_on_selector_all(
                    'div.provider__highlights-item.sg-tooltip-v2.location',
                    'els => els.map(el => el.textContent.trim())'
                )

                for i, name in enumerate(featured_names):
                    raw = featured_raw_links[i] if i < len(featured_raw_links) else None
                    website = f"{urlparse(raw).scheme}://{urlparse(raw).netloc}" if raw else None
                    loc = featured_locs[i] if i < len(featured_locs) else None
                    results.append({
                        'company': name,
                        'website': website,
                        'location': loc,
                        'featured': True,
                        'source_page': url
                    })

                return results

            finally:
                await context.close()
                await browser.close()

    except Exception as e:
        logging.error(f"Scrape error on {url}: {e}")
        return []

# ---------- POST Endpoint ----------
@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    urls = [f"{req.base_url}?page={p}" for p in range(1, req.total_pages + 1)]
    tasks = []

    async def delayed_scrape(u: str, d: float) -> List[Dict]:
        await asyncio.sleep(d)
        return await scrape_page(u)

    for url in urls:
        delay = random.uniform(1.0, 3.0)
        tasks.append(delayed_scrape(url, delay))

    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logging.error(f"Error on page {i + 1}: {r}")

        flat_results = [item for sublist in results if isinstance(sublist, list) for item in sublist]

        if not flat_results:
            raise HTTPException(status_code=204, detail="No data scraped.")

        return {"count": len(flat_results), "data": flat_results}

    except Exception as e:
        logging.error(f"Scraping failed: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
