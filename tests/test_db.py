import sqlite3
from unittest.mock import patch

from sagg.storage.db import SCHEMA_VERSION, Database


def test_get_schema_version_uninitialized(temp_db_path):
    """Test get_schema_version when the table doesn't exist."""
    db = Database(temp_db_path)
    # Don't call initialize_schema
    assert db.get_schema_version() == 0
    db.close()


def test_get_schema_version_operational_error(temp_db_path):
    """Test get_schema_version when an OperationalError occurs."""
    db = Database(temp_db_path)

    with patch.object(db, 'execute', side_effect=sqlite3.OperationalError("Mocked error")):
        assert db.get_schema_version() == 0

    db.close()


def test_get_schema_version_success(temp_db_path):
    """Test get_schema_version returns correct version after initialization."""
    db = Database(temp_db_path)
    db.initialize_schema()

    assert db.get_schema_version() == SCHEMA_VERSION
    db.close()
