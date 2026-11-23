#!/usr/bin/env python3
"""Spin up or tear down a tiny EC2 t3.micro running mock_upstream.py in eu-north-1."""

import argparse
import base64
import json
import os
import sys
import time
import urllib.request

import boto3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGION = "eu-north-1"
STATE_PATH = os.path.join(ROOT, "results", "aws", "ec2-upstream.json")
SG_NAME = "mcpbench-mock-upstream-8080"


def load_env(path: str = os.path.expanduser("~/.aws-mcpbench.env")):
    if os.environ.get("AWS_ACCESS_KEY_ID") or not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def latest_al2023_ami(ec2) -> str:
    resp = ec2.describe_images(
        Owners=["amazon"],
        Filters=[
            {"Name": "name", "Values": ["al2023-ami-2023.*-x86_64"]},
            {"Name": "state", "Values": ["available"]},
        ],
    )
    imgs = sorted(resp["Images"], key=lambda x: x["CreationDate"], reverse=True)
    if not imgs:
        raise RuntimeError("No AL2023 x86_64 AMI found in " + REGION)
    return imgs[0]["ImageId"]


def ensure_sg(ec2) -> str:
    try:
        sgs = ec2.describe_security_groups(GroupNames=[SG_NAME])["SecurityGroups"]
        sg_id = sgs[0]["GroupId"]
    except Exception:
        vpcs = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"]
        vpc_id = vpcs[0]["VpcId"]
        sg_id = ec2.create_security_group(
            GroupName=SG_NAME,
            Description="Temporary mock_upstream HTTP 8080 for MCP_Serverless",
            VpcId=vpc_id,
        )["GroupId"]
        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[{
                "IpProtocol": "tcp",
                "FromPort": 8080,
                "ToPort": 8080,
                "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "mock upstream"}],
            }],
        )
    return sg_id


def cmd_start():
    ec2 = boto3.client("ec2", region_name=REGION)
    src = open(os.path.join(ROOT, "mcp_bench", "mock_upstream.py"), "rb").read()
    src_b64 = base64.b64encode(src).decode()
    user_data = f"""#!/bin/bash
set -e
cat <<'EOF' | base64 -d > /opt/mock_upstream.py
{src_b64}
EOF
nohup /usr/bin/python3 /opt/mock_upstream.py --host 0.0.0.0 --port 8080 > /var/log/mock_upstream.log 2>&1 &
"""
    ami = latest_al2023_ami(ec2)
    sg_id = ensure_sg(ec2)
    resp = ec2.run_instances(
        ImageId=ami,
        InstanceType="t3.micro",
        MinCount=1,
        MaxCount=1,
        SecurityGroupIds=[sg_id],
        UserData=user_data,
        TagSpecifications=[{
            "ResourceType": "instance",
            "Tags": [{"Key": "Name", "Value": "mcpbench-mock-upstream"}],
        }],
    )
    iid = resp["Instances"][0]["InstanceId"]
    print(f"Launched {iid} (AMI {ami}), waiting for running...", flush=True)
    ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
    desc = ec2.describe_instances(InstanceIds=[iid])["Reservations"][0]["Instances"][0]
    ip = desc["PublicIpAddress"]
    url = f"http://{ip}:8080"
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    json.dump({"instance_id": iid, "sg_id": sg_id, "ip": ip, "url": url}, open(STATE_PATH, "w"), indent=2)

    print(f"Waiting for {url}/health ...", flush=True)
    for _ in range(90):
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=3) as r:
                if r.status == 200:
                    print(f"READY: {url}", flush=True)
                    # Pre-warm 1 MB dataset cache for 630.data-analysis
                    urllib.request.urlopen(f"{url}/api?latency_ms=0&size=1048576&seed=1", timeout=30).read()
                    urllib.request.urlopen(f"{url}/api?latency_ms=0&size=65536&seed=1", timeout=30).read()
                    urllib.request.urlopen(f"{url}/api?latency_ms=0&size=16384&seed=1", timeout=30).read()
                    urllib.request.urlopen(f"{url}/page?latency_ms=0&size=200000&seed=1", timeout=30).read()
                    print("Pre-warmed mock_upstream caches.", flush=True)
                    return
        except Exception:
            time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {url}/health")


def cmd_stop():
    if not os.path.exists(STATE_PATH):
        print("No state file found.")
        return
    state = json.load(open(STATE_PATH))
    ec2 = boto3.client("ec2", region_name=REGION)
    iid = state["instance_id"]
    print(f"Terminating {iid}...", flush=True)
    ec2.terminate_instances(InstanceIds=[iid])
    ec2.get_waiter("instance_terminated").wait(InstanceIds=[iid])
    try:
        ec2.delete_security_group(GroupId=state["sg_id"])
        print(f"Deleted security group {state['sg_id']}.", flush=True)
    except Exception as exc:
        print(f"Note: could not delete SG {state['sg_id']}: {exc}")
    os.remove(STATE_PATH)
    print("Cleaned up.", flush=True)


def main():
    load_env()
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=("start", "stop"))
    args = p.parse_args()
    if args.action == "start":
        cmd_start()
    else:
        cmd_stop()


if __name__ == "__main__":
    main()
