import streamlit as st
import requests
import os
import json
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

st.session_state.setdefault("messages", [])
st.session_state.setdefault("metrics_history", [])
st.session_state.setdefault("session_id", "default")

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
            timeout=180,
            headers=_headers(),
        )
        return r.json()
    except Exception as e:
        return {"error": str(e), "answer": "Agent unreachable."}

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

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("DevOps AI Copilot")
    st.caption("v1.1.0 - AI-Powered SRE Assistant")
    st.divider()

    health = get_health()
    col1, col2 = st.columns(2)
    with col1:
        status = health.get("status", "unknown")
        color = "green" if status == "ok" else "red" if status == "unreachable" else "yellow"
        st.markdown(f"**Agent** :{color}[{status}]")
    with col2:
        llm_provider = health.get("llm", {}).get("provider", "unknown")
        st.caption(f"LLM: `{llm_provider}`")

    # Quick metrics
    cache = get_cache_stats()
    if cache:
        qc = cache.get("query_cache", {})
        st.caption(f"Cache hit ratio: **{qc.get('hit_ratio', 0)*100:.1f}%**")

    st.divider()
    page = st.radio(
        "Navigation",
        ["💬 Chat", "📊 Dashboard", "🔧 Tools", "⚙️ Configuration", "📈 Metrics"],
        label_visibility="collapsed",
    )
    st.divider()
    session_id = st.text_input("Session ID", value=st.session_state.session_id)
    st.session_state.session_id = session_id
    if st.button("Refresh Status"):
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
    ]
    cols = st.columns(3)
    for idx, action in enumerate(quick_actions):
        with cols[idx % 3]:
            if st.button(action, key=f"qa_{idx}"):
                st.session_state.messages.append({"role": "user", "content": action})

    st.divider()

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("metadata"):
                meta = msg["metadata"]
                if meta.get("cached"):
                    st.caption(":clock1: Cached response")
                if meta.get("corr_id"):
                    st.caption(f"corr_id: `{meta['corr_id']}`")
                if meta.get("latency"):
                    st.caption(f"Latency: {meta['latency']:.2f}s")

    if prompt := st.chat_input("e.g. Show Nginx error logs for the last hour..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                result = ask_agent(prompt, session_id=st.session_state.session_id)
            answer = result.get("answer", result.get("error", "No response."))
            st.markdown(answer)

            # Show additional metadata
            meta = {}
            if result.get("cached") is not None:
                meta["cached"] = result["cached"]
            if result.get("corr_id"):
                meta["corr_id"] = result["corr_id"]
            if result.get("latency_seconds"):
                meta["latency"] = result["latency_seconds"]

            col1, col2 = st.columns(2)
            with col1:
                if result.get("tool_used"):
                    st.caption(f"Tool used: `{result['tool_used']}`")
            with col2:
                if result.get("sources"):
                    with st.expander("Sources"):
                        st.json(result["sources"])

            st.session_state.messages.append({"role": "assistant", "content": answer, "metadata": meta})

    if st.session_state.messages:
        col1, col2, col3 = st.columns([1, 1, 1])
        with col1:
            if st.button("Clear Chat"):
                st.session_state.messages = []
                st.rerun()
        with col2:
            if st.button("Export Chat"):
                export = json.dumps(st.session_state.messages, indent=2)
                st.download_button("Download JSON", export, file_name="chat_history.json", mime="application/json")

# ---------------------------------------------------------------------------
# Page: Dashboard
# ---------------------------------------------------------------------------
elif page == "📊 Dashboard":
    st.header("Infrastructure Dashboard")
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
    statuses = {}
    for idx, (name, url, always_show) in enumerate(service_map):
        with cols[idx]:
            if url:
                try:
                    r = requests.get(url, timeout=4)
                    status_code = r.status_code
                    color = "green" if 200 <= status_code < 300 else "orange" if status_code < 500 else "red"
                    st.markdown(f"**{name}**")
                    st.markdown(f":{color}[{status_code}]")
                    statuses[name] = status_code
                except Exception:
                    st.markdown(f"**{name}**")
                    st.markdown(":red[unreachable]")
                    statuses[name] = "unreachable"
            elif always_show:
                st.markdown(f"**{name}**")
                st.markdown(":gray[not configured]")
            else:
                st.markdown(f"**{name}**")
                st.markdown(":gray[not configured]")

    st.divider()

    # Grafana panel if configured
    grafana_url = cfg.get("grafana_url")
    if grafana_url:
        st.subheader("Grafana Quick View")
        try:
            dashboards_r = requests.get(
                f"{grafana_url.rstrip('/')}/api/search",
                headers={"Authorization": f"Bearer {os.getenv('GRAFANA_API_KEY', '')}"} if os.getenv("GRAFANA_API_KEY") else {},
                timeout=5,
            )
            if dashboards_r.ok:
                dash_data = dashboards_r.json()
                dash_titles = [d.get("title", "Unknown") for d in dash_data[:10]]
                selected = st.selectbox("Select Dashboard", dash_titles)
                if selected:
                    selected_dash = next((d for d in dash_data if d.get("title") == selected), None)
                    if selected_dash:
                        st.info(f"Dashboard URL: {grafana_url}{selected_dash.get('url', '')}")
        except Exception as e:
            st.warning(f"Could not fetch Grafana dashboards: {e}")
    else:
        st.info("Configure `grafana_url` to enable Grafana integration.")

    st.divider()
    cache = get_cache_stats()
    if cache:
        st.subheader("Cache Performance")
        qc = cache.get("query_cache", {})
        tc = cache.get("tool_cache", {})
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Query Cache Hit Ratio", f"{qc.get('hit_ratio', 0)*100:.1f}%",
                      delta=f"{qc.get('hits', 0)} hits" if qc.get('hits') else None)
            st.caption(f"Query cache size: {qc.get('size', 0)} entries")
        with col2:
            st.metric("Tool Cache Hit Ratio", f"{tc.get('hit_ratio', 0)*100:.1f}%",
                      delta=f"{tc.get('hits', 0)} hits" if tc.get('hits') else None)
            st.caption(f"Tool cache size: {tc.get('size', 0)} entries")

