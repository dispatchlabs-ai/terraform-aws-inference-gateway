import copy
import time
import unittest
from rollout import Controller, GateError


class Fixture:
    def __init__(self):
        self.manifest = {
            "cluster": "arn:aws:ecs:us-east-1:123456789012:cluster/test",
            "service": "arn:aws:ecs:us-east-1:123456789012:service/test/gateway",
            "deployment": "deployment", "owner_table": "owner", "listener_rule": "rule",
            "source": {"tasks": ["old"], "task_definition": "definition-old", "target_group": "blue"},
            "target": {"tasks": ["new"], "task_definition": "definition-new", "target_group": "green"},
        }
        self.writer = {"taskArn": "old", "generation": "old-generation"}
        self.stage, self.route, self.busy = "POST_SCALE_UP", "source", False
        self.calls = []
        self.states = {name: {"taskArn": name, "generation": name + "-generation", "protocol": 2,
                              "accepting": True, "protectedUntil": time.time() * 1000 + 60000, "drained": False}
                       for name in ("old", "new")}

    def aws(self, service, operation, **payload):
        self.calls.append((service, operation, payload))
        if operation == "describe-service-deployments":
            return {"serviceDeployments": [{"serviceDeploymentArn": self.manifest["deployment"],
                    "clusterArn": self.manifest["cluster"], "serviceArn": self.manifest["service"],
                    "deploymentConfiguration": {"strategy": "BLUE_GREEN"}, "lifecycleStage": self.stage,
                    "status": "IN_PROGRESS", "lifecycleHookDetails": [
                        {"targetType": "PAUSE", "status": "AWAITING_ACTION", "timeoutAction": "ROLLBACK", "hookId": self.stage}]}]}
        if operation == "describe-tasks":
            return {"tasks": [{"taskArn": name, "clusterArn": self.manifest["cluster"], "group": "service:gateway",
                    "taskDefinitionArn": "definition-" + name, "lastStatus": "RUNNING", "desiredStatus": "RUNNING",
                    "attachments": [{"details": [{"name": "privateIPv4Address", "value": "10.0.0.1" if name == "old" else "10.0.0.2"}]}]}
                    for name in payload["tasks"]]}
        if operation == "describe-target-health":
            return {"TargetHealthDescriptions": [{"Target": {"Id": "10.0.0.1" if payload["TargetGroupArn"] == "blue" else "10.0.0.2", "Port": 8787},
                                                  "TargetHealth": {"State": "healthy"}}]}
        if operation == "get-item":
            return {"Item": {**{k: {"S": v} for k, v in self.writer.items()}, "protocol": {"N": "2"}, "phase": {"S": "active"}}}
        if operation == "describe-rules":
            return {"Rules": [{"Actions": [{"Type": "forward", "ForwardConfig": {"TargetGroups": [
                {"TargetGroupArn": group, "Weight": 100 if self.route == side else 0}
                for side, group in [("source", "blue"), ("target", "green")]]}}]}]}
        if operation == "continue-service-deployment":
            if payload["action"] == "ROLLBACK":
                self.route = "source"
            elif self.stage == "POST_SCALE_UP":
                self.stage, self.route = "POST_PRODUCTION_TRAFFIC_SHIFT", "target"
            else:
                self.stage = "CLEAN_UP"
            return {}
        if operation == "modify-rule":
            self.route = "source"
            return {}
        if operation == "get-task-protection":
            return {"protectedTasks": [{"taskArn": name, "protectionEnabled": not self.states[name].get("retiring", False)}
                                      for name in payload["tasks"]]}
        raise AssertionError(operation)

    def http(self, origin, path, body=None):
        self.calls.append(("http", path, body))
        name = "old" if "10.0.0.1:" in origin else "new"
        if path.endswith("/handoff"):
            self.writer = copy.deepcopy(body)
        elif path.endswith("/activate"):
            self.states[name].update(accepting=True, drained=False)
        elif path.endswith("/drain"):
            self.states[name].update(accepting=False, drained=not self.busy)
        elif path.endswith("/retire"):
            assert self.states[name]["drained"]
            self.states[name]["retiring"] = True
        return copy.deepcopy(self.states[name])

    def controller(self):
        return Controller(self.manifest, self.aws, self.http)


