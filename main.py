import os
import asyncio
import random
import uuid
import pandas as pd
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# --- Configuration ---
HEADLESS = True
USE_AGENT = True
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/112.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.01.722.58",
]
PROXIES = [None]

# --- FastAPI setup ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://91cbe760-1127-49d7-ae27-85bed47022aa.lovableproject.com",
        "https://bf2aeaa9-1c53-465a-85da-704004dcf688.lovableproject.com",
        "https://e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovableproject.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScrapeRequest(BaseModel):
    base_url: str = "https://clutch.co/agencies/digital-marketing"
    total_pages: int = 3
    headless: bool = HEADLESS

# In-memory job store
jobs: dict[str, dict] = {}

# --- Scraping logic ---
async def scrape_page(url: str, headless: bool, ua: str | None, proxy: str | None):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context_kwargs = {}
        if ua:
            context_kwargs["user_agent"] = ua
        if proxy:
            context_kwargs["proxy"] = {"server": proxy}
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        await page.goto(url, timeout=120_000)
        await page.wait_for_load_state("networkidle", timeout=60_000)
        await page.wait_for_selector("a.provider__title-link.directory_profile", timeout=60_000)

        names = await page.eval_on_selector_all(
            "a.provider__title-link.directory_profile",
            "els => els.map(el => el.textContent.trim())"
        )

        raw_sites = await page.evaluate("""
        () => {
          const sel = "a.provider__cta-link.sg-button-v2.sg-button-v2--primary.website-link__item.website-link__item--non-ppc";
          return Array.from(document.querySelectorAll(sel)).map(el => {
            const href = el.getAttribute("href");
            let dest = null;
            try {
              const params = new URL(href, location.origin).searchParams;
              dest = params.get("u") ? decodeURIComponent(params.get("u")) : null;
            } catch {}
            return { destination_url: dest };
          });
        }
        """)

        locations = await page.eval_on_selector_all(
            ".provider__highlights-item.sg-tooltip-v2.location",
            "els => els.map(el => el.textContent.trim())"
        )

        await browser.close()
        return names, raw_sites, locations

async def run_scraper(base_url: str, total_pages: int, headless: bool, out_path: str):
    all_data = []
    for page_num in range(1, total_pages + 1):
        await asyncio.sleep(random.uniform(1, 3))
        paged_url = f"{base_url}?page={page_num}"
        ua = random.choice(USER_AGENTS) if USE_AGENT else None
        proxy = random.choice(PROXIES)
        try:
            names, raw_sites, locations = await scrape_page(paged_url, headless, ua, proxy)
        except Exception:
            continue
        for idx, name in enumerate(names):
            raw = raw_sites[idx]["destination_url"] if idx < len(raw_sites) else None
            site = None
            if raw:
                p = urlparse(raw)
                site = f"{p.scheme}://{p.netloc}"
            loc = locations[idx] if idx < len(locations) else None
            all_data.append({
                "S.No": len(all_data) + 1,
                "Company": name,
                "Website": site,
                "Location": loc
            })

    df = pd.DataFrame(all_data)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    return len(df)

def _do_scrape(job_id: str, base_url: str, total_pages: int, headless: bool):
    """Background runner—updates jobs[job_id]."""
    try:
        filename = f"{job_id}_clutch.csv"
        count = asyncio.run(run_scraper(base_url, total_pages, headless, filename))
        jobs[job_id].update({"status": "success", "records": count, "file": filename})
    except Exception as e:
        jobs[job_id].update({"status": "error", "message": str(e)})

# --- API Endpoints ---
@app.get("/")
async def root():
    return {"status": "alive"}

@app.post("/scrape", status_code=202)
async def scrape_endpoint(req: ScrapeRequest, background_tasks: BackgroundTasks):
    job_id = uuid.uuid4().hex
    jobs[job_id] = {"status": "pending", "records": 0}
    background_tasks.add_task(_do_scrape, job_id, req.base_url, req.total_pages, req.headless)
    return {"status": "accepted", "job_id": job_id}

@app.get("/status/{job_id}")
async def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job

@app.get("/download/{job_id}")
async def download(job_id: str):
    job = jobs.get(job_id)
    if not job or job.get("status") != "success":
        raise HTTPException(404, "File not available")
    path = job["file"]
    if not os.path.exists(path):
        raise HTTPException(404, "File not found on disk")
    # Stream back the CSV with correct headers
    return FileResponse(path, media_type="text/csv", filename=os.path.basename(path))
