"""Desk-only administration and diagnostic endpoints.

SECURITY REQUIREMENT:
These endpoints are NEVER exposed to mobile Bearer tokens.
They require an active Frappe session with System Manager or Mobile Admin role.
"""

from __future__ import annotations

import json
import frappe
from frappe import _


def _require_admin() -> None:
	"""Enforce that the caller has System Manager or Mobile Admin desk permissions."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.AuthenticationError)

	roles = set(frappe.get_roles())
	if "System Manager" not in roles and "Mobile Admin" not in roles:
		frappe.throw(_("Administrator permissions required."), frappe.PermissionError)


@frappe.whitelist(methods=["POST"])
def test_fcm_configuration() -> dict:
	"""Validate that Firebase credentials can be parsed and authenticated.

	Does not send a push, but verifies project ID and service account authentication.
	"""
	_require_admin()

	settings = frappe.get_single("Primers Mobile Settings")
	if not settings.firebase_project_id:
		return {"ok": False, "message": _("Firebase Project ID is not configured in Primers Mobile Settings.")}

	sa_json_raw = settings.get_password("firebase_service_account")
	if not sa_json_raw:
		return {"ok": False, "message": _("Firebase Service Account JSON is not configured.")}

	try:
		sa_info = json.loads(sa_json_raw)
	except (json.JSONDecodeError, TypeError):
		return {"ok": False, "message": _("Firebase Service Account JSON is invalid or malformed JSON.")}

	required_keys = {"type", "project_id", "private_key", "client_email"}
	missing = required_keys - set(sa_info.keys())
	if missing:
		return {
			"ok": False,
			"message": _("Service Account JSON is missing required fields: {0}").format(", ".join(missing)),
		}

	# Verify credential refresh using google.auth
	try:
		import google.auth.transport.requests
		import google.oauth2.service_account

		scopes = ["https://www.googleapis.com/auth/firebase.messaging"]
		credentials = google.oauth2.service_account.Credentials.from_service_account_info(
			sa_info, scopes=scopes
		)
		auth_req = google.auth.transport.requests.Request()
		credentials.refresh(auth_req)
		token_preview = credentials.token[:10] + "..." if credentials.token else "OK"
		return {
			"ok": True,
			"message": _("Firebase authentication successful. Project: {0}, Client Email: {1}").format(
				sa_info.get("project_id"), sa_info.get("client_email")
			),
		}
	except Exception as exc:
		return {
			"ok": False,
			"message": _("Firebase authentication failed: {0}").format(str(exc)),
		}


@frappe.whitelist(methods=["POST"])
def send_test_push(device_name: str | None = None, user: str | None = None) -> dict:
	"""Send an immediate test push notification to a device or all devices of a user.

	Used from Desk by administrators to verify device push delivery.
	"""
	_require_admin()

	from primer_mobile.notifications.builder import send_notification

	target_user = user
	if not target_user and device_name:
		target_user = frappe.db.get_value("Mobile Device", device_name, "user")

	if not target_user:
		frappe.throw(_("Target User or Device Name is required."), frappe.ValidationError)

	notif_name = send_notification(
		user=target_user,
		category_key="system",
		notification_type="test",
		title_en="Test Push Notification",
		title_ar="إشعار اختباري تجريبي",
		body_en=f"This is a test notification from Desk sent at {frappe.utils.now()}.",
		body_ar=f"هذا إشعار تجريبي من لوحة التحكم أُرسل في {frappe.utils.now()}.",
		route="notifications",
		enqueue=False,  # Run synchronously so we can report result immediately
	)

	# Fetch recent push log for this notification
	logs = frappe.get_all(
		"Mobile Push Log",
		filters={"notification": notif_name},
		fields=["name", "device", "status", "error_code", "provider_message_id"],
	)

	return {
		"ok": True,
		"notification": notif_name,
		"logs": logs,
		"message": _("Test notification dispatched to {0} device(s).").format(len(logs)),
	}


@frappe.whitelist(methods=["GET", "POST"])
def preview_bootstrap(user: str | None = None, employee: str | None = None) -> dict:
	"""Preview the effective bootstrap payload for a specified User or Employee.

	Enables administrators to test and verify profile resolution, menu, and
	permissions without having to log in on a physical device.
	"""
	_require_admin()

	target_user = user
	if not target_user and employee:
		target_user = frappe.db.get_value("Employee", employee, "user_id")

	if not target_user:
		frappe.throw(_("User or Employee is required to preview bootstrap."), frappe.ValidationError)

	from primer_mobile.core.access import bootstrap as resolve_bootstrap

	data = resolve_bootstrap(target_user)
	settings = frappe.get_single("Primers Mobile Settings")
	data["config_version"] = frappe.utils.cint(settings.config_version)
	data["branding"] = {
		"app_name": settings.app_display_name,
		"accent_color": settings.accent_color,
		"support_email": settings.support_email,
		"support_phone": settings.support_phone,
	}
	return data
