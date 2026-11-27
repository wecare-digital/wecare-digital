"""Offline public-directory contract tests. No external network or real records."""
import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/apollo_public_directory.py'
spec = importlib.util.spec_from_file_location('apollo_public_directory', SCRIPT)
directory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(directory)


def test_permission_gate_precedes_any_fetch():
    get = Mock()
    with pytest.raises(directory.DirectoryUnavailable):
        directory.discover('doctors', get=get)
    get.assert_not_called()


def test_robots_denial_stops_before_directory():
    get = Mock(return_value='User-agent: *\nDisallow: /doctors\n')
    with pytest.raises(directory.DirectoryUnavailable):
        directory.discover('doctors', approved=True, get=get)
    get.assert_called_once_with(directory.ORIGIN + '/robots.txt', max_bytes=256 * 1024, media='text/plain')


def test_directory_only_normalized_same_origin_links():
    html = '''
      <a href="/doctors/synthetic-speciality/test-city/dr-test">Dr <span>Test</span></a>
      <a href="/doctors/synthetic-speciality/test-city/dr-test/">Dr Test</a>
      <a href="https://evil.example/doctors/test/city/dr-other">Dr Other</a>
      <a href="//www.apollohospitals.com.evil.example/doctors/test/city/dr-other">Dr Other</a>
      <a href="/doctors/test/city/dr-other?patient=private">Dr Other</a>
      <a href="https://user@www.apollohospitals.com/doctors/test/city/dr-other">Dr Other</a>
      <a href="/doctors/test/city">Find Doctors</a>
      <a href="/doctors/test/city/dr-other#slot">Dr Other</a>
      <script>fake data</script>
    '''
    get = Mock(side_effect=['User-agent: *\nAllow: /\n', html])
    result = directory.discover('doctors', approved=True, get=get)
    assert result['directoryOnly'] is True
    assert result['coverage'] == 'first-page-only'
    assert result['items'] == [{
        'label': 'Dr Test', 'url': directory.ORIGIN + '/doctors/synthetic-speciality/test-city/dr-test',
        'specialitySlug': 'synthetic-speciality', 'citySlug': 'test-city',
    }]
    assert get.call_count == 2
    assert get.call_args.args == (directory.SOURCES['doctors'],)


def test_hospital_link_discovery_keeps_only_directory_labels():
    items, truncated = directory.parse_directory('hospitals', '''
        <h3><a href="/hospitals/apollo-synthetic">Apollo Synthetic Hospital</a></h3>
        <a href="/hospitals/apollo-synthetic">Best Hospital</a>
        <a href="/doctors">Book Appointment</a>
        <a href="/hospitals/other">See Details</a>
    ''')
    assert items == [{'label': 'Apollo Synthetic Hospital', 'url': directory.ORIGIN + '/hospitals/apollo-synthetic'}]
    assert not truncated


def test_empty_layout_is_failure_not_empty_inventory():
    with pytest.raises(directory.DirectoryUnavailable):
        directory.parse_directory('doctors', '<html>Login required</html>')


def test_limit_and_no_slot_or_booking_fields(monkeypatch):
    monkeypatch.setattr(directory, 'MAX_LINKS', 1)
    items, truncated = directory.parse_directory('doctors', '''
        <a href="/doctors/test/city/dr-one">Dr One</a>
        <a href="/doctors/test/city/dr-two">Dr Two</a>
    ''')
    assert len(items) == 1 and truncated
    assert set(items[0]) == {'label', 'url', 'specialitySlug', 'citySlug'}
