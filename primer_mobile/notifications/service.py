"""Notification service layer — storage, preference decisions, inbox management.

No FCM credentials or provider secrets pass through this module.
All user-ownership checks are enforced before any read or mutation.
"""

from __future__ import annotations

import hashlib

import frappe
from frappe import _
from frappe.utils import cint, get_system_timezone, now_datetime


# ---------------------------------------------------------------------------
# FCM token registration
# ---------------------------------------------------------------------------


def register_fcm_token(user: str, device_id: str, token: str) -> dict:
	"""Store the FCM registration token on the user's device.

	The raw token is stored in an encrypted Password field only.
	A SHA-256 hash is stored separately for deduplication lookups.
	The token is never returned through any API response.
	"""
	if not token or not isinstance(token, str) or len(token) > 4096:
		frappe.throw(_("Invalid FCM token."), frappe.ValidationError)

	device = _owned_device(user, device_id)
	device_doc = frappe.get_doc("Mobile Device", device.name)
	# Store encrypted
	device_doc.set_password("fcm_token", token)
	device_doc.save(ignore_permissions=True)
	# Store hash for dedup/search (not the raw token)
	frappe.db.set_value(
		"Mobile Device",
		device.name,
		{
			"fcm_token_hash": hashlib.sha256(token.encode()).hexdigest(),
			"last_seen_at": now_datetime(),
		},
		update_modified=False,
	)
	return {"registered": True}


def unregister_fcm_token(user: str, device_id: str) -> dict:
	"""Clear the FCM token for this device (e.g., user logs out)."""
	device = _owned_device(user, device_id)
	device_doc = frappe.get_doc("Mobile Device", device.name)
	device_doc.set_password("fcm_token", "")
	device_doc.save(ignore_permissions=True)
	frappe.db.set_value(
		"Mobile Device",
		device.name,
		{"fcm_token_hash": ""},
		update_modified=False,
	)
	return {"unregistered": True}


# ---------------------------------------------------------------------------
# Notification preferences (versioned, conflict-safe)
# ---------------------------------------------------------------------------


def get_notification_prefs(user: str) -> dict:
	"""Return current notification preferences with version for optimistic locking."""
	categories = frappe.get_all(
		"Mobile Notification Category",
		filters={"enabled": 1},
		fields=[
			"name", "category_key", "category_name", "label_en", "label_ar",
			"mandatory", "default_enabled", "user_configurable",
			"importance", "bypass_quiet_hours", "action_set",
		],
		order_by="category_name",
	)
	prefs_map = {
		item.category: item
		for item in frappe.get_all(
			"Mobile Notification Preference",
			filters={"user": user},
			fields=["name", "category", "enabled", "quiet_hours_enabled",
			        "quiet_hours_start", "quiet_hours_end", "timezone", "pref_version"],
		)
	}

	# Compute a deterministic version: sum of individual pref_version values
	version = sum(cint(p.get("pref_version", 0)) for p in prefs_map.values()) or 1

	categories_out = []
	quiet_hours_pref = None
	for category in categories:
		pref = prefs_map.get(category.name)
		if cint(category.mandatory):
			enabled = True
		else:
			enabled = bool(cint(pref.enabled if pref else category.default_enabled))

		categories_out.append(
			{
				"key": category.category_key,
				"label_en": category.label_en or category.category_name,
				"label_ar": category.label_ar or category.category_name,
				"mandatory": bool(cint(category.mandatory)),
				"default_enabled": bool(cint(category.default_enabled)),
				"user_configurable": bool(cint(category.user_configurable)),
				"importance": category.importance or "default",
				"bypass_quiet_hours": bool(cint(category.bypass_quiet_hours)),
				"action_set": category.action_set or "none",
				"enabled": enabled,
			}
		)
		if pref and not quiet_hours_pref and cint(pref.quiet_hours_enabled):
			quiet_hours_pref = pref

	return {
		"version": version,
		"categories": {c["key"]: c["enabled"] for c in categories_out},
		"categories_detail": categories_out,
		"quiet_hours": {
			"enabled": bool(quiet_hours_pref),
			"start": str(quiet_hours_pref.quiet_hours_start) if quiet_hours_pref else "22:00:00",
			"end": str(quiet_hours_pref.quiet_hours_end) if quiet_hours_pref else "07:00:00",
			"timezone": quiet_hours_pref.timezone if quiet_hours_pref else get_system_timezone(),
		},
	}


