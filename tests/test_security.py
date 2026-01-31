from sagg.security.scrubber import DataScrubber


def test_scrubber_api_key():
    """Test scrubbing of API keys."""
    scrubber = DataScrubber()

    text = "My API key is sk-1234567890abcdef12345678"
    scrubbed = scrubber.scrub(text)
    assert "sk-" not in scrubbed
    assert "[REDACTED:OPENAI_KEY]" in scrubbed


def test_scrubber_email():
    """Test scrubbing of emails."""
    scrubber = DataScrubber()

    text = "Contact me at user@example.com"
    scrubbed = scrubber.scrub(text)
    assert "user@example.com" not in scrubbed
    assert "[REDACTED:EMAIL]" in scrubbed


def test_scrubber_object():
    """Test recursive object scrubbing."""
    scrubber = DataScrubber()

    data = {
        "key": "sk-1234567890abcdef12345678",
        "nested": {"list": ["foo", "ghp_abcdef1234567890abcdef12345678901234"]},
    }

    scrubbed = scrubber.scrub_object(data)
    assert "sk-" not in scrubbed["key"]
    assert "ghp_" not in scrubbed["nested"]["list"][1]
