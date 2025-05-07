from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random, logging
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from urllib.parse import urlparse
from fastapi.middleware.cors import CORSMiddleware

# ─── Configuration ─────────────────────────────────────────────────────────────
HEADLESS         = True
MAX_CONCURRENT   = 5   # number of parallel contexts/workers
USER_AGENTS      = [
    # populate with 8–10 realistic UAs
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) … Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) … Version/15.6 Safari/605.1.15",
    # …
]
PROXIES          = [None]  # e.g. ["http://user:pass@proxy1:port", …]
ENABLE_CORS      = True
FRONTEND_ORIGINS = [
    "https://e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovableproject.com",
    "https://id-preview--e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovable.app",
    "https://clutch-agency-explorer-ui.lovable.app",
    "https://preview--clutch-agency-explorer-ui.lovable.app",
]

logging.basicConfig(level=logging.INFO)

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

# ─── Request Schema (no upper cap) ──────────────────────────────────────────────
class ScrapeRequest(BaseModel):
    base_url: HttpUrl
    total_pages: conint(gt=0) = 3

# ─── Globals for Playwright ────────────────────────────────────────────────────
browser: Browser                  = None
context_pool: list[BrowserContext] = []
queue: asyncio.Queue             = asyncio.Queue()
results: list                    = []

# ─── Startup & Shutdown ────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    global browser, context_pool
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=HEADLESS)
    logging.info("▶ Playwright browser launched")

    # Pre-create a pool of contexts—one per worker
    for i in range(MAX_CONCURRENT):
        proxy = random.choice(PROXIES)
        ua    = random.choice(USER_AGENTS)
        ctx = await browser.new_context(
            user_agent=ua,
            proxy={"server": proxy} if proxy else None
        )
        context_pool.append(ctx)
    logging.info(f"▶ Created {len(context_pool)} browser contexts for workers")

@app.on_event("shutdown")
async def shutdown():
    for ctx in context_pool:
        await ctx.close()
    await browser.close()
    logging.info("◼ All contexts & browser closed")

# ─── Utilities ────────────────────────────────────────────────────────────────
async def auto_scroll(page: Page):
    prev_h = await page.evaluate("document.body.scrollHeight")
    while True:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1 + random.random())
        new_h = await page.evaluate("document.body.scrollHeight")
        if new_h == prev_h:
            break
        prev_h = new_h

async def scrape_page(page: Page, url: str) -> list[dict]:
    """Load, detect rate-limit, scroll, extract, return."""
    try:
        await page.goto(url, timeout=120_000)
    except Exception as e:
        logging.error(f"[{url}] initial load failed: {e}")
        return []

    content = await page.content()
    if "captcha" in content.lower() or "rate limit" in content.lower():
        logging.warning(f"[{url}] Possible block detected—waiting 60s then retry")
        await page.wait_for_timeout(60_000)
        try:
            await page.goto(url, timeout=120_000)
        except Exception as e:
            logging.error(f"[{url}] retry failed: {e}")
            return []

    await auto_scroll(page)
    await page.wait_for_load_state("networkidle")

    # ---- extract regular listings ----
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

    if not (len(names) == len(raw_links) == len(locs)):
        logging.warning(
            f"[{url}] selector mismatch: "
            f"names={len(names)}, links={len(raw_links)}, locs={len(locs)}"
        )

    out = []
    for i, nm in enumerate(names):
        raw = (raw_links[i] if i < len(raw_links) else None)
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

    # ---- extract featured listings ----
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
        raw = (f_raws[i] if i < len(f_raws) else None)
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

# ─── /scrape Endpoint ─────────────────────────────────────────────────────────
@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    # 1) build URL queue
    for i in range(1, req.total_pages + 1):
        await queue.put(f"{req.base_url}?page={i}")
    logging.info(f"Enqueued {req.total_pages} pages to scrape")

    # 2) worker coroutine
    async def worker(idx: int):
        ctx = context_pool[idx]
        while True:
            try:
                url = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            page = await ctx.new_page()
            try:
                data = await scrape_page(page, url)
                results.extend(data)
            except Exception as e:
                logging.error(f"[Worker {idx}] error on {url}: {e}")
            finally:
                await page.close()
                await asyncio.sleep(random.uniform(0.5, 1.5))
                queue.task_done()

    # 3) spawn & await workers
    tasks = [asyncio.create_task(worker(i)) for i in range(MAX_CONCURRENT)]
    await queue.join()
    for t in tasks:
        t.cancel()

    if not results:
        raise HTTPException(status_code=204, detail="No data scraped")

    return {"count": len(results), "data": results}