def update_notification_prefs(
	user: str,
	version: int,
	categories: dict,
	quiet_hours: dict,
) -> dict:
	"""Update preferences with optimistic locking via version.

	If the client's version doesn't match the current server version,
	return CONFLICT with the current state so the client can refresh.
	Mandatory categories cannot be disabled.
	"""
	current = get_notification_prefs(user)
	current_version = current["version"]

	if cint(version) != current_version:
		# Return CONFLICT with current data so the client can refresh
		frappe.local.response.http_status_code = 409
		return {
			"ok": False,
			"error": {"code": "CONFLICT", "message": _("Preferences were updated by another client. Please refresh.")},
			"data": current,
		}

	# Apply category preferences
	for cat_key, enabled in (categories or {}).items():
		category = frappe.db.get_value(
			"Mobile Notification Category",
			{"category_key": cat_key, "enabled": 1},
			["name", "mandatory"],
			as_dict=True,
		)
		if not category:
			continue
		# Mandatory: silently ignore attempt to disable
		if cint(category.mandatory) and not cint(enabled):
			continue
		_upsert_pref(user, category.name, enabled=cint(enabled))

	# Apply quiet hours: apply to all non-mandatory categories
	qh = quiet_hours or {}
	qh_enabled = cint(qh.get("enabled", 0))
	qh_start = qh.get("start", "22:00:00")
	qh_end = qh.get("end", "07:00:00")
	qh_tz = (qh.get("timezone") or get_system_timezone())[:100]

	# Validate time format
	_validate_time_string(qh_start)
	_validate_time_string(qh_end)

	# Update quiet hours on all existing prefs for this user
	all_prefs = frappe.get_all(
		"Mobile Notification Preference",
		filters={"user": user},
		pluck="name",
	)
	for pref_name in all_prefs:
		frappe.db.set_value(
			"Mobile Notification Preference",
			pref_name,
			{
				"quiet_hours_enabled": qh_enabled,
				"quiet_hours_start": qh_start,
				"quiet_hours_end": qh_end,
				"timezone": qh_tz,
				"pref_version": (frappe.db.get_value("Mobile Notification Preference", pref_name, "pref_version") or 0) + 1,
			},
			update_modified=False,
		)

	return {"ok": True, "data": get_notification_prefs(user)}


def _upsert_pref(user: str, category_name: str, *, enabled: int) -> None:
	name = frappe.db.exists("Mobile Notification Preference", {"user": user, "category": category_name})
	if name:
		current_ver = frappe.db.get_value("Mobile Notification Preference", name, "pref_version") or 0
		frappe.db.set_value(
			"Mobile Notification Preference",
			name,
			{"enabled": enabled, "pref_version": current_ver + 1},
			update_modified=False,
		)
	else:
		frappe.get_doc(
			{
				"doctype": "Mobile Notification Preference",
				"user": user,
				"category": category_name,
				"enabled": enabled,
				"pref_version": 1,
			}
		).insert(ignore_permissions=True)


def _validate_time_string(value: str) -> None:
	"""Raise ValidationError for a malformed HH:MM or HH:MM:SS string."""
	try:
		parts = str(value).split(":")
		h, m = int(parts[0]), int(parts[1])
		if not (0 <= h <= 23 and 0 <= m <= 59):
			raise ValueError
	except (ValueError, IndexError):
		frappe.throw(_(f"Invalid time format: '{value}'. Expected HH:MM or HH:MM:SS."), frappe.ValidationError)


# ---------------------------------------------------------------------------
# Legacy preference accessor (kept for backwards compatibility)
# ---------------------------------------------------------------------------


def list_preferences(user: str) -> list[dict]:
	"""Legacy endpoint: flat list of category preferences."""
	prefs = get_notification_prefs(user)
	return prefs["categories_detail"]


