from app.metadata import extract_page_metadata


def test_extracts_raw_html_metadata_and_json_ld() -> None:
    html = """
    <html lang="en"><head>
      <title>Document title</title>
      <meta name="description" content="  A useful description  ">
      <meta name="keywords" content="metadata, reader">
      <meta property="og:title" content="Open Graph title">
      <meta property="og:image" content="https://cdn.example.test/image.png">
      <meta name="twitter:card" content="summary_large_image">
      <link rel="canonical" href="/canonical">
      <link rel="alternate" hreflang="fr" href="/fr/page">
      <script type="application/ld+json">{"@type":"Article","headline":"JSON-LD title"}</script>
    </head><body><article><p>Readable article text.</p></article></body></html>
    """
    metadata = extract_page_metadata(html, "https://example.test/page")

    assert metadata["html"]["title"] == "Document title"
    assert metadata["html"]["language"] == "en"
    assert metadata["html"]["seo"]["description"] == "A useful description"
    assert metadata["html"]["open_graph"]["title"] == "Open Graph title"
    assert metadata["html"]["twitter"]["card"] == "summary_large_image"
    assert metadata["html"]["canonical"] == "https://example.test/canonical"
    assert metadata["html"]["hreflang"] == [{"language": "fr", "url": "https://example.test/fr/page"}]
    assert metadata["html"]["json_ld"] == [{"@type": "Article", "headline": "JSON-LD title"}]


def test_preserves_repeated_open_graph_tags() -> None:
    metadata = extract_page_metadata(
        '<meta property="og:image" content="https://example.test/one.png"><meta property="og:image" content="https://example.test/two.png">',
        "https://example.test/",
    )
    assert metadata["html"]["open_graph"]["image"] == [
        "https://example.test/one.png",
        "https://example.test/two.png",
    ]
