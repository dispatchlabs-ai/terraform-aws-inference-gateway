import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

# The deployed Lambda supplies boto3. Keep local qualification stdlib-only.
boto3 = ModuleType('boto3')
boto3.client = Mock()
exceptions = ModuleType('botocore.exceptions')
exceptions.ClientError = type('ClientError', (Exception,), {})
with patch.dict(sys.modules, {'boto3': boto3, 'botocore': ModuleType('botocore'), 'botocore.exceptions': exceptions}):
    spec = importlib.util.spec_from_file_location('observer', Path(__file__).parents[1] / 'lambda/stopped.py')
    observer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(observer)

class ServingHealth(unittest.TestCase):
    def setUp(self):
        self.elb, self.metrics = Mock(), Mock()
        boto3.client.side_effect = lambda name: self.elb if name == 'elbv2' else self.metrics
        self.health = {'blue': 0, 'green': 2}
        self.elb.describe_target_health.side_effect = lambda TargetGroupArn: {'TargetHealthDescriptions': [
            {'TargetHealth': {'State': 'healthy'}} for _ in range(self.health[TargetGroupArn])
        ]}
        self.env = patch.dict(os.environ, SERVICE='synthetic', TARGET_GROUPS=json.dumps(['blue', 'green']), LISTENER_RULE='rule')
        self.env.start()
        self.addCleanup(self.env.stop)

    def poll(self, weights):
        self.elb.describe_rules.return_value = {'Rules': [{'Actions': [{'Type': 'forward', 'ForwardConfig': {'TargetGroups': [
            {'TargetGroupArn': group, 'Weight': weight} for group, weight in weights.items()
        ]}}]}]}
        observer.handler({'source': 'aws.events', 'detail-type': 'Scheduled Event'}, None)
        return self.metrics.put_metric_data.call_args.kwargs['MetricData'][0]['Value']

    def test_cutover_and_rollback_follow_live_rule(self):
        self.assertEqual(self.poll({'blue': 0, 'green': 100}), 2)
        self.assertEqual(self.poll({'blue': 100, 'green': 0}), 0)

    def test_standby_and_split_cannot_mask_unhealthy_serving_group(self):
        self.assertEqual(self.poll({'blue': 50, 'green': 50}), 0)
        self.assertEqual(self.poll({'blue': 100, 'green': 0}), 0)

    def test_invalid_route_does_not_publish_healthy(self):
        for weights in [{'blue': 0, 'green': 0}, {'unexpected': 100}]:
            with self.assertRaises(ValueError):
                self.poll(weights)
        self.metrics.put_metric_data.assert_not_called()

    def test_legacy_group_and_failed_observation(self):
        os.environ.update(LISTENER_RULE='', TARGET_GROUPS='["green"]')
        observer.serving_health()
        self.assertEqual(self.metrics.put_metric_data.call_args.kwargs['MetricData'][0]['Value'], 2)
        self.elb.describe_rules.assert_not_called()
        self.metrics.reset_mock()
        self.elb.describe_target_health.side_effect = RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):
            observer.serving_health()
        self.metrics.put_metric_data.assert_not_called()

if __name__ == '__main__':
    unittest.main()
