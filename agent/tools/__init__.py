# agent/tools/__init__.py
"""Tool registry – import all tools so orchestrator can discover them."""

from .nginx_tool import NginxTool
from .kibana_tool import KibanaTool
from .jenkins_tool import JenkinsTool
from .artifactory_tool import ArtifactoryTool
from .kubernetes_tool import KubernetesTool
from .prometheus_tools import PROMETHEUS_TOOLS
from .grafana_tool import GRAFANA_TOOLS

ALL_TOOLS = [
    NginxTool,
    KibanaTool,
    JenkinsTool,
    ArtifactoryTool,
    KubernetesTool,
] + PROMETHEUS_TOOLS + GRAFANA_TOOLS

__all__ = ["ALL_TOOLS", "NginxTool", "KibanaTool", "JenkinsTool", "ArtifactoryTool", "KubernetesTool", "PROMETHEUS_TOOLS", "GRAFANA_TOOLS"]
