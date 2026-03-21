# tests/conftest.py - Test configuration and shared fixtures
# Provides isolated mocking per-test without polluting sys.modules globally.
from __future__ import annotations

import sys
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Minimal stubs for agent package dependencies
# These are activated only via mock.patch at test level,
# NOT by modifying sys.modules globally.
# ---------------------------------------------------------------------------

def make_langchain_stub():
    """Create a minimal langchain stub for testing without full langchain."""
    langchain_stub = MagicMock()
    langchain_stub.agents = MagicMock()
    langchain_stub.agents.AgentExecutor = MagicMock(name="AgentExecutor")
    langchain_stub.agents.create_react_agent = MagicMock(name="create_react_agent")
    return langchain_stub


def make_requests_stub():
    """Create a requests stub that returns predictable responses."""
    stub = MagicMock(name="requests")
    stub.get = MagicMock()
    stub.post = MagicMock()
    stub.put = MagicMock()
    stub.delete = MagicMock()
    stub.patch = MagicMock()
    stub.head = MagicMock()
    stub.options = MagicMock()
    return stub


def make_boto3_stub():
    """Create a boto3 stub."""
    stub = MagicMock(name="boto3")
    stub.client = MagicMock()
    stub.session = MagicMock()
    return stub
