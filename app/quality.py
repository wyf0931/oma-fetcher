from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup


BOILERPLATE_PATTERNS = (
    "limited functionality in this browser",
    "we only support the recent versions of major browsers",
    "this website uses cookies to improve your experience",
)


@dataclass(frozen=True)
class ContentAssessment:
    usable: bool
    content: str
    kind: str | None
    extraction_method: str | None
    signals: list[str]


def assess_page_content(*, html: str, url: str, trafilatura_content: str) -> ContentAssessment:
    text = trafilatura_content.strip()
    lowered = text.lower()
    boilerplate = [pattern for pattern in BOILERPLATE_PATTERNS if pattern in lowered]
    if not boilerplate and len(text) >= 160:
        return ContentAssessment(True, text, "article", "trafilatura", [])

    listing = extract_article_cards(html, url)
    signals = [f"boilerplate:{pattern}" for pattern in boilerplate]
    if listing:
        signals.append("rendered_article_cards")
        return ContentAssessment(True, listing, "listing", "article_cards", signals)
    if len(text) < 160:
        signals.append("trafilatura_too_short")
    return ContentAssessment(False, text, None, None, signals)


def extract_article_cards(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    scope = soup.find("main") or soup
    cards: list[tuple[str, str | None, str | None]] = []
    for article in scope.find_all("article"):
        heading = article.find(["h1", "h2", "h3", "h4"])
        if not heading:
            continue
        title = _clean(heading.get_text(" ", strip=True))
        if not title:
            continue
        link = heading.find("a", href=True) or article.find("a", href=True)
        href = urljoin(base_url, link["href"]) if link else None
        time = article.find("time")
        date = _clean(time.get_text(" ", strip=True)) if time else None
        cards.append((title, href, date))
    if len(cards) < 2:
        return None

    page_title = _clean(soup.title.get_text(" ", strip=True) if soup.title else None) or "Listing"
    lines = [f"# {page_title}"]
    for title, href, date in cards:
        lines.append("")
        lines.append(f"## [{title}]({href})" if href else f"## {title}")
        if date:
            lines.append(date)
    return "\n".join(lines)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
