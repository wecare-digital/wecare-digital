"""
Test configuration — handles module isolation for Lambda handlers.

All Lambda handlers are named handler.py, so we need to clear the module
cache between test files to avoid import collisions.
"""
import sys
import os
import pytest

# NO AWS REGION DEFAULT HERE, AND THAT IS DELIBERATE.
#
# This file briefly carried `os.environ.setdefault('AWS_DEFAULT_REGION', 'us-east-1')` to stop
# `botocore.exceptions.NoRegionError` during collection, which was failing 7 tests and with
# them the whole blocking `Route auth` gate. It was the wrong fix and it is removed.
#
# The cause was one handler constructing its DynamoDB resource at import time with no region
# argument, so importing the module reached for AWS configuration before any test ran.
# 39cfcf85 fixed that properly by building those resources lazily. Checked across the tree:
# 53 of the 54 handler files that touch boto3 at module scope already pass
# `region_name=os.environ.get('AWS_REGION', 'us-east-1')` themselves - so a region fallback at
# the call site is the established convention here, and url-shortener was the lone outlier.
#
# A default in this file would have masked the next outlier instead of surfacing it: the suite
# would pass, and the handler would still be reaching for AWS config at import time where a
# Lambda cold start or a local run without AWS config would break. Keeping the environment bare
# is what makes that class of defect visible to the gate at all.
#
# So if a new test fails with NoRegionError, that is the signal working - fix the handler, not
# this file.

# Ensure shared lambda_utils is always importable
_shared_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'shared'))
if _shared_path not in sys.path:
    sys.path.insert(0, _shared_path)

# Base path for all handler directories
_functions_base = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions'))


def _clean_handler_paths():
    """Remove all handler-specific paths from sys.path (keep shared lambda_utils)."""
    sys.path[:] = [
        p for p in sys.path
        if not (os.path.abspath(p).startswith(_functions_base) and os.path.abspath(p) != _shared_path)
    ]


@pytest.fixture(autouse=True, scope='function')
def isolate_handler_imports():
    """Clear cached handler module between tests to avoid cross-contamination.
    
    Each test file inserts its handler path at module level. We clear the handler
    module from sys.modules so the next import picks up the correct handler.
    We also clean stale handler paths so only the current test file's path remains.
    """
    # Clear handler module cache
    _evict_cross_file_modules()
    yield
    _evict_cross_file_modules()


# The seo-tools handler directory lays its modules out as bare-name siblings on sys.path -
# storage.py, blog_sources.py, seo_engine.py, faq.py and so on - and several test files import
# them under those bare names (`import storage`, `import blog_sources as bs`) or force-load them
# with importlib.util + `sys.modules[name] = mod` (see tests/test_seo_engine.py._load). Because the
# names are bare, the FIRST file to load one wins the sys.modules slot for the whole session, and a
# later file importing the same bare name silently gets the earlier file's object. The blog tests
# monkeypatch `storage.table`, but `blog_sources` was compiled against a different `storage`
# instance left behind by the seo tests, so the patch lands on the wrong object and the call
# reaches real AWS - NoCredentialsError, 281 failures, order-dependent.
#
# Clearing them at both ends of every test forces each file to re-import its own consistent set.
_SEO_TOOLS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'amplify', 'functions', 'operations', 'seo-tools'))


def _evict_cross_file_modules():
    for mod_name in list(sys.modules.keys()):
        if mod_name == 'handler' or mod_name.startswith('handler.'):
            del sys.modules[mod_name]
            continue
        mod = sys.modules.get(mod_name)
        mod_file = getattr(mod, '__file__', None) or ''
        if mod_file and os.path.abspath(mod_file).startswith(_SEO_TOOLS_DIR):
            del sys.modules[mod_name]
