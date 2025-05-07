import scrapy

class ClutchItem(scrapy.Item):
    company  = scrapy.Field()
    website  = scrapy.Field()
    location = scrapy.Field()
    featured = scrapy.Field()
