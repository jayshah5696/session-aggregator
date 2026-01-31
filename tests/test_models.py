import time
from sagg.models import UnifiedSession, generate_session_id, extract_project_name


def test_generate_session_id():
    """Test UUID v7 generation."""
    id1 = generate_session_id()
    time.sleep(0.002)  # Ensure millisecond difference for sort order
    id2 = generate_session_id()
    assert len(id1) == 36
    assert id1 != id2
    # Lexicographical sort should match time order roughly
    assert id1 < id2


def test_extract_project_name():
    """Test project name extraction from paths."""
    assert extract_project_name("/Users/dev/projects/my-app") == "my-app"
    assert extract_project_name("/home/user/code/") == "code"
    assert extract_project_name("") == "unknown"
    assert extract_project_name("foo") == "foo"


def test_session_serialization(sample_session):
    """Test JSON serialization and deserialization."""
    json_str = sample_session.model_dump_json()
    restored = UnifiedSession.model_validate_json(json_str)

    assert restored.id == sample_session.id
    assert restored.source == sample_session.source
    assert len(restored.turns) == 1
    assert restored.turns[0].messages[0].parts[0].content == "Hello"


def test_extract_text_content(sample_session):
    """Test text content extraction for FTS."""
    content = sample_session.extract_text_content()
    assert "Hello" in content
    assert "Hi there" in content