# ---------------------------------------------------------------------------
# Page: Tools
# ---------------------------------------------------------------------------
elif page == "🔧 Tools":
    st.header("Available Tools")
    st.caption("Tools the AI agent can invoke automatically. Organized by category.")
    tools = get_tools()

    if not tools:
        st.warning("Could not fetch tools list from agent.")
    else:
        # Group tools by prefix
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
# Page: Configuration
# ---------------------------------------------------------------------------
elif page == "⚙️ Configuration":
    st.header("Configuration")
    st.caption("All changes take effect immediately (hot-reload enabled). Changes require API key.")
    cfg = get_config()

    if not cfg:
        st.error("Could not load configuration from agent. Is the API key set?")
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
                index=["ollama", "vertexai", "bedrock"].index(cfg.get("llm_provider", "ollama")) if cfg.get("llm_provider") in ["ollama", "vertexai", "bedrock"] else 0,
            )
            if llm_provider == "ollama":
                ollama_url = st.text_input("Ollama Base URL", value=cfg.get("ollama_base_url", "http://ollama:11434"))
                ollama_model = st.text_input("Default Model", value=cfg.get("ollama_model", "mistral"))
                temperature = st.slider("Temperature", 0.0, 2.0, float(cfg.get("ollama_temperature", 0.7)), 0.05)
                max_tokens = st.number_input("Max Tokens", 128, 8192, int(cfg.get("ollama_max_tokens", 2048)))
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
                payload = {}  # VertexAI uses secret ARNs
            else:
                bedrock_region = st.text_input("Region", value=cfg.get("bedrock_region", "us-east-1"))
                bedrock_model = st.text_input("Model ID", value=cfg.get("bedrock_model_id", ""))
                payload = {}

        with tab2:
            st.subheader("Service URLs")
            nginx_url = st.text_input("Nginx URL", value=cfg.get("nginx_url", ""))
            kibana_url = st.text_input("Kibana URL", value=cfg.get("kibana_url", ""))
            jenkins_url = st.text_input("Jenkins URL", value=cfg.get("jenkins_url", ""))
            artifactory_url = st.text_input("Artifactory URL", value=cfg.get("artifactory_url", ""))
            prometheus_url = st.text_input("Prometheus URL", value=cfg.get("prometheus_url", "http://prometheus.monitoring.svc:9090"))
            grafana_url = st.text_input("Grafana URL", value=cfg.get("grafana_url", ""))
            payload = {
                "nginx_url": nginx_url,
                "kibana_url": kibana_url,
                "jenkins_url": jenkins_url,
                "artifactory_url": artifactory_url,
                "prometheus_url": prometheus_url,
                "grafana_url": grafana_url,
            }

        with tab3:
            st.subheader("Kubernetes")
            kcol1, kcol2 = st.columns(2)
            with kcol1:
                k8s_in_cluster = st.checkbox("In-Cluster Auth", value=bool(cfg.get("k8s_in_cluster", True)))
                k8s_namespace = st.text_input("Default Namespace", value=cfg.get("k8s_namespace", "default"))
            with kcol2:
                k8s_kubeconfig = st.text_input("Kubeconfig Path", value=cfg.get("k8s_kubeconfig_path", ""))
            payload = {
                "k8s_in_cluster": k8s_in_cluster,
                "k8s_namespace": k8s_namespace,
                "k8s_kubeconfig_path": k8s_kubeconfig,
            }

        with tab4:
            st.subheader("Cache Settings")
            cache_ttl = st.slider("Cache TTL (seconds)", 30, 3600, 300, 30)
            cache_max = st.number_input("Max Cache Entries", 50, 10000, 500, 50)
            if st.button("Invalidate Cache"):
                try:
                    inv = requests.post(f"{AGENT_URL}/cache/invalidate", headers=_headers())
                    if inv.ok:
                        st.success("Cache invalidated!")
                    else:
                        st.error("Failed to invalidate cache")
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
    st.caption("Prometheus-format metrics from the DevOps AI Copilot agent.")

    metrics_text = get_metrics()
    if metrics_text:
        # Parse and display key metrics
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

        # Display key metrics in cards
        col1, col2, col3, col4 = st.columns(4)
        key_metrics = [
            ("devops_copilot_requests_total", "Total Requests", col1),
            ("devops_copilot_cache_hits_total", "Cache Hits", col2),
            ("devops_copilot_cache_misses_total", "Cache Misses", col3),
            ("devops_copilot_errors_total", "Total Errors", col4),
        ]
        for metric_name, label, col in key_metrics:
            if metric_name in metric_data:
                entries = metric_data[metric_name]
                total = sum(float(e["value"]) for e in entries)
                col.metric(label, f"{total:.0f}")

        st.divider()

        # Cache hit ratio chart
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

        # Request latency histogram
        if "devops_copilot_request_latency_seconds" in metric_data:
            st.subheader("Request Latency Distribution")
            # Extract bucket data for histogram
            buckets = [(e["labels"].get("le", "inf"), float(e["value"])) for e in metric_data["devops_copilot_request_latency_seconds"]]
            if buckets:
                fig = px.bar(
                    x=[b[0] for b in buckets],
                    y=[b[1] for b in buckets],
                    labels={"x": "Latency bucket (seconds)", "y": "Count"},
                    title="Request Latency Histogram",
                )
                st.plotly_chart(fig, use_container_width=True)

        # Tool usage breakdown
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

        with st.expander("Raw Prometheus Metrics"):
            st.code(metrics_text, language="text")
    else:
        st.warning("Could not fetch metrics from agent.")
