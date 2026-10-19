"""Exercise the deployed edge code with synthetic requests; no network traffic."""

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).parents[1]


def test_exact_host_exclusions_and_fixed_destination_after_host_normalization():
    blocked = [
        variant
        for host in ("www.wecare.digital", "www.xout.wecare.digital")
        for variant in (host, host.upper(), host + ".", host + ":443", host + ".:443")
    ]
    allowed = [f"{host}.wecare.digital" for host in ("shop", "store", "xout", "release-check-unknown")]
    events = [{"request": {
        "headers": {"host": {"value": host}},
        "uri": "/old/path",
        "querystring": {"old": {"value": "must-not-forward"}},
    }} for host in blocked + allowed]
    program = """
const fs = require('fs'), vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(input.code, sandbox);
process.stdout.write(JSON.stringify(input.events.map(event => sandbox.handler(event))));
"""
    result = subprocess.run(
        ["node", "-e", program],
        input=json.dumps({"code": (ROOT / "scripts/home-fallback-function.js").read_text(), "events": events}),
        text=True, capture_output=True, check=True,
    )
    responses = json.loads(result.stdout)
    assert len(responses) == len(events)
    for response in responses[:len(blocked)]:
        assert response["statusCode"] == 404
        assert "location" not in response["headers"]
    for response in responses[len(blocked):]:
        assert response["statusCode"] == 302
        assert response["headers"]["location"] == {"value": "https://wecare.digital/"}
    assert all(response["headers"]["cache-control"] == {"value": "no-store"} for response in responses)
