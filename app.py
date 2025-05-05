from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random
from playwright.async_api import async_playwright
from urllib.parse import urlparse

# --- Configuration ---
HEADLESS = True
USE_AGENT = True
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
    # add more
]
PROXIES = [None]

# --- Request Schema ---
class ScrapeRequest(BaseModel):
    base_url: HttpUrl
    total_pages: conint(gt=0, le=20) = 3

app = FastAPI(title="Clutch Scraper API")

async def scrape_page(url: str):
    ua = random.choice(USER_AGENTS) if USE_AGENT else None
    proxy = random.choice(PROXIES)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        ctx_kwargs = {}
        if proxy:
            ctx_kwargs['proxy'] = {'server': proxy}
        context = await browser.new_context(**ctx_kwargs)
        if ua:
            await context.set_extra_http_headers({'User-Agent': ua})
        page = await context.new_page()
        await page.goto(url, timeout=120_000)
        await page.wait_for_load_state('networkidle')
        # extract names, websites, locations (same selectors)
        names = await page.eval_on_selector_all(
            'a.provider__title-link.directory_profile',
            'els => els.map(el => el.textContent.trim())'
        )
        raw_links = await page.evaluate("""
        () => Array.from(
          document.querySelectorAll('a.provider__cta-link.website-link__item')
        ).map(el => el.href)
        """
        )
        locations = await page.eval_on_selector_all(
            '.provider__highlights-item.location',
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

@app.post('/scrape')
async def scrape(req: ScrapeRequest):
    tasks = []
    for p in range(1, req.total_pages + 1):
        url = f"{req.base_url}?page={p}"
        tasks.append(scrape_page(url))
    pages = await asyncio.gather(*tasks)
    # flatten
    flat = [item for sub in pages for item in sub]
    if not flat:
        raise HTTPException(status_code=204, detail="No data scraped.")
    return {'count': len(flat), 'data': flat}
