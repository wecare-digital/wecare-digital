"""CORE-5 call sites: every destructive consume binds the redeeming actor."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
CALL = "destructive_confirm.consume("


def _calls(src):
    """Each full `destructive_confirm.consume(...)` call, matched by balancing parentheses."""
    out, start = [], src.find(CALL)
    while start != -1:
        depth, i = 0, start + len(CALL) - 1
        while True:
            depth += {"(": 1, ")": -1}.get(src[i], 0)
            if depth == 0:
                break
            i += 1
        out.append(src[start:i + 1])
        start = src.find(CALL, i)
    return out


def _source(rel):
    return (ROOT / rel).read_text()


def test_system_cleanup_passes_the_actor_and_records_the_previewer():
    src = _source("amplify/functions/operations/system-cleanup/handler.py")
    assert "destructive_confirm.consume(CONFIRM_SCOPE, token, selection, actor=actor)" in src
    assert "_consume_confirmation(token, selected, actor=_actor(event))" in src
    assert "'previewActor': consumed.get('actor', '')" in src


def test_contact_cleanup_passes_the_actor():
    calls = _calls(_source("amplify/functions/core/contacts/handler.py"))
    assert calls and all("actor=actor" in c for c in calls)


def test_every_consume_call_binds_an_actor():
    seen = 0
    for path in (ROOT / "amplify/functions").rglob("handler.py"):
        for call in _calls(path.read_text()):
            seen += 1
            assert "actor=" in call, f"{path}: {call}"
    assert seen >= 3
