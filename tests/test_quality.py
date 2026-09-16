from app.quality import assess_page_content
import json


def test_browser_fallback_is_replaced_by_rendered_article_cards() -> None:
    html = """
    <html><head><title>ITU News</title></head><body><main>
      <article><h2><a href="/one">First news card</a></h2><time>2026-09-08</time></article>
      <article><h2><a href="/two">Second news card</a></h2><time>2026-09-07</time></article>
    </main></body></html>
    """
    result = assess_page_content(
        html=html,
        url="https://example.test/hub/",
        trafilatura_content="This website will offer limited functionality in this browser. We only support the recent versions of major browsers.",
        output_format="markdown",
    )
    assert result.usable
    assert result.kind == "listing"
    assert result.extraction_method == "article_cards"
    assert "[First news card](https://example.test/one)" in result.content
    assert "rendered_article_cards" in result.signals


def test_normal_article_uses_trafilatura_content() -> None:
    result = assess_page_content(
        html="<html><body><main>irrelevant</main></body></html>",
        url="https://example.test/",
        trafilatura_content="A" * 200,
        output_format="markdown",
    )
    assert result.usable
    assert result.kind == "article"
    assert result.extraction_method == "trafilatura"


def test_listing_honors_txt_json_and_xml_output_formats() -> None:
    html = """
    <html><head><title>ITU News</title></head><body><main>
      <article><h2><a href="/one">First news card</a></h2></article>
      <article><h2><a href="/two">Second news card</a></h2></article>
    </main></body></html>
    """
    fallback = "This website will offer limited functionality in this browser."
    txt = assess_page_content(html=html, url="https://example.test/", trafilatura_content=fallback, output_format="txt")
    as_json = assess_page_content(html=html, url="https://example.test/", trafilatura_content=fallback, output_format="json")
    xml = assess_page_content(html=html, url="https://example.test/", trafilatura_content=fallback, output_format="xml")
    assert "First news card" in txt.content
    assert json.loads(as_json.content)["items"][0]["title"] == "First news card"
    assert "<listing>" in xml.content
