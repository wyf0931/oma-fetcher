from app.discovery import _parse_sitemap, sitemap_declarations


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