def set_preference(
	user: str,
	category_key: str,
	enabled: int,
	quiet_hours_enabled: int = 0,
	quiet_hours_start=None,
	quiet_hours_end=None,
	timezone=None,
) -> dict:
	"""Legacy single-category update (no version checking)."""
	category = frappe.db.get_value(
		"Mobile Notification Category",
		{"category_key": category_key, "enabled": 1},
		["name", "mandatory"],
		as_dict=True,
	)
	if not category:
		frappe.throw(_("Unknown notification category."), frappe.ValidationError)
	if cint(category.mandatory) and not cint(enabled):
		frappe.throw(_("This notification category is mandatory and cannot be disabled."), frappe.PermissionError)

	_upsert_pref(user, category.name, enabled=cint(enabled))
	# Update quiet hours if provided
	if quiet_hours_start or quiet_hours_end:
		name = frappe.db.exists("Mobile Notification Preference", {"user": user, "category": category.name})
		if name:
			frappe.db.set_value(
				"Mobile Notification Preference",
				name,
				{
					"quiet_hours_enabled": cint(quiet_hours_enabled),
					"quiet_hours_start": quiet_hours_start,
					"quiet_hours_end": quiet_hours_end,
					"timezone": timezone,
				},
				update_modified=False,
			)
	return {"updated": True}


# ---------------------------------------------------------------------------
# Notification inbox
# ---------------------------------------------------------------------------


def list_notifications(user: str, page: int = 1, page_size: int = 20, unread_only: bool = False) -> dict:
	"""Return paginated notifications owned by the requesting user only."""
	page = max(cint(page), 1)
	page_size = min(max(cint(page_size), 1), 50)
	filters = {"user": user}
	if unread_only:
		filters["read_at"] = ["is", "not set"]

	rows = frappe.get_list(
		"Mobile Notification",
		filters=filters,
		fields=[
			"name", "category", "title_ar", "title_en", "body_ar", "body_en",
			"notification_type", "reference_doctype", "reference_name",
			"route", "read_at", "sent_at", "creation",
		],
		order_by="creation desc",
		start=(page - 1) * page_size,
		page_length=page_size + 1,
	)
	return {
		"items": rows[:page_size],
		"page": page,
		"page_size": page_size,
		"has_more": len(rows) > page_size,
	}


def mark_read(user: str, notification_name: str) -> dict:
	"""Mark a single notification as read. Verifies ownership."""
	_assert_owns_notification(user, notification_name)
	if not frappe.db.get_value("Mobile Notification", notification_name, "read_at"):
		frappe.db.set_value(
			"Mobile Notification", notification_name, "read_at", now_datetime(), update_modified=False
		)
	return {"read": True}


def mark_all_read(user: str) -> dict:
	"""Mark all unread notifications for this user as read."""
	unread = frappe.get_all(
		"Mobile Notification",
		filters={"user": user, "read_at": ["is", "not set"]},
		pluck="name",
		limit_page_length=1000,
	)
	now = now_datetime()
	for name in unread:
		frappe.db.set_value("Mobile Notification", name, "read_at", now, update_modified=False)
	return {"updated": len(unread)}


def unread_count(user: str) -> dict:
	"""Return the count of unread notifications for this user."""
	count = frappe.db.count("Mobile Notification", filters={"user": user, "read_at": ["is", "not set"]})
	return {"count": cint(count)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _owned_device(user: str, device_id: str):
	"""Return the Mobile Device doc for this user+device_id. Raises if not found."""
	device = frappe.db.get_value(
		"Mobile Device",
		{"device_id": device_id, "user": user, "enabled": 1},
		["name"],
		as_dict=True,
	)
	if not device:
		frappe.throw(
			_("Active device not found for the current user."),
			frappe.AuthenticationError,
		)
	return device


def _assert_owns_notification(user: str, notification_name: str) -> None:
	"""Raise DoesNotExistError if the user does not own this notification."""
	if not frappe.db.exists("Mobile Notification", {"name": notification_name, "user": user}):
		frappe.throw(_("Notification not found."), frappe.DoesNotExistError)
