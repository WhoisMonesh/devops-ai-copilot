# agent/orchestrator.py
# Runs INSIDE the Kubernetes cluster.
# - Uses in-cluster service DNS (jenkins.devops.svc, elasticsearch.devops.svc, etc.)
# - LLM provider is fully swappable via LLM_PROVIDER env var (ollama | vertexai | bedrock)
# - All tool sets toggled via *_ENABLED env vars (set from GUI -> ConfigMap)

import logging
import time
import uuid
from typing import Any, List, Optional, TYPE_CHECKING

from langchain.agents import AgentExecutor, create_react_agent
from langchain.memory import ConversationBufferWindowMemory
from langchain_core.language_models.llms import LLM
from langchain_core.prompts import PromptTemplate

import agent.llm_client as llm_client  # unified multi-provider LLM client
from .config import config
from .permissions import get_permissions, check_tool_permission, audit_log

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enhanced system prompt with better query understanding
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are DevOps AI Copilot - expert SRE assistant running inside the Kubernetes cluster.

You have access to these tools: {tool_names}

{tools}

Current infrastructure endpoints:
  Nginx:         {nginx_url}
  Kibana:        {kibana_url}
  Jenkins:       {jenkins_url}
  Artifactory:   {artifactory_url}
  K8s Namespace: {k8s_namespace}
  Prometheus:    {prometheus_url}
  Grafana:       {grafana_url}
  LLM Provider:  {llm_provider}

## Intent Classification
Classify the user's query into one of these categories:
1. **STATUS** - Live state queries (pod health, build status, service uptime)
2. **LOGS** - Log search/analysis (error traces, access logs, search queries)
3. **METRICS** - Time-series data (Prometheus/Grafana queries, dashboards)
4. **ARTIFACT** - Artifact management (search, upload, metadata)
5. **DEPLOY** - Deployment operations (rollouts, scaling, restarts)
6. **INCIDENT** - Root-cause analysis, alerting, runbooks
7. **GENERAL** - Documentation, how-to, configuration help

## Query Routing Rules
- STATUS/LOGS/ARTIFACT queries: use appropriate tool immediately
- METRICS queries: prefer Prometheus tools; fall back to Grafana for dashboards
- INCIDENT queries: chain tools (logs -> RCA -> runbook generation)
- DEPLOY queries: verify state before and after with status tools
- When unsure, use the most specific tool available rather than guessing

## Response Guidelines
1. Always use a tool when the question is about live infra state
2. Never make up facts - if a tool fails, say so clearly with the error message
3. Be concise and actionable. Use bullet points for status queries
4. For metrics: include timestamps, units, and comparison to thresholds
5. For incidents: follow the 3-part RCA format (cause, remediation, prevention)
6. Prefer JSON/dict output for structured data; prose for summaries
7. When multiple tools are relevant, chain them logically (get pods -> get logs)

## Query Understanding Hints
- "show me X" or "what is X" → STATUS query
- "find errors in" or "search logs for" → LOGS query
- "metrics for" or "dashboard for" → METRICS query
- "deploy" or "restart" → DEPLOY query
- "why is X down" or "root cause" → INCIDENT query
- "compare configs" or "diff" → use llm_compare_configs

Format:
  Thought: <reasoning>
  Action: <tool_name>
  Action Input: <input>
  Observation: <result>
  ... (repeat as needed)
  Final Answer: <clear answer to the user>
