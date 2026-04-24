import json
from friday.tools.operator import register

def test_inspect_desktop_screen_mocked(mock_mcp, mocker, mock_workspace):
    register(mock_mcp)
    inspect_desktop_screen = mock_mcp.tools["inspect_desktop_screen"]
    
    # Mock OS and dependencies
    mocker.patch("friday.tools.operator._capture_desktop_screenshot", return_value=None)
    mocker.patch("friday.tools.operator._image_dimensions", return_value=(1920, 1080))
    mocker.patch("friday.tools.operator._open_window_snapshot", return_value=["Chrome", "VS Code"])
    mocker.patch("friday.tools.operator._openai_vision_text", return_value="Mocked vision analysis")
    
    result = inspect_desktop_screen(question="What do you see?", include_windows=True)
    
    assert "Image size: 1920x1080" in result
    assert "Visible windows:" in result
    assert "Chrome" in result
    assert "Mocked vision analysis" in result

def test_locate_screen_target_mocked(mock_mcp, mocker, mock_workspace):
    register(mock_mcp)
    locate_screen_target = mock_mcp.tools["locate_screen_target"]
    
    mocker.patch("friday.tools.operator._capture_desktop_screenshot", return_value=None)
    mocker.patch("friday.tools.operator._image_dimensions", return_value=(1920, 1080))
    mocker.patch("friday.tools.operator._open_window_snapshot", return_value=[])
    
    mock_json_response = '```json\n{"found": true, "x": 100, "y": 200, "width": 50, "height": 50, "confidence": 0.9, "label": "submit", "reason": "found it"}\n```'
    mocker.patch("friday.tools.operator._openai_vision_text", return_value=mock_json_response)
    
    result = locate_screen_target(target="submit button")
    
    parsed = json.loads(result)
    assert parsed["found"] is True
    assert parsed["x"] == 100
    assert parsed["y"] == 200
    assert "screenshot_path" in parsed
