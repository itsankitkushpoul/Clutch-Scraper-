from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random, logging
from playwright.async_api import async_playwright
from fastapi.middleware.cors import CORSMiddleware
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO)

HEADLESS = True
USE_AGENT = True
ENABLE_CORS = True
MAX_CONCURRENT_TASKS = 5

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)...",
    # Add more realistic User-Agent strings here
]
PROXIES = [None]  # Add proxy URLs if available

class ScrapeRequest(BaseModel):
    base_url: HttpUrl
    total_pages: conint(gt=0, le=100) = 3

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

@app.get("/health")
def health():
    return {"status": "ok"}

async def extract_page_data(page, url):
    await page.wait_for_load_state("networkidle")
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
            'featured': False
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
            'featured': True
        })

    return results

async def scrape_page(context, page_url):
    ua = random.choice(USER_AGENTS) if USE_AGENT else None
    try:
        page = await context.new_page()
        if ua:
            await page.set_extra_http_headers({'User-Agent': ua})

        retries = 3
        while retries:
            try:
                await page.goto(page_url, timeout=120_000)
                break
            except Exception as e:
                retries -= 1
                logging.warning(f"Retrying {page_url}, {2 - retries} attempts left. Error: {e}")
                if retries == 0:
                    logging.error(f"Failed to load {page_url} after retries.")
                    await page.close()
                    return []

        data = await extract_page_data(page, page_url)
        await page.close()
        await asyncio.sleep(random.uniform(1, 2))
        return data
    except Exception as e:
        logging.error(f"Failed to scrape {page_url}: {e}")
        return []

@app.post("/scrape")
async def scrape_data(req: ScrapeRequest):
    base_url = req.base_url
    total_pages = req.total_pages

    results = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        proxy = random.choice(PROXIES)
        context = await browser.new_context(
            proxy={"server": proxy} if proxy else None
        )

        async def limited_scrape(i):
            async with semaphore:
                page_url = f"{base_url}?page={i}"
                return await scrape_page(context, page_url)

        tasks = [limited_scrape(i) for i in range(1, total_pages + 1)]
        all_results = await asyncio.gather(*tasks)
        await browser.close()

    for r in all_results:
        results.extend(r)

    if not results:
        raise HTTPException(status_code=204, detail="No data scraped.")
    return {"count": len(results), "data": results}
