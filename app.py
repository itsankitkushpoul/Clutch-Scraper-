import os
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl, conint

ENABLE_CORS = True
FRONTEND_ORIGINS = [
    "https://e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovableproject.com",
    "https://id-preview--e51cf8eb-9b6c-4f29-b00d-077534d53b9d.lovable.app",
    "https://clutch-agency-explorer-ui.lovable.app",
    "https://preview--clutch-agency-explorer-ui.lovable.app",
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

    project_dir = os.path.dirname(__file__)
    proc = subprocess.run(
        cmd,
        cwd=project_dir,
        capture_output=True,
        text=True
    )

    # Print stdout and stderr for debugging
    print("STDOUT:\n", proc.stdout)
    print("STDERR:\n", proc.stderr)

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr)

    return {"status": "ok", "output_file": "results.json"}

@app.get("/download")
def download_results():
    file_path = os.path.join(os.path.dirname(__file__), "results.json")
    if os.path.exists(file_path):
        return FileResponse(path=file_path, filename="results.json", media_type='application/json')
    raise HTTPException(status_code=404, detail="results.json not found")
