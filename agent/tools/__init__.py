# agent/tools/__init__.py
"""Tool registry – import all tools so orchestrator can discover them."""

from .nginx_tool import get_nginx_tools
from .kibana_tool import kibana_tools
from .jenkins_tool import jenkins_tools
from .artifactory_tool import artifactory_tools
from .kubernetes_tool import k8s_tools
from .prometheus_tools import PROMETHEUS_TOOLS
from .grafana_tool import GRAFANA_TOOLS
from .aws_tool import AWS_TOOLS
from .cloudwatch_tool import CLOUDWATCH_TOOLS
from .database_tool import DATABASE_TOOLS
from .docker_tool import DOCKER_TOOLS
from .github_tool import GITHUB_TOOLS
from .pagerduty_tool import PAGERDUTY_TOOLS
from .ssl_tool import SSL_TOOLS
from .terraform_tool import TERRAFORM_TOOLS
from .llm_tools import LLM_TOOLS
from .knowledge_base_tool import KB_TOOLS

# Combine all tools
ALL_TOOLS = (
    get_nginx_tools() +
    kibana_tools +
    jenkins_tools +
    artifactory_tools +
    k8s_tools +
    PROMETHEUS_TOOLS +
    GRAFANA_TOOLS +
    AWS_TOOLS +
    CLOUDWATCH_TOOLS +
    DATABASE_TOOLS +
    DOCKER_TOOLS +
    GITHUB_TOOLS +
    PAGERDUTY_TOOLS +
    SSL_TOOLS +
    TERRAFORM_TOOLS +
    LLM_TOOLS +
    KB_TOOLS
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
    "AWS_TOOLS",
    "CLOUDWATCH_TOOLS",
    "DATABASE_TOOLS",
    "DOCKER_TOOLS",
    "GITHUB_TOOLS",
    "PAGERDUTY_TOOLS",
    "SSL_TOOLS",
    "TERRAFORM_TOOLS",
    "LLM_TOOLS",
    "KB_TOOLS",
]
