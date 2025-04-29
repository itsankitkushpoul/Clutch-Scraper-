import os
import asyncio
import random
import traceback
import pandas as pd
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from tqdm import tqdm
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware  # ✅ Add this line

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

# ✅ Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://preview--clutch-agency-explorer.lovable.app/"],  # Replace "*" with your frontend domain for production (e.g. "https://your-frontend.lovable.app")
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScrapeRequest(BaseModel):
    base_url: str = "https://clutch.co/agencies/digital-marketing"
    total_pages: int = 3
    headless: bool = HEADLESS

# (The rest of your code remains unchanged)
# ... scrape_page, run_scraper, and endpoints ...

@app.get("/")
async def root():
    return {"status": "alive"}

@app.post("/scrape")
async def scrape_endpoint(req: ScrapeRequest):
    try:
        count, filename = await run_scraper(req.base_url, req.total_pages, req.headless)
        return {"status": "success", "records": count, "file": filename}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download")
async def download():
    path = "clutch_companies.csv"
    if os.path.exists(path):
        return FileResponse(path, filename=path)
    raise HTTPException(status_code=404, detail="Not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
