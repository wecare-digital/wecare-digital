"""Payment-setting changes need publication even when the Lambda zip is unchanged."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/snapstart_publish.py'
spec=importlib.util.spec_from_file_location('audit_snapstart_publish',SCRIPT)
publisher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def test_same_code_different_environment_publishes_and_moves_alias():
    lam=Mock()
    lam.get_function_configuration.side_effect=[
        {'Environment':{'Variables':{}}},
        {'Environment':{'Variables':{'EXPECTED_PROVIDER_MID':'verified-mid'}}},
    ]
    lam.publish_version.return_value={'Version':'6','CodeSha256':'same-code'}
    with patch.object(publisher,'current_state',side_effect=[('5','same-code','same-code'),('6','same-code','same-code')]), \
         patch.object(publisher,'wait_active',return_value=True):
        assert publisher.publish_and_move(lam,'payment',False,True)=='updated'
    lam.update_alias.assert_called_once_with(FunctionName='payment',Name='live',FunctionVersion='6')


def test_matching_code_and_environment_skip_publication():
    lam=Mock()
    lam.get_function_configuration.return_value={'Environment':{'Variables':{'EXPECTED_PROVIDER_MID':'same'}}}
    with patch.object(publisher,'current_state',return_value=('5','same-code','same-code')):
        assert publisher.publish_and_move(lam,'payment',False,True)=='skipped'
    lam.publish_version.assert_not_called()
    lam.update_alias.assert_not_called()
