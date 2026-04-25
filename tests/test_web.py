from friday.tools.web import _parse_rss_items


def test_parse_rss_items_extracts_search_results():
    xml_text = """
    <rss version="2.0">
      <channel>
        <item>
          <title>Example Result</title>
          <link>https://example.com/result</link>
          <description><![CDATA[<p>This is a snippet.</p>]]></description>
        </item>
      </channel>
    </rss>
    """

    results = _parse_rss_items(xml_text)

    assert results == [
        {
            "title": "Example Result",
            "url": "https://example.com/result",
            "snippet": "This is a snippet.",
        }
    ]


def test_parse_rss_items_returns_empty_for_invalid_xml():
    assert _parse_rss_items("<rss>broken") == []
