"""Device management endpoints — FCM token registration, unregistration."""

from __future__ import annotations

import frappe
from frappe import _

from primer_mobile.core.mobile_api import require_mobile_session
from primer_mobile.notifications.service import register_fcm_token, unregister_fcm_token


@frappe.whitelist(methods=["POST"])
def register_push_token(token: str) -> dict:
	"""Register or update the FCM push token for the current device.

	The raw token is stored encrypted server-side and never returned.

	Request body: { "token": "<FCM registration token>" }
	Response: { "registered": true }
	"""
	require_mobile_session()
	device_id = frappe.get_request_header("X-Device-Id")
	if not device_id:
		frappe.local.response.http_status_code = 400
		frappe.throw(_("X-Device-Id header is required."), frappe.ValidationError)
	return register_fcm_token(frappe.session.user, device_id, token)


@frappe.whitelist(methods=["POST"])
def unregister_push_token() -> dict:
	"""Clear the FCM token for this device (logout/token reset).

	Response: { "unregistered": true }
	"""
	require_mobile_session()
	device_id = frappe.get_request_header("X-Device-Id")
	if not device_id:
		frappe.local.response.http_status_code = 400
		frappe.throw(_("X-Device-Id header is required."), frappe.ValidationError)
	return unregister_fcm_token(frappe.session.user, device_id)


# Kept for backwards compatibility
@frappe.whitelist(methods=["POST"])
def register_fcm(token: str) -> dict:
	"""Deprecated alias for register_push_token."""
	require_mobile_session()
	return register_push_token(token)