class RolloutTests(unittest.TestCase):
    def test_cutover_handoff_then_drain_then_retire_without_any_inference(self):
        f = Fixture()
        f.controller().step("cutover")
        self.assertEqual(f.writer["taskArn"], "new")
        f.busy = True
        self.assertIn("Draining", f.controller().step("drain"))
        with self.assertRaises(GateError):
            f.controller().step("finish")
        self.assertFalse(f.states["old"].get("retiring"))
        f.busy = False
        f.controller().step("drain")
        f.controller().step("finish")
        self.assertTrue(f.states["old"]["retiring"])
        retirement = next(i for i, c in enumerate(f.calls) if c[1].endswith("/retire"))
        released = max(i for i, c in enumerate(f.calls) if c[1] == "get-task-protection")
        continued = max(i for i, c in enumerate(f.calls) if c[1] == "continue-service-deployment")
        self.assertLess(retirement, released)
        self.assertLess(released, continued, "ECS deregistration must follow confirmed application close")
        self.assertFalse(any("responses" in call[1] or "stop-task" == call[1] for call in f.calls))

    def test_finish_resumes_after_a_retirement_reply_was_lost(self):
        f = Fixture()
        f.controller().step("cutover")
        f.controller().step("drain")
        f.states["old"]["retiring"] = True
        f.controller().step("finish")
        self.assertEqual(f.stage, "CLEAN_UP")
        self.assertFalse(any(c[1].endswith("/retire") for c in f.calls))

    def test_interrupted_controller_resumes_from_observed_ownership(self):
        f = Fixture()
        f.writer = {"taskArn": "new", "generation": "new-generation"}
        f.controller().step("cutover")
        self.assertFalse(any(call[1].endswith("/handoff") for call in f.calls))

    def test_unknown_legacy_runtime_cannot_pass_cutover_gate(self):
        f = Fixture()
        del f.states["old"]["protocol"]
        with self.assertRaisesRegex(GateError, "Legacy migration"):
            f.controller().step("cutover")
        self.assertFalse(any(call[1] == "continue-service-deployment" for call in f.calls))
        self.assertEqual(f.writer["taskArn"], "old")

    def test_rollback_drains_candidate_before_ecs_may_deregister_it(self):
        f = Fixture()
        f.controller().step("cutover")
        f.controller().step("drain")
        f.busy = True
        self.assertIn("Rollback draining", f.controller().step("rollback"))
        self.assertEqual(f.writer["taskArn"], "old")
        self.assertEqual(f.route, "source", "New requests move before candidate target deregistration")
        self.assertEqual(f.stage, "POST_PRODUCTION_TRAFFIC_SHIFT", "Existing streams retain candidate registration")
        self.assertFalse(f.states["old"].get("retiring"))
        f.busy = False
        f.controller().step("rollback")
        self.assertEqual(f.route, "source")
        self.assertTrue(f.states["new"]["retiring"], "Retire before ECS can deregister candidates")
        f.controller().step("cleanup-target")
        self.assertTrue(f.states["new"]["retiring"])

    def test_cleanup_never_retires_the_current_writer_or_unfenced_task(self):
        f = Fixture()
        with self.assertRaises(GateError):
            f.controller().step("cleanup-source")
        with self.assertRaises(GateError):
            f.controller().step("cleanup-target")
        self.assertFalse(any(call[1].endswith("/retire") for call in f.calls))

    def test_wrong_traffic_unprotected_or_unresolved_runtime_fail_closed(self):
        for field, value in [("protectedUntil", 0), ("unresolvedRotation", True), ("taskArn", "foreign")]:
            with self.subTest(field=field):
                f = Fixture()
                f.states["new"][field] = value
                with self.assertRaises(GateError):
                    f.controller().step("cutover")
                self.assertFalse(any(call[1] == "continue-service-deployment" for call in f.calls))
        f = Fixture()
        f.stage = "POST_PRODUCTION_TRAFFIC_SHIFT"
        with self.assertRaises(GateError):
            f.controller().step("drain")


if __name__ == "__main__":
    unittest.main()
