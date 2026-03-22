# agent/tools/kubernetes_tool.py - Kubernetes/EKS Tool
import os
import json
from langchain.tools import tool
from kubernetes import client, config
from kubernetes.client.rest import ApiException
import logging

logger = logging.getLogger(__name__)

def _get_k8s_client():
    try:
        config.load_incluster_config()
    except OSError:
        # Intentionally broad: kubeconfig load may fail due to missing file, permissions, or network issues
        kubeconfig = os.getenv("KUBECONFIG", os.path.expanduser("~/.kube/config"))
        config.load_kube_config(config_file=kubeconfig)
    return client.CoreV1Api(), client.AppsV1Api()

@tool
def list_pods(namespace: str = "default") -> str:
    """List all pods in a Kubernetes namespace with their status and restart counts.
    Args: namespace - K8s namespace (default: 'default')"""
    try:
        v1, _ = _get_k8s_client()
        pods = v1.list_namespaced_pod(namespace=namespace)
        result = []
        for pod in pods.items:
            containers = pod.status.container_statuses or []
            restarts = sum(c.restart_count for c in containers)
            result.append({
                "name": pod.metadata.name,
                "status": pod.status.phase,
                "restarts": restarts,
                "node": pod.spec.node_name,
                "age": str(pod.metadata.creation_timestamp)
            })
        return json.dumps(result, indent=2)
    except ApiException as e:
        return f"K8s API error: {e}"
    except Exception:
        # Intentionally broad: K8s client operations may raise various API or network errors
        pass

@tool
def get_pod_logs(pod_name: str, namespace: str = "default", tail_lines: int = 100) -> str:
    """Get logs from a specific Kubernetes pod.
    Args: pod_name - pod name, namespace - K8s namespace, tail_lines - number of recent log lines"""
    try:
        v1, _ = _get_k8s_client()
        logs = v1.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=tail_lines,
            timestamps=True
        )
        return logs or "No logs found"
    except ApiException as e:
        return f"K8s API error: {e}"
    except Exception:
        # Intentionally broad: K8s client operations may raise various API or network errors
        pass

@tool
def describe_pod(pod_name: str, namespace: str = "default") -> str:
    """Get detailed info about a Kubernetes pod including events and conditions.
    Args: pod_name - pod name, namespace - K8s namespace"""
    try:
        v1, _ = _get_k8s_client()
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        events = v1.list_namespaced_event(
            namespace=namespace,
            field_selector=f"involvedObject.name={pod_name}"
        )
        info = {
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "status": pod.status.phase,
            "node": pod.spec.node_name,
            "labels": pod.metadata.labels,
            "conditions": [
                {"type": c.type, "status": c.status, "reason": c.reason}
                for c in (pod.status.conditions or [])
            ],
            "containers": [
                {"name": c.name, "image": c.image,
                 "ready": cs.ready if cs else False,
                 "restarts": cs.restart_count if cs else 0}
                for c, cs in zip(
                    pod.spec.containers,
                    pod.status.container_statuses or [None]*len(pod.spec.containers)
                )
            ],
            "events": [
                {"reason": e.reason, "message": e.message, "type": e.type}
                for e in events.items
            ]
        }
        return json.dumps(info, indent=2)
    except ApiException as e:
        return f"K8s API error: {e}"
    except Exception:
        # Intentionally broad: K8s client operations may raise various API or network errors
        pass

@tool
def get_deployments(namespace: str = "default") -> str:
    """List all deployments in a namespace with replica status.
    Args: namespace - K8s namespace"""
    try:
        _, apps_v1 = _get_k8s_client()
        deployments = apps_v1.list_namespaced_deployment(namespace=namespace)
        result = []
        for d in deployments.items:
            result.append({
                "name": d.metadata.name,
                "desired": d.spec.replicas,
                "ready": d.status.ready_replicas,
                "available": d.status.available_replicas,
                "image": d.spec.template.spec.containers[0].image if d.spec.template.spec.containers else "unknown"
            })
        return json.dumps(result, indent=2)
    except Exception:
        # Intentionally broad: K8s client operations may raise various API or network errors
        pass

@tool
def get_high_restart_pods(namespace: str = "default", threshold: int = 3) -> str:
    """Find pods with restart count above threshold - useful for incident investigation.
    Args: namespace - K8s namespace, threshold - restart count threshold"""
    try:
        v1, _ = _get_k8s_client()
        pods = v1.list_namespaced_pod(namespace=namespace)
        problem_pods = []
        for pod in pods.items:
            containers = pod.status.container_statuses or []
            for cs in containers:
                if cs.restart_count >= threshold:
                    problem_pods.append({
                        "pod": pod.metadata.name,
                        "container": cs.name,
                        "restarts": cs.restart_count,
                        "ready": cs.ready,
                        "state": str(cs.state)
                    })
        return json.dumps(problem_pods, indent=2) if problem_pods else "No pods above restart threshold"
    except Exception:
        # Intentionally broad: K8s client operations may raise various API or network errors
        pass

def get_kubernetes_tools():
    return [list_pods, get_pod_logs, describe_pod, get_deployments, get_high_restart_pods]
