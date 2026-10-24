# GutGPT v18.3 — widget-only migration notes

## Changes in this working copy

- Removed the standalone customer-facing `index.html` and legacy `chat.html`.
- Removed the FastAPI root route that served `index.html`; `/` now returns backend status JSON.
- Removed `/bristol-stool-chart.png` and its now-unused standalone chart image, which were only used by the removed standalone pages. The current Shopify widget contains its Bristol chart markup/data itself.
- Kept `/gutgpt-widget.js`, `/api/health`, customer/session/chat APIs, admin routes, and the existing diagnosis, safety, recommendation, and persistence modules.
- Kept Docker Compose as backend + PostgreSQL only; it does not define a port-3000 service.
- Updated the regression test to assert the standalone pages are absent and token handling is checked in the widget.
- Did not modify database contents or the included database backup.

## Validation

- `python -m py_compile app.py tests/test_security_hardening_followup.py`: passed.
- `node --check gutgpt-widget.js`: passed.
- Targeted pytest collection is blocked in this environment because `langchain_core` is not installed (`ModuleNotFoundError`). No full test pass is claimed.
- Shopify browser/session restore testing has not been performed here.

## Port 3000

No service on port 3000 is defined in this project's `docker-compose.yaml`, `Dockerfile`, or Python backend. If port 3000 remains active on the user's computer, identify the owning PID/container and stop that separate process; this codebase cannot stop a process launched outside it.
