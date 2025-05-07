from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random, logging
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from urllib.parse import urlparse
from fastapi.middleware.cors import CORSMiddleware

# ─── Configuration ─────────────────────────────────────────────────────────────
HEADLESS         = True
MAX_CONCURRENT   = 5   # tune this: 3–5 for safety, up to 10 if your machine can handle it
USER_AGENTS      = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) … Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) … Version/15.6 Safari/605.1.15",
    # add at least 8–10 more realistic UAs
]
PROXIES          = [None]  # or ["http://user:pass@proxy1:port", ...]
ENABLE_CORS      = True
FRONTEND_ORIGINS = [
    "https://e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovableproject.com",
    "https://id-preview--e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovable.app",
    "https://clutch-agency-explorer-ui.lovable.app",
    "https://preview--clutch-agency-explorer-ui.lovable.app",
]

logging.basicConfig(level=logging.INFO)
semaphore = asyncio.Semaphore(MAX_CONCURRENT)

# ─── FastAPI App & CORS ────────────────────────────────────────────────────────
app = FastAPI(title="Clutch Scraper API")
if ENABLE_CORS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logging.info(f"CORS enabled for: {FRONTEND_ORIGINS}")

@app.get("/health")
def health():
    return {"status": "ok"}

# ─── Request Schema (no hard upper‐bound) ────────────────────────────────────────
class ScrapeRequest(BaseModel):
    base_url: HttpUrl
    total_pages: conint(gt=0) = 3

# ─── Globals for Playwright ────────────────────────────────────────────────────
browser: Browser        = None
context: BrowserContext = None

@app.on_event("startup")
async def startup():
    global browser, context
    playwright = await async_playwright().start()
    browser   = await playwright.chromium.launch(headless=HEADLESS)
    # Create one context for all pages: will rotate UA/proxy per page below
    context = await browser.new_context()
    logging.info("▶ Playwright launched and context created")

@app.on_event("shutdown")
async def shutdown():
    await context.close()
    await browser.close()
    logging.info("◼ Playwright context & browser closed")

# ─── Utilities ────────────────────────────────────────────────────────────────
async def auto_scroll(page: Page):
    """Scroll to bottom in a loop until no more new content loads."""
    prev_height = await page.evaluate("document.body.scrollHeight")
    while True:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1 + random.random())
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == prev_height:
            break
        prev_height = new_height

async def scrape_page(page: Page, url: str) -> list:
    """Navigate, detect rate‐limit, scroll, extract, and return results."""
    # Rotate UA and proxy per page
    ua = random.choice(USER_AGENTS)
    proxy = random.choice(PROXIES)
    await page.context.set_extra_http_headers({"User-Agent": ua})
    if proxy:
        await page.context.set_proxy({"server": proxy})

    try:
        await page.goto(url, timeout=120_000)
    except Exception as e:
        logging.error(f"[{url}] failed to load: {e}")
        return []

    content = await page.content()
    if "rate limit" in content.lower() or "captcha" in content.lower():
        logging.warning(f"[{url}] rate limited or CAPTCHA detected; backing off 60s")
        await page.wait_for_timeout(60_000)
        # try once more
        try:
            await page.goto(url, timeout=120_000)
        except:
            return []

    # Trigger lazy‐loads
    await auto_scroll(page)
    await page.wait_for_load_state("networkidle")

    # Extract standard listings
    names     = await page.eval_on_selector_all(
        "a.provider__title-link.directory_profile",
        "els => els.map(e => e.textContent.trim())"
    )
    raw_links = await page.evaluate(
        """() => Array.from(
              document.querySelectorAll(
                'a.provider__cta-link.sg-button-v2--primary.website-link__item--non-ppc'))
            .map(el => {
              try {
                let u = new URL(el.href, location.origin).searchParams.get("u");
                return u ? decodeURIComponent(u) : null;
              } catch { return null; }
            });"""
    )
    locs      = await page.eval_on_selector_all(
        ".provider__highlights-item.sg-tooltip-v2.location",
        "els => els.map(e => e.textContent.trim())"
    )

    # Sanity check
    if not (len(names) == len(raw_links) == len(locs)):
        logging.warning(
            f"[{url}] selector mismatch: names={len(names)}, "
            f"links={len(raw_links)}, locs={len(locs)}"
        )

    results = []
    for i, name in enumerate(names):
        raw = raw_links[i] if i < len(raw_links) else None
        website = None
        if raw:
            p = urlparse(raw)
            website = f"{p.scheme}://{p.netloc}"
        results.append({
            "company": name,
            "website": website,
            "location": locs[i] if i < len(locs) else None,
            "featured": False
        })

    # Extract featured listings
    f_names     = await page.eval_on_selector_all(
        "a.provider__title-link.ppc-website-link",
        "els => els.map(e => e.textContent.trim())"
    )
    f_raw_links = await page.evaluate(
        """() => Array.from(
              document.querySelectorAll('a.provider__cta-link.ppc_position--link'))
            .map(el => {
              try {
                let u = new URL(el.href, location.origin).searchParams.get("u");
                return u ? decodeURIComponent(u) : null;
              } catch { return null; }
            });"""
    )
    f_locs      = await page.eval_on_selector_all(
        "div.provider__highlights-item.sg-tooltip-v2.location",
        "els => els.map(e => e.textContent.trim())"
    )

    for i, name in enumerate(f_names):
        raw = f_raw_links[i] if i < len(f_raw_links) else None
        website = None
        if raw:
            p = urlparse(raw)
            website = f"{p.scheme}://{p.netloc}"
        results.append({
            "company": name,
            "website": website,
            "location": f_locs[i] if i < len(f_locs) else None,
            "featured": True
        })

    logging.info(f"[{url}] scraped {len(results)} entries")
    return results

# ─── Scrape Endpoint with Bounded Queue ───────────────────────────────────────
@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    urls = [f"{req.base_url}?page={i}" for i in range(1, req.total_pages + 1)]
    results = []

    queue = asyncio.Queue()
    for u in urls:
        await queue.put(u)

    async def worker(name: str):
        while True:
            try:
                url = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            async with semaphore:
                page = await context.new_page()
                try:
                    data = await scrape_page(page, url)
                    results.extend(data)
                except Exception as e:
                    logging.error(f"[{name}] error on {url}: {e}")
                finally:
                    await page.close()
                    # random delay to avoid bans
                    await asyncio.sleep(random.uniform(0.5, 1.5))
            queue.task_done()

    # spawn workers
    workers = [asyncio.create_task(worker(f"W{i}")) for i in range(MAX_CONCURRENT)]
    await queue.join()
    for w in workers:
        w.cancel()

    if not results:
        raise HTTPException(status_code=204, detail="No data scraped")

    return {"count": len(results), "data": results}
