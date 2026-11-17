"""Mobile-session exchange endpoints; native Frappe login/2FA runs first."""

from __future__ import annotations

import frappe
from frappe import _

from primer_mobile.core.auth import (
	issue_session as create_mobile_session,
	revoke_current_session,
	rotate_refresh_session,
)


@frappe.whitelist(methods=["POST"])
def issue_session(device_id: str, platform: str = "ANDROID", app_version_code: int | None = None, device_name: str | None = None) -> dict:
	"""Exchange an already-authenticated native Frappe session for mobile tokens."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Complete the native login and two-factor challenge first."), frappe.AuthenticationError)
	return create_mobile_session(frappe.session.user, device_id, platform, app_version_code, device_name)


@frappe.whitelist(allow_guest=True, methods=["POST"])
def refresh(refresh_token: str, device_id: str) -> dict:
	return rotate_refresh_session(refresh_token, device_id)


@frappe.whitelist(methods=["POST"])
def logout() -> dict:
	revoke_current_session()
	return {"revoked": True}
