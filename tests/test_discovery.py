import httpx

from app.discovery import _parse_sitemap, is_usable_discovery_response, sitemap_declarations


def test_sitemap_declarations_are_case_insensitive() -> None:
    text = "User-agent: *\nSitemap: https://example.com/a.xml\nsitemap: https://example.com/b.xml\n"
    assert sitemap_declarations(text) == ["https://example.com/a.xml", "https://example.com/b.xml"]


def test_urlset_and_index_parse_differently() -> None:
    leaves, children = _parse_sitemap(b'<urlset><url><loc>https://example.com/a</loc></url></urlset>')
    assert leaves == ["https://example.com/a"]
    assert children == []
    leaves, children = _parse_sitemap(b'<sitemapindex><sitemap><loc>https://example.com/a.xml</loc></sitemap></sitemapindex>')
    assert leaves == []
    assert children == ["https://example.com/a.xml"]


def test_empty_202_is_not_usable_discovery_content() -> None:
    assert not is_usable_discovery_response(httpx.Response(202, content=b""))
    assert not is_usable_discovery_response(httpx.Response(202, content=b"queued"))
    assert not is_usable_discovery_response(httpx.Response(200, content=b""))
    assert is_usable_discovery_response(httpx.Response(200, content=b"User-agent: *"))
    assert is_usable_discovery_response(httpx.Response(404, content=b"not found"))
