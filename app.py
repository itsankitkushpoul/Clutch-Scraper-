from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, random, logging
from urllib.parse import urlparse
from pyppeteer_cluster import Cluster
from fastapi.middleware.cors import CORSMiddleware

# ─── Configuration ─────────────────────────────────────────────────────────────
HEADLESS = True
MAX_CONCURRENT = 5   # number of parallel contexts/workers
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) … Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) … Version/15.6 Safari/605.1.15",
    # … add other user agents
]
PROXIES = [None]  # e.g. ["http://user:pass@proxy1:port", …]
ENABLE_CORS = True
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

# ─── Request Schema ────────────────────────────────────────────────────────────
class ScrapeRequest(BaseModel):
    base_url: HttpUrl
    total_pages: conint(gt=0) = 3

# ─── Cluster Setup ─────────────────────────────────────────────────────────────
cluster = None  # Cluster will be initialized in the startup event

@app.on_event("startup")
async def startup():
    global cluster
    cluster = await Cluster.launch(
        page_pool_size=MAX_CONCURRENT,
        headless=HEADLESS,
        user_agent=random.choice(USER_AGENTS),
        proxies=PROXIES,
    )
    logging.info("▶ Pyppeteer Cluster launched")

@app.on_event("shutdown")
async def shutdown():
    await cluster.close()
    logging.info("◼ Pyppeteer Cluster closed")

# ─── Scraping Logic ────────────────────────────────────────────────────────────
async def scrape_page(page, url: str) -> list[dict]:
    """Load, scroll, extract, and return data."""
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

    # Auto-scroll to ensure lazy-loaded content is fetched
    prev_h = await page.evaluate("document.body.scrollHeight")
    while True:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1 + random.random())
        new_h = await page.evaluate("document.body.scrollHeight")
        if new_h == prev_h:
            break
        prev_h = new_h

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
    urls = [f"{req.base_url}?page={p}" for p in range(1, req.total_pages + 1)]
    logging.info(f"Scraping {len(urls)} pages")

    # 2) Worker task function for cluster
    async def worker(url):
        page = await cluster.new_page()
        try:
            return await scrape_page(page, url)
        except Exception as e:
            logging.error(f"Error scraping {url}: {e}")
            return []
        finally:
            await page.close()

    # 3) Process all URLs in parallel with the cluster
    tasks = [worker(url) for url in urls]
    results = await asyncio.gather(*tasks)

    # Flatten the results from all pages
    flat_results = [item for sublist in results for item in sublist]

    if not flat_results:
        raise HTTPException(status_code=204, detail="No data scraped")

    return {"count": len(flat_results), "data": flat_results}
