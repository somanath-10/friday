from friday.tools.utils import register

def test_format_json(mock_mcp):
    register(mock_mcp)
    format_json = mock_mcp.tools["format_json"]

    # Test valid JSON
    valid_json = '{"b": 2, "a": 1}'
    result = format_json(valid_json)
    assert "{\n  \"b\": 2,\n  \"a\": 1\n}" in result

    # Test invalid JSON
    invalid_json = '{b: 2, a: 1}'
    result = format_json(invalid_json)
    assert "Invalid JSON" in result

def test_word_count(mock_mcp):
    register(mock_mcp)
    word_count = mock_mcp.tools["word_count"]

    text = "Hello world\nThis is a test."
    result = word_count(text)

    assert result["words"] == 6
    assert result["lines"] == 2
    assert result["characters"] == len(text)
