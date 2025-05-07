from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random, logging
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Browser, BrowserContext
from fastapi.middleware.cors import CORSMiddleware

# ─── Configuration ─────────────────────────────────────────────────────────────
HEADLESS        = True
MAX_CONCURRENT  = 5
USER_AGENTS     = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Version/15.6 Safari/605.1.15",
]
PROXIES         = [None]
ENABLE_CORS     = True
FRONTEND_ORIGINS = [
    "https://e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovableproject.com",
    "https://id-preview--e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovable.app",
    "https://clutch-agency-explorer-ui.lovable.app",
    "https://preview--clutch-agency-explorer-ui.lovable.app",
]

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Clutch Scraper API")
if ENABLE_CORS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

@app.get("/health")
def health():
    return {"status": "ok"}

class ScrapeRequest(BaseModel):
    base_url: HttpUrl
    total_pages: conint(gt=0) = 3

# ─── Globals ──────────────────────────────────────────────────────────────────
_playwright = None
_browser: Browser = None
_contexts: list[BrowserContext] = []

@app.on_event("startup")
async def startup():
    global _playwright, _browser, _contexts
    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=HEADLESS)
    # pre-create contexts
    for _ in range(MAX_CONCURRENT):
        opts = {"user_agent": random.choice(USER_AGENTS)}
        proxy = random.choice(PROXIES)
        if proxy:
            opts["proxy"] = {"server": proxy}
        ctx = await _browser.new_context(**opts)
        _contexts.append(ctx)
    logging.info(f"▶ Started Playwright with {len(_contexts)} contexts")

@app.on_event("shutdown")
async def shutdown():
    for ctx in _contexts:
        await ctx.close()
    await _browser.close()
    await _playwright.stop()
    logging.info("◼ Playwright shut down")

async def scrape_page(page, url: str) -> list[dict]:
    try:
        await page.goto(url, timeout=120_000)
    except Exception as e:
        logging.error(f"[{url}] goto failed: {e}")
        return []

    content = await page.content()
    if any(block in content.lower() for block in ("captcha", "rate limit")):
        logging.warning(f"[{url}] blocked, backing off 60s…")
        await page.wait_for_timeout(60_000)
        try:
            await page.goto(url, timeout=120_000)
        except:
            return []

    # fully scroll
    prev_h = await page.evaluate("() => document.body.scrollHeight")
    while True:
        await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1 + random.random())
        new_h = await page.evaluate("() => document.body.scrollHeight")
        if new_h == prev_h:
            break
        prev_h = new_h

    await page.wait_for_load_state("networkidle")

    # extract data…
    names = await page.eval_on_selector_all(
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
    locs = await page.eval_on_selector_all(
        ".provider__highlights-item.sg-tooltip-v2.location",
        "els => els.map(e => e.textContent.trim())"
    )

    out = []
    for i, nm in enumerate(names):
        raw = raw_links[i] if i < len(raw_links) else None
        site = None
        if raw:
            p = urlparse(raw)
            site = f"{p.scheme}://{p.netloc}"
        out.append({
            "company": nm,
            "website": site,
            "location": (locs[i] if i < len(locs) else None),
            "featured": False
        })

    # featured
    f_names = await page.eval_on_selector_all(
        "a.provider__title-link.ppc-website-link",
        "els => els.map(e => e.textContent.trim())"
    )
    f_raws = await page.evaluate(
        """() => Array.from(
              document.querySelectorAll('a.provider__cta-link.ppc_position--link'))
            .map(el => {
              try {
                let u = new URL(el.href, location.origin).searchParams.get("u");
                return u ? decodeURIComponent(u) : null;
              } catch { return null; }
            });"""
    )
    f_locs = await page.eval_on_selector_all(
        "div.provider__highlights-item.sg-tooltip-v2.location",
        "els => els.map(e => e.textContent.trim())"
    )

    for i, nm in enumerate(f_names):
        raw = f_raws[i] if i < len(f_raws) else None
        site = None
        if raw:
            p = urlparse(raw)
            site = f"{p.scheme}://{p.netloc}"
        out.append({
            "company": nm,
            "website": site,
            "location": (f_locs[i] if i < len(f_locs) else None),
            "featured": True
        })

    logging.info(f"[{url}] scraped {len(out)} items")
    return out

@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    # local queue & results per-request
    queue: asyncio.Queue[str] = asyncio.Queue()
    results: list[dict] = []

    for p in range(1, req.total_pages + 1):
        queue.put_nowait(f"{req.base_url}?page={p}")

    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def worker(ctx: BrowserContext):
        while not queue.empty():
            url = await queue.get()
            async with sem:
                page = await ctx.new_page()
                try:
                    data = await scrape_page(page, url)
                    results.extend(data)
                finally:
                    await page.close()
            queue.task_done()

    # spawn one worker per context
    tasks = [asyncio.create_task(worker(ctx)) for ctx in _contexts]
    await queue.join()
    for t in tasks:
        t.cancel()

    if not results:
        raise HTTPException(status_code=204, detail="No data scraped")

    return {"count": len(results), "data": results}
