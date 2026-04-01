import os
import json
from google import genai
from ai.models import Event, SourceExtractionResult, MergedEventsResult


MODEL = "gemini-3.1-flash-lite-preview"

LINKEDIN_CHUNK_SIZE = 20  # Process 20 posts at a time
SEARCH_CHUNK_SIZE = 5     # Process 5 search results at a time (full page content now)
WEBSITE_CHUNK_SIZE = 5    # Process 5 pages at a time


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")
    return genai.Client(api_key=api_key)


# ── Step 1: Summarize each source, preserving event-related details ──────────

SUMMARIZE_PROMPT = """You are an assistant that summarizes content while preserving ALL information about events, conferences, trade shows, summits, expos, corporate events, webinars, and similar gatherings.

Given the following content from {source_type}, summarize it while:
- Keeping ALL mentions of events, conferences, trade shows, dates, locations, and URLs EXACTLY as written
- Preserving any links/URLs verbatim — do NOT modify or shorten them
- Removing only content that is clearly unrelated to events or company activities

Content:
{content}"""


def summarize_source(content: str, source_type: str) -> str:
    """Summarize a source while preserving event-related info."""
    client = _get_client()

    # Chunk if content is very long (>30k chars)
    if len(content) > 30000:
        chunks = [content[i:i+30000] for i in range(0, len(content), 30000)]
        summaries = []
        for i, chunk in enumerate(chunks):
            print(f"    Summarizing {source_type} chunk {i+1}/{len(chunks)}...")
            resp = client.models.generate_content(
                model=MODEL,
                config={
                    "system_instruction": (
                        "You summarize content while preserving ALL event-related information. "
                        "Output a concise summary keeping all dates, URLs, event names, and locations verbatim."
                    ),
                },
                contents=SUMMARIZE_PROMPT.format(source_type=source_type, content=chunk),
            )
            summaries.append(resp.text)
        return "\n\n".join(summaries)
    else:
        resp = client.models.generate_content(
            model=MODEL,
            config={
                "system_instruction": (
                    "You summarize content while preserving ALL event-related information. "
                    "Output a concise summary keeping all dates, URLs, event names, and locations verbatim."
                ),
            },
            contents=SUMMARIZE_PROMPT.format(source_type=source_type, content=content),
        )
        return resp.text


# ── Step 2: Extract events from each summarized source ──────────────────────

EXTRACT_PROMPT = """You are an event extraction assistant. Your job is to find ONLY events that fall into the categories listed below. If an event does not fit one of these categories, DO NOT include it.

ALLOWED CATEGORIES (only extract events that fit one of these):
1. "Conferences / Keynotes / Events" — Industry conferences, keynote speeches, trade shows, expos, summits, forums, panels, industry gatherings where the company has a presence
2. "ESG / Sustainability" — Environmental, social, governance events, sustainability summits, climate forums, green initiatives events
3. "Sporting Events / Athletic Sponsorships" — Charity tournaments, golf tournaments, sports sponsorships, athletic events the company sponsors or participates in
4. "Financial Events" — Earnings calls, shareholder meetings, investor days, stock exchange events, award ceremonies for business/finance
5. "Community Engagement / Indigenous Relations" — Community events, Indigenous partnerships, reconciliation events, cultural celebrations, volunteer initiatives, charity events, sponsorships of community gatherings
6. "Career Fairs / Student Events" — Career fairs, scholarship programs, student conferences, intern events, campus recruiting
7. "Special Events / Celebrations" — Milestone celebrations, anniversaries, galas, company-hosted special events

DO NOT INCLUDE — if it doesn't fit the above categories, skip it:
- National holidays or awareness days the company simply acknowledges (IWD, Earth Day, Pride Month posts, etc.)
- Product launches or promotions NOT tied to a specific event
- Blog posts or articles that just give tips/advice
- Job postings (unless it's a career fair)
- Generic social media posts
- Internal team meetings or routine company updates
- Hiring announcements

For the REFERENCES field, write a detailed professional narrative about the company's involvement. Here are examples of good references:

EXAMPLE 1: "CEO François Poirier participated in a high-level panel at Canada House during CERAWeek to discuss the integration of North American energy markets and the specific role of Canadian infrastructure in global supply."

EXAMPLE 2: "TC Energy leadership joined the International Gas Union (IGU) and global energy peers to discuss the entire LNG value chain, focusing on market delivery and the emerging role of hydrogen and decarbonized gas in global energy security."

EXAMPLE 3: "Nearly 100 TC Energy volunteers provided community giveaways and celebrated local culture at this premier high-visibility event."

Use information from the source content to write the reference. If specific people are mentioned, include their names and titles. If topics discussed are mentioned, include them. Write in third person.

CRITICAL RULES:
- Copy event names, dates, locations, and URLs EXACTLY as they appear in the text
- Do NOT rephrase, reformat, or modify any information
- Do NOT guess dates or locations — if not mentioned, use "Unknown"
- Include the exact original text snippet that mentions each event in the raw_text field
- Source URLs must be copied verbatim with no modifications whatsoever
- If there are NO real events found, return an empty events list
- ONLY include events from the last {months_back} months. Ignore anything older.
- If the source is from a web search and you CANNOT determine the date/timeframe of an event, DO NOT include it. We only want events we can confirm fall within the timeframe.
- For search results specifically: if the event date is unclear, ambiguous, or missing — skip it entirely.

IMPORTANT: You are researching events for the company "{company_name}". ONLY include events where THIS SPECIFIC COMPANY is directly involved — attending, sponsoring, exhibiting, presenting, or hosting. Do NOT include events that just happen to appear on the same page but have nothing to do with {company_name}.

The content below is from: {source_type}
The source URL is: {source_url}

Content:
{content}"""


