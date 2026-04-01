import os
import asyncio
import requests
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode


BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
NUM_RESULTS = 5  # Max per query
MAX_CHARS_PER_PAGE = 25000


def search_company_events(company_name: str, months_back: int = 3) -> list[dict]:
    """
    Search for events/conferences a company is attending using Brave Search API.
    Returns a list of {url, title, snippet, query} dicts.
    """
    from datetime import datetime, timedelta

    api_key = os.getenv("BRAVE_API_KEY")
    if not api_key:
        print("  [!] BRAVE_API_KEY not set, skipping web search.")
        return []

    # Build dynamic date range from months_back
    start_date = datetime.now() - timedelta(days=months_back * 30)
    end_date = datetime.now()
    # Get unique years in the range, current year first for better ranking
    current_year = end_date.year
    years = sorted(set([start_date.year, end_date.year]), reverse=True)
    year_str = " ".join(str(y) for y in years)

    queries = [
        f'{company_name} conferences {current_year}',
        f'{company_name} keynotes {current_year}',
        f'{company_name} events {year_str}',
        f'{company_name} ESG sustainability events {year_str}',
        f'{company_name} sporting events athletic sponsorships {year_str}',
        f'{company_name} financial events investor day {year_str}',
        f'{company_name} community engagement indigenous relations {year_str}',
        f'{company_name} career fair student events {year_str}',
        f'{company_name} special events celebrations {year_str}',
        f'{company_name} trade show expo summit {year_str}',
    ]

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }

    results = []
    seen_urls = set()

    for query in queries:
        print(f"  Searching: {query}")
        # Use Brave's custom date range format
        freshness = f"{start_date.strftime('%Y-%m-%d')}to{end_date.strftime('%Y-%m-%d')}"
        params = {
            "q": query,
            "count": NUM_RESULTS,
            "freshness": freshness,
        }

        try:
            resp = requests.get(BRAVE_SEARCH_URL, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            web_results = data.get("web", {}).get("results", [])
            for item in web_results:
                url = item.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    results.append({
                        "url": url,
                        "title": item.get("title", ""),
                        "snippet": item.get("description", ""),
                        "query": query,
                    })

        except requests.RequestException as e:
            print(f"  [!] Brave search error for '{query}': {e}")

    print(f"  Found {len(results)} unique search results.")
    return results


async def crawl_search_results(search_results: list[dict]) -> list[dict]:
    """
    Crawl each search result URL with Crawl4AI to get full page content.
    Returns the search results with markdown content added.
    """
    if not search_results:
        return []

    print(f"\n  Crawling {len(search_results)} search result pages...")

    browser_config = BrowserConfig(headless=True, verbose=False)
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        stream=False,
    )

    enriched = []

    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            for i, item in enumerate(search_results):
                url = item["url"]
                print(f"  [{i + 1}/{len(search_results)}] Crawling {url[:80]}...")

                try:
                    result = await crawler.arun(url=url, config=run_config)
                    if result.success and result.markdown:
                        enriched.append({
                            "url": item["url"],
                            "title": item["title"],
                            "snippet": item["snippet"],
                            "query": item["query"],
                            "markdown": result.markdown[:MAX_CHARS_PER_PAGE],
                        })
                        print(f"    [OK] {len(result.markdown)} chars")
                    else:
                        # Keep the result with just title/snippet
                        enriched.append({
                            "url": item["url"],
                            "title": item["title"],
                            "snippet": item["snippet"],
                            "query": item["query"],
                            "markdown": "",
                        })
                        print(f"    [SKIP] Could not crawl, keeping title/snippet only")
                except Exception as e:
                    enriched.append({
                        "url": item["url"],
                        "title": item["title"],
                        "snippet": item["snippet"],
                        "query": item["query"],
                        "markdown": "",
                    })
                    print(f"    [SKIP] Error: {e}")

    except Exception as e:
        print(f"  [!] Crawl4AI error: {e}")
        # Return whatever we have with just titles/snippets
        return search_results

    print(f"  Successfully crawled {sum(1 for r in enriched if r.get('markdown'))} of {len(search_results)} pages.")
    return enriched


if __name__ == "__main__":
    import json
    from dotenv import load_dotenv
    load_dotenv()

    company = input("Enter company name: ").strip()
    results = search_company_events(company)
    # Also crawl the results
    enriched = asyncio.run(crawl_search_results(results))
    print(json.dumps(enriched, indent=2))
