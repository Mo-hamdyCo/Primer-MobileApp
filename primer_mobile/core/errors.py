"""Stable, safe errors used by the mobile RPC API."""

from __future__ import annotations

import frappe
from frappe import _


def abort(code: str, message: str, *, http_status_code: int = 400, details: dict | None = None) -> None:
	frappe.local.response.http_status_code = http_status_code
	frappe.throw(_(message), exc=frappe.ValidationError, title=code)
