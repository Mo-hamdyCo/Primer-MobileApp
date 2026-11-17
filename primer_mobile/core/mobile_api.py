from __future__ import annotations

import frappe
from frappe import _


def require_mobile_session() -> None:
	if not getattr(frappe.local, "mobile_session", None):
		frappe.throw(_("A valid mobile bearer token is required."), frappe.AuthenticationError)
