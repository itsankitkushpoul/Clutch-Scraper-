from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl, conint
import asyncio, logging
from urllib.parse import urlparse

# pip install pyppeteer-cluster pyppeteer
from pyppeteer_cluster import Cluster
from pyppeteer import launch

# ─── Configuration ─────────────────────────────────────────────────────────────
HEADLESS       = True
MAX_CONCURRENT = 5   # number of parallel Chromium workers
USER_AGENTS    = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) … Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) … Version/15.6 Safari/605.1.15",
    # … add 6–8 more realistic strings
]
PROXIES        = [None]  # e.g. "http://user:pass@proxy:port"
ENABLE_CORS    = True
FRONTEND_ORIGINS = [
    "https://e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovableproject.com",
    "https://id-preview--e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovable.app",
    "https://clutch-agency-explorer-ui.lovable.app",
    "https://preview--clutch-agency-explorer-ui.lovable.app",
]

logging.basicConfig(level=logging.INFO)

# ─── FastAPI App & CORS ────────────────────────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware

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

# ─── Scrape Endpoint Using pyppeteer-cluster ──────────────────────────────────
@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    urls = [f"{req.base_url}?page={i}" for i in range(1, req.total_pages + 1)]
    results = []

    # 1) Launch a pyppeteer-cluster
    cluster = await Cluster.launch(
        concurrency=Cluster.CONCURRENCY_CONTEXT,  # one context per worker
        max_workers=MAX_CONCURRENT,
        browser_launch_kwargs={
            "headless": HEADLESS,
            # you can add {"args": ["--no-sandbox"]} here if needed
        },
        cluster_options={
            "monitor": False,
        }
    )

    # 2) Define a worker function
    async def worker_task(page, data):
        url = data
        # Rotate UA & proxy
        ua = USER_AGENTS[hash(url) % len(USER_AGENTS)]
        await page.setUserAgent(ua)
        proxy = PROXIES[hash(url[::-1]) % len(PROXIES)]
        if proxy:
            # pyppeteer Cluster does not support per-page proxy natively;
            # you'd incorporate it in launch args if needed.
            pass

        try:
            await page.goto(url, {"timeout": 120_000, "waitUntil": "networkidle2"})
        except Exception as e:
            logging.error(f"[{url}] initial load failed: {e}")
            return

        content = await page.content()
        if "captcha" in content.lower() or "rate limit" in content.lower():
            logging.warning(f"[{url}] blocked – backing off 60s")
            await asyncio.sleep(60)
            try:
                await page.goto(url, {"timeout": 120_000, "waitUntil": "networkidle2"})
            except Exception as e:
                logging.error(f"[{url}] retry failed: {e}")
                return

        # Auto‐scroll until bottom
        prev_h = await page.evaluate("() => document.body.scrollHeight")
        while True:
            await page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1 + random.random())
            new_h = await page.evaluate("() => document.body.scrollHeight")
            if new_h == prev_h:
                break
            prev_h = new_h

        # Extract listings
        names = await page.evaluate(
            """() => Array.from(
                  document.querySelectorAll('a.provider__title-link.directory_profile'))
                .map(el => el.textContent.trim())"""
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
                })"""
        )
        locs = await page.evaluate(
            """() => Array.from(
                  document.querySelectorAll('.provider__highlights-item.sg-tooltip-v2.location'))
                .map(el => el.textContent.trim())"""
        )

        # Sanity check
        if not (len(names) == len(raw_links) == len(locs)):
            logging.warning(
                f"[{url}] selector mismatch: names={len(names)}, "
                f"links={len(raw_links)}, locs={len(locs)}"
            )

        # Build result objects
        for i, nm in enumerate(names):
            raw = raw_links[i] if i < len(raw_links) else None
            site = None
            if raw:
                p = urlparse(raw)
                site = f"{p.scheme}://{p.netloc}"
            results.append({
                "company": nm,
                "website": site,
                "location": locs[i] if i < len(locs) else None,
                "featured": False
            })

        # Featured listings
        f_names = await page.evaluate(
            """() => Array.from(
                  document.querySelectorAll('a.provider__title-link.ppc-website-link'))
                .map(el => el.textContent.trim())"""
        )
        f_raws = await page.evaluate(
            """() => Array.from(
                  document.querySelectorAll('a.provider__cta-link.ppc_position--link'))
                .map(el => {
                  try {
                    let u = new URL(el.href, location.origin).searchParams.get("u");
                    return u ? decodeURIComponent(u) : null;
                  } catch { return null; }
                })"""
        )
        f_locs = await page.evaluate(
            """() => Array.from(
                  document.querySelectorAll('div.provider__highlights-item.sg-tooltip-v2.location'))
                .map(el => el.textContent.trim())"""
        )
        for i, nm in enumerate(f_names):
            raw = f_raws[i] if i < len(f_raws) else None
            site = None
            if raw:
                p = urlparse(raw)
                site = f"{p.scheme}://{p.netloc}"
            results.append({
                "company": nm,
                "website": site,
                "location": f_locs[i] if i < len(f_locs) else None,
                "featured": True
            })

        logging.info(f"[{url}] scraped {len(names) + len(f_names)} items")

    # 3) Queue up all URLs
    for url in urls:
        await cluster.queue(worker_task, url)

    # 4) Wait for completion and shutdown
    await cluster.idle()
    await cluster.close()

    if not results:
        raise HTTPException(status_code=204, detail="No data scraped")

    return {"count": len(results), "data": results}
