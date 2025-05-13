
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random, logging
from playwright.async_api import async_playwright
from fastapi.middleware.cors import CORSMiddleware

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
        "https://your-frontend.com"
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

async def extract_page_data(page):
    try:
        await page.wait_for_load_state("networkidle")
        names = await page.eval_on_selector_all(
            'a.provider__title-link.directory_profile',
            'els => els.map(el => el.textContent.trim())'
        )
        raw_links = await page.eval_on_selector_all(
            'a.provider__title-link.directory_profile',
            'els => els.map(el => el.href)'
        )
        return list(zip(names, raw_links))
    except Exception as e:
        logging.error(f"Failed to extract data: {e}")
        return []

async def scrape_page(context, page_url):
    ua = random.choice(USER_AGENTS) if USE_AGENT else None
    try:
        page = await context.new_page()
        if ua:
            await page.set_extra_http_headers({'User-Agent': ua})

        await page.goto(page_url, timeout=120_000)
        results = await extract_page_data(page)
        await page.close()
        await asyncio.sleep(random.uniform(1, 2))
        return results
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

    return {"results": results}
