# agent/tools/llm_tools.py
# LangChain tools that call LLM providers (Vertex AI / Bedrock / Ollama)
# Used for summarisation, root-cause analysis, and free-form reasoning.

from __future__ import annotations

import logging
from typing import Optional

from langchain_core.tools import tool

import llm_client  # unified multi-provider LLM client

logger = logging.getLogger(__name__)


@tool
def llm_summarise(text: str, max_words: int = 150) -> str:
    """Summarise a block of text (logs, events, config) in plain English."""
    try:
        prompt = (
            f"Summarise the following DevOps output in at most {max_words} words. "
            "Focus on errors, warnings, and actionable items.\n\n"
            f"{text[:8000]}"
        )
        return llm_client.chat(prompt)
    except Exception as exc:
        logger.error("llm_summarise failed: %s", exc)
        return f"Error: {exc}"


@tool
def llm_root_cause_analysis(error_log: str, service: Optional[str] = None) -> str:
    """Perform root-cause analysis on an error log and suggest fixes."""
    try:
        svc_hint = f" for the {service} service" if service else ""
        prompt = (
            f"You are a senior SRE. Analyse the following error log{svc_hint} "
            "and provide:\n"
            "1. Root cause (2-3 sentences)\n"
            "2. Immediate remediation steps\n"
            "3. Long-term prevention\n\n"
            f"{error_log[:8000]}"
        )
        return llm_client.chat(prompt)
    except Exception as exc:
        logger.error("llm_root_cause_analysis failed: %s", exc)
        return f"Error: {exc}"


@tool
def llm_generate_runbook(task_description: str) -> str:
    """Generate a step-by-step runbook for a DevOps task."""
    try:
        prompt = (
            "You are a DevOps expert. Write a concise runbook for the following task.\n"
            "Include: prerequisites, numbered steps, rollback procedure.\n\n"
            f"Task: {task_description}"
        )
        return llm_client.chat(prompt)
    except Exception as exc:
        logger.error("llm_generate_runbook failed: %s", exc)
        return f"Error: {exc}"


@tool
def llm_explain_k8s_error(error_message: str) -> str:
    """Explain a Kubernetes error message and suggest kubectl commands to fix it."""
    try:
        prompt = (
            "You are a Kubernetes expert. Explain the following error in plain English "
            "and provide kubectl commands to diagnose and fix it.\n\n"
            f"Error: {error_message}"
        )
        return llm_client.chat(prompt)
    except Exception as exc:
        logger.error("llm_explain_k8s_error failed: %s", exc)
        return f"Error: {exc}"


@tool
def llm_compare_configs(config_a: str, config_b: str, context: str = "") -> str:
    """Compare two configuration blobs and highlight meaningful differences."""
    try:
        ctx = f" Context: {context}" if context else ""
        prompt = (
            f"Compare the following two configurations.{ctx}\n"
            "List only the meaningful differences and whether each change is safe or risky.\n\n"
            f"--- Config A ---\n{config_a[:4000]}\n\n"
            f"--- Config B ---\n{config_b[:4000]}"
        )
        return llm_client.chat(prompt)
    except Exception as exc:
        logger.error("llm_compare_configs failed: %s", exc)
        return f"Error: {exc}"


LLM_TOOLS = [
    llm_summarise,
    llm_root_cause_analysis,
    llm_generate_runbook,
    llm_explain_k8s_error,
    llm_compare_configs,
]
