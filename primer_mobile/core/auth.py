"""Device-bound bearer and refresh-session support for the mobile API."""

from __future__ import annotations

import hashlib
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime


MOBILE_PREFIX = "/api/method/primer_mobile.api.v1."


def _digest(token: str) -> str:
	return hashlib.sha256(token.encode()).hexdigest()


def _bearer_token() -> str | None:
	authorization = frappe.get_request_header("Authorization") or ""
	if authorization.startswith("Bearer "):
		return authorization.removeprefix("Bearer ").strip()
	return None


def authenticate_mobile_bearer() -> None:
	"""Authenticate only our bearer tokens, never as a generic Frappe API key."""
	token = _bearer_token()
	if not token:
		return
	path = getattr(frappe.request, "path", "")
	if not path.startswith(MOBILE_PREFIX) or path.startswith(f"{MOBILE_PREFIX}admin."):
		frappe.throw(_("Mobile tokens cannot access this endpoint."), frappe.PermissionError)
	if path.endswith(("auth.issue_session", "auth.refresh")):
		return
	device_id = frappe.get_request_header("X-Device-Id")
	if not device_id:
		frappe.throw(_("X-Device-Id is required."), frappe.AuthenticationError)
	sessions = frappe.get_all(
		"Mobile Session",
		filters={"enabled": 1, "access_token_hash": _digest(token)},
		fields=["name", "user", "device", "access_expires_at"],
		limit_page_length=1,
	)
	if not sessions or get_datetime(sessions[0].access_expires_at) <= now_datetime():
		frappe.throw(_("Mobile session has expired."), frappe.AuthenticationError)
	session = sessions[0]
	device = frappe.db.get_value("Mobile Device", session.device, ["device_id", "user", "enabled"], as_dict=True)
	if not device or not cint(device.enabled) or device.device_id != device_id or device.user != session.user:
		frappe.throw(_("Mobile device is not active."), frappe.AuthenticationError)
	frappe.set_user(session.user)
	frappe.local.mobile_session = session
	frappe.db.set_value("Mobile Session", session.name, "last_used_at", now_datetime(), update_modified=False)


def issue_session(user: str, device_id: str, platform: str, app_version_code: int | None, device_name: str | None = None) -> dict[str, Any]:
	settings = frappe.get_single("Primers Mobile Settings")
	if not settings.enabled:
		frappe.throw(_("Mobile access is not enabled."), frappe.PermissionError)
	from primer_mobile.core.access import resolve_profile

	if not resolve_profile(user):
		frappe.throw(_("You do not have mobile access."), frappe.PermissionError)
	if not device_id or len(device_id) > 140:
		frappe.throw(_("A valid device identifier is required."), frappe.ValidationError)
	if platform not in {"ANDROID", "IOS"}:
		frappe.throw(_("Unsupported mobile platform."), frappe.ValidationError)
	device_name = (device_name or "")[:140]
	device = frappe.db.get_value("Mobile Device", {"device_id": device_id}, ["name", "user", "enabled"], as_dict=True)
	if device and device.user != user:
		frappe.throw(_("This device is already bound to another user."), frappe.PermissionError)
	if device and not cint(device.enabled):
		frappe.throw(_("This device has been revoked."), frappe.PermissionError)
	if not device:
		active = frappe.db.count("Mobile Device", {"user": user, "enabled": 1})
		if active >= cint(settings.max_active_devices_per_user):
			frappe.throw(_("Maximum active devices reached."), frappe.PermissionError)
		device_doc = frappe.get_doc({"doctype": "Mobile Device", "device_id": device_id, "user": user, "enabled": 1, "platform": platform, "app_version_code": app_version_code, "device_name": device_name, "last_seen_at": now_datetime()})
		device_doc.insert(ignore_permissions=True)
		target_device_name = device_doc.name
	else:
		target_device_name = device.get("name") if isinstance(device, dict) else device.name
		frappe.db.set_value("Mobile Device", target_device_name, {"app_version_code": app_version_code, "device_name": device_name, "last_seen_at": now_datetime()}, update_modified=False)
	access_token, refresh_token = frappe.generate_hash(length=64), frappe.generate_hash(length=64)
	access_expires = add_to_date(now_datetime(), minutes=cint(settings.access_token_ttl_minutes or 30))
	refresh_expires = add_to_date(now_datetime(), days=cint(settings.refresh_token_ttl_days or 30))
	frappe.get_doc({"doctype": "Mobile Session", "user": user, "device": target_device_name, "enabled": 1, "access_token_hash": _digest(access_token), "refresh_token_hash": _digest(refresh_token), "access_expires_at": access_expires, "refresh_expires_at": refresh_expires, "last_used_at": now_datetime()}).insert(ignore_permissions=True)
	return {"access_token": access_token, "refresh_token": refresh_token, "access_expires_at": access_expires, "refresh_expires_at": refresh_expires, "device_id": device_id}


def rotate_refresh_session(refresh_token: str, device_id: str) -> dict[str, Any]:
	if not refresh_token or not device_id:
		frappe.throw(_("Refresh token and device identifier are required."), frappe.AuthenticationError)
	sessions = frappe.get_all("Mobile Session", filters={"enabled": 1, "refresh_token_hash": _digest(refresh_token)}, fields=["name", "user", "device", "refresh_expires_at"], limit_page_length=1)
	if not sessions:
		frappe.throw(_("Invalid refresh token."), frappe.AuthenticationError)
	session = sessions[0]
	device = frappe.db.get_value("Mobile Device", session.device, ["device_id", "enabled"], as_dict=True)
	if not device or device.device_id != device_id or not cint(device.enabled) or get_datetime(session.refresh_expires_at) <= now_datetime():
		frappe.db.set_value("Mobile Session", session.name, "enabled", 0, update_modified=False)
		frappe.throw(_("Refresh session has expired."), frappe.AuthenticationError)
	# Rotation makes a replayed refresh token invalid immediately.
	frappe.db.set_value("Mobile Session", session.name, "enabled", 0, update_modified=False)
	return issue_session(session.user, device_id, frappe.db.get_value("Mobile Device", session.device, "platform"), frappe.db.get_value("Mobile Device", session.device, "app_version_code"), frappe.db.get_value("Mobile Device", session.device, "device_name"))


def revoke_current_session() -> None:
	session = getattr(frappe.local, "mobile_session", None)
	if session:
		frappe.db.set_value("Mobile Session", session.name, {"enabled": 0, "revoked_at": now_datetime()}, update_modified=False)
