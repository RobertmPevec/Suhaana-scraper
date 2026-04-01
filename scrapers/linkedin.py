import os
import json
import time
from datetime import datetime, timedelta
import requests


BRIGHT_DATA_DATASET_ID = "gd_lyy3tktm25m4avu764"  # LinkedIn Posts dataset


def scrape_linkedin_posts(linkedin_url: str, months_back: int = 3) -> list[dict]:
    """
    Scrape LinkedIn company posts using Bright Data's Web Scraper API.
    Returns a list of post dicts with text, date, url, etc.
    """
    api_key = os.getenv("BRIGHT_DATA_API_KEY")
    if not api_key:
        print("  [!] BRIGHT_DATA_API_KEY not set, skipping LinkedIn scraping.")
        return []

    # Calculate date range
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=months_back * 30)).strftime("%Y-%m-%d")

    # Build request matching Bright Data's API format
    url = (
        f"https://api.brightdata.com/datasets/v3/scrape"
        f"?dataset_id={BRIGHT_DATA_DATASET_ID}"
        f"&notify=false"
        f"&include_errors=true"
        f"&type=discover_new"
        f"&discover_by=company_url"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = json.dumps({
        "input": [{
            "url": linkedin_url,
            "start_date": start_date,
            "end_date": end_date,
        }],
    })

    print(f"  Triggering Bright Data scrape for {linkedin_url}...")
    print(f"  Date range: {start_date} to {end_date}")

    try:
        resp = requests.post(url, headers=headers, data=payload, timeout=300)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  [!] Bright Data trigger failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"      Response: {e.response.text[:500]}")
        return []

    # Bright Data may return NDJSON (one JSON object per line) or regular JSON
    try:
        result = resp.json()
    except requests.exceptions.JSONDecodeError:
        # Parse NDJSON — each line is a separate JSON object
        lines = resp.text.strip().split("\n")
        posts = []
        for line in lines:
            if line.strip():
                posts.append(json.loads(line))
        print(f"  Got {len(posts)} LinkedIn posts.")
        return posts

    # If we get results directly (synchronous response)
    if isinstance(result, list):
        print(f"  Got {len(result)} LinkedIn posts.")
        return result

    # If async, we get a snapshot_id to poll
    snapshot_id = result.get("snapshot_id")
    if not snapshot_id:
        print(f"  [!] Unexpected response: {result}")
        return []

    # Poll for results
    snapshot_url = f"https://api.brightdata.com/datasets/v3/snapshot/{snapshot_id}?format=json"
    print(f"  Waiting for results (snapshot: {snapshot_id})...")

    for attempt in range(60):  # Up to 5 minutes
        time.sleep(5)
        try:
            poll_resp = requests.get(snapshot_url, headers=headers, timeout=30)
            if poll_resp.status_code == 200:
                posts = poll_resp.json()
                if isinstance(posts, list):
                    print(f"  Got {len(posts)} LinkedIn posts.")
                    return posts
                else:
                    print(f"  [!] Unexpected response format: {type(posts)}")
                    return []
            elif poll_resp.status_code == 202:
                if attempt % 6 == 0:
                    print(f"  Still processing... ({attempt * 5}s elapsed)")
                continue
            else:
                print(f"  [!] Poll returned status {poll_resp.status_code}: {poll_resp.text[:300]}")
                return []
        except requests.RequestException as e:
            print(f"  [!] Poll request failed: {e}")
            continue

    print("  [!] Timed out waiting for Bright Data results.")
    return []


def format_linkedin_data(posts: list[dict]) -> list[dict]:
    """
    Normalize Bright Data post data into a consistent format for AI processing.
    Uses the actual field names from Bright Data's LinkedIn Posts output.
    """
    formatted = []
    for post in posts:
        formatted.append({
            "text": post.get("post_text", ""),
            "date": post.get("date_posted", "Unknown"),
            "url": post.get("url", ""),
            "title": post.get("title", ""),
            "hashtags": post.get("hashtags", []),
            "embedded_links": post.get("embedded_links", []),
            "num_likes": post.get("num_likes", 0),
            "num_comments": post.get("num_comments", 0),
            "tagged_companies": post.get("tagged_companies", []),
            "post_type": post.get("post_type", ""),
        })
    return formatted


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    url = input("Enter LinkedIn company URL: ").strip()
    months = input("Months back to search? [3]: ").strip()
    months = int(months) if months else 3

    posts = scrape_linkedin_posts(url, months)
    print(json.dumps(posts, indent=2))
