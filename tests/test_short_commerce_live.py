"""No-credential offline tests for the Short Commerce production attestation gate."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/check_short_commerce_live.py"
spec = importlib.util.spec_from_file_location("check_short_commerce_live", SOURCE)
assert spec and spec.loader
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

ACCOUNT = "775261844268"
REGION = "us-east-1"
HASHES = {
    name: base64.b64encode(bytes([i + 1]) * 32).decode("ascii")
    for i, name in enumerate(checker.RECEIVERS)
}
VERSIONS = {name: str(400 + i) for i, name in enumerate(checker.RECEIVERS)}


def manifest():
    return {
        "schema_version": "short-commerce-release-v1",
        "account": ACCOUNT,
        "region": REGION,
        "source_commit": "a" * 40,
        "receivers": {name: {"version": VERSIONS[name], "code_sha256": HASHES[name]}
                      for name in checker.RECEIVERS},
    }


class FakeSTS:
    def get_caller_identity(self):
        return {"Account": ACCOUNT}


class FakeLambda:
    def __init__(self, *, wrong_sha=None, missing_flag=None, wrong_alias=None, weighted=None):
        self.wrong_sha = wrong_sha
        self.missing_flag = missing_flag
        self.wrong_alias = wrong_alias
        self.weighted = weighted

    def get_alias(self, *, FunctionName, Name):
        assert Name == "live"
        version = VERSIONS[FunctionName]
        return {
            "FunctionVersion": "1" if FunctionName == self.wrong_alias else version,
            "RoutingConfig": {"AdditionalVersionWeights": {"2": 0.1}}
            if FunctionName == self.weighted else {},
        }

    def get_function_configuration(self, *, FunctionName, Qualifier):
        assert Qualifier == "live"
        return {
            "Version": VERSIONS[FunctionName],
            "CodeSha256": "wrong" if FunctionName == self.wrong_sha else HASHES[FunctionName],
            "Environment": {"Variables": {} if FunctionName == self.missing_flag
                            else {checker.FLAG: "true"}},
            "State": "Active",
            "LastUpdateStatus": "Successful",
        }


class FakeWatch:
    def __init__(self, *, missing=None, alarm=None):
        self.missing = missing
        self.alarm = alarm

    def describe_alarms(self, *, AlarmNames):
        assert set(AlarmNames) == set(checker.PAYMENT_ALARMS)
        return {"MetricAlarms": [
            {"AlarmName": name, "StateValue": "ALARM" if name == self.alarm else "OK"}
            for name in AlarmNames if name != self.missing
        ]}


class FakeSession:
    def __init__(self, *, lam=None, watch=None):
        self.clients = {"sts": FakeSTS(), "lambda": lam or FakeLambda(),
                        "cloudwatch": watch or FakeWatch()}

    def client(self, service, *, region_name):
        assert region_name == REGION
        return self.clients[service]


class ReleaseManifestTests(unittest.TestCase):
    def validate(self, content):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "release.json"
            path.write_text(json.dumps(content), encoding="utf-8")
            return checker.read_release_manifest(path, expected_account=ACCOUNT, region=REGION)

    def test_accepts_exact_reviewed_bundle_manifest(self):
        self.assertEqual(manifest(), self.validate(manifest()))

    def test_rejects_other_account_or_missing_receiver(self):
        bad = manifest()
        bad["account"] = "123456789012"
        with self.assertRaises(ValueError):
            self.validate(bad)
        bad = manifest()
        del bad["receivers"][checker.RECEIVERS[-1]]
        with self.assertRaises(ValueError):
            self.validate(bad)

    def test_rejects_unpinned_version_hash_and_git_revision(self):
        name = checker.RECEIVERS[0]
        for version in ("$LATEST", "live", "0", 123):
            with self.subTest(version=version):
                bad = manifest()
                bad["receivers"][name]["version"] = version
                with self.assertRaises(ValueError):
                    self.validate(bad)
        bad = manifest()
        bad["receivers"][name]["code_sha256"] = "not-a-sha"
        with self.assertRaises(ValueError):
            self.validate(bad)
        bad = manifest()
        bad["source_commit"] = "short-hash"
        with self.assertRaises(ValueError):
            self.validate(bad)


class LiveReadinessTests(unittest.TestCase):
    def audit(self, *, release=None, lam=None, watch=None):
        return checker.live_snapshot(FakeSession(lam=lam, watch=watch),
                                     region=REGION, release_manifest=release)

    def test_approved_versions_flags_and_eight_alarms_ready(self):
        result = self.audit(release=manifest())
        self.assertTrue(result["config_ok"])
        self.assertTrue(result["alarms_ok"])
        self.assertEqual(3, len(result["receivers"]))
        self.assertEqual(8, len(result["payment_alarms"]))

    def test_no_manifest_fails_closed_even_if_flags_and_alarms_healthy(self):
        result = self.audit()
        self.assertFalse(result["config_ok"])
        self.assertTrue(result["alarms_ok"])
        self.assertTrue(all(not row["ready"] for row in result["receivers"]))

    def test_stale_alias_or_code_sha_prevents_ready(self):
        name = checker.RECEIVERS[0]
        for lam in (FakeLambda(wrong_alias=name), FakeLambda(wrong_sha=name),
                    FakeLambda(weighted=name), FakeLambda(missing_flag=name)):
            with self.subTest(lam=lam.__dict__):
                result = self.audit(release=manifest(), lam=lam)
                self.assertFalse(result["config_ok"])
                self.assertFalse(result["receivers"][0]["ready"])

    def test_missing_or_alarming_named_payment_alarm_prevents_ready(self):
        alarm = checker.PAYMENT_ALARMS[0]
        for watch in (FakeWatch(missing=alarm), FakeWatch(alarm=alarm)):
            with self.subTest(watch=watch.__dict__):
                result = self.audit(release=manifest(), watch=watch)
                self.assertTrue(result["config_ok"])
                self.assertFalse(result["alarms_ok"])


if __name__ == "__main__":
    unittest.main()