def extract_events_from_source(
    content: str, source_type: str, source_url: str, months_back: int = 3, company_name: str = ""
) -> list[Event]:
    """Extract events from a single summarized source using structured output."""
    if not content.strip():
        return []

    client = _get_client()

    resp = client.models.generate_content(
        model=MODEL,
        config={
            "response_mime_type": "application/json",
            "response_schema": SourceExtractionResult,
            "system_instruction": (
                "You extract events from content. "
                "Output ONLY valid JSON matching the schema. "
                "Copy all URLs, dates, and names EXACTLY as they appear. Do NOT modify anything."
            ),
        },
        contents=EXTRACT_PROMPT.format(
            source_type=source_type,
            source_url=source_url,
            content=content,
            months_back=months_back,
            company_name=company_name,
        ),
    )

    result = SourceExtractionResult.model_validate_json(resp.text)
    return result.events


# ── Step 3: Merge and deduplicate all events ─────────────────────────────────

MERGE_PROMPT = """You are given a list of events extracted from multiple sources (LinkedIn, company website, Brave search). Some events may be duplicates found across different sources.

Your job:
1. FIRST: Remove any entries that do NOT fit these categories: "Conferences / Keynotes / Events", "ESG / Sustainability", "Sporting Events / Athletic Sponsorships", "Financial Events", "Community Engagement / Indigenous Relations", "Career Fairs / Student Events", "Special Events / Celebrations". If it doesn't fit, drop it.
2. SECOND: Remove any entries where the date is "Unknown" or unclear — we only want events with confirmed dates within the timeframe.
3. Identify duplicate events (same event mentioned in multiple sources)
4. For duplicates, merge them into one entry keeping the MOST COMPLETE information
4. When merging, prefer the version with more details (fuller date, location, description)
5. Preserve ALL source URLs and raw text exactly as provided — do NOT modify them
6. For merged entries, keep the source_url and source_type from the most informative source
7. Keep the raw_text from the most detailed mention

CRITICAL: Do NOT modify any URLs, dates, or event names. Copy them exactly.

Events to deduplicate:
{events_json}"""


def merge_events(all_events: list[Event]) -> list[Event]:
    """Deduplicate and merge events from all sources."""
    if not all_events:
        return []

    # If few enough events, no need for AI dedup
    if len(all_events) <= 3:
        return all_events

    client = _get_client()
    events_json = json.dumps([e.model_dump() for e in all_events], indent=2)

    resp = client.models.generate_content(
        model=MODEL,
        config={
            "response_mime_type": "application/json",
            "response_schema": MergedEventsResult,
            "system_instruction": (
                "You deduplicate and merge events. "
                "Output ONLY valid JSON matching the schema. "
                "Preserve all URLs, dates, and text exactly as provided."
            ),
        },
        contents=MERGE_PROMPT.format(events_json=events_json),
    )

    result = MergedEventsResult.model_validate_json(resp.text)
    return result.events


# ── Full pipeline ────────────────────────────────────────────────────────────

