#!/usr/bin/env python3
"""Protocol-2 rollout gates. No inference, StopTask, token reads, or lease stealing."""
import argparse
import ipaddress
import json
import os
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path


class GateError(Exception):
    pass


class TaskHttpError(GateError):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(f"Task returned HTTP {status}: {code}")


def require(condition, message):
    if not condition:
        raise GateError(message)


class Controller:
    def __init__(self, manifest, aws, http):
        self.m = manifest
        self.aws = aws
        self.http = http
        require(manifest["source"]["tasks"] and manifest["target"]["tasks"], "Both task sets are required")
        require(not set(manifest["source"]["tasks"]) & set(manifest["target"]["tasks"]), "Task sets overlap")
        require(manifest["source"]["target_group"] != manifest["target"]["target_group"], "Target groups overlap")

    def deployment(self):
        result = self.aws("ecs", "describe-service-deployments", serviceDeploymentArns=[self.m["deployment"]])
        values = result.get("serviceDeployments", [])
        require(not result.get("failures") and len(values) == 1, "Deployment not established")
        deployment = values[0]
        require(deployment["serviceDeploymentArn"] == self.m["deployment"]
                and deployment["clusterArn"] == self.m["cluster"]
                and deployment["serviceArn"] == self.m["service"], "Deployment identity mismatch")
        require(deployment["deploymentConfiguration"]["strategy"] == "BLUE_GREEN", "Blue/green required")
        return deployment

    def hook(self, stage):
        deployment = self.deployment()
        require(deployment["lifecycleStage"] == stage and deployment["status"] == "IN_PROGRESS", "Deployment is not at the expected pause")
        hooks = [h for h in deployment.get("lifecycleHookDetails", [])
                 if h["targetType"] == "PAUSE" and h["status"] == "AWAITING_ACTION"]
        require(len(hooks) == 1 and hooks[0]["timeoutAction"] == "ROLLBACK", "Expected one rollback-on-timeout pause")
        return hooks[0]["hookId"]

    def tasks(self, side, cleanup=False):
        expected = self.m[side]
        values = []
        # DescribeTasks' documented API maximum, not a serving concurrency limit.
        for start in range(0, len(expected["tasks"]), 100):
            result = self.aws("ecs", "describe-tasks", cluster=self.m["cluster"], tasks=expected["tasks"][start:start + 100])
            require(not result.get("failures"), "Task observation incomplete")
            values += result["tasks"]
        require({t["taskArn"] for t in values} == set(expected["tasks"]), "Task set changed")
        result = []
        for task in values:
            require(task["clusterArn"] == self.m["cluster"] and task["group"] == f"service:{self.m['service'].split('/')[-1]}"
                    and task["taskDefinitionArn"] == expected["task_definition"], "Task identity or release mismatch")
            if cleanup:
                if task["lastStatus"] == "STOPPED":
                    continue
                # A previous retire may have closed HTTP before its reply was
                # received. The runtime alone clears protection after closure.
                protection = self.aws("ecs", "get-task-protection", cluster=self.m["cluster"], tasks=[task["taskArn"]]).get("protectedTasks", [])
                short = task["taskArn"].replace(":task/" + self.m["cluster"].split("/")[-1] + "/", ":task/")
                if any(p["taskArn"] in (task["taskArn"], short) and p.get("protectionEnabled") is False for p in protection):
                    continue
            require(task["lastStatus"] == "RUNNING" and task["desiredStatus"] == "RUNNING", "Task is not RUNNING")
            ips = [d["value"] for a in task.get("attachments", []) for d in a.get("details", []) if d["name"] == "privateIPv4Address"]
            require(len(ips) == 1 and ipaddress.ip_address(ips[0]).version == 4, "Task address unavailable")
            origin = f"http://{ips[0]}:8787"
            state = self.http(origin, "/v1/admin/deployment")
            require(state.get("protocol") == 2, "Legacy migration is not qualified; refuse retirement/cutover")
            require(state.get("taskArn") == task["taskArn"] and state.get("generation"), "Runtime identity mismatch")
            require(state.get("protectedUntil", 0) > time.time() * 1000 and not state.get("retiring"), "Task not protected")
            self.http(origin, "/readyz")
            result.append({"origin": origin, "ip": ips[0], "state": state,
                           "image": next((c.get("imageDigest") for c in task.get("containers", []) if c["name"] == "gateway"), None),
                           "identity": {k: state[k] for k in ("taskArn", "generation")}})
        if not cleanup:
            health = self.aws("elbv2", "describe-target-health", TargetGroupArn=expected["target_group"])["TargetHealthDescriptions"]
            registered = {h["Target"]["Id"]: h for h in health}
            require(set(registered) == {t["ip"] for t in result}, "Registered targets do not match the pinned task set")
            require(all(h["TargetHealth"]["State"] == "healthy" and h["Target"]["Port"] == 8787 for h in health), "Targets not healthy")
        return result

    def writer(self):
        value = self.aws("dynamodb", "get-item", TableName=self.m["owner_table"], Key={"id": {"S": "provider-owner"}}, ConsistentRead=True).get("Item", {})
        require(value.get("protocol", {}).get("N") == "2" and value.get("phase", {}).get("S") == "active", "Protocol-2 writer required")
        return {k: value[k]["S"] for k in ("taskArn", "generation")}

    def routed(self, side):
        rules = self.aws("elbv2", "describe-rules", RuleArns=[self.m["listener_rule"]])["Rules"]
        require(len(rules) == 1, "Listener rule missing")
        actions = rules[0]["Actions"]
        require(len(actions) == 1 and actions[0]["Type"] == "forward", "Unexpected routing action")
        forward = actions[0].get("ForwardConfig", {})
        require(not forward.get("TargetGroupStickinessConfig", {}).get("Enabled"), "Sticky routing not supported")
        groups = forward.get("TargetGroups", [])
        weights = {g["TargetGroupArn"]: g["Weight"] for g in groups}
        expected = {self.m["source"]["target_group"], self.m["target"]["target_group"]}
        require(set(weights) == expected and weights[self.m[side]["target_group"]] > 0
                and all(weight == 0 for arn, weight in weights.items() if arn != self.m[side]["target_group"]), "Traffic shift is not confirmed")

    def rollback_route(self):
        # Shift weights while ECS is still paused. Asking ECS to roll back
        # before draining could deregister candidate targets under live streams.
        rules = self.aws("elbv2", "describe-rules", RuleArns=[self.m["listener_rule"]])["Rules"]
        require(len(rules) == 1 and len(rules[0]["Actions"]) == 1, "Unexpected rollback rule")
        action = rules[0]["Actions"][0]
        groups = action.get("ForwardConfig", {}).get("TargetGroups", [])
        require(action["Type"] == "forward"
                and {g["TargetGroupArn"] for g in groups} == {self.m["source"]["target_group"], self.m["target"]["target_group"]},
                "Unexpected rollback targets")
        self.aws("elbv2", "modify-rule", RuleArn=self.m["listener_rule"], Actions=[{
            "Type": "forward", "ForwardConfig": {"TargetGroups": [
                {"TargetGroupArn": g["TargetGroupArn"], "Weight": 100 if g["TargetGroupArn"] == self.m["source"]["target_group"] else 0}
                for g in groups], "TargetGroupStickinessConfig": {"Enabled": False}}
        }])
        self.routed("source")

    def await_retired(self, tasks):
        # The app acknowledges retire before its final close/unprotect work.
        # Confirm completion before ECS may deregister targets; never a timer.
        for task in tasks:
            arn = task["identity"]["taskArn"]
            while True:
                observed = self.aws("ecs", "describe-tasks", cluster=self.m["cluster"], tasks=[arn])["tasks"]
                require(len(observed) == 1 and observed[0]["taskArn"] == arn, "Retirement task disappeared")
                if observed[0]["lastStatus"] == "STOPPED":
                    break
                protection = self.aws("ecs", "get-task-protection", cluster=self.m["cluster"], tasks=[arn]).get("protectedTasks", [])
                short = arn.replace(":task/" + self.m["cluster"].split("/")[-1] + "/", ":task/")
                if any(t["taskArn"] in (arn, short) and t.get("protectionEnabled") is False for t in protection):
                    break
                time.sleep(1)

    def transfer(self, old, new):
        writer = self.writer()
        chosen = next((t for t in new if t["identity"] == writer), None)
        if chosen:
            return chosen
        current = next((t for t in old if t["identity"] == writer), None)
        require(current is not None, "Writer is outside the pinned task sets")
        chosen = next((t for t in new if t["state"].get("writeEligible", True)), None)
        require(chosen is not None, "No eligible successor writer")
        try:
            self.http(current["origin"], "/v1/admin/deployment/handoff", chosen["identity"])
        except TaskHttpError as error:
            # The first protocol-2 runtime seals admission and awaits every
            # write, then returns this error when a durable journal is pending.
            # An explicit, reviewed source-image pin enables that older barrier.
            # Do not clear journals: they fence the same secret on the successor.
            migration = self.m["source"].get("sealed_rotation_handoff", {})
            require(error.status == 409 and error.code == "credential_rotation_unresolved"
                    and current["identity"]["taskArn"] in self.m["source"]["tasks"]
                    and migration.get("image_digest") == current.get("image")
                    and current.get("image") and migration.get("journals"),
                    "Handoff failed; no reviewed sealed-writer migration")
            state = self.http(current["origin"], "/v1/admin/deployment")
            require(all(state.get(k) == v for k, v in current["identity"].items())
                    and state.get("pendingWrites") == 0 and state.get("writeEligible") is False
                    and state.get("unresolvedRotation") is True, "Old writer seal not established")
            for journal in migration["journals"]:
                require(journal["id"].startswith("credential-rotation:"), "Invalid quarantine journal")
                item = self.aws("dynamodb", "get-item", TableName=self.m["owner_table"],
                                Key={"id": {"S": journal["id"]}}, ConsistentRead=True).get("Item", {})
                require(item.get("pending", {}).get("BOOL") is True
                        and item.get("attempt", {}).get("S") == journal["attempt"], "Quarantine journal changed")
            require(self.writer() == current["identity"], "Sealed writer changed")
            identity = chosen["identity"]
            try:
                self.aws("dynamodb", "put-item", TableName=self.m["owner_table"], Item={
                    "id": {"S": "provider-owner"}, **{k: {"S": v} for k, v in identity.items()},
                    "protocol": {"N": "2"}, "phase": {"S": "active"}, "heartbeatAt": {"N": str(int(time.time() * 1000))}
                }, ConditionExpression="taskArn = :task AND generation = :generation AND protocol = :protocol",
                    ExpressionAttributeValues={":task": {"S": current["identity"]["taskArn"]},
                                               ":generation": {"S": current["identity"]["generation"]}, ":protocol": {"N": "2"}})
            except Exception:
                if self.writer() != identity:
                    raise
        require(self.writer() == chosen["identity"], "Handoff not confirmed")
        return chosen

    def drain(self, tasks, successor):
        for task in tasks:
            self.http(task["origin"], "/v1/admin/deployment/drain", successor["identity"])
        # /drain seals local admission before these observations. Counter zero
        # without that fence is not retirement evidence.
        return all(self.http(task["origin"], "/v1/admin/deployment").get("drained") is True for task in tasks)

    def step(self, action):
        if action == "cutover":
            hook = self.hook("POST_SCALE_UP")
            self.routed("source")
            source, target = self.tasks("source"), self.tasks("target")
            require(all(t["state"]["accepting"] for t in target), "Candidate not accepting")
            self.transfer(source, target)
            # An uncertain Continue response is resolved on the next invocation
            # from ECS state, never by restarting inference.
            self.aws("ecs", "continue-service-deployment", hookId=hook, action="CONTINUE")
            return "Cutover authorized; wait for POST_PRODUCTION_TRAFFIC_SHIFT."
        if action == "drain":
            self.hook("POST_PRODUCTION_TRAFFIC_SHIFT")
            self.routed("target")
            source, target = self.tasks("source"), self.tasks("target")
            chosen = self.transfer(source, target)
            return "Drained; finish may proceed." if self.drain(source, chosen) else "Draining; both task sets retained. Run drain again."
        if action == "finish":
            hook = self.hook("POST_PRODUCTION_TRAFFIC_SHIFT")
            self.routed("target")
            source, target = self.tasks("source", cleanup=True), self.tasks("target")
            require(self.writer() in [t["identity"] for t in target], "Writer not on candidate")
            require(all(t["state"].get("drained") is True for t in source), "Old tasks have not drained")
            # Close HTTP admission and verify app-owned unprotection BEFORE ECS
            # may deregister targets. A sampled zero count is not that proof.
            for task in source:
                self.http(task["origin"], "/v1/admin/deployment/retire", {})
            self.await_retired(source)
            require(self.hook("POST_PRODUCTION_TRAFFIC_SHIFT") == hook, "Deployment pause changed during retirement")
            self.aws("ecs", "continue-service-deployment", hookId=hook, action="CONTINUE")
            return "Source retirement confirmed; verify ECS completion and traffic externally."
        if action == "rollback":
            deployment = self.deployment()
            require(deployment["lifecycleStage"] in ("POST_SCALE_UP", "POST_PRODUCTION_TRAFFIC_SHIFT"), "Rollback needs a retained pause")
            hook = self.hook(deployment["lifecycleStage"])
            source, target = self.tasks("source"), self.tasks("target", cleanup=True)
            for task in source:
                if not task["state"].get("accepting"):
                    task["state"] = self.http(task["origin"], "/v1/admin/deployment/activate", {})
            chosen = self.transfer(target, source)
            self.rollback_route()
            if not self.drain(target, chosen):
                return "Rollback draining; candidates forward to source. Run rollback again."
            for task in target:
                self.http(task["origin"], "/v1/admin/deployment/retire", {})
            self.await_retired(target)
            self.aws("ecs", "continue-service-deployment", hookId=hook, action="ROLLBACK")
            return "Candidate retirement confirmed; rollback requested."
        if action in ("cleanup-source", "cleanup-target"):
            retired = action.split("-")[1]
            serving = "target" if retired == "source" else "source"
            self.deployment()
            self.routed(serving)
            current = self.tasks(serving)
            require(all(t["state"]["accepting"] for t in current), "Serving tasks must not forward back to retiring tasks")
            require(self.writer() in [t["identity"] for t in current], "Writer is not on the serving side")
            previous = self.tasks(retired, cleanup=True)
            require(all(t["state"].get("drained") is True for t in previous), "Retiring tasks are not drained")
            for task in previous:
                self.http(task["origin"], "/v1/admin/deployment/retire", {})
            self.await_retired(previous)
            return "Remaining task retirement confirmed; verify ECS deployment completion."
        raise GateError("Unknown action")


