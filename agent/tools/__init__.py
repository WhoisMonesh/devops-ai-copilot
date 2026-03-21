# agent/tools/__init__.py
"""Tool registry – import all tools so orchestrator can discover them."""

from .nginx_tool import get_nginx_tools
from .kibana_tool import kibana_tools
from .jenkins_tool import jenkins_tools
from .artifactory_tool import artifactory_tools
from .kubernetes_tool import k8s_tools
from .prometheus_tools import PROMETHEUS_TOOLS
from .grafana_tool import GRAFANA_TOOLS
from .jenkins_tools import JENKINS_TOOLS as jenkins_tools_v2

# Combine all tools
ALL_TOOLS = (
    get_nginx_tools() +
    kibana_tools +
    jenkins_tools +
    artifactory_tools +
    k8s_tools +
    PROMETHEUS_TOOLS +
    GRAFANA_TOOLS +
    JENKINS_TOOLS
)

__all__ = [
    "ALL_TOOLS",
    "get_nginx_tools",
    "kibana_tools",
    "jenkins_tools",
    "artifactory_tools",
    "k8s_tools",
    "PROMETHEUS_TOOLS",
    "GRAFANA_TOOLS",
]
