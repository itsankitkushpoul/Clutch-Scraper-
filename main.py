from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random, logging
from playwright.async_api import async_playwright, Browser, BrowserContext
from urllib.parse import urlparse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Optional
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Enable basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Configuration from environment variables
HEADLESS = os.getenv('HEADLESS', 'true').lower() == 'true'
USE_AGENT = os.getenv('USE_AGENT', 'true').lower() == 'true'
ENABLE_CORS = os.getenv('ENABLE_CORS', 'true').lower() == 'true'
PAGE_TIMEOUT = int(os.getenv('PAGE_TIMEOUT', '30000'))
MAX_RETRIES = int(os.getenv('MAX_RETRIES', '3'))

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0"
]

# Get proxy list from environment variable
PROXY_LIST = os.getenv('PROXY_LIST', '').split(',') if os.getenv('PROXY_LIST') else [None]

# Global browser instance
browser: Optional[Browser] = None
playwright = None

@asynccontextmanager
async def get_browser_context():
    global browser, playwright
    try:
        if browser is None:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(
                headless=HEADLESS,
                args=[
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-gpu',
                    '--disable-software-rasterizer'
                ]
            )
        context = await browser.new_context(
            proxy={"server": random.choice(PROXY_LIST)} if PROXY_LIST[0] else None
        )
        if USE_AGENT:
            await context.set_extra_http_headers({'User-Agent': random.choice(USER_AGENTS)})
        yield context
    except Exception as e:
        logging.error(f"Browser context error: {e}")
        raise
    finally:
        await context.close()

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
            "https://preview--clutch-agency-explorer-ui.lovable.app",
            "http://localhost:3000"
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

@app.get("/")
async def root():
    return {"message": "Clutch Scraper API is running"}

@app.get("/health")
async def health():
    try:
        if browser:
            # Check if browser is still responsive
            context = await browser.new_context()
            page = await context.new_page()
            await page.close()
            await context.close()
        return {"status": "ok", "browser": "connected"}
    except Exception as e:
        logging.error(f"Health check failed: {e}")
        return {"status": "error", "message": str(e)}

async def scrape_page(url: str):
    async with get_browser_context() as context:
        page = await context.new_page()
        results = []
        
        try:
            # Retry mechanism for page.goto()
            for attempt in range(MAX_RETRIES):
                try:
                    await page.goto(url, timeout=PAGE_TIMEOUT)
                    await page.wait_for_load_state('networkidle', timeout=PAGE_TIMEOUT)
                    break
                except Exception as e:
                    if attempt == MAX_RETRIES - 1:
                        logging.error(f"Failed to load {url} after {MAX_RETRIES} attempts: {e}")
                        return []
                    logging.warning(f"Retry {attempt + 1}/{MAX_RETRIES} for {url}: {e}")
                    await asyncio.sleep(1)  # Wait before retry

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

        except Exception as e:
            logging.error(f"Error scraping {url}: {e}")
            return []
        finally:
            await page.close()

@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    try:
        tasks = [
            scrape_page(f"{req.base_url}?page={p}")
            for p in range(1, req.total_pages + 1)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Flatten and filter out failed tasks
        flat = [item for sublist in results if isinstance(sublist, list) for item in sublist]
        
        if not flat:
            raise HTTPException(status_code=204, detail="No data scraped.")
            
        return {
            "status": "success",
            "count": len(flat),
            "data": flat
        }
    except Exception as e:
        logging.error(f"Scraping failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("shutdown")
async def shutdown_event():
    global browser, playwright
    if browser:
        await browser.close()
    if playwright:
        await playwright.stop()
