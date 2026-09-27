"""Keep the test suite out of the shipped plan cache.

`data/cache/plans/` is a build artefact that ships inside the image — one
solved plan per month the UI can reach. Running pytest used to write test
instances into it, so the committed cache filled with three-day, eight-task
plans that no deployment will ever ask for.

The cache directory is read from the environment at import time, so this must
run before anything imports `src.api.cache`. conftest is imported before test
modules, which is exactly that point.
"""

from __future__ import annotations

import os
import tempfile

os.environ["PLAN_CACHE_DIR"] = tempfile.mkdtemp(prefix="railvia-test-plans-")
