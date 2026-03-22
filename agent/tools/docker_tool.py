# agent/tools/docker_tool.py
# Docker and container tools for DevOps AI Copilot

import logging
import subprocess

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _run_docker_command(args: list) -> tuple[str, str, int]:
    """Run docker command and return stdout, stderr, returncode."""
    try:
        result = subprocess.run(
            ["docker"] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout, result.stderr, result.returncode
    except Exception:
        # Intentionally broad: FileNotFoundError (docker not installed), OSError, subprocess errors
        return "", "docker command failed", 1


@tool
def docker_list_containers(all_containers: bool = False) -> str:
    """List all Docker containers.
    Args:
      all_containers - Show stopped containers too (default: False = running only)"""
    try:
        args = ["ps", "--format", "table {{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"]
        if all_containers:
            args.append("-a")

        stdout, stderr, code = _run_docker_command(args)
        if code != 0:
            return f"Docker error: {stderr or 'command failed'}"

        lines = stdout.strip().split("\n")
        if len(lines) <= 1:
            return "No containers found."

        header = lines[0]
        result_lines = ["Docker Containers:", header]
        result_lines.extend(lines[1:])

        return "\n".join(result_lines)
    except Exception:
        # Intentionally broad: subprocess errors
        return "Error listing containers"


@tool
def docker_container_logs(container_name: str, lines: int = 50, follow: bool = False) -> str:
    """Get container logs.
    Args:
      container_name - Container name or ID
      lines - Number of log lines to fetch (default: 50)
      follow - Follow log output (default: False)"""
    try:
        args = ["logs"]
        if follow:
            args.append("-f")
        else:
            args.append(f"--tail={lines}")
        args.append(container_name)

        stdout, stderr, code = _run_docker_command(args)
        if code != 0:
            return f"Docker error: {stderr or 'command failed'}"

        output = (stdout + stderr).strip()
        if not output:
            return f"No logs available for {container_name}"

        return f"Logs for {container_name} (last {lines} lines):\n{output}"[:5000]
    except Exception:
        # Intentionally broad: subprocess errors
        return "Error getting container logs"


@tool
def docker_container_stats(container_name: str = "", stats_all: bool = False) -> str:
    """Get container resource usage stats.
    Args:
      container_name - Specific container name/ID (default: empty for all)
      stats_all - Get stats for all containers (default: False)"""
    try:
        args = ["stats", "--no-stream", "--format", "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}"]
        if container_name:
            args.append(container_name)

        stdout, stderr, code = _run_docker_command(args)
        if code != 0:
            return f"Docker error: {stderr or 'command failed'}"

        lines = stdout.strip().split("\n")
        if len(lines) <= 1:
            return "No container stats available."

        return "Docker Container Stats:\n" + "\n".join(lines)
    except Exception:
        # Intentionally broad: subprocess errors
        return "Error getting container stats"


@tool
def docker_image_list() -> str:
    """List all Docker images."""
    try:
        stdout, stderr, code = _run_docker_command(["images", "--format", "table {{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}"])
        if code != 0:
            return f"Docker error: {stderr or 'command failed'}"

        lines = stdout.strip().split("\n")
        if len(lines) <= 1:
            return "No Docker images found."

        return "Docker Images:\n" + "\n".join(lines)
    except Exception:
        # Intentionally broad: subprocess errors
        return "Error listing images"


@tool
def docker_swarm_services() -> str:
    """List all Docker Swarm services and their status."""
    try:
        stdout, stderr, code = _run_docker_command(["service", "ls", "--format", "table {{.Name}}\t{{.Mode}}\t{{.Replicas}}\t{{.Image}}\t{{.Status}}"])
        if code != 0:
            return "Docker Swarm not active or not a swarm manager."

        lines = stdout.strip().split("\n")
        if len(lines) <= 1:
            return "No Swarm services found."

        return "Docker Swarm Services:\n" + "\n".join(lines)
    except Exception:
        # Intentionally broad: subprocess errors
        return "Error listing Swarm services"


@tool
def docker_swarm_nodes() -> str:
    """List all Docker Swarm nodes and their status."""
    try:
        stdout, stderr, code = _run_docker_command(["node", "ls", "--format", "table {{.ID}}\t{{.Hostname}}\t{{.Status}}\t{{.Availability}}\t{{.Manager Status}}"])
        if code != 0:
            return "Docker Swarm not active."

        lines = stdout.strip().split("\n")
        if len(lines) <= 1:
            return "No Swarm nodes found."

        return "Docker Swarm Nodes:\n" + "\n".join(lines)
    except Exception:
        # Intentionally broad: subprocess errors
        return "Error listing Swarm nodes"


@tool
def docker_system_info() -> str:
    """Get Docker system-wide information and resource usage."""
    try:
        stdout, stderr, code = _run_docker_command(["system", "df", "--format", "table {{.Type}}\t{{.Total}}\t{{.Active}}\t{{.Size}}\t{{.Reclaimable}}"])
        if code != 0:
            return f"Docker error: {stderr or 'command failed'}"

        info_lines = ["Docker System Usage:"]
        info_lines.extend(stdout.strip().split("\n"))

        # Add version info
        v_stdout, _, _ = _run_docker_command(["version", "--format", "{{.Server.Version}}"])
        info_lines.append(f"\nDocker Server Version: {v_stdout.strip()}")

        return "\n".join(info_lines)
    except Exception:
        # Intentionally broad: subprocess errors
        return "Error getting Docker system info"


DOCKER_TOOLS = [
    docker_list_containers,
    docker_container_logs,
    docker_container_stats,
    docker_image_list,
    docker_swarm_services,
    docker_swarm_nodes,
    docker_system_info,
]
