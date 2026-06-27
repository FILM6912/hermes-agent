"""Dashboard service — wraps api.dashboard_probe for FastAPI v1 routes."""

from __future__ import annotations

from typing import Any

from app.domain import dashboard_probe


class DashboardService:
    def get_status(self, *, config_data: dict | None = None) -> dict[str, Any]:
        return dashboard_probe.get_dashboard_status(config_data)

    def get_config(self, *, config_data: dict | None = None) -> dict[str, Any]:
        return dashboard_probe.get_dashboard_config(config_data)

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dashboard_probe.save_dashboard_config(payload)
