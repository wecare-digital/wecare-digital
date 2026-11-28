"""MSG-9: the group-image route fetches only a public https JPEG of at most 5 MB.

Compiled from the real whatsapp-business-api source (the handler needs `cryptography`
at import time); network calls are replaced by fakes.
"""
import ast
import hashlib
import hmac
import json
import socket
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from typing import Dict
from unittest import mock

import pytest

BUSINESS_API = (Path(__file__).resolve().parents[2]
                / "amplify/functions/messaging/whatsapp-business-api/handler.py")
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64


def compiled():
    names = {"GROUP_IMAGE_MAX_BYTES", "_NoRedirect", "_set_group_image", "_is_ssrf_safe_url"}
    tree = ast.parse(BUSINESS_API.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body
             if (isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names)
             or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in names
                                                   for t in n.targets))]
    env = {"__builtins__": __builtins__, "Dict": Dict, "urllib": urllib, "json": json,
           "hmac": hmac, "hashlib": hashlib, "GRAPH_BASE": "https://graph.example/v26.0",
           "logger": mock.Mock(), "_get_meta_token": lambda: "token", "_get_app_secret": lambda: "",
           "_resp": lambda code, body: {"statusCode": code, "body": body}}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(BUSINESS_API), "exec"), env)
    return env


class FakeResponse:
    def __init__(self, body, content_type="image/jpeg"):
        self.body = body
        self.headers = {"Content-Type": content_type}
        self.read_limits = []

    def read(self, limit=-1):
        self.read_limits.append(limit)
        return self.body if limit is None or limit < 0 else self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def env():
    return compiled()


def run(env, url, response=None, address="93.184.216.34"):
    openers, uploads = [], []

    def build_opener(*handlers):
        openers.append(handlers)
        return SimpleNamespace(open=lambda req, timeout: response)

    def urlopen(req, timeout):
        uploads.append(req)
        return FakeResponse(b'{"success": true}')

    with mock.patch.object(socket, "getaddrinfo", return_value=[(2, 1, 6, "", (address, 443))]), \
            mock.patch.object(urllib.request, "build_opener", side_effect=build_opener), \
            mock.patch.object(urllib.request, "urlopen", side_effect=urlopen):
        result = env["_set_group_image"]("group-1", url)
    return result, openers, uploads


@pytest.mark.parametrize("url,address", [
    ("file:///etc/passwd", "93.184.216.34"),
    ("http://example.com/pic.jpg", "93.184.216.34"),
    ("https://metadata.example/latest/meta-data", "169.254.169.254"),
    ("https://internal.example/pic.jpg", "10.0.0.7"),
])
def test_non_public_or_non_https_urls_are_never_fetched(env, url, address):
    result, openers, uploads = run(env, url, address=address)
    assert result["statusCode"] == 400
    assert openers == [] and uploads == []


def test_fetch_refuses_redirects(env):
    _, openers, _ = run(env, "https://cdn.example/pic.jpg", FakeResponse(JPEG))
    assert openers == [(env["_NoRedirect"],)]
    # urllib raises HTTPError for a 3xx when the redirect handler returns None.
    handler = env["_NoRedirect"]()
    assert handler.redirect_request(None, None, 302, "Found", {}, "http://169.254.169.254/") is None


def test_oversized_image_is_refused_after_a_bounded_read(env):
    big = FakeResponse(JPEG + b"0" * env["GROUP_IMAGE_MAX_BYTES"])
    result, _, uploads = run(env, "https://cdn.example/pic.jpg", big)
    assert result["statusCode"] == 400 and uploads == []
    assert big.read_limits == [env["GROUP_IMAGE_MAX_BYTES"] + 1]


@pytest.mark.parametrize("body,content_type", [
    (b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png"),
    (b"<html>not an image</html>", "image/jpeg"),
    (JPEG, "text/html"),
])
def test_only_jpeg_is_uploaded(env, body, content_type):
    result, _, uploads = run(env, "https://cdn.example/pic", FakeResponse(body, content_type))
    assert result["statusCode"] == 400 and uploads == []


def test_valid_jpeg_is_uploaded(env):
    result, _, uploads = run(env, "https://cdn.example/pic.jpg", FakeResponse(JPEG))
    assert result["statusCode"] == 200
    assert len(uploads) == 1 and b"Content-Type: image/jpeg" in uploads[0].data