def aws_cli(service, operation, **payload):
    command = ["aws", service, operation, "--cli-input-json", json.dumps(payload), "--output", "json", "--no-cli-pager"]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    value = json.loads(result.stdout or "{}")
    require(not value.get("failures"), f"{operation}: incomplete AWS result")
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise GateError("Unexpected task redirect")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["cutover", "drain", "finish", "rollback", "cleanup-source", "cleanup-target"])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--operation-id", required=True, help="Caller-stable UUID; resume only after the previous process has exited.")
    args = parser.parse_args()
    operation = str(uuid.UUID(args.operation_id))
    manifest = json.loads(args.manifest.read_text())
    token_file = Path(os.environ["GATEWAY_ADMIN_TOKEN_FILE"])
    require(token_file.stat().st_mode & 0o077 == 0, "Admin token file must be owner-only")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def http(origin, path, body=None):
        token = token_file.read_text().strip()
        request = urllib.request.Request(origin + path, None if body is None else json.dumps(body).encode(),
                                         {"Authorization": token if token.startswith("Bearer ") else "Bearer " + token,
                                          "Content-Type": "application/json"})
        # No inference/stream deadline is imposed. Ctrl-C leaves protected tasks.
        try:
            with opener.open(request) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            try:
                code = json.load(error).get("error", {}).get("code", "unknown")
            except (ValueError, AttributeError):
                code = "unknown"
            raise TaskHttpError(error.code, code) from None

    # Serialize deployment actions across operators. No expiry or automatic
    # stealing: an interrupted controller's identity must be explicitly resumed.
    key = {"id": {"S": "deployment-controller"}}
    table = manifest["owner_table"]
    identity = {"operation": {"S": operation}, "deployment": {"S": manifest["deployment"]}, "action": {"S": args.action}}
    values = {":operation": identity["operation"], ":deployment": identity["deployment"], ":action": identity["action"], ":no": {"BOOL": False}}
    aws_cli("dynamodb", "put-item", TableName=table, Item={**key, **identity, "held": {"BOOL": True}},
            ConditionExpression="attribute_not_exists(id) OR held = :no OR (operation = :operation AND deployment = :deployment AND #action = :action)",
            ExpressionAttributeNames={"#action": "action"}, ExpressionAttributeValues=values)
    controller = Controller(manifest, aws_cli, http)
    result = controller.step(args.action)
    aws_cli("dynamodb", "update-item", TableName=table, Key=key, UpdateExpression="SET held = :no",
            ConditionExpression="operation = :operation", ExpressionAttributeValues={":no": {"BOOL": False}, ":operation": {"S": operation}})
    print(result)


if __name__ == "__main__":
    try:
        main()
    except (GateError, subprocess.CalledProcessError, urllib.error.URLError) as error:
        # Do not dump HTTP request/auth content or AWS CLI arguments.
        print(f"Rollout stopped safely: {str(error) if isinstance(error, GateError) else type(error).__name__}. Inspect current state before resuming.")
        raise SystemExit(1)
