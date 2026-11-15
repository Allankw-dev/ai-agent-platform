"""Test-wide setup, run before any test module imports the app.

A developer's local port choices (WEB_PORT in .env) reach the API container as the CORS_ORIGINS and
FRONTEND_URL variables. The tests must give the same answer whatever ports are in use, so the
defaults are pinned here. Tests that need other values set them with `monkeypatch`.
"""

import os

os.environ["CORS_ORIGINS"] = '["http://localhost:3000"]'
os.environ["FRONTEND_URL"] = "http://localhost:3000"
