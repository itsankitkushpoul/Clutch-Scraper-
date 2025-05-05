from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import random
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

        # Grab everything in one map, in DOM order
        results = await page.evaluate("""
        () => {
          return Array.from(
            document.querySelectorAll('a.provider__title-link.directory_profile')
          ).map(anchor => {
            const company = anchor.textContent.trim();

            // Walk up to the nearest parent that contains both name, link, and location
            const container = anchor.closest('[class*="provider"]');

            // Website link
            let website = null;
            if (container) {
              const linkEl = container.querySelector(
                'a.provider__cta-link.sg-button-v2--primary.website-link__item--non-ppc'
              );
              if (linkEl) {
                try {
                  const urlObj = new URL(linkEl.href, location.origin);
                  const real = urlObj.searchParams.get('u');
                  website = real ? decodeURIComponent(real) : linkEl.href;
                } catch {
                  website = linkEl.href;
                }
              }
            }

            // Location
            let locationText = null;
            if (container) {
              const locEl = container.querySelector('.provider__highlights-item.location');
              if (locEl) locationText = locEl.textContent.trim();
            }

            return { company, website, location: locationText };
          });
        }
        """)

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
