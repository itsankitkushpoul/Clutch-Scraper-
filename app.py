from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random
from playwright.async_api import async_playwright
from urllib.parse import urlparse
from fastapi.middleware.cors import CORSMiddleware
import logging

# Enable basic logging
logging.basicConfig(level=logging.INFO)

# Configuration
HEADLESS = True
USE_AGENT = True
ENABLE_CORS = True  # Toggle CORS on/off easily
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
    # Add more if needed
]
PROXIES = [None]

# Request schema
class ScrapeRequest(BaseModel):
    base_url: HttpUrl
    total_pages: conint(gt=0, le=20) = 3

app = FastAPI(title="Clutch Scraper API")

# CORS settings
if ENABLE_CORS:
    try:
        frontend_domain = "https://bf2aeaa9-1c53-465a-85da-704004dcf688.lovableproject.com"
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[frontend_domain],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        logging.info(f"CORS enabled for: {frontend_domain}")
    except Exception as e:
        logging.error(f"Failed to add CORS middleware: {e}")

@app.get("/health")
def health():
    return {"status": "ok"}

async def scrape_page(url: str):
    ua = random.choice(USER_AGENTS) if USE_AGENT else None
    proxy = random.choice(PROXIES)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(
            proxy={"server": proxy} if proxy else None
        )
        if ua:
            await context.set_extra_http_headers({'User-Agent': ua})
        page = await context.new_page()

        await page.goto(url, timeout=120_000)
        await page.wait_for_load_state('networkidle')

        # Company Names
        names = await page.eval_on_selector_all(
            'a.provider__title-link.directory_profile',
            'els => els.map(el => el.textContent.trim())'
        )

        # Website Links
        raw_links = await page.evaluate("""
        () => {
          const selector = "a.provider__cta-link.sg-button-v2.sg-button-v2--primary.website-link__item.website-link__item--non-ppc";
          return Array.from(document.querySelectorAll(selector)).map(el => {
            const href = el.getAttribute("href");
            let dest = null;
            try {
              const params = new URL(href, location.origin).searchParams;
              dest = params.get("u") ? decodeURIComponent(params.get("u")) : null;
            } catch {}
            return dest;
          });
        }
        """)

        # Locations
        locations = await page.eval_on_selector_all(
            '.provider__highlights-item.sg-tooltip-v2.location',
            'els => els.map(el => el.textContent.trim())'
        )

        await browser.close()

        results = []
        for i, name in enumerate(names):
            raw = raw_links[i] if i < len(raw_links) else None
            website = f"{urlparse(raw).scheme}://{urlparse(raw).netloc}" if raw else None
            loc = locations[i] if i < len(locations) else None
            results.append({'company': name, 'website': website, 'location': loc})

        return results

@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    tasks = []
    for p in range(1, req.total_pages + 1):
        tasks.append(scrape_page(f"{req.base_url}?page={p}"))
    results = await asyncio.gather(*tasks)
    flat = [item for sub in results for item in sub]
    if not flat:
        raise HTTPException(status_code=204, detail="No data scraped.")
    return {"count": len(flat), "data": flat}
