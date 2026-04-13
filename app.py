from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parent
INNER_APP_PATH = BASE_DIR / "vaultsignalsai_flask" / "app.py"

spec = importlib.util.spec_from_file_location("vaultsignalsai_inner_app", INNER_APP_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load Flask app from {INNER_APP_PATH}")

module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)

app = module.app


if __name__ == "__main__":
    module.validate_security_configuration()
    module.init_db()
    app.run(
        host=os.getenv("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_RUN_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() in {"1", "true", "yes"},
    )