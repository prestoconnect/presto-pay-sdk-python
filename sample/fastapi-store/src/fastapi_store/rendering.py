from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"

templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
