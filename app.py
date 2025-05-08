import os                      # ← add this
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl, conint

ENABLE_CORS = True
FRONTEND_ORIGINS = [
    "https://…",
    # etc.
]

app = FastAPI(title="Clutch Scraper Controller")

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
    total_pages: conint(gt=0, le=1000) = 3

@app.post("/scrape")
async def run_scrapy(req: ScrapeRequest):
    cmd = [
        "scrapy", "crawl", "clutch",
        "-a", f"base_url={req.base_url}",
        "-a", f"total_pages={req.total_pages}"
    ]

    # ─── NEW ──────────────────────────────────────────────────────────────
    # project_dir now points at the folder containing this app.py (and scrapy.cfg)
    project_dir = os.path.dirname(__file__)
    proc = subprocess.run(
        cmd,
        cwd=project_dir,
        capture_output=True,
        text=True
    )
    # ──────────────────────────────────────────────────────────────────────

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr)

    return {"status": "ok", "output_file": "results.json"}
