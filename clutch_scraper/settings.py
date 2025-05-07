DOWNLOADER_MIDDLEWARES = {
    "scrapy_playwright.middleware.ScrapyPlaywrightDownloadHandler": 800,
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}

CONCURRENT_REQUESTS       = 16
PLAYWRIGHT_MAX_CONTEXTS   = 8
AUTOTHROTTLE_ENABLED      = True
AUTOTHROTTLE_START_DELAY  = 1.0
AUTOTHROTTLE_MAX_DELAY    = 10.0

FEEDS = {
    "results.json": {"format": "json", "overwrite": True},
}
