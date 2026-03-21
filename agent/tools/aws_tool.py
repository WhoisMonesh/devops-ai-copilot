# agent/tools/aws_tool.py
# AWS EC2, ELB, ASG, and RDS tools for DevOps AI Copilot

import logging

import boto3
import os
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def _get_ec2_client():
    """Get EC2 client with IRSA or explicit credentials."""
    kwargs = {"region_name": AWS_REGION}
    key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    if key_id and secret:
        kwargs["aws_access_key_id"] = key_id
        kwargs["aws_secret_access_key"] = secret
        session_token = os.getenv("AWS_SESSION_TOKEN", "")
        if session_token:
            kwargs["aws_session_token"] = session_token
    return boto3.client("ec2", **kwargs)


def _get_elb_client():
    """Get ELB client."""
    kwargs = {"region_name": AWS_REGION}
    key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    if key_id and secret:
        kwargs["aws_access_key_id"] = key_id
        kwargs["aws_secret_access_key"] = secret
    return boto3.client("elbv2", **kwargs)


def _get_autoscaling_client():
    """Get ASG client."""
    kwargs = {"region_name": AWS_REGION}
    key_id = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    if key_id and secret:
        kwargs["aws_access_key_id"] = key_id
        kwargs["aws_secret_access_key"] = secret
    return boto3.client("autoscaling", **kwargs)


@tool
def ec2_list_instances(
    state: str = "running",
    tag_filter: str = "",
    max_results: int = 50
) -> str:
    """List EC2 instances filtered by state and optional tag filter.
    Args:
      state - Instance state: running, stopped, terminated (default: running)
      tag_filter - Optional tag filter like 'Name=myapp,Environment=prod'
      max_results - Maximum number of instances to return (default: 50)"""
    try:
        client = _get_ec2_client()
        filters = [{"Name": "instance-state-name", "Values": [state]}]

        if tag_filter:
            for tag in tag_filter.split(","):
                key, val = tag.split("=")
                filters.append({"Name": f"tag:{key.strip()}", "Values": [val.strip()]})

        response = client.describe_instances(Filters=filters, MaxResults=max_results)
        instances = []
        for reservation in response.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                name = next((t["Value"] for t in instance.get("Tags", []) if t["Key"] == "Name"), "unnamed")
                instances.append({
                    "id": instance["InstanceId"],
                    "type": instance["InstanceType"],
                    "state": instance["State"]["Name"],
                    "az": instance["Placement"]["AvailabilityZone"],
                    "name": name,
                    "private_ip": instance.get("PrivateIpAddress", "N/A"),
                    "public_ip": instance.get("PublicIpAddress", "N/A"),
                })

        if not instances:
            return f"No {state} EC2 instances found."

        lines = [f"EC2 Instances ({state}) - {len(instances)} found:"]
        for i in instances:
            lines.append(f"  [{i['id']}] {i['name']} | {i['type']} | {i['az']} | {i['state']} | Private: {i['private_ip']} | Public: {i['public_ip']}")
        return "\n".join(lines)
    except Exception as e:
        logger.exception("ec2_list_instances failed")
        return f"Error listing EC2 instances: {e}"


@tool
def ec2_get_instance_status(instance_id: str) -> str:
    """Get detailed status of a specific EC2 instance.
    Args:
      instance_id - EC2 instance ID (e.g., i-0abc123def456)"""
    try:
        client = _get_ec2_client()
        response = client.describe_instances(InstanceIds=[instance_id])
        instances = response.get("Reservations", [{}])[0].get("Instances", [])
        if not instances:
            return f"Instance {instance_id} not found."

        i = instances[0]
        name = next((t["Value"] for t in i.get("Tags", []) if t["Key"] == "Name"), "unnamed")
        lines = [
            f"EC2 Instance: {instance_id}",
            f"Name: {name}",
            f"Type: {i['InstanceType']}",
            f"State: {i['State']['Name']}",
            f"AZ: {i['Placement']['AvailabilityZone']}",
            f"Private IP: {i.get('PrivateIpAddress', 'N/A')}",
            f"Public IP: {i.get('PublicIpAddress', 'N/A')}",
            f"VPC: {i.get('VpcId', 'N/A')}",
            f"Subnet: {i.get('SubnetId', 'N/A')}",
            f"AMI: {i.get('ImageId', 'N/A')}",
            f"Launched: {i.get('LaunchTime', 'N/A')}",
            f"Platform: {i.get('Platform', 'linux')}",
        ]
        return "\n".join(lines)
    except Exception as e:
        logger.exception("ec2_get_instance_status failed")
        return f"Error getting instance status: {e}"


