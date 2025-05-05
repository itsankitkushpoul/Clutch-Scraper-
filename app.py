from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import random
from playwright.async_api import async_playwright
from urllib.parse import urlparse
from fastapi.middleware.cors import CORSMiddleware
import logging
import re

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

# Selectors
LISTING_CONTAINER_SELECTOR = 'li.provider-list-item'
MAIN_INFO_SELECTOR = 'div.provider__main-info'
NAME_SELECTOR = 'a.provider__title-link.directory_profile'
LOCATION_SELECTOR = 'div.provider__highlights div.location'
WEBSITE_BUTTON_SELECTOR = 'div.provider__cta-container a.sg-button-v2--primary:has-text("Visit Website")'

# Utility to clean text

def clean_text(text: str) -> str:
    if text:
        return re.sub(r'\s+', ' ', text).strip()
    return None

# Request schema
class ScrapeRequest(BaseModel):
    base_url: HttpUrl
    total_pages: conint(gt=0, le=20) = 3

app = FastAPI(title="Clutch Scraper API")

# CORS settings
if ENABLE_CORS:
    frontend_domains = [
        "https://e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovableproject.com",
        "https://id-preview--e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovable.app",
        "https://clutch-agency-explorer-ui.lovable.app"
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

async def scrape_page(url: str):
    ua = random.choice(USER_AGENTS) if USE_AGENT else None
    proxy = random.choice(PROXIES)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(proxy={"server": proxy} if proxy else None)
        if ua:
            await context.set_extra_http_headers({'User-Agent': ua})
        page = await context.new_page()

        await page.goto(url, timeout=120_000)
        await page.wait_for_load_state('networkidle')

        listings = page.locator(LISTING_CONTAINER_SELECTOR)
        count = await listings.count()
        results = []

        for i in range(count):
            item = listings.nth(i)
            # Scope to main-info block for consistent grouping
            block = item.locator(MAIN_INFO_SELECTOR).first

            # Name
            name = None
            name_loc = block.locator(NAME_SELECTOR).first
            if await name_loc.count() > 0:
                raw_name = await name_loc.text_content()
                name = clean_text(raw_name)

            # Website
            website = None
            link_loc = block.locator(WEBSITE_BUTTON_SELECTOR).first
            if await link_loc.count() > 0:
                href = await link_loc.get_attribute('href')
                if href:
                    try:
                        from urllib.parse import parse_qs, unquote
                        url_obj = urlparse(href)
                        qs = parse_qs(url_obj.query).get('u', [])
                        dest = unquote(qs[0]) if qs else href
                        parsed = urlparse(dest)
                        website = f"{parsed.scheme}://{parsed.netloc}"
                    except Exception:
                        website = href

            # Location (outside main-info)
            location = None
            loc_loc = item.locator(LOCATION_SELECTOR).first
            if await loc_loc.count() > 0:
                raw_loc = await loc_loc.text_content()
                location = clean_text(raw_loc)

            if name:
                results.append({
                    'company': name,
                    'website': website,
                    'location': location
                })

        await browser.close()
        return results

@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    all_results = []
    for page_num in range(1, req.total_pages + 1):
        page_url = f"{req.base_url}?page={page_num}"
        logging.info(f"Scraping page {page_num}: {page_url}")
        page_results = await scrape_page(page_url)
        all_results.extend(page_results)

    if not all_results:
        raise HTTPException(status_code=204, detail="No data scraped.")

    return {"count": len(all_results), "data": all_results}
