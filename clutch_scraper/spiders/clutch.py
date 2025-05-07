import scrapy
from scrapy_playwright.page import PageMethod
from clutch_scraper.items import ClutchItem
from urllib.parse import urlparse, parse_qs, unquote

class ClutchSpider(scrapy.Spider):
    name = "clutch"
    custom_settings = { "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 120_000 }

    def __init__(self, base_url=None, total_pages=3, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not base_url:
            raise ValueError("You must provide --set base_url=<URL>")
        self.base_url = base_url
        self.total_pages = int(total_pages)

    def start_requests(self):
        for p in range(1, self.total_pages + 1):
            url = f"{self.base_url}?page={p}"
            yield scrapy.Request(
                url,
                meta={
                    "playwright": True,
                    "playwright_page_methods": [
                        PageMethod("wait_for_load_state", "networkidle"),
                        PageMethod("evaluate", "window.scrollTo(0, document.body.scrollHeight)"),
                        PageMethod("wait_for_timeout", 1000),
                    ],
                },
                callback=self.parse_page,
                errback=self.errback,
            )

    def parse_page(self, response):
        for sel in response.css("div.provider-row"):
            item = ClutchItem()
            item["company"] = sel.css("a.provider__title-link.directory_profile::text") \
                                  .get(default="").strip()
            raw_href = sel.css("a.provider__cta-link.website-link__item--non-ppc::attr(href)").get()
            item["website"]  = self._extract_website(raw_href)
            item["location"] = sel.css(".provider__highlights-item.location::text") \
                                   .get(default="").strip()
            item["featured"] = False
            yield item

        for sel in response.css("div.provider-row.featured"):
            item = ClutchItem()
            item["company"] = sel.css("a.provider__title-link.ppc-website-link::text") \
                                  .get(default="").strip()
            raw_href = sel.css("a.provider__cta-link.ppc_position--link::attr(href)").get()
            item["website"]  = self._extract_website(raw_href)
            item["location"] = sel.css(".provider__highlights-item.location::text") \
                                   .get(default="").strip()
            item["featured"] = True
            yield item

    def _extract_website(self, href):
        if not href:
            return None
        try:
            qs = parse_qs(urlparse(href).query)
            u  = qs.get("u", [None])[0]
            if not u:
                return None
            decoded = unquote(u)
            parsed2 = urlparse(decoded)
            return f"{parsed2.scheme}://{parsed2.netloc}"
        except Exception:
            return None

    def errback(self, failure):
        self.logger.error(f"Request failed: {failure.request.url}")
