from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
from fastapi.middleware.cors import CORSMiddleware
from playwright.async_api import async_playwright
from urllib.parse import urlparse, urljoin
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
PROXIES = [None]  # Replace with actual proxy URLs if needed

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

# ---------- Scraping Function ----------
async def scrape_all_pages(base_url: str, total_pages: int) -> List[Dict]:
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context()

        if USE_AGENT:
            await context.set_extra_http_headers({
                "User-Agent": random.choice(USER_AGENTS)
            })

        for page_num in range(1, total_pages + 1):
            page_url = f"{base_url}?page={page_num}" if "?" not in base_url else f"{base_url}&page={page_num}"
            logging.info(f"Scraping page {page_num}: {page_url}")
            page = await context.new_page()

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    await page.goto(page_url, timeout=PAGE_LOAD_TIMEOUT)
                    await page.wait_for_load_state("networkidle")
                    break
                except Exception as e:
                    logging.warning(f"Attempt {attempt} failed for {page_url}: {e}")
                    if attempt == MAX_RETRIES:
                        logging.error(f"Skipping {page_url} after {MAX_RETRIES} attempts")
                        await page.close()
                        continue
                    await asyncio.sleep(2 ** attempt)

            try:
                # Scrape regular listings
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
                        'source_page': page_url
                    })

                # Scrape featured listings
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
                        'source_page': page_url
                    })

            except Exception as e:
                logging.error(f"Failed to parse page {page_url}: {e}")

            await page.close()

        await context.close()
        await browser.close()

    return results

# ---------- POST Endpoint ----------
@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    try:
        results = await scrape_all_pages(str(req.base_url), req.total_pages)

        if not results:
            raise HTTPException(status_code=204, detail="No data scraped.")

        return {"count": len(results), "data": results}

    except Exception as e:
        logging.error(f"Scraping failed: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
