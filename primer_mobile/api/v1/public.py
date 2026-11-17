"""Guest endpoints with no access to personal or configuration secrets."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint


@frappe.whitelist(allow_guest=True, methods=["GET"])
def handshake(app_version_code: int | None = None) -> dict:
	settings = frappe.get_single("Primers Mobile Settings")
	version = cint(app_version_code)
	status = "OK"
	if not settings.enabled:
		status = "DISABLED"
	elif settings.maintenance_mode:
		status = "MAINTENANCE"
	elif version and version < cint(settings.min_version_code):
		status = "UPDATE_REQUIRED"
	return {"api_version": cint(settings.api_version), "status": status, "min_version_code": cint(settings.min_version_code), "latest_version_code": cint(settings.latest_version_code), "latest_version_name": settings.latest_version_name, "force_update": cint(settings.force_update), "message": settings.maintenance_message_ar if frappe.local.lang == "ar" else settings.maintenance_message_en}
