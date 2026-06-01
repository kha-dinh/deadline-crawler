"""Scrapy settings for deadline_crawler project."""

BOT_NAME = "deadline_crawler"

SPIDER_MODULES = ["deadline_crawler.spiders"]
NEWSPIDER_MODULE = "deadline_crawler.spiders"

# Obey robots.txt — disabled because CFP pages are public and
# robots.txt on academic sites often blocks all scrapers.
ROBOTSTXT_OBEY = False

# Concurrency — matches legacy --workers=8 default
CONCURRENT_REQUESTS = 8
CONCURRENT_REQUESTS_PER_DOMAIN = 4

# No delay by default (pages are lightweight); AutoThrottle handles spikes
DOWNLOAD_DELAY = 0
DOWNLOAD_TIMEOUT = 10

# Retry
RETRY_ENABLED = True
RETRY_TIMES = 2

# Allow non-200 responses through to spider callbacks for error reporting
HTTPERROR_ALLOW_ALL = True

# User agent — same as legacy crawler
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Pipelines
ITEM_PIPELINES = {
    "deadline_crawler.pipelines.ValidationPipeline": 300,
    "deadline_crawler.pipelines.OutputPipeline": 800,
}

# Downloader middlewares — fixture middleware disabled by default
DOWNLOADER_MIDDLEWARES = {
    "deadline_crawler.middlewares.FixtureDownloaderMiddleware": 1,
}

# Extensions — progress bar + stats summary
EXTENSIONS = {
    "deadline_crawler.extensions.ProgressExtension": 500,
    "deadline_crawler.extensions.StatsExtension": 501,
}

# AutoThrottle — adaptive delay based on server response time
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1
AUTOTHROTTLE_MAX_DELAY = 10

# HTTP cache — disabled by default, enable with --cache flag
HTTPCACHE_ENABLED = False
HTTPCACHE_DIR = ".scrapy_cache"
HTTPCACHE_POLICY = "scrapy.extensions.httpcache.RFC2616Policy"

# Logging — ERROR suppresses all Scrapy noise; we print our own summary
LOG_LEVEL = "ERROR"
LOG_SHORT_NAMES = True


# Disable telnet console (not needed for CLI usage)
TELNETCONSOLE_ENABLED = False

# Request fingerprinting (Scrapy 2.7+ default)
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"

# Encoding — use apparent encoding like legacy _fetch()
FEED_EXPORT_ENCODING = "utf-8"

# --- Custom settings ---
# Path to conferences.yaml config
CONFERENCE_CONFIG = "conferences.yaml"
# Output format: "json" or "yaml"
OUTPUT_FORMAT = "json"
# Output path (None = auto: output/deadlines.{format})
OUTPUT_PATH = None
# Strict mode: V14/V16/V20 violations → errors instead of warnings
STRICT_MODE = False
# Fixture mode: path to fixtures dir, or None to disable
FIXTURES_DIR = None
# Diff mode: path to baseline output file for change detection, or None
DIFF_BASELINE = None
# Change log: path to JSONL changelog file, or None
CHANGE_LOG = None
