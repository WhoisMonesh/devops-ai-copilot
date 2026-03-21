import streamlit as st
import requests
import os
import json
import time
from datetime import datetime
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(
    page_title="DevOps AI Copilot",
    page_icon="robot",
    layout="wide",
    initial_sidebar_state="expanded",
)

AGENT_URL = os.getenv("AGENT_URL", "http://agent:8000")
API_KEY = os.getenv("AGENT_API_KEY", "")

# ---------------------------------------------------------------------------
# Session persistence via query params (Streamlit supports this via URL)
# ---------------------------------------------------------------------------
query_params = st.query_params
_default_session = query_params.get("session", "default") if hasattr(query_params, "get") else "default"

st.session_state.setdefault("messages", [])
st.session_state.setdefault("metrics_history", [])
st.session_state.setdefault("session_id", _default_session)
st.session_state.setdefault("operation_mode", "read_write")
st.session_state.setdefault("dark_mode", False)
st.session_state.setdefault("show_tool_timing", True)
st.session_state.setdefault("llm_provider", "ollama")

# ---------------------------------------------------------------------------
# Theme CSS injection
# ---------------------------------------------------------------------------
def inject_theme_css(dark: bool):
    if dark:
        st.markdown("""
        <style>
        :root {
            --bg-primary: #0e1117;
            --bg-secondary: #1c1f26;
            --text-primary: #f0f6fc;
            --text-secondary: #8b949e;
            --border: #30363d;
            --accent: #58a6ff;
            --success: #3fb950;
            --warning: #d29922;
            --danger: #f85149;
        }
        .stApp { background: var(--bg-primary); color: var(--text-primary); }
        .element-container { border: 1px solid var(--border); border-radius: 6px; padding: 8px; }
        .stMetric { background: var(--bg-secondary) !important; }
        </style>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <style>
        :root {
            --bg-primary: #ffffff;
            --bg-secondary: #f6f8fa;
            --text-primary: #1f2328;
            --text-secondary: #656d76;
            --border: #d0d7de;
            --accent: #0969da;
            --success: #1a7f37;
            --warning: #9a6700;
            --danger: #cf222e;
        }
        </style>
        """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _headers():
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def get_health():
    try:
        r = requests.get(f"{AGENT_URL}/health", timeout=5, headers=_headers())
        return r.json()
    except Exception as e:
        return {"status": "unreachable", "error": str(e)}


def get_llm_health():
    """Get detailed LLM provider health including circuit breaker state."""
    h = get_health()
    llm_info = h.get("llm", {})
    providers = llm_info.get("providers", {})
    return {
        "status": h.get("status", "unknown"),
        "provider": llm_info.get("provider", "unknown"),
        "providers": providers,
        "primary_status": llm_info.get("status", "unknown"),
        "detail": llm_info.get("detail", ""),
    }


def get_kb_stats():
    try:
        r = requests.get(f"{AGENT_URL}/kb/stats", timeout=5, headers=_headers())
        return r.json() if r.ok else {}
    except Exception:
        return {}


def get_config():
    try:
        r = requests.get(f"{AGENT_URL}/config", timeout=5, headers=_headers())
        return r.json()
    except Exception:
        return {}


def update_config(payload):
    try:
        r = requests.post(f"{AGENT_URL}/config", json=payload, timeout=10, headers=_headers())
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def ask_agent(question, context="", session_id="default"):
    try:
        r = requests.post(
            f"{AGENT_URL}/query",
            json={"question": question, "context": context, "session_id": session_id},
            timeout=300,
            headers=_headers(),
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.Timeout:
        return {"error": "Request timed out after 300s. The query is too complex or LLM is overloaded.", "answer": "Request timed out."}
    except Exception as e:
        return {"error": str(e), "answer": f"Agent unreachable: {e}"}


def get_tools():
    try:
        r = requests.get(f"{AGENT_URL}/tools", timeout=5, headers=_headers())
        return r.json() if isinstance(r.json(), list) else r.json().get("tools", [])
    except Exception:
        return []


def get_metrics():
    try:
        r = requests.get(f"{AGENT_URL}/metrics", timeout=5, headers=_headers())
        return r.text
    except Exception:
        return ""


def get_cache_stats():
    try:
        r = requests.get(f"{AGENT_URL}/cache/stats", timeout=5, headers=_headers())
        return r.json()
    except Exception:
        return {}


def get_permissions_status():
    try:
        r = requests.get(f"{AGENT_URL}/permissions/status", timeout=5, headers=_headers())
        return r.json()
    except Exception:
        return {}


def set_operation_mode(mode):
    try:
        r = requests.post(f"{AGENT_URL}/permissions/mode", json={"mode": mode}, timeout=5, headers=_headers())
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def check_tool_permission(tool_name):
    try:
        r = requests.get(f"{AGENT_URL}/permissions/check/{tool_name}", timeout=5, headers=_headers())
        return r.json()
    except Exception:
        return {}


def render_llm_status_indicator(llm_health: dict):
    """Render LLM provider status with circuit breaker state."""
    providers = llm_health.get("providers", {})
    primary = llm_health.get("provider", "unknown")

    for name, info in providers.items():
        if info.get("is_primary"):
            cb_state = info.get("circuit_breaker", "unknown")
            status = info.get("status", "unknown")
            detail = info.get("detail", "")

            if cb_state == "open":
                st.warning(f"⚠️ **LLM Circuit Breaker OPEN** — `{primary}` is temporarily unavailable ({detail}). Retrying...")
            elif cb_state == "half":
                st.info(f"🔄 **LLM Probing Recovery** — `{primary}` is testing availability.")
            elif status == "error":
                st.error(f"❌ **LLM Error** — `{primary}`: {detail}")
            else:
                st.success(f"✅ **LLM Online** — `{primary}` ({cb_state})")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("DevOps AI Copilot")
    st.caption("v1.2.0 - AI-Powered SRE Assistant")
    st.divider()

    # LLM status with circuit breaker
    llm_h = get_llm_health()
    agent_status = get_health().get("status", "unknown")
    status_color = "green" if agent_status == "ok" else "red" if agent_status == "unreachable" else "yellow"

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Agent** :{status_color}[{agent_status}]")
    with col2:
        st.markdown(f"**LLM** :{'green' if llm_h.get('primary_status') == 'ok' else 'red'}[{llm_h.get('provider', '?')}]")

    # Circuit breaker status
    with st.expander("🔌 LLM Provider Health"):
        render_llm_status_indicator(llm_h)
        for name, info in llm_h.get("providers", {}).items():
            is_p = "⭐" if info.get("is_primary") else "  "
            st.caption(f"{is_p} `{name}`: {info.get('status','?')} ({info.get('circuit_breaker','?')})")

    # Cache stats
    cache = get_cache_stats()
    if cache:
        qc = cache.get("query_cache", {})
        hit_ratio = qc.get("hit_ratio", 0) * 100
        st.caption(f"Cache hit ratio: **{hit_ratio:.1f}%**")

    st.divider()

    # Dark mode toggle
    dark_mode = st.toggle("🌙 Dark Mode", value=st.session_state.dark_mode)
    if dark_mode != st.session_state.dark_mode:
        st.session_state.dark_mode = dark_mode
        st.rerun()

    st.divider()

    # Navigation
    pages = [
        "💬 Chat",
        "📊 Dashboard",
        "🔧 Tools",
        "📚 Knowledge Base",
        "⚙️ Configuration",
        "📈 Metrics",
        "🔒 Permissions",
    ]
    page = st.radio("Navigation", pages, label_visibility="collapsed")
    st.divider()

    # Session ID with URL persistence
    session_id = st.text_input(
        "Session ID",
        value=st.session_state.session_id,
        help="Use the same session ID to continue conversations",
    )
    st.session_state.session_id = session_id

    if st.button("🔄 Refresh"):
        st.rerun()

    st.caption(f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")


# ---------------------------------------------------------------------------
# Page: Chat
# ---------------------------------------------------------------------------
if page == "💬 Chat":
    st.header("Ask Your DevOps Copilot")
    st.caption(
        "Query Kubernetes, Jenkins, Kibana, Grafana, Prometheus, Nginx, Artifactory, "
        "and more. Try: *'Show me pod restart counts'* or *'Why is the nginx pod crashing?'*"
    )

    # Quick action chips
    quick_actions = [
        "Show all pods with restart counts",
        "Find errors in Kibana last hour",
        "Check Jenkins build status",
        "List Grafana dashboards",
        "Show Prometheus alerts",
        "Get nginx error logs",
        "Check SSL certificates expiry",
        "Search runbooks for DB failover",
    ]
    cols = st.columns(3)
    for idx, action in enumerate(quick_actions):
        with cols[idx % 3]:
            if st.button(action, key=f"qa_{idx}"):
                st.session_state.messages.append({"role": "user", "content": action})

    st.divider()

    # Display messages with tool timing
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("metadata"):
                meta = msg["metadata"]
                badges = []
                if meta.get("cached"):
                    badges.append(":clock1: Cached")
                if meta.get("corr_id"):
                    badges.append(f"ID: `{meta['corr_id']}`")
                if meta.get("latency"):
                    badges.append(f"⏱ {meta['latency']:.2f}s")
                if meta.get("tool_used"):
                    badges.append(f"🔧 `{meta['tool_used']}`")
                if badges:
                    st.caption(" | ".join(badges))

    # Chat input
    if prompt := st.chat_input("e.g. Show Nginx error logs for the last hour..."):
        start_ts = time.time()
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                result = ask_agent(prompt, session_id=st.session_state.session_id)

            elapsed = time.time() - start_ts
            answer = result.get("answer", result.get("error", "No response."))
            st.markdown(answer)

            meta = {
                "cached": result.get("cached", False),
                "corr_id": result.get("corr_id", ""),
                "latency": elapsed,
                "tool_used": result.get("tool_used"),
            }

            col1, col2, col3 = st.columns(3)
            with col1:
                if result.get("cached"):
                    st.caption(":clock1: Cached")
            with col2:
                st.caption(f"⏱ {elapsed:.1f}s")
            with col3:
                if result.get("tool_used"):
                    st.caption(f"🔧 `{result['tool_used']}`")

            st.session_state.messages.append({"role": "assistant", "content": answer, "metadata": meta})

    # Action row
    if st.session_state.messages:
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            if st.button("Clear Chat"):
                st.session_state.messages = []
                st.rerun()
        with col2:
            export = json.dumps(st.session_state.messages, indent=2)
            st.download_button("Export JSON", export, file_name="chat_history.json", mime="application/json")
        with col3:
            # Copy session ID to clipboard
            st.caption(f"Session: `{st.session_state.session_id}`")


# ---------------------------------------------------------------------------
# Page: Dashboard
# ---------------------------------------------------------------------------
elif page == "📊 Dashboard":
    st.header("Infrastructure Dashboard")

    llm_h = get_llm_health()
    render_llm_status_indicator(llm_h)
    st.divider()

    cfg = get_config()

    service_map = [
        ("Agent", f"{AGENT_URL}/health", True),
        ("Nginx", cfg.get("nginx_url"), False),
        ("Kibana", cfg.get("kibana_url"), False),
        ("Jenkins", cfg.get("jenkins_url"), False),
        ("Artifactory", cfg.get("artifactory_url"), False),
        ("Prometheus", cfg.get("prometheus_url"), False),
        ("Grafana", cfg.get("grafana_url"), False),
    ]

    cols = st.columns(len(service_map))
    for idx, (name, url, always_show) in enumerate(service_map):
        with cols[idx]:
            if url:
                try:
                    r = requests.get(url, timeout=4)
                    code = r.status_code
                    color = "green" if 200 <= code < 300 else "orange" if code < 500 else "red"
                    st.markdown(f"**{name}**")
                    st.markdown(f":{color}[{code}]")
                except Exception:
                    st.markdown(f"**{name}**")
                    st.markdown(":red[unreachable]")
            elif always_show:
                st.markdown(f"**{name}**")
                st.markdown(":gray[not configured]")
            else:
                st.markdown(f"**{name}**")
                st.markdown(":gray[not configured]")

    st.divider()

    # KB stats
    kb_stats = get_kb_stats()
    if kb_stats:
        st.subheader("Knowledge Base")
        kb_cols = st.columns(len(kb_stats))
        for idx, (coll, count) in enumerate(kb_stats.items()):
            with kb_cols[idx]:
                st.metric(coll.title(), count if count >= 0 else "N/A")

    st.divider()

    # Grafana quick view
    grafana_url = cfg.get("grafana_url")
    if grafana_url:
        st.subheader("Grafana Quick View")
        try:
            headers = {}
            if os.getenv("GRAFANA_API_KEY"):
                headers["Authorization"] = f"Bearer {os.getenv('GRAFANA_API_KEY')}"
            dashboards_r = requests.get(
                f"{grafana_url.rstrip('/')}/api/search",
                headers=headers,
                timeout=5,
            )
            if dashboards_r.ok:
                dash_data = dashboards_r.json()
                dash_titles = [d.get("title", "Unknown") for d in dash_data[:15]]
                selected = st.selectbox("Select Dashboard", dash_titles)
                if selected:
                    selected_dash = next((d for d in dash_data if d.get("title") == selected), None)
                    if selected_dash:
                        st.info(f"Dashboard: {grafana_url}{selected_dash.get('url', '')}")
        except Exception as e:
            st.warning(f"Could not fetch Grafana dashboards: {e}")
    else:
        st.info("Configure `grafana_url` to enable Grafana integration.")

    st.divider()

    # Cache performance
    cache = get_cache_stats()
    if cache:
        st.subheader("Cache Performance")
        qc = cache.get("query_cache", {})
        tc = cache.get("tool_cache", {})
        col1, col2 = st.columns(2)
        with col1:
            st.metric(
                "Query Cache Hit Ratio",
                f"{qc.get('hit_ratio', 0)*100:.1f}%",
                delta=f"{qc.get('hits', 0)} hits" if qc.get('hits') else None,
            )
            st.caption(f"Entries: {qc.get('size', 0)}")
        with col2:
            st.metric(
                "Tool Cache Hit Ratio",
                f"{tc.get('hit_ratio', 0)*100:.1f}%",
                delta=f"{tc.get('hits', 0)} hits" if tc.get('hits') else None,
            )
            st.caption(f"Entries: {tc.get('size', 0)}")


# ---------------------------------------------------------------------------
# Page: Tools
# ---------------------------------------------------------------------------
elif page == "🔧 Tools":
    st.header("Available Tools")
    st.caption("Tools the AI agent can invoke. Grouped by category.")
    tools = get_tools()

    if not tools:
        st.warning("Could not fetch tools list from agent.")
    else:
        categories = {}
        for tool in tools:
            name = tool.get("name", "")
            category = name.split("_")[0] if "_" in name else "general"
            categories.setdefault(category, []).append(tool)

        for cat, cat_tools in sorted(categories.items()):
            with st.expander(f"**{cat.upper()}** ({len(cat_tools)} tools)"):
                for tool in cat_tools:
                    with st.container():
                        st.markdown(f"**`{tool.get('name', 'unknown')}`**")
                        st.caption(tool.get("description", "No description"))
                        if tool.get("parameters"):
                            with st.expander("Parameters"):
                                st.json(tool["parameters"])


# ---------------------------------------------------------------------------
# Page: Knowledge Base
# ---------------------------------------------------------------------------
elif page == "📚 Knowledge Base":
    st.header("Enterprise Knowledge Base")
    st.caption("Semantic search and management of runbooks, SOPs, configs, and incident docs.")

    kb_stats = get_kb_stats()
    if kb_stats:
        cols = st.columns(len(kb_stats))
        for idx, (coll, count) in enumerate(kb_stats.items()):
            with cols[idx]:
                st.metric(coll.title(), count if count >= 0 else "N/A")

    st.divider()

    # Search
    search_col1, search_col2 = st.columns([3, 1])
    with search_col1:
        kb_query = st.text_input("🔍 Search knowledge base", placeholder="e.g. 'nginx restart procedure'")
    with search_col2:
        top_k = st.selectbox("Top K", [3, 5, 10], index=1)

    if kb_query:
        with st.spinner("Searching..."):
            try:
                r = requests.post(
                    f"{AGENT_URL}/kb/search",
                    json={"query": kb_query, "top_k": top_k},
                    timeout=30,
                    headers=_headers(),
                )
                if r.ok:
                    data = r.json()
                    results = data.get("results", [])
                    st.success(f"Found {len(results)} results for: '{kb_query}'")

                    for res in results:
                        with st.expander(f"📄 {res.get('title', 'Untitled')} (similarity={res.get('similarity', 0):.2f})"):
                            st.markdown(f"**Collection:** `{res.get('collection', '')}`")
                            st.markdown(f"**Tags:** {', '.join(res.get('tags', []))}")
                            st.markdown(f"**Content:**\n\n{res.get('content', '')[:1000]}")
                else:
                    st.error(f"Search failed: {r.status_code}")
            except Exception as e:
                st.error(f"Search error: {e}")

    st.divider()

    # Quick KB queries
    st.subheader("Quick Search Examples")
    quick_queries = [
        "restart nginx in kubernetes",
        "database failover procedure",
        "SSL certificate renewal steps",
        "Jenkins pipeline troubleshooting",
        "Prometheus alert runbook",
    ]
    qcols = st.columns(3)
    for idx, q in enumerate(quick_queries):
        with qcols[idx % 3]:
            if st.button(f"🔍 {q}", key=f"kb_q_{idx}"):
                st.session_state["kb_search_query"] = q
                st.rerun()


# ---------------------------------------------------------------------------
# Page: Configuration
# ---------------------------------------------------------------------------
elif page == "⚙️ Configuration":
    st.header("Configuration")
    st.caption("All changes take effect immediately (hot-reload). Requires API key.")
    cfg = get_config()

    if not cfg:
        st.error("Could not load configuration. Is the API key set?")
        api_key_input = st.text_input("Agent API Key", type="password")
        if api_key_input:
            os.environ["AGENT_API_KEY"] = api_key_input
            st.rerun()
    else:
        tab1, tab2, tab3, tab4 = st.tabs(["AI / LLM", "Service URLs", "Kubernetes", "Cache"])

        with tab1:
            st.subheader("LLM Provider")
            llm_provider = st.selectbox(
                "Provider",
                ["ollama", "vertexai", "bedrock"],
                index=["ollama", "vertexai", "bedrock"].index(cfg.get("llm_provider", "ollama"))
                if cfg.get("llm_provider") in ["ollama", "vertexai", "bedrock"] else 0,
            )
            if llm_provider == "ollama":
                ollama_url = st.text_input("Base URL", value=cfg.get("ollama_base_url", "http://ollama:11434"))
                ollama_model = st.text_input("Model", value=cfg.get("ollama_model", "mistral"))
                temperature = st.slider("Temperature", 0.0, 2.0, float(cfg.get("ollama_temperature", 0.7)), 0.05)
                max_tokens = st.number_input("Max Tokens", 128, 8192, int(cfg.get("ollama_max_tokens", 2048)))
                timeout = st.number_input("Timeout (s)", 30, 300, int(cfg.get("ollama_timeout", 120)) if cfg.get("ollama_timeout") else 120)
                payload = {
                    "ollama_base_url": ollama_url,
                    "ollama_model": ollama_model,
                    "ollama_temperature": temperature,
                    "ollama_max_tokens": max_tokens,
                }
            elif llm_provider == "vertexai":
                vertexai_project = st.text_input("Project", value=cfg.get("vertexai_project", ""))
                vertexai_location = st.text_input("Location", value=cfg.get("vertexai_location", "us-central1"))
                vertexai_model = st.text_input("Model", value=cfg.get("vertexai_model", "gemini-1.5-pro"))
                payload = {}
            else:
                bedrock_region = st.text_input("Region", value=cfg.get("bedrock_region", "us-east-1"))
                bedrock_model = st.text_input("Model ID", value=cfg.get("bedrock_model_id", ""))
                payload = {}

        with tab2:
            st.subheader("Service URLs")
            payload = {
                "nginx_url": st.text_input("Nginx URL", value=cfg.get("nginx_url", "")),
                "kibana_url": st.text_input("Kibana URL", value=cfg.get("kibana_url", "")),
                "jenkins_url": st.text_input("Jenkins URL", value=cfg.get("jenkins_url", "")),
                "artifactory_url": st.text_input("Artifactory URL", value=cfg.get("artifactory_url", "")),
                "prometheus_url": st.text_input("Prometheus URL", value=cfg.get("prometheus_url", "http://prometheus.monitoring.svc:9090")),
                "grafana_url": st.text_input("Grafana URL", value=cfg.get("grafana_url", "")),
            }

        with tab3:
            st.subheader("Kubernetes")
            kc1, kc2 = st.columns(2)
            with kc1:
                k8s_in_cluster = st.checkbox("In-Cluster Auth", value=bool(cfg.get("k8s_in_cluster", True)))
                k8s_namespace = st.text_input("Default Namespace", value=cfg.get("k8s_namespace", "default"))
            with kc2:
                k8s_kubeconfig = st.text_input("Kubeconfig Path", value=cfg.get("k8s_kubeconfig_path", ""))
            payload = {
                "k8s_in_cluster": k8s_in_cluster,
                "k8s_namespace": k8s_namespace,
                "k8s_kubeconfig_path": k8s_kubeconfig,
            }

        with tab4:
            st.subheader("Cache Settings")
            cache_ttl = st.slider("TTL (seconds)", 30, 3600, 300, 30)
            cache_max = st.number_input("Max Entries", 50, 10000, 500, 50)
            if st.button("Invalidate Cache"):
                try:
                    inv = requests.post(f"{AGENT_URL}/cache/invalidate", headers=_headers())
                    st.success("Cache invalidated!" if inv.ok else "Failed")
                except Exception as e:
                    st.error(f"Error: {e}")
            payload = {"cache_ttl": cache_ttl, "cache_max_size": cache_max}

        st.divider()
        if st.button("Save Configuration", type="primary"):
            result = update_config(payload)
            if "error" in result:
                st.error(f"Failed: {result['error']}")
            else:
                st.success("Configuration saved and hot-reloaded!")


# ---------------------------------------------------------------------------
# Page: Metrics
# ---------------------------------------------------------------------------
elif page == "📈 Metrics":
    st.header("Agent Metrics")

    metrics_text = get_metrics()
    if metrics_text:
        lines = [ln for ln in metrics_text.strip().split("\n") if ln and not ln.startswith("#")]

        metric_data = {}
        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                metric_name = parts[0].split("{")[0]
                value = parts[-1]
                labels = {}
                if "{" in parts[0]:
                    label_str = parts[0].split("{")[1].rstrip("}")
                    for label in label_str.split(","):
                        if "=" in label:
                            k, v = label.split("=", 1)
                            labels[k.strip('"')] = v.strip('"')
                metric_data.setdefault(metric_name, []).append({"labels": labels, "value": value})

        # Key metric cards
        col1, col2, col3, col4 = st.columns(4)
        key_metrics = [
            ("devops_copilot_requests_total", "Total Requests", col1),
            ("devops_copilot_cache_hits_total", "Cache Hits", col2),
            ("devops_copilot_cache_misses_total", "Cache Misses", col3),
            ("devops_copilot_errors_total", "Total Errors", col4),
        ]
        for metric_name, label, col in key_metrics:
            if metric_name in metric_data:
                total = sum(float(e["value"]) for e in metric_data[metric_name])
                col.metric(label, f"{total:.0f}")

        st.divider()

        # Cache hit ratio gauge
        if "devops_copilot_cache_hit_ratio" in metric_data:
            ratio_val = float(metric_data["devops_copilot_cache_hit_ratio"][0]["value"])
            st.subheader("Cache Hit Ratio")
            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=ratio_val * 100,
                gauge={
                    "axis": {"range": [0, 100]},
                    "bar": {"color": "green" if ratio_val > 0.7 else "orange" if ratio_val > 0.4 else "red"},
                    "steps": [
                        {"range": [0, 40], "color": "red"},
                        {"range": [40, 70], "color": "orange"},
                        {"range": [70, 100], "color": "green"},
                    ],
                },
                title={"text": "Cache Hit Ratio (%)"},
            ))
            st.plotly_chart(fig, use_container_width=True)

        # Latency histogram
        if "devops_copilot_request_latency_seconds" in metric_data:
            st.subheader("Request Latency Histogram")
            buckets = [(e["labels"].get("le", "inf"), float(e["value"])) for e in metric_data["devops_copilot_request_latency_seconds"]]
            if buckets:
                fig = px.bar(
                    x=[b[0] for b in buckets],
                    y=[b[1] for b in buckets],
                    labels={"x": "Latency bucket (s)", "y": "Count"},
                )
                st.plotly_chart(fig, use_container_width=True)

        # Tool usage
        if "devops_copilot_tool_calls_total" in metric_data:
            st.subheader("Tool Usage")
            tool_counts = {}
            for e in metric_data["devops_copilot_tool_calls_total"]:
                tool_name = e["labels"].get("tool_name", "unknown")
                count = float(e["value"])
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + count
            if tool_counts:
                df = pd.DataFrame(list(tool_counts.items()), columns=["Tool", "Calls"])
                df = df.sort_values("Calls", ascending=False)
                fig = px.bar(df, x="Tool", y="Calls", color="Calls", title="Tool Usage Breakdown")
                st.plotly_chart(fig, use_container_width=True)

        # LLM metrics
        llm_metrics = [k for k in metric_data if "llm" in k]
        if llm_metrics:
            st.subheader("LLM Metrics")
            for m in llm_metrics[:5]:
                total = sum(float(e["value"]) for e in metric_data[m])
                st.metric(m.replace("devops_copilot_", ""), f"{total:.0f}")

        with st.expander("Raw Prometheus Metrics"):
            st.code(metrics_text, language="text")
    else:
        st.warning("Could not fetch metrics from agent.")


# ---------------------------------------------------------------------------
# Page: Permissions
# ---------------------------------------------------------------------------
elif page == "🔒 Permissions":
    st.header("Operation Mode & Permissions")

    perms = get_permissions_status()
    if not perms:
        st.error("Could not fetch permissions status from agent.")
    else:
        col1, col2 = st.columns([1, 1])

        with col1:
            st.subheader("Current Mode")
            current_mode = perms.get("mode", "unknown")
            mode_colors = {"read_only": "red", "read_write": "green", "safe_mode": "orange"}
            color = mode_colors.get(current_mode, "gray")
            st.markdown(f"**Mode:** :{color}[{current_mode.upper()}]")

            st.subheader("Change Operation Mode")
            mc1, mc2, mc3 = st.columns(3)
            modes = [
                (mc1, "🔴 Read Only", "read_only"),
                (mc2, "🟢 Read/Write", "read_write"),
                (mc3, "🟠 Safe Mode", "safe_mode"),
            ]
            for col, label, mode in modes:
                with col:
                    if st.button(label):
                        result = set_operation_mode(mode)
                        if "error" not in result:
                            st.success(f"Mode set to {mode.upper().replace('_', ' ')}")
                            st.rerun()
                        else:
                            st.error(result.get("message", "Failed"))

        with col2:
            st.subheader("Security Status")
            audit_enabled = perms.get("audit_enabled", False)
            st.checkbox("Audit Logging", value=audit_enabled, disabled=True)
            denied = perms.get("denied_tools", [])
            st.write(f"**Denied Tools:** {len(denied)}")
            if denied:
                st.code(", ".join(denied))

        st.divider()

        # Tool permission checker
        st.subheader("Check Tool Permissions")
        tool_name = st.text_input("Tool name", placeholder="e.g. delete_pod")
        if tool_name:
            result = check_tool_permission(tool_name)
            if result:
                allowed = result.get("allowed", False)
                st.success("✅ ALLOWED") if allowed else st.error("❌ DENIED")
                st.caption(f"Reason: {result.get('reason', 'N/A')}")
                st.caption(f"Mode: `{result.get('current_mode', '?')}`")

        st.divider()
        st.info("💡 Use READ_ONLY mode during incident investigation to prevent accidental changes.")
