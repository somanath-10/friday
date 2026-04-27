from friday.integrations.registry import list_integrations, resolve_input_source


def test_builtin_integrations_include_local_input_channels():
    integrations = list_integrations()
    sources = {manifest.source for manifest in integrations}

    assert "browser_upload" in sources
    assert "desktop_microphone" in sources
    assert "mobile_sync" in sources
    assert "wearable_sync" in sources
    assert "chat_text" in sources


def test_resolve_input_source_supports_aliases():
    mobile = resolve_input_source("phone")
    wearable = resolve_input_source("wearable")
    browser = resolve_input_source("browser")

    assert mobile.source == "mobile_sync"
    assert wearable.source == "wearable_sync"
    assert browser.source == "browser_upload"
