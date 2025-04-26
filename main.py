import os
import asyncio
import random
import pandas as pd
from urllib.parse import urlparse
from tqdm import tqdm
from playwright.async_api import async_playwright

# --- Config via ENV VARS ---
BASE_URL = os.getenv("BASE_URL", "https://clutch.co/agencies/digital-marketing")
TOTAL_PAGES = int(os.getenv("TOTAL_PAGES", "3"))
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)…",
    # … your other agents …
]

PROXIES = [ None ]  # add as needed

async def scrape_page(url, headless, ua, proxy):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context_kwargs = {}
        if proxy:
            context_kwargs["proxy"] = { "server": proxy }
        context = await browser.new_context(**context_kwargs)
        if ua:
            await context.set_extra_http_headers({"User-Agent": ua})
        page = await context.new_page()
        await page.goto(url, timeout=120_000)
        await page.wait_for_load_state("networkidle")
        # … your existing eval/selectors …
        names = await page.eval_on_selector_all(
            "a.provider__title-link.directory_profile",
            "els => els.map(el => el.textContent.trim())"
        )
        data = await page.evaluate("""() => { /* … */ }""")
        locations = await page.eval_on_selector_all(
            ".provider__highlights-item.sg-tooltip-v2.location",
            "els => els.map(el => el.textContent.trim())"
        )
        await browser.close()
        return names, data, locations

async def main():
    print(f"Scraping {TOTAL_PAGES} pages from {BASE_URL}")
    rows = []
    for i in tqdm(range(1, TOTAL_PAGES+1), desc="Pages"):
        await asyncio.sleep(random.uniform(1,3))
        url = f"{BASE_URL}?page={i}"
        ua = random.choice(USER_AGENTS)
        proxy = random.choice(PROXIES)
        names, websites, locs = await scrape_page(url, HEADLESS, ua, proxy)
        for idx, name in enumerate(names):
            raw = websites[idx].get("destination_url") if idx < len(websites) else None
            site = f"{urlparse(raw).scheme}://{urlparse(raw).netloc}" if raw else None
            loc = locs[idx] if idx < len(locs) else None
            rows.append({
                "S.No": len(rows)+1, "Company": name,
                "Website": site, "Location": loc
            })
    df = pd.DataFrame(rows)
    out = "clutch_companies.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"Saved {len(df)} records to {out}")

if __name__ == "__main__":
    asyncio.run(main())
