# Run unit tests
test:
    uv run pytest tests/ -v

# Crawl a specific conference and export
crawl name format="json":
    uv run python main.py crawl --conf "{{name}}" --format {{format}}

# Crawl all conferences and export
crawl-all format="json":
    uv run python main.py crawl --format {{format}}

# Crawl and export to specific file
crawl-to name output format="json":
    uv run python main.py crawl --conf "{{name}}" --output {{output}} --format {{format}}
