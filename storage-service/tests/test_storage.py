from storage_service.core.exceptions import ServiceError
from storage_service.domain.paths import build_storage_key, sanitize_filename
from storage_service.infrastructure.auth import require_internal_key
from uuid import uuid4

import pytest


def test_sanitize_filename_strips_path_and_unsafe_chars():
    assert sanitize_filename("../../notes file.txt") == "notes_file.txt"
    assert sanitize_filename("") == "file"


def test_storage_key_is_thread_scoped():
    agent_id = uuid4()
    thread_id = uuid4()
    artifact_id = uuid4()
    key = build_storage_key(agent_id, thread_id, "INPUT", artifact_id, "a.txt")
    assert str(thread_id) in key
    assert "/threads/" in key
    assert key.endswith("/a.txt")


def test_internal_key_fails_closed():
    with pytest.raises(ServiceError):
        require_internal_key(None, "")
    with pytest.raises(ServiceError):
        require_internal_key("nope", "expected")
    require_internal_key("expected", "expected")
