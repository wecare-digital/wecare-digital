"""Exercise the workflow's branch check against local Git remotes; no GitHub writes."""
import os
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('state', ['present', 'absent', 'unreachable'])
def test_branch_preflight_distinguishes_missing_target_from_remote_error(tmp_path, state):
    workflow = yaml.safe_load((ROOT / '.github/workflows/sync-gastronomy-quality.yml').read_text())
    steps = workflow['jobs']['sync']['steps']
    check = next(step for step in steps if step.get('id') == 'target')
    remote = tmp_path / 'remote.git'
    checkout = tmp_path / 'checkout'
    subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
    subprocess.run(['git', 'init', str(checkout)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(checkout), 'remote', 'add', 'origin', str(remote)], check=True)
    if state == 'present':
        subprocess.run(['git', '-C', str(checkout), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                        'commit', '--allow-empty', '-m', 'fixture'], check=True, capture_output=True)
        subprocess.run(['git', '-C', str(checkout), 'push', 'origin', 'HEAD:refs/heads/gastronomy-quality'],
                       check=True, capture_output=True)
    if state == 'unreachable':
        subprocess.run(['git', '-C', str(checkout), 'remote', 'set-url', 'origin', str(tmp_path / 'missing.git')], check=True)
    output = tmp_path / 'output'
    summary = tmp_path / 'summary'
    env = dict(os.environ, RUNNER_TEMP=str(tmp_path), GITHUB_OUTPUT=str(output), GITHUB_STEP_SUMMARY=str(summary))
    result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', check['run']], cwd=checkout,
                            env=env, capture_output=True, text=True)
    if state == 'unreachable':
        assert result.returncode != 0
        assert not output.exists()
    else:
        assert result.returncode == 0
        assert output.read_text().strip() == 'exists=' + str(state == 'present').lower()
        if state == 'absent':
            assert 'sync skipped' in result.stdout and 'does not exist' in summary.read_text()
    for name in ('Configure Git identity', 'Merge latest stack', 'Push synchronized branch'):
        assert next(step for step in steps if step['name'] == name)['if'] == "steps.target.outputs.exists == 'true'"
