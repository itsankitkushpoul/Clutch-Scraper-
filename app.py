from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random, logging
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from urllib.parse import urlparse
from fastapi.middleware.cors import CORSMiddleware

# ─── Configuration ─────────────────────────────────────────────────────────────
HEADLESS        = True
MAX_CONCURRENT  = 5                # bump this up if your machine can handle it
USER_AGENTS     = [
    # real UA strings here
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) … Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) … Version/15.6 Safari/605.1.15",
]
PROXIES         = [None]           # or ["http://user:pass@proxy:port", …]
ENABLE_CORS     = True
FRONTEND_ORIGINS = [
    "https://e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovableproject.com",
    "https://id-preview--e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovable.app",
    "https://clutch-agency-explorer-ui.lovable.app",
    "https://preview--clutch-agency-explorer-ui.lovable.app"
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

# ─── Global Browser & Context ──────────────────────────────────────────────────
browser: Browser        = None
context: BrowserContext = None

@app.on_event("startup")
async def startup():
    global browser, context
    playwright = await async_playwright().start()
    browser   = await playwright.chromium.launch(headless=HEADLESS)
    # Create one context for all pages—rotate proxy/UA here if you like
    proxy = random.choice(PROXIES)
    ua    = random.choice(USER_AGENTS)
    context = await browser.new_context(
        user_agent=ua,
        proxy={"server": proxy} if proxy else None,
    )
    logging.info("▶ Playwright launched and context created")

@app.on_event("shutdown")
async def shutdown():
    await context.close()
    await browser.close()
    logging.info("◼ Playwright context & browser closed")

# ─── Utilities ────────────────────────────────────────────────────────────────
async def auto_scroll(page: Page):
    """Scroll to bottom in a loop until no more new content."""
    prev_height = await page.evaluate("document.body.scrollHeight")
    while True:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1 + random.random())
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == prev_height:
            break
        prev_height = new_height

async def scrape_page(page: Page, url: str) -> list:
    """Scrape one URL using an existing Page instance."""
    await page.set_extra_http_headers({"User-Agent": random.choice(USER_AGENTS)})
    try:
        await page.goto(url, timeout=120_000)
    except Exception as e:
        logging.error(f"[{url}] failed to load: {e}")
        return []

    # human‐like scroll & wait
    await auto_scroll(page)
    await page.wait_for_load_state("networkidle")

    # extract
    names       = await page.eval_on_selector_all(
        "a.provider__title-link.directory_profile",
        "els => els.map(e => e.textContent.trim())"
    )
    raw_links   = await page.evaluate(
        """() => Array.from(
              document.querySelectorAll(
                'a.provider__cta-link.sg-button-v2--primary.website-link__item--non-ppc'))
            .map(el => {
              try {
                let p = new URL(el.href, location.origin).searchParams.get("u");
                return p ? decodeURIComponent(p) : null;
              } catch { return null; }
            });"""
    )
    locs        = await page.eval_on_selector_all(
        ".provider__highlights-item.sg-tooltip-v2.location",
        "els => els.map(e => e.textContent.trim())"
    )

    # sanity check
    if not (len(names) == len(raw_links) == len(locs)):
        logging.warning(
            f"[{url}] selector mismatch: "
            f"names={len(names)}, links={len(raw_links)}, locs={len(locs)}"
        )

    out = []
    for i, name in enumerate(names):
        raw = raw_links[i] if i < len(raw_links) else None
        website = None
        if raw:
            p = urlparse(raw)
            website = f"{p.scheme}://{p.netloc}"
        out.append({
            "company": name,
            "website": website,
            "location": locs[i] if i < len(locs) else None,
            "featured": False
        })

    # featured
    f_names      = await page.eval_on_selector_all(
        "a.provider__title-link.ppc-website-link",
        "els => els.map(e => e.textContent.trim())"
    )
    f_raw_links  = await page.evaluate(
        """() => Array.from(
              document.querySelectorAll(
                'a.provider__cta-link.ppc_position--link'))
            .map(el => {
              try {
                let p = new URL(el.href, location.origin).searchParams.get("u");
                return p ? decodeURIComponent(p) : null;
              } catch { return null; }
            });"""
    )
    f_locs       = await page.eval_on_selector_all(
        "div.provider__highlights-item.sg-tooltip-v2.location",
        "els => els.map(e => e.textContent.trim())"
    )

    for i, name in enumerate(f_names):
        raw = f_raw_links[i] if i < len(f_raw_links) else None
        website = None
        if raw:
            p = urlparse(raw)
            website = f"{p.scheme}://{p.netloc}"
        out.append({
            "company": name,
            "website": website,
            "location": f_locs[i] if i < len(f_locs) else None,
            "featured": True
        })

    logging.info(f"[{url}] scraped {len(out)} entries")
    return out

# ─── Endpoint ────────────────────────────────────────────────────────────────
@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    # build page URLs
    urls = [f"{req.base_url}?page={i}" for i in range(1, req.total_pages + 1)]
    results = []

    async def worker(u: str):
        async with semaphore:
            page = await context.new_page()
            try:
                data = await scrape_page(page, u)
            finally:
                await page.close()
            return data

    pages = await asyncio.gather(*[worker(u) for u in urls])
    results = [item for sub in pages for item in sub]

    if not results:
        raise HTTPException(status_code=204, detail="No data scraped")

    return {"count": len(results), "data": results}