def process_linkedin_data(posts: list[dict], months_back: int = 3, company_name: str = "") -> list[Event]:
    """Process LinkedIn posts through summarize → extract pipeline, chunked by 20."""
    if not posts:
        return []

    all_events = []

    # Chunk posts into batches of LINKEDIN_CHUNK_SIZE
    for batch_start in range(0, len(posts), LINKEDIN_CHUNK_SIZE):
        batch = posts[batch_start:batch_start + LINKEDIN_CHUNK_SIZE]
        batch_num = (batch_start // LINKEDIN_CHUNK_SIZE) + 1
        total_batches = (len(posts) + LINKEDIN_CHUNK_SIZE - 1) // LINKEDIN_CHUNK_SIZE

        print(f"  Processing LinkedIn batch {batch_num}/{total_batches} ({len(batch)} posts)...")

        # Build content string from this batch
        content_parts = []
        for post in batch:
            text = post.get("text", "")
            date = post.get("date", "Unknown")
            url = post.get("url", "")
            hashtags = post.get("hashtags", [])
            tagged = post.get("tagged_companies", [])
            links = post.get("embedded_links", [])
            if text:
                part = f"[Post date: {date}] [URL: {url}]\n{text}"
                if hashtags:
                    part += f"\nHashtags: {', '.join(hashtags) if isinstance(hashtags, list) else hashtags}"
                if tagged:
                    part += f"\nTagged companies: {', '.join(str(t) for t in tagged) if isinstance(tagged, list) else tagged}"
                if links:
                    part += f"\nEmbedded links: {', '.join(str(l) for l in links) if isinstance(links, list) else links}"
                content_parts.append(part)

        content = "\n\n---\n\n".join(content_parts)
        if not content.strip():
            continue

        print(f"    Summarizing batch {batch_num}...")
        summary = summarize_source(content, "LinkedIn company posts")

        print(f"    Extracting events from batch {batch_num}...")
        source_url = batch[0].get("url", "LinkedIn")
        events = extract_events_from_source(summary, "linkedin", source_url, months_back, company_name)
        all_events.extend(events)
        print(f"    Found {len(events)} events in batch {batch_num}.")

    print(f"  Total events from LinkedIn: {len(all_events)}")
    return all_events


def process_website_data(pages: list[dict], months_back: int = 3, company_name: str = "") -> list[Event]:
    """Process website pages through summarize → extract pipeline, chunked by 5."""
    if not pages:
        return []

    all_events = []

    # Chunk pages into batches of WEBSITE_CHUNK_SIZE
    for batch_start in range(0, len(pages), WEBSITE_CHUNK_SIZE):
        batch = pages[batch_start:batch_start + WEBSITE_CHUNK_SIZE]
        batch_num = (batch_start // WEBSITE_CHUNK_SIZE) + 1
        total_batches = (len(pages) + WEBSITE_CHUNK_SIZE - 1) // WEBSITE_CHUNK_SIZE

        print(f"  Processing website batch {batch_num}/{total_batches} ({len(batch)} pages)...")

        # Combine batch pages into one content block
        content_parts = []
        batch_urls = []
        for page in batch:
            url = page.get("url", "")
            markdown = page.get("markdown", "")
            if markdown.strip():
                content_parts.append(f"[Page URL: {url}]\n{markdown}")
                batch_urls.append(url)

        content = "\n\n===PAGE BREAK===\n\n".join(content_parts)
        if not content.strip():
            continue

        print(f"    Summarizing batch {batch_num}...")
        summary = summarize_source(content, f"company website ({len(batch)} pages)")

        print(f"    Extracting events from batch {batch_num}...")
        source_url = batch_urls[0] if batch_urls else "website"
        events = extract_events_from_source(summary, "website", source_url, months_back, company_name)
        all_events.extend(events)
        print(f"    Found {len(events)} events in batch {batch_num}.")

    print(f"  Total events from website: {len(all_events)}")
    return all_events


def process_search_data(search_results: list[dict], months_back: int = 3, company_name: str = "") -> list[Event]:
    """Process search results through summarize → extract pipeline, chunked by 5."""
    if not search_results:
        return []

    all_events = []

    # Chunk search results into batches of SEARCH_CHUNK_SIZE
    for batch_start in range(0, len(search_results), SEARCH_CHUNK_SIZE):
        batch = search_results[batch_start:batch_start + SEARCH_CHUNK_SIZE]
        batch_num = (batch_start // SEARCH_CHUNK_SIZE) + 1
        total_batches = (len(search_results) + SEARCH_CHUNK_SIZE - 1) // SEARCH_CHUNK_SIZE

        print(f"  Processing search batch {batch_num}/{total_batches} ({len(batch)} results)...")

        # Build content from this batch — use full markdown if available, fall back to snippet
        content_parts = []
        for result in batch:
            url = result.get("url", "")
            title = result.get("title", "")
            markdown = result.get("markdown", "")
            snippet = result.get("snippet", "")
            query = result.get("query", "")

            if markdown:
                content_parts.append(f"[Search query: {query}]\n[URL: {url}]\nTitle: {title}\n\n{markdown}")
            else:
                content_parts.append(f"[Search query: {query}]\n[URL: {url}]\nTitle: {title}\nSnippet: {snippet}")

        content = "\n\n".join(content_parts)

        print(f"    Summarizing batch {batch_num}...")
        summary = summarize_source(content, "Brave search results")

        print(f"    Extracting events from batch {batch_num}...")
        events = extract_events_from_source(summary, "search", "Brave Search", months_back, company_name)
        all_events.extend(events)
        print(f"    Found {len(events)} events in batch {batch_num}.")

    print(f"  Total events from search: {len(all_events)}")
    return all_events
