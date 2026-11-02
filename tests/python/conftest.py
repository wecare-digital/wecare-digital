"""pytest bootstrap for the shared Lambda utilities.

The shared utilities under ``amplify/functions/shared/lambda_utils`` are imported
as ``lambda_utils.<pkg>.<mod>`` (e.g. ``lambda_utils.ecommerce.money``). In a
deployed Lambda package ``lambda_utils/`` sits at the import root, so no package
install is involved; the handler's bundle just has ``amplify/functions/shared``
on its import path. Mirror that here by prepending the same directory to
``sys.path`` so the tests import the real shared code without an editable install.

The path is resolved relative to the repo root (this file lives at
``<repo>/tests/python/conftest.py``, so the repo root is two directories up).
Keeping the shim here means ``pytest`` works whether or not ``PYTHONPATH`` was
exported by the caller or CI.
"""

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_SHARED_ROOT = os.path.join(_REPO_ROOT, "amplify", "functions", "shared")

if _SHARED_ROOT not in sys.path:
    sys.path.insert(0, _SHARED_ROOT)
