import asyncio
import os
from datetime import datetime

from dotenv import load_dotenv
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

from linkedin_playwright import scrape_linkedin_posts
from scrapers.website import crawl_website
# from scrapers.search import search_company_events, crawl_search_results
from ai.extractor import (
    process_linkedin_data,
    process_website_data,
    # process_search_data,
    merge_events,
)
from ai.models import Event

load_dotenv()


def get_user_input() -> dict:
    """Collect company details from the user."""
    print("\n🔍 Event Scraper for Suhaana")
    print("=" * 40)

    company_name = input("Enter company name: ").strip()
    linkedin_url = input("Enter LinkedIn company URL: ").strip()
    website_url = input("Enter company website URL: ").strip()
    months_back = input("How many months back to search? ").strip()

    return {
        "company_name": company_name,
        "linkedin_url": linkedin_url,
        "website_url": website_url,
        "months_back": int(months_back) if months_back else 3,
    }


async def run_scrapers(inputs: dict) -> dict:
    """Run LinkedIn first (needs manual login), then website + search concurrently."""
    print("\n📡 Starting scrapers...")

    # Step 1: LinkedIn via Playwright (sync, headed browser, manual login)
    print("\n[LinkedIn — Playwright]")
    raw_posts = await scrape_linkedin_posts(inputs["linkedin_url"], inputs["months_back"])
    # Format into the structure the AI extractor expects
    linkedin_data = []
    for post in raw_posts:
        linkedin_data.append({
            "text": post.get("text", ""),
            "date": post.get("age", "Unknown"),
            "url": post.get("url", ""),
            "hashtags": [],
            "embedded_links": [],
            "tagged_companies": [],
        })
    print(f"  LinkedIn done: {len(linkedin_data)} posts.")

    # Step 2: Website crawler
    print("\n📡 Running website crawler...")
    print("\n[Website]")
    website_data = await crawl_website(inputs["website_url"])

    # # Step 3: Brave Search (commented out for now)
    # async def async_search():
    #     print("\n[Brave Search]")
    #     loop = asyncio.get_event_loop()
    #     search_results = await loop.run_in_executor(
    #         None,
    #         search_company_events,
    #         inputs["company_name"],
    #         inputs["months_back"],
    #     )
    #     enriched = await crawl_search_results(search_results)
    #     return enriched
    # search_data = await async_search()

    return {
        "linkedin": linkedin_data,
        "website": website_data,
        "search": [],
    }


def run_ai_extraction(scraped_data: dict, months_back: int, company_name: str) -> list[Event]:
    """Run AI extraction on each source, then merge."""
    print("\n🤖 Running AI extraction...")

    print("\n[AI] Processing LinkedIn data...")
    linkedin_events = process_linkedin_data(scraped_data["linkedin"], months_back, company_name)

    print("\n[AI] Processing website data...")
    website_events = process_website_data(scraped_data["website"], months_back, company_name)

    # print("\n[AI] Processing search results...")
    # search_events = process_search_data(scraped_data["search"], months_back)

    all_events = linkedin_events + website_events
    print(f"\n[AI] Total events before dedup: {len(all_events)}")

    if len(all_events) > 0:
        print("[AI] Merging and deduplicating...")
        final_events = merge_events(all_events)
        print(f"[AI] Final event count: {len(final_events)}")
        return final_events

    return []


def save_to_excel(events: list[Event], company_name: str) -> str:
    """Save events to an Excel file."""
    os.makedirs("output", exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_name = company_name.replace(" ", "_").replace("/", "_")
    filename = f"output/{safe_name}_events_{date_str}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Events"

    # Headers
    headers = [
        "Event Name",
        "Date",
        "Location",
        "Type",
        "Description",
        "References",
        "Source URL",
        "Source Type",
        "Raw Text",
    ]
    header_font = Font(bold=True, size=12)
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    # Data rows
    for row_idx, event in enumerate(events, 2):
        ws.cell(row=row_idx, column=1, value=event.event_name)
        ws.cell(row=row_idx, column=2, value=event.date)
        ws.cell(row=row_idx, column=3, value=event.location)
        ws.cell(row=row_idx, column=4, value=event.event_type)
        ws.cell(row=row_idx, column=5, value=event.description)
        ws.cell(row=row_idx, column=6, value=event.references)
        ws.cell(row=row_idx, column=7, value=event.source_url)
        ws.cell(row=row_idx, column=8, value=event.source_type)
        ws.cell(row=row_idx, column=9, value=event.raw_text)

    # Auto-size columns (approximate)
    for col_idx, header in enumerate(headers, 1):
        max_len = len(header)
        for row in range(2, len(events) + 2):
            val = ws.cell(row=row, column=col_idx).value
            if val:
                max_len = max(max_len, min(len(str(val)), 60))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = max_len + 4

    wb.save(filename)
    return filename


async def main():
    inputs = get_user_input()

    # Step 1: Scrape all sources
    scraped_data = await run_scrapers(inputs)

    # Step 2: AI extraction & merge
    events = run_ai_extraction(scraped_data, inputs["months_back"], inputs["company_name"])

    # Step 3: Output
    if events:
        filepath = save_to_excel(events, inputs["company_name"])
        print(f"\n✅ Found {len(events)} events! Saved to {filepath}")
    else:
        print("\n⚠️  No events found. Try a different company or broader search.")


if __name__ == "__main__":
    asyncio.run(main())
