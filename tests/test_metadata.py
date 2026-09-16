from app.metadata import METADATA_FIELDS, extract_page_metadata


def test_returns_only_trafilatura_metadata_fields() -> None:
    html = """
    <html lang="en"><head>
      <title>Document title</title>
      <meta name="description" content="A useful description">
      <meta property="og:title" content="Open Graph title">
      <meta property="og:image" content="https://cdn.example.test/image.png">
    </head><body><article><p>Readable article text.</p></article></body></html>
    """
    metadata = extract_page_metadata(html, "https://example.test/page")

    assert set(metadata) == set(METADATA_FIELDS)
    assert metadata["title"] == "Open Graph title"
    assert metadata["description"] == "A useful description"
    assert metadata["url"] == "https://example.test/page"
    assert metadata["image"] == "https://cdn.example.test/image.png"


def test_metadata_omits_trafilatura_document_tree() -> None:
    metadata = extract_page_metadata("<title>Only title</title>", "https://example.test/")
    assert "body" not in metadata
    assert "commentsbody" not in metadata
    assert "html" not in metadata
    assert "trafilatura" not in metadata
