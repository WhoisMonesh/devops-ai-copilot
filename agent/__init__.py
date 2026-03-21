# agent/__init__.py
"""DevOps AI Copilot – Agent package."""

from .config import config

__all__ = ["config", "Orchestrator"]


def __getattr__(name: str):
    if name == "Orchestrator":
        from .orchestrator import Orchestrator
        return Orchestrator
    if name == "orchestrator":
        from . import orchestrator
        return orchestrator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
