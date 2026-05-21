"""Scrapy items for conference deadline data."""

import scrapy


class ConferenceItem(scrapy.Item):
    """One conference (or one cycle of a conference) with extracted deadlines."""

    name = scrapy.Field()
    year = scrapy.Field()
    link = scrapy.Field()
    deadlines = scrapy.Field()  # list[dict] — [{label: str, date: str}]
    cycle = scrapy.Field()
    date = scrapy.Field()
    place = scrapy.Field()
    description = scrapy.Field()
    tags = scrapy.Field()  # [area_code, core_rank]
    timezone = scrapy.Field()
    comment = scrapy.Field()
