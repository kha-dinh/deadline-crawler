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
    area = scrapy.Field()  # area code string (e.g. SEC, SYS)
    rank = scrapy.Field()  # CORE rank (A*, A, B, C, unknown)
    timezone = scrapy.Field()
    comment = scrapy.Field()
    url_hotcrp = scrapy.Field()
