# Run unit tests
test:
    uv run pytest tests/ -v

# Crawl a specific conference live (e.g. just crawl "USENIX Security")
crawl name:
    uv run python -c "from crawler.strategy import crawl_conference; from crawler.config import load_conferences; confs = load_conferences('conferences.yaml'); matches = [c for c in confs if c['name'].lower() == '{{name}}'.lower()]; assert matches, 'Conference not found: {{name}}'; results = crawl_conference(matches[0], 2026); [print(f'--- {r.cycle or r.name} ---\n  Deadlines: {r.deadlines}\n  Date: {r.date}\n  Place: {r.place}\n  Description: {r.description}\n  Tags: {r.tags}\n') for r in results]"

# Crawl all configured conferences live
crawl-all:
    uv run python -c "from crawler.strategy import crawl_all; results = crawl_all(year=2026); [print(f'{r.name} ({r.cycle or \"single\"}): {r.deadlines}') for r in results]"
