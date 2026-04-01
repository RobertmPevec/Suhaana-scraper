import os
import asyncio
from urllib.parse import urldefrag
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from google import genai
from ai.models import RelevantLinks

MAX_DEPTH = 4
MAX_PAGES = 50
MAX_CHARS_PER_PAGE = 25000

FILTER_PROMPT = """You are given a list of internal links found on a company's website. Your job is to identify which links COULD contain information about events, conferences, trade shows, summits, expos, webinars, or similar gatherings that the company is attending, sponsoring, or participating in.

BE GENEROUS — when in doubt, INCLUDE the link. We'd rather crawl a few extra pages than miss an event mention.

ALWAYS include links like:
- Blog posts / news articles (ANY of them — events are often mentioned casually in blog posts)
- Events, media, or press pages
- About us, our story, partners pages
- Any page with dates, announcements, or company updates
- Industry or community pages

ONLY exclude links that are clearly irrelevant:
- Product catalog/shop/search pages
- Contact forms
- Privacy policy / terms of service
- Login / account pages
- Image or PDF files

When in doubt, INCLUDE IT. You MUST return at least 1 URL — never return an empty list.

Links found on the website:
{links}"""


def _filter_links_with_ai(links: list[dict]) -> list[str]:
    """Use Gemini to pick which links are most likely to contain event info."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return [l["url"] for l in links]

    # Format links as "URL — link text" for Gemini
    link_lines = []
    for link in links:
        text = link.get("text", "").strip()
        url = link.get("url", "")
        if text:
            link_lines.append(f"{url} — {text}")
        else:
            link_lines.append(url)

    links_str = "\n".join(link_lines)

    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="gemini-3.1-flash-lite-preview",
        config={
            "response_mime_type": "application/json",
            "response_schema": RelevantLinks,
            "system_instruction": (
                "You filter website links to find ones likely to contain event information. "
                "Output ONLY valid JSON matching the schema. "
                "Copy URLs exactly as provided — do NOT modify them."
            ),
        },
        contents=FILTER_PROMPT.format(links=links_str),
    )

    result = RelevantLinks.model_validate_json(resp.text)
    return result.urls


async def crawl_website(website_url: str) -> list[dict]:
    """
    Crawl a company website depth by depth:
    - Depth 0: crawl homepage
    - Each depth: crawl all pages, collect all new links, one AI filter call, repeat
    """
    print(f"  Crawling {website_url} (depth {MAX_DEPTH}, max {MAX_PAGES} pages)...")

    browser_config = BrowserConfig(headless=True, verbose=False)
    run_config = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        stream=False,
    )

    def normalize_url(url):
        return urldefrag(url)[0]

    visited = set()
    pages = []

    # Start with the homepage
    urls_to_crawl = [normalize_url(website_url)]

    try:
        async with AsyncWebCrawler(config=browser_config) as crawler:
            for depth in range(MAX_DEPTH + 1):  # 0 through MAX_DEPTH
                if not urls_to_crawl or len(pages) >= MAX_PAGES:
                    break

                print(f"\n  === Depth {depth}: {len(urls_to_crawl)} URLs to crawl ===")

                # Crawl all URLs at this depth, collecting new links as we go
                all_new_links = []

                for url in urls_to_crawl:
                    if len(pages) >= MAX_PAGES:
                        break

                    norm_url = normalize_url(url)
                    if norm_url in visited:
                        continue
                    visited.add(norm_url)

                    print(f"  [Page {len(pages) + 1}, Depth {depth}] Crawling {url}...")
                    result = await crawler.arun(url=url, config=run_config)

                    if result.success and result.markdown:
                        pages.append({
                            "url": result.url,
                            "markdown": result.markdown[:MAX_CHARS_PER_PAGE],
                        })
                        print(f"    [OK] {len(result.markdown)} chars")

                        # Collect new internal links
                        for link in result.links.get("internal", []):
                            next_url = normalize_url(link["href"])
                            if next_url not in visited:
                                all_new_links.append({
                                    "url": next_url,
                                    "text": link.get("text", ""),
                                })
                    else:
                        error = result.error_message if hasattr(result, 'error_message') else "unknown"
                        print(f"    [SKIP] {error}")

                # Deduplicate collected links
                seen = set()
                unique_links = []
                for link in all_new_links:
                    if link["url"] not in seen and link["url"] not in visited:
                        seen.add(link["url"])
                        unique_links.append(link)

                # AI filter for next depth (skip if no new links or we've hit max depth)
                if unique_links and depth < MAX_DEPTH and len(pages) < MAX_PAGES:
                    print(f"\n  Found {len(unique_links)} new links. Asking AI to filter...")
                    relevant_urls = _filter_links_with_ai(unique_links)
                    print(f"  AI selected {len(relevant_urls)} links for depth {depth + 1}.")
                    urls_to_crawl = relevant_urls
                else:
                    urls_to_crawl = []

    except Exception as e:
        import traceback
        print(f"  [!] Crawl4AI error: {e}")
        traceback.print_exc()

    print(f"\n  Crawled {len(pages)} pages total.")
    return pages


if __name__ == "__main__":
    import json
    from dotenv import load_dotenv
    load_dotenv()

    url = input("Enter company website URL: ").strip()
    pages = asyncio.run(crawl_website(url))
    print(json.dumps(pages, indent=2))