"""


# ---------------------------------------------------------------------------
# LangChain LLM wrapper that delegates to llm_client.chat()
# ---------------------------------------------------------------------------
class DevOpsLLM(LLM):
    """Thin LangChain LLM wrapper over our unified llm_client."""

    @property
    def _llm_type(self) -> str:
        return f"devops-llm-{config.llm.provider}"

    def _call(self, prompt: str, stop: Optional[List[str]] = None, **kwargs: Any) -> str:
        response = llm_client.chat(prompt)
        if stop:
            for s in stop:
                if s in response:
                    response = response[: response.index(s)]
        return response

    @property
    def _identifying_params(self) -> dict:
        return {
            "provider": config.llm.provider,
            "model": (
                config.llm.ollama_model
                if config.llm.provider == "ollama"
                else config.llm.vertexai_model
                if config.llm.provider in ("vertexai", "gemini")
                else config.llm.bedrock_model_id
            ),
        }


# ---------------------------------------------------------------------------
# Permission-aware tool wrapper
# ---------------------------------------------------------------------------
def _wrap_tool_with_permission(tool):
    """Wrap a LangChain tool with permission checking."""
    from langchain_core.tools import BaseTool

    tool_name = tool.name
    original_run = getattr(tool, '_run', None)
    original_arun = getattr(tool, '_arun', None)

    def permitted_run(*args, **kwargs):
        allowed, reason = check_tool_permission(tool_name)
        op_type = get_permissions().get_operation_type(tool_name)
        audit_log(
            tool_name=tool_name,
            operation=op_type.value,
            mode=get_permissions().mode.value,
            allowed=allowed,
            details=reason,
        )
        if not allowed:
            logger.warning("Tool '%s' blocked by permissions: %s", tool_name, reason)
            return f"Permission denied: {reason}"
        if original_run:
            return original_run(*args, **kwargs)
        return f"Tool '{tool_name}' executed"

    async def permitted_arun(*args, **kwargs):
        allowed, reason = check_tool_permission(tool_name)
        op_type = get_permissions().get_operation_type(tool_name)
        audit_log(
            tool_name=tool_name,
            operation=op_type.value,
            mode=get_permissions().mode.value,
            allowed=allowed,
            details=reason,
        )
        if not allowed:
            logger.warning("Tool '%s' blocked by permissions: %s", tool_name, reason)
            return f"Permission denied: {reason}"
        if original_arun:
            return await original_arun(*args, **kwargs)
        return f"Tool '{tool_name}' executed"

    class PermittedTool(BaseTool):
        name: str = tool.name
        description: str = tool.description
        args_schema: Optional[type] = getattr(tool, 'args_schema', None)

        def _run(self, *args, **kwargs):
            return permitted_run(*args, **kwargs)

        async def _arun(self, *args, **kwargs):
            return await permitted_arun(*args, **kwargs)

    return PermittedTool()


# ---------------------------------------------------------------------------
# Tool loading (lazy import so missing creds don't crash startup)
# ---------------------------------------------------------------------------
def _load_tools() -> list:
    tools: list = []
    try:
        from .tools.k8s_tool import k8s_tools
        tools.extend(k8s_tools)
        logger.info("Loaded K8s tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.jenkins_tool import jenkins_tools
        tools.extend(jenkins_tools)
        logger.info("Loaded Jenkins tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.kibana_tool import kibana_tools
        tools.extend(kibana_tools)
        logger.info("Loaded Kibana tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.artifactory_tool import artifactory_tools
        tools.extend(artifactory_tools)
        logger.info("Loaded Artifactory tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.nginx_tool import get_nginx_tools
        tools.extend(get_nginx_tools())
        logger.info("Loaded Nginx tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.prometheus_tools import PROMETHEUS_TOOLS
        tools.extend(PROMETHEUS_TOOLS)
        logger.info("Loaded Prometheus tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.grafana_tool import GRAFANA_TOOLS
        tools.extend(GRAFANA_TOOLS)
        logger.info("Loaded Grafana tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.llm_tools import LLM_TOOLS
        tools.extend(LLM_TOOLS)
        logger.info("Loaded LLM tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.aws_tool import AWS_TOOLS
        tools.extend(AWS_TOOLS)
        logger.info("Loaded AWS tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.cloudwatch_tool import CLOUDWATCH_TOOLS
        tools.extend(CLOUDWATCH_TOOLS)
        logger.info("Loaded CloudWatch tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.database_tool import DATABASE_TOOLS
        tools.extend(DATABASE_TOOLS)
        logger.info("Loaded Database tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.docker_tool import DOCKER_TOOLS
        tools.extend(DOCKER_TOOLS)
        logger.info("Loaded Docker tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.github_tool import GITHUB_TOOLS
        tools.extend(GITHUB_TOOLS)
        logger.info("Loaded GitHub tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.pagerduty_tool import PAGERDUTY_TOOLS
        tools.extend(PAGERDUTY_TOOLS)
        logger.info("Loaded PagerDuty tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.ssl_tool import SSL_TOOLS
        tools.extend(SSL_TOOLS)
        logger.info("Loaded SSL tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.terraform_tool import TERRAFORM_TOOLS
        tools.extend(TERRAFORM_TOOLS)
        logger.info("Loaded Terraform tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    try:
        from .tools.knowledge_base_tool import KB_TOOLS
        tools.extend(KB_TOOLS)
        logger.info("Loaded Knowledge Base tools")
    except Exception:
        pass  # Intentionally broad: tool loading may fail due to missing deps, config, or import errors
    if not tools:
        logger.error("No tools loaded - agent will have very limited capability")
    # Wrap all tools with permission checks
    wrapped_tools = [_wrap_tool_with_permission(t) for t in tools]
    logger.info("Tools wrapped with permission checks | total=%d", len(wrapped_tools))
    return wrapped_tools


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
class Orchestrator:
    def __init__(self) -> None:
        self._agent_executor: Optional[AgentExecutor] = None
        self._memory = ConversationBufferWindowMemory(
            memory_key="chat_history", k=10, return_messages=True
        )
        self._build()

    def _build(self) -> None:
        """(Re-)build agent executor - called on startup and config hot-reload."""
        tools = _load_tools()
        llm = DevOpsLLM()
        tool_names = ", ".join(t.name for t in tools)
        grafana_url = config.infra.grafana_url or 'not configured'

        # Build a template that preserves {tools} and {tool_names} for create_react_agent
        # Only pre-format the infrastructure variables that don't change at runtime
        infrastructure_template = SYSTEM_PROMPT.format(
            tool_names='{tool_names}',  # preserved for agent
            tools='{tools}',           # preserved for agent
            nginx_url=config.infra.nginx_url or "not configured",
            kibana_url=config.infra.kibana_url or "not configured",
            jenkins_url=config.infra.jenkins_url or "not configured",
            artifactory_url=config.infra.artifactory_url or "not configured",
            k8s_namespace=config.infra.k8s_namespace,
            prometheus_url=getattr(config.infra, 'prometheus_url', 'not configured'),
            grafana_url=grafana_url,
            llm_provider=config.llm.provider,
        )

        prompt = PromptTemplate.from_template(
            infrastructure_template
            + "\n\nChat History:\n{chat_history}\n\nQuestion: {input}\n{agent_scratchpad}"
        )
        agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)
        self._agent_executor = AgentExecutor(
            agent=agent,
            tools=tools,
            memory=self._memory,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=8,
        )
        logger.info(
            "Orchestrator built | provider=%s | tools=%d",
            config.llm.provider,
            len(tools),
        )

    def reload(self) -> None:
        """Hot-reload: refresh config then rebuild agent."""
        config.reload()
        self._build()
        logger.info("Orchestrator hot-reloaded")

    def run(self, question: str, session_id: str = "default") -> dict:
        """Run the agent on a user question and return structured result.

        Implements:
        - Query caching (5-min TTL) to avoid repeated LLM calls
        - Per-request correlation ID for tracing
        - Self-metrics collection (latency, tool usage, errors)
        """
        from agent.cache import _question_cache_key, QUERY_CACHE
        from agent.metrics import get_metrics_collector

        metrics = get_metrics_collector()
        corr_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        # --- Check query cache ---
        cache_key = _question_cache_key(question, session_id)
        cached = QUERY_CACHE.get(cache_key)
        if cached is not None:
            metrics.record_cache_hit()
            latency = time.time() - start_time
            metrics.record_latency(latency)
            logger.info("[corr_id=%s] Cache hit for question (session=%s)", corr_id, session_id)
            return {
                "answer": cached["answer"],
                "tool_used": cached.get("tool_used"),
                "sources": cached.get("sources") or [],
                "cached": True,
                "corr_id": corr_id,
            }
        metrics.record_cache_miss()

        if not self._agent_executor:
            metrics.record_error("initialization", "orchestrator")
            return {"answer": "Agent not initialized.", "tool_used": None, "sources": []}

        try:
            result = self._agent_executor.invoke({"input": question})
            latency = time.time() - start_time
            metrics.record_latency(latency)
            metrics.record_request("success")
            answer = result.get("output", "")

            # --- Cache the response ---
            QUERY_CACHE.set(cache_key, {
                "answer": answer,
                "tool_used": result.get("tool_used"),
                "sources": result.get("sources"),
            })

            return {
                "answer": answer,
                "tool_used": None,
                "sources": [],
                "cached": False,
                "corr_id": corr_id,
                "latency_seconds": round(latency, 2),
            }
        except Exception:
            # Intentionally broad: orchestrator run() may encounter agent, LLM, or tool errors
            latency = time.time() - start_time
            metrics.record_latency(latency)
            metrics.record_request("error")
            metrics.record_error("Exception", "orchestrator")
            logger.exception("Agent error [corr_id=%s] for question=%r", corr_id, question)
            return {"answer": "Error: agent execution failed", "tool_used": None, "sources": None}

    def llm_health(self) -> dict:
        """Return LLM provider health info."""
        return llm_client.health()
