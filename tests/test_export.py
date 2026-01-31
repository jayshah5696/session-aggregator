from sagg.export.markdown import MarkdownExporter
from sagg.models import UnifiedSession


def test_markdown_export(sample_session):
    """Test Markdown export format."""
    exporter = MarkdownExporter()
    md = exporter.export_session(sample_session)

    assert "# Test Session" in md
    assert "**ID**: `" in md
    assert "Hello" in md
    assert "Hi there" in md
    assert "### 👤 User" in md
