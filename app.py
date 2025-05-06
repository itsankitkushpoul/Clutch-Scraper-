from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random, logging
from playwright.async_api import async_playwright, Browser, Playwright
from urllib.parse import urlparse
from fastapi.middleware.cors import CORSMiddleware

# Enable basic logging
logging.basicConfig(level=logging.INFO)

# Configuration
HEADLESS = True
USE_AGENT = True
ENABLE_CORS = True
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
    # Add more realistic User-Agent strings here
]
PROXIES = [None]  # Add working proxies if available, else keep as [None]

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
    except Exception as e:
        logging.error(f"Failed to add CORS middleware: {e}")

@app.get("/health")
def health():
    return {"status": "ok"}

# Globals for Playwright
playwright: Playwright = None
browser: Browser = None

@app.on_event("startup")
async def startup():
    global playwright, browser
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=HEADLESS)
    logging.info("Playwright browser launched")

@app.on_event("shutdown")
async def shutdown():
    await browser.close()
    await playwright.stop()
    logging.info("Playwright browser closed")

async def scrape_page(url: str) -> list:
    ua = random.choice(USER_AGENTS) if USE_AGENT else None
    proxy = random.choice(PROXIES)
    results = []

    try:
        context = await browser.new_context(
            proxy={"server": proxy} if proxy else None
        )
        if ua:
            await context.set_extra_http_headers({'User-Agent': ua})
        page = await context.new_page()

        # Attempt to load page with retries
        retries = 3
        while retries:
            try:
                await page.goto(url, timeout=120_000)
                break
            except Exception as e:
                retries -= 1
                logging.warning(f"[{url}] load failed, retries left={retries}: {e}")
                if not retries:
                    await context.close()
                    return []
                await asyncio.sleep(1)

        # Simple scroll to bottom to trigger lazy loads
        await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        await asyncio.sleep(random.uniform(1, 2))
        await page.wait_for_load_state('networkidle')

        # --- 1) Regular listings ---
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
            website = f"{urlparse(raw).scheme}://{urlparse(raw).netloc}" if raw else None
            loc = locations[i] if i < len(locations) else None
            results.append({
                'company': name,
                'website': website,
                'location': loc,
                'featured': False
            })

        # --- 2) Featured listings ---
        featured_names = await page.eval_on_selector_all(
            'a.provider__title-link.ppc-website-link',
            'els => els.map(el => el.textContent.trim())'
        )
        featured_raw_links = await page.evaluate("""() => {
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

        await context.close()
        logging.info(f"[{url}] scraped {len(results)} items")
        # slight delay before next scrape
        await asyncio.sleep(random.uniform(0.5, 1.5))
        return results

    except Exception as e:
        logging.error(f"Unexpected error in scrape_page({url}): {e}")
        try:
            await context.close()
        except: pass
        return []

@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    urls = [f"{req.base_url}?page={p}" for p in range(1, req.total_pages + 1)]
    tasks = [scrape_page(u) for u in urls]
    pages = await asyncio.gather(*tasks)
    flat = [item for sub in pages for item in sub]
    if not flat:
        raise HTTPException(status_code=204, detail="No data scraped.")
    return {"count": len(flat), "data": flat}
