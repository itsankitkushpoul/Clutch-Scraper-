from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio
import random
import logging
import time
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from urllib.parse import urlparse, urljoin
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any, Optional

# Enable basic logging
logging.basicConfig(level=logging.INFO)

# Configuration
HEADLESS = True
ENABLE_CORS = True
MAX_CONCURRENT_TASKS = 3  # Reduced to avoid overwhelming the server
RETRIES = 3
REQUEST_TIMEOUT = 60000  # 60 seconds
PAGE_LOAD_TIMEOUT = 30000  # 30 seconds
DELAY_BETWEEN_REQUESTS = (2, 5)  # Random delay range in seconds

# More realistic user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36"
]

# Add working proxies if available, else keep as [None]
# Format: "http://user:pass@host:port" or "socks5://user:pass@host:port"
PROXIES = [None]

# Request schema
class ScrapeRequest(BaseModel):
    base_url: HttpUrl
    total_pages: conint(gt=0, le=20) = 3

# FastAPI app
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

async def extract_full_page_data(page, url):
    from urllib.parse import urlparse
    try:
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

    except Exception as e:
        logging.error(f"Failed to extract full page data from {url}: {e}")
        return []

async def is_last_page(page) -> bool:
    """Check if the current page is the last page of results."""
    try:
        next_button = await page.query_selector('li.page-item.next:not(.disabled) a.page-link[rel="next"]')
        return next_button is None
    except Exception as e:
        logging.warning(f"Error checking for last page: {e}")
        return True

async def scrape_single_page(pw, base_url: str, page_num: int, context=None, browser=None) -> tuple[list[dict], bool, Optional[Any], Optional[Any]]:
    """
    Scrape a single page of results.
    Returns a tuple of (results, is_last_page, context, browser)
    """
    ua = random.choice(USER_AGENTS)
    proxy = random.choice(PROXIES)
    url = f"{base_url}?page={page_num}" if '?' not in base_url else f"{base_url}&page={page_num}"
    
    # Use existing context and browser if provided
    close_browser = False
    if context is None or browser is None:
        close_browser = True
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=['--disable-blink-features=AutomationControlled']
        )
        context = await browser.new_context(
            user_agent=ua,
            viewport={'width': random.randint(1200, 1600), 'height': random.randint(800, 1200)},
            proxy={"server": proxy} if proxy else None,
            # Disable WebDriver flag
            java_script_enabled=True,
            bypass_csp=True
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
    
    page = None
    try:
        page = await context.new_page()
        
        # Set extra headers to appear more like a real browser
        await page.set_extra_http_headers({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.google.com/'
        })
        
        # Randomize viewport size and other browser properties
        await page.set_viewport_size({
            'width': random.randint(1200, 1920),
            'height': random.randint(800, 1080)
        })
        
        logging.info(f"Loading {url} (attempt 1)")
        
        # Navigate with timeout and wait for the main content
        await page.goto(url, timeout=REQUEST_TIMEOUT, wait_until='domcontentloaded')
        
        # Wait for either the content to load or a captcha to appear
        try:
            await asyncio.wait_for(
                page.wait_for_selector('.provider-row, .provider__title-link, .captcha', state='visible', timeout=PAGE_LOAD_TIMEOUT),
                timeout=PAGE_LOAD_TIMEOUT / 1000 + 5
            )
        except (PlaywrightTimeoutError, asyncio.TimeoutError):
            logging.warning(f"Timeout waiting for content on {url}")
            if close_browser:
                await context.close()
                await browser.close()
            return [], True, None, None
        
        # Check for captcha
        captcha = await page.query_selector('.captcha, #captcha')
        if captcha:
            logging.warning("Captcha detected. Please solve it manually or use a proxy.")
            if close_browser:
                await context.close()
                await browser.close()
            return [], True, None, None
        
        # Check if we're on the last page
        is_last = await is_last_page(page)
        
        # Extract data
        result = await extract_full_page_data(page, url)
        
        # Random delay between requests to appear more human-like
        if not is_last:
            delay = random.uniform(*DELAY_BETWEEN_REQUESTS)
            logging.info(f"Waiting {delay:.2f} seconds before next request...")
            await asyncio.sleep(delay)
        
        if close_browser:
            await context.close()
            await browser.close()
            return result, is_last, None, None
        else:
            return result, is_last, context, browser
            
    except Exception as e:
        logging.error(f"Error on {url}: {str(e)}")
        if page:
            await page.screenshot(path=f'error_page_{page_num}.png')
        if close_browser and browser:
            await context.close()
            await browser.close()
        return [], True, None, None
    finally:
        if page and close_browser:
            await page.close()

async def scrape_with_retry(pw, base_url: str, max_pages: int = 20) -> List[Dict]:
    """Scrape multiple pages with retry logic and proper session management."""
    results = []
    page_num = 1
    context = None
    browser = None
    
    try:
        async with async_playwright() as pw_session:
            while page_num <= max_pages:
                logging.info(f"Scraping page {page_num}...")
                
                # Scrape the current page
                page_results, is_last_page, context, browser = await scrape_single_page(
                    pw_session, base_url, page_num, context, browser
                )
                
                # Add results if any
                if page_results:
                    results.extend(page_results)
                    logging.info(f"Found {len(page_results)} results on page {page_num}")
                else:
                    logging.warning(f"No results found on page {page_num}")
                
                # Stop if we've reached the last page or max pages
                if is_last_page or page_num >= max_pages:
                    logging.info(f"Reached the last page or max pages at page {page_num}")
                    break
                    
                page_num += 1
                
                # Random delay between pages
                delay = random.uniform(*DELAY_BETWEEN_REQUESTS)
                await asyncio.sleep(delay)
                
    except Exception as e:
        logging.error(f"Error during scraping: {str(e)}")
    finally:
        # Clean up resources
        if context:
            await context.close()
        if browser:
            await browser.close()
    
    return results

@app.post("/scrape")
async def scrape_data(req: ScrapeRequest):
    base_url = str(req.base_url)
    total_pages = min(req.total_pages, 50)  # Limit to 50 pages max for safety
    
    # Validate the base URL
    if not base_url.startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail="Invalid URL. Must start with http:// or https://")
    
    if 'clutch.co' not in base_url:
        logging.warning("This scraper is specifically designed for clutch.co. Results may be unexpected.")
    
    logging.info(f"Starting scrape of {base_url} for {total_pages} pages")
    start_time = time.time()
    
    try:
        async with async_playwright() as pw:
            results = await scrape_with_retry(pw, base_url, total_pages)
        
        if not results:
            raise HTTPException(status_code=204, detail="No data scraped. The website might be blocking requests.")
        
        # Remove duplicates based on company name and website
        unique_results = []
        seen = set()
        for item in results:
            key = (item.get('company', ''), item.get('website', ''))
            if key not in seen and all(key):
                seen.add(key)
                unique_results.append(item)
        
        duration = time.time() - start_time
        logging.info(f"Scraping completed in {duration:.2f} seconds. Found {len(unique_results)} unique results.")
        
        return {
            "count": len(unique_results),
            "pages_scraped": min(page_num, total_pages) if 'page_num' in locals() else 0,
            "duration_seconds": round(duration, 2),
            "data": unique_results
        }
        
    except Exception as e:
        logging.error(f"Failed to complete scraping: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")
