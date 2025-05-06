from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random, logging
from playwright.async_api import async_playwright
from urllib.parse import urlparse
from fastapi.middleware.cors import CORSMiddleware

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
        context = await browser.new_context(proxy={"server": proxy} if proxy else None)
        if ua:
            await context.set_extra_http_headers({'User-Agent': ua})
        page = await context.new_page()

        await page.goto(url, timeout=120_000)
        await page.wait_for_load_state('networkidle')

        results = []

        # --- 1) Regular directory listings ---
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
                'featured': False
            })

        # --- 2) Featured (sponsored) listings ---
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
                'featured': True
            })

        await browser.close()
        return results

@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    tasks = [
        scrape_page(f"{req.base_url}?page={p}")
        for p in range(1, req.total_pages + 1)
    ]
    results = await asyncio.gather(*tasks)
    flat = [item for sub in results for item in sub]
    if not flat:
        raise HTTPException(status_code=204, detail="No data scraped.")
    return {"count": len(flat), "data": flat}
