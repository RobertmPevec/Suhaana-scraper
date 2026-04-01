from pydantic import BaseModel, Field


class Event(BaseModel):
    event_name: str = Field(
        description="Exact name of the event as mentioned in the source. Copy verbatim — do NOT rephrase."
    )
    date: str = Field(
        description="Date or date range exactly as written in the source. Do NOT reformat or guess."
    )
    location: str = Field(
        description="Location exactly as written in the source, or 'Unknown' if not mentioned."
    )
    event_type: str = Field(
        description="Must be one of: 'Conferences / Keynotes / Events', 'ESG / Sustainability', 'Sporting Events / Athletic Sponsorships', 'Financial Events', 'Community Engagement / Indigenous Relations', 'Career Fairs / Student Events', 'Special Events / Celebrations'."
    )
    description: str = Field(
        description="Brief description of the event and the company's involvement or role."
    )
    references: str = Field(
        description="Detailed contextual write-up of the company's involvement in this event. Include who from the company attended/spoke, what they discussed or presented, why it matters for the company's brand, and any relevant outcomes. Write in a professional, third-person narrative style. Example: 'CEO John Smith participated in a high-level panel to discuss the integration of North American markets and the specific role of Canadian infrastructure in global supply.'"
    )
    source_url: str = Field(
        description="Exact URL where this event was found. Copy the full URL verbatim — do NOT modify."
    )
    source_type: str = Field(
        description="Where this was found: 'linkedin', 'website', or 'search'."
    )
    raw_text: str = Field(
        description="The exact original text/snippet that mentions this event. Copy verbatim from the source."
    )


class RelevantLinks(BaseModel):
    urls: list[str] = Field(
        description="URLs that are most likely to contain information about events, conferences, trade shows, summits, or similar gatherings the company is attending or participating in. Only include URLs that are genuinely relevant — do not pad the list."
    )


class SourceExtractionResult(BaseModel):
    events: list[Event] = Field(
        description="All events found in this source material."
    )


class MergedEventsResult(BaseModel):
    events: list[Event] = Field(
        description="Deduplicated final list of all unique events across sources."
    )
