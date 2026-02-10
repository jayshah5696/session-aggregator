import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sagg.adapters.pi import PiAdapter, decode_pi_path
from sagg.models import SourceTool, TextPart, ToolCallPart, UnifiedSession

class TestPiAdapter:
    @pytest.fixture
    def adapter(self, tmp_path):
        """Create a PiAdapter with a mocked default path."""
        adapter = PiAdapter()
        # Monkeypatch get_default_path to return a temp directory
        # We can't easily monkeypatch a method on an instance that is called internally
        # unless we subclass or patch the class.
        # But here we only call methods on the instance, so patching the instance method is fine
        # if the method is called by other methods?
        # parse_session doesn't call get_default_path. list_sessions does.
        adapter.get_default_path = lambda: tmp_path / ".pi" / "agent" / "sessions"
        return adapter

    def test_decode_pi_path(self):
        """Test decoding of Pi project paths."""
        assert decode_pi_path("--Users-foo-code-myapp") == "/Users/foo/code/myapp"
        assert decode_pi_path("-Users-foo") == "/Users/foo"
        assert decode_pi_path("Users-foo--") == "/Users/foo"
        assert decode_pi_path("") == ""
        # Test already decoded-like input just in case
        assert decode_pi_path("/Users/foo") == "/Users/foo"

    def test_is_available(self, adapter, tmp_path):
        """Test availability check."""
        assert not adapter.is_available()
        (tmp_path / ".pi" / "agent" / "sessions").mkdir(parents=True)
        assert adapter.is_available()

    def test_list_sessions(self, adapter, tmp_path):
        """Test listing sessions."""
        sessions_dir = tmp_path / ".pi" / "agent" / "sessions"
        project_dir = sessions_dir / "--Users-test-project"
        project_dir.mkdir(parents=True)

        # Create a valid session file
        session_file = project_dir / "2023-10-27T10-00-00.jsonl"
        session_file.write_text('{"id": "1", "role": "user", "content": "hello"}', encoding="utf-8")

        # Create an invalid file
        (project_dir / "not_a_session.txt").write_text("ignore me")

        sessions = adapter.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].id == "2023-10-27T10-00-00"
        assert sessions[0].path == session_file

        # Test filtering by date
        future = datetime.now(timezone.utc) + timedelta(days=1)
        assert len(adapter.list_sessions(since=future)) == 0

    def test_parse_session(self, adapter, tmp_path):
        """Test parsing a session file."""
        sessions_dir = tmp_path / ".pi" / "agent" / "sessions"
        project_dir = sessions_dir / "--Users-test-project"
        project_dir.mkdir(parents=True)
        session_file = project_dir / "session1.jsonl"

        content = [
            {
                "id": "msg1",
                "role": "user",
                "content": "list files",
                "timestamp": "2023-10-27T10:00:00Z"
            },
            {
                "id": "msg2",
                "role": "assistant",
                "content": [{"type": "text", "text": "Listing files..."}],
                "timestamp": "2023-10-27T10:00:01Z",
                "tool_calls": [
                    {
                        "id": "call1",
                        "function": {"name": "ls", "arguments": "."}
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 20}
            }
        ]

        with session_file.open("w", encoding="utf-8") as f:
            for line in content:
                f.write(json.dumps(line) + "\n")

        sessions = adapter.list_sessions()
        assert len(sessions) == 1

        unified = adapter.parse_session(sessions[0])

        assert isinstance(unified, UnifiedSession)
        assert unified.source == SourceTool.PI
        assert unified.project_path == "/Users/test/project"
        assert unified.project_name == "project"
        assert unified.title == "list files"

        assert len(unified.turns) == 1
        turn = unified.turns[0]
        assert len(turn.messages) == 2

        msg1 = turn.messages[0]
        assert msg1.role == "user"
        assert isinstance(msg1.parts[0], TextPart)
        assert msg1.parts[0].content == "list files"

        msg2 = turn.messages[1]
        assert msg2.role == "assistant"
        assert len(msg2.parts) == 2
        assert isinstance(msg2.parts[0], TextPart)
        assert msg2.parts[0].content == "Listing files..."
        assert isinstance(msg2.parts[1], ToolCallPart)
        assert msg2.parts[1].tool_name == "ls"

        assert unified.stats.message_count == 2
        assert unified.stats.tool_call_count == 1
        assert unified.stats.input_tokens == 10
        assert unified.stats.output_tokens == 20

    def test_parse_session_tree_structure(self, adapter, tmp_path):
        """Test parsing out-of-order messages (tree structure simulation)."""
        sessions_dir = tmp_path / ".pi" / "agent" / "sessions"
        project_dir = sessions_dir / "--Users-test-project"
        project_dir.mkdir(parents=True)
        session_file = project_dir / "tree.jsonl"

        # Messages in random order
        content = [
            {"id": "2", "role": "assistant", "content": "Hi", "timestamp": "2023-10-27T10:00:01Z"},
            {"id": "1", "role": "user", "content": "Hello", "timestamp": "2023-10-27T10:00:00Z"},
        ]

        with session_file.open("w", encoding="utf-8") as f:
            for line in content:
                f.write(json.dumps(line) + "\n")

        sessions = adapter.list_sessions()
        unified = adapter.parse_session(sessions[0])

        # Should be sorted by timestamp
        assert len(unified.turns) == 1
        assert unified.turns[0].messages[0].role == "user"
        assert unified.turns[0].messages[1].role == "assistant"

    def test_parse_session_missing_timestamps(self, adapter, tmp_path):
        """Test parsing when timestamps are missing."""
        sessions_dir = tmp_path / ".pi" / "agent" / "sessions"
        project_dir = sessions_dir / "--Users-test-project"
        project_dir.mkdir(parents=True)
        session_file = project_dir / "no_time.jsonl"

        content = [
            {"id": "1", "role": "user", "content": "Hello"},
            {"id": "2", "role": "assistant", "content": "Hi"},
        ]

        with session_file.open("w", encoding="utf-8") as f:
            for line in content:
                f.write(json.dumps(line) + "\n")

        sessions = adapter.list_sessions()
        unified = adapter.parse_session(sessions[0])

        assert len(unified.turns) > 0
        # Since timestamps are missing, it uses current time, so sort order might depend on implementation details
        # (stable sort of equal elements)
        assert len(unified.turns[0].messages) == 2
