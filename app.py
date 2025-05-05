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

        # Company Names & featured flag
        items = await page.evaluate("""
        () => {
          const nameEls = Array.from(document.querySelectorAll(
            'a.provider__title-link.directory_profile, a.provider__title-link.ppc-website-link'
          ));
          const locations = Array.from(document.querySelectorAll(
            '.provider__highlights-item.sg-tooltip-v2.location'
          ));
          const linkEls = Array.from(document.querySelectorAll(
            'a.provider__cta-link.sg-button-v2.sg-button-v2--primary.website-link__item'
          ));

          return nameEls.map((el, idx) => {
            const raw = linkEls[idx]?.getAttribute('href') || null;
            let website = null;
            if (raw) {
              try {
                const params = new URL(raw, location.origin).searchParams;
                const dest = params.get('u') ? decodeURIComponent(params.get('u')) : null;
                if (dest) {
                  const parsed = new URL(dest);
                  website = `${parsed.protocol}//${parsed.host}`;
                }
              } catch {}
            }
            return {
              company: el.textContent.trim(),
              location: locations[idx]?.textContent.trim() || None,
              website,
              featured: el.classList.contains('ppc-website-link')
            };
          });
        }
        """)

        await browser.close()
        return items

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
