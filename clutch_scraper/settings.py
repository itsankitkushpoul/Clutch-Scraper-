# Enable Playwright download handler
DOWNLOADER_MIDDLEWARES = {
    "scrapy_playwright.middleware.ScrapyPlaywrightDownloadHandler": 800,
}

# Use the asyncio reactor
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

# Playwright settings
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": True,
    # add proxy / user_agent overrides here if desired
}

# Concurrency & throttling
CONCURRENT_REQUESTS = 16
PLAYWRIGHT_MAX_CONTEXTS = 8
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 10.0

# Output
FEEDS = {
    "results.json": {"format": "json", "overwrite": True},
}
