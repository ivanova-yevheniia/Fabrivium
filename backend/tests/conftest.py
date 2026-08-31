"""Suite-wide test configuration for FactoryMind."""

from __future__ import annotations

import os

# Must happen at import time — before any test module imports app.main.
os.environ["FACTORYMIND_LLM_ENABLED"] = "false"
