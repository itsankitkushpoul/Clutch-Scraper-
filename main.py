#!/usr/bin/env python3
import os
import json
import asyncio
import random
import pandas as pd
from urllib.parse import urlparse
from playwright.async_api import async_playwright

# Default lists (fallbacks if you don't override via ENV)
DEFAULT_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) "
      "Gecko/20100101 Firefox/112.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.01.722.58",
]
DEFAULT_PROXIES = [None]

# Read config from ENV
BASE_URL    = os.getenv("BASE_URL")
TOTAL_PAGES = int(os.getenv("TOTAL_PAGES", "3"))
HEADLESS    = os.getenv("HEADLESS", "true").lower() == "true"
USE_AGENT   = os.getenv("USE_AGENT", "true").lower() == "true"
USER_AGENTS = json.loads(os.getenv("USER_AGENTS", json.dumps(DEFAULT_USER_AGENTS)))
PROXIES     = json.loads(os.getenv("PROXIES", json.dumps(DEFAULT_PROXIES)))

if not BASE_URL:
    raise Exception("Please set BASE_URL env var")

async def scrape_clutch(page, url: str):
    await page.goto(url, timeout=120_000)
    await page.wait_for_load_state("networkidle", timeout=60_000)
    await page.wait_for_selector("a.provider__title-link.directory_profile", timeout=60_000)

    names = await page.eval_on_selector_all(
        "a.provider__title-link.directory_profile",
        "els => els.map(el => el.textContent.trim())"
    )
    websites = await page.evaluate(r"""
    () => {
        const selector = 
          "a.provider__cta-link.sg-button-v2.sg-button-v2--primary"
        + ".website-link__item.website-link__item--non-ppc";
        return Array.from(document.querySelectorAll(selector))
          .map(el => {
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

    rows = []
    for i, name in enumerate(names):
        url_raw = websites[i]["destination_url"] if i < len(websites) else None
        host = (urlparse(url_raw).scheme + "://" + urlparse(url_raw).netloc) if url_raw else None
        loc  = locations[i] if i < len(locations) else None
        rows.append({
            "company": name,
            "website": host,
            "location": loc
        })
    return rows

async def main():
    all_data = []

    # launch browser once, reuse contexts/pages
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=["--disable-dev-shm-usage","--no-sandbox"]
        )
        context = await browser.new_context()

        for page_num in range(1, TOTAL_PAGES + 1):
            await asyncio.sleep(random.uniform(1, 3))
            ua = random.choice(USER_AGENTS) if USE_AGENT else None
            proxy = random.choice(PROXIES)

            # apply per‐page UA/proxy
            if proxy:
                await context.set_proxy({ "server": proxy })
            if ua:
                await context.set_extra_http_headers({ "User-Agent": ua })

            page = await context.new_page()
            url  = f"{BASE_URL}?page={page_num}"
            rows = await scrape_clutch(page, url)
            await page.close()
            all_data.extend(rows)

        await browser.close()

    # Save to CSV
    df = pd.DataFrame(all_data)
    out_path = "/app/clutch_companies.csv"
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"Written {len(df)} rows to {out_path}")

if __name__ == "__main__":
    asyncio.run(main())
