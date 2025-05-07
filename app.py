from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random, logging
from urllib.parse import urlparse
from playwright.async_api import async_playwright, Browser, BrowserContext
from fastapi.middleware.cors import CORSMiddleware

# ─── Configuration ─────────────────────────────────────────────────────────────
HEADLESS = True
MAX_CONCURRENT = 5
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Version/15.6 Safari/605.1.15",
]
PROXIES = [None]
ENABLE_CORS = True
FRONTEND_ORIGINS = [
    "https://e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovableproject.com",
    "https://id-preview--e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovable.app",
    "https://clutch-agency-explorer-ui.lovable.app",
    "https://preview--clutch-agency-explorer-ui.lovable.app",
]

logging.basicConfig(level=logging.INFO)

# ─── FastAPI App ───────────────────────────────────────────────────────────────
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

# ─── Models ────────────────────────────────────────────────────────────────────
class ScrapeRequest(BaseModel):
    base_url: HttpUrl
    total_pages: conint(gt=0) = 3

# ─── Global Objects ────────────────────────────────────────────────────────────
playwright = None
browser: Browser = None
context_pool: list[BrowserContext] = []

@app.on_event("startup")
async def startup():
    global playwright, browser, context_pool
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=HEADLESS)
    context_pool = []

    for i in range(MAX_CONCURRENT):
        proxy = random.choice(PROXIES) if PROXIES else None
        args = {"user_agent": random.choice(USER_AGENTS)}
        if proxy:
            args["proxy"] = {"server": proxy}
        ctx = await browser.new_context(**args)
        context_pool.append(ctx)

    logging.info(f"▶ Playwright started with {MAX_CONCURRENT} contexts")

@app.on_event("shutdown")
async def shutdown():
    for ctx in context_pool:
        await ctx.close()
    await browser.close()
    await playwright.stop()
    logging.info("◼ Playwright shutdown complete")

# ─── Scraping Function ─────────────────────────────────────────────────────────
async def scrape_page(page, url: str) -> list[dict]:
    try:
        await page.goto(url, timeout=120_000)
    except Exception as e:
        logging.error(f"[{url}] Load failed: {e}")
        return []

    content = await page.content()
    if "captcha" in content.lower() or "rate limit" in content.lower():
        logging.warning(f"[{url}] Blocked? Waiting and retrying...")
        await page.wait_for_timeout(60_000)
        try:
            await page.goto(url, timeout=120_000)
        except:
            return []

    prev_h = await page.evaluate("document.body.scrollHeight")
    while True:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1 + random.random())
        new_h = await page.evaluate("document.body.scrollHeight")
        if new_h == prev_h:
            break
        prev_h = new_h

    await page.wait_for_load_state("networkidle")

    names = await page.eval_on_selector_all(
        "a.provider__title-link.directory_profile",
        "els => els.map(e => e.textContent.trim())"
    )
    raw_links = await page.evaluate("""() => Array.from(
        document.querySelectorAll('a.provider__cta-link.sg-button-v2--primary.website-link__item--non-ppc')
    ).map(el => {
        try {
            let u = new URL(el.href, location.origin).searchParams.get("u");
            return u ? decodeURIComponent(u) : null;
        } catch { return null; }
    })""")
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

    f_names = await page.eval_on_selector_all(
        "a.provider__title-link.ppc-website-link",
        "els => els.map(e => e.textContent.trim())"
    )
    f_raws = await page.evaluate("""() => Array.from(
        document.querySelectorAll('a.provider__cta-link.ppc_position--link')
    ).map(el => {
        try {
            let u = new URL(el.href, location.origin).searchParams.get("u");
            return u ? decodeURIComponent(u) : null;
        } catch { return null; }
    })""")
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

# ─── Endpoint ──────────────────────────────────────────────────────────────────
@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    urls = [f"{req.base_url}?page={p}" for p in range(1, req.total_pages + 1)]
    logging.info(f"Scraping {len(urls)} pages...")

    results = []

    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def worker(url):
        async with sem:
            ctx = random.choice(context_pool)
            page = await ctx.new_page()
            try:
                return await scrape_page(page, url)
            except Exception as e:
                logging.error(f"[{url}] scraping failed: {e}")
                return []
            finally:
                await page.close()

    tasks = [worker(url) for url in urls]
    res = await asyncio.gather(*tasks)
    for r in res:
        results.extend(r)

    if not results:
        raise HTTPException(status_code=204, detail="No data scraped")

    return {"count": len(results), "data": results}