@tool
def ec2_get_asg_status() -> str:
    """Get status of all Auto Scaling Groups including desired/min/max capacity and instance health."""
    try:
        client = _get_autoscaling_client()
        response = client.describe_auto_scaling_groups()
        groups = response.get("AutoScalingGroups", [])

        if not groups:
            return "No Auto Scaling Groups found."

        lines = [f"Auto Scaling Groups - {len(groups)} found:"]
        for g in groups:
            instances = g.get("Instances", [])
            healthy = sum(1 for i in instances if i["HealthStatus"] == "Healthy")
            lines.append(f"\n[{g['AutoScalingGroupName']}]")
            lines.append(f"  Desired: {g['DesiredCapacity']} | Min: {g['MinSize']} | Max: {g['MaxSize']}")
            lines.append(f"  Healthy: {healthy}/{len(instances)} instances")
            lines.append(f"  VPC Zone: {', '.join(g['AvailabilityZones'])}")
            lines.append(f"  Launch Config: {g.get('LaunchConfigurationName', g.get('LaunchTemplate', {}).get('LaunchTemplateName', 'N/A'))}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("ec2_get_asg_status failed")
        return f"Error getting ASG status: {e}"


@tool
def elb_list_load_balancers(tag_filter: str = "") -> str:
    """List all ELBv2 (Application/Network) load balancers.
    Args:
      tag_filter - Optional tag filter like 'Environment=prod'"""
    try:
        client = _get_elb_client()
        response = client.describe_load_balancers()
        lbs = response.get("LoadBalancers", [])

        if tag_filter:
            filtered = []
            for lb in lbs:
                tags = client.describe_tags(ResourceArns=[lb["LoadBalancerArn"]])["TagDescriptions"]
                for tag_desc in tags:
                    for tag in tag_desc.get("Tags", []):
                        if tag_filter in f"{tag['Key']}={tag['Value']}":
                            filtered.append(lb)
                            break
            lbs = filtered

        if not lbs:
            return "No load balancers found."

        lines = [f"Load Balancers - {len(lbs)} found:"]
        for lb in lbs:
            lines.append(f"  [{lb['LoadBalancerName']}] {lb['DNSName']}")
            lines.append(f"    Type: {lb['Type']} | Scheme: {lb['Scheme']} | State: {lb['State']['Code']}")
            lines.append(f"    AZs: {', '.join([az['ZoneName'] for az in lb['AvailabilityZones']])}")
            lines.append(f"    Targets: {len(lb.get('TargetGroups', []))} groups")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("elb_list_load_balancers failed")
        return f"Error listing load balancers: {e}"


@tool
def elb_get_target_health(target_group_arn: str = "") -> str:
    """Get target group health and status for an ELB.
    Args:
      target_group_arn - Target Group ARN (or name to look up)"""
    try:
        client = _get_elb_client()

        # If name provided, find the ARN
        if target_group_arn and not target_group_arn.startswith("arn:"):
            tg_response = client.describe_target_groups(Names=[target_group_arn])
            tgs = tg_response.get("TargetGroups", [])
            if tgs:
                target_group_arn = tgs[0]["TargetGroupArn"]

        if not target_group_arn:
            return "Please provide a target group name or ARN."

        response = client.describe_target_health(TargetGroupArn=target_group_arn)
        health = response.get("TargetHealthDescriptions", [])

        if not health:
            return "No targets found in target group."

        lines = [f"Target Health - {len(health)} targets:"]
        for t in health:
            state = t["TargetHealth"]["State"]
            lines.append(f"  [{t['Target']['Id']}:{t['Target']['Port']}] State: {state}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("elb_get_target_health failed")
        return f"Error getting target health: {e}"


AWS_TOOLS = [
    ec2_list_instances,
    ec2_get_instance_status,
    ec2_get_asg_status,
    elb_list_load_balancers,
    elb_get_target_health,
]
