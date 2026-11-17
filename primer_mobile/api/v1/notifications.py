"""Notification inbox and preference management endpoints.

All endpoints enforce user ownership — no cross-user reads or writes.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from primer_mobile.core.mobile_api import require_mobile_session
from primer_mobile.notifications.service import (
	get_notification_prefs,
	list_notifications,
	list_preferences,
	mark_all_read,
	mark_read,
	set_preference,
	unread_count,
	update_notification_prefs,
)


# ---------------------------------------------------------------------------
# Preference endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["GET"])
def get_prefs() -> dict:
	"""Return full notification preferences with version.

	Response:
	{
	  "version": 3,
	  "categories": { "approvals": true, "leave_status": false, ... },
	  "categories_detail": [ { "key", "label_en", "label_ar", "mandatory",
	                            "default_enabled", "user_configurable",
	                            "importance", "bypass_quiet_hours",
	                            "action_set", "enabled" }, ... ],
	  "quiet_hours": { "enabled": true, "start": "22:00:00", "end": "07:00:00",
	                   "timezone": "Africa/Cairo" }
	}
	"""
	require_mobile_session()
	return get_notification_prefs(frappe.session.user)


@frappe.whitelist(methods=["POST"])
def update_prefs(version: int, categories: dict | None = None, quiet_hours: dict | None = None) -> dict:
	"""Update notification preferences with optimistic locking.

	Request body:
	{
	  "version": 3,
	  "categories": { "approvals": true, "leave_status": false },
	  "quiet_hours": { "enabled": true, "start": "22:00:00", "end": "07:00:00",
	                   "timezone": "Africa/Cairo" }
	}

	On conflict (version mismatch):
	  HTTP 409 + { "ok": false, "error": { "code": "CONFLICT" }, "data": <current_prefs> }

	On success:
	  { "ok": true, "data": <updated_prefs> }
	"""
	require_mobile_session()
	return update_notification_prefs(
		frappe.session.user,
		version=cint(version),
		categories=categories or {},
		quiet_hours=quiet_hours or {},
	)


# Legacy single-category update (kept for compatibility)
@frappe.whitelist(methods=["POST"])
def update_preference(
	category: str,
	enabled: int,
	quiet_hours_enabled: int = 0,
	quiet_hours_start=None,
	quiet_hours_end=None,
	timezone=None,
) -> dict:
	"""Legacy: update a single category preference without version checking."""
	require_mobile_session()
	return set_preference(
		frappe.session.user,
		category,
		enabled,
		quiet_hours_enabled,
		quiet_hours_start,
		quiet_hours_end,
		timezone,
	)


@frappe.whitelist(methods=["GET"])
def preferences() -> list[dict]:
	"""Legacy: flat list of category preferences."""
	require_mobile_session()
	return list_preferences(frappe.session.user)


# ---------------------------------------------------------------------------
# Inbox endpoints
# ---------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def list(page: int = 1, page_size: int = 20, unread_only: int = 0) -> dict:
	"""Return a paginated notification inbox for the authenticated user.

	Request body: { "page": 1, "page_size": 20, "unread_only": 0 }

	Response:
	{
	  "items": [ { "name", "category", "title_ar", "title_en", "body_ar",
	               "body_en", "notification_type", "reference_doctype",
	               "reference_name", "route", "read_at", "sent_at" }, ... ],
	  "page": 1,
	  "page_size": 20,
	  "has_more": false
	}
	"""
	require_mobile_session()
	return list_notifications(
		frappe.session.user,
		page=cint(page),
		page_size=cint(page_size),
		unread_only=bool(cint(unread_only)),
	)


@frappe.whitelist(methods=["POST"])
def mark_as_read(names: list | None = None) -> dict:
	"""Mark one or more notifications as read. Only the owner can mark.

	Request body: { "names": ["NOTIF-00001", "NOTIF-00002"] }
	Response: { "updated": 2 }
	"""
	require_mobile_session()
	if not names or not isinstance(names, list):
		frappe.throw(_("'names' must be a non-empty list of notification names."), frappe.ValidationError)
	updated = 0
	for name in names:
		if not isinstance(name, str) or not name.strip():
			continue
		try:
			mark_read(frappe.session.user, name.strip())
			updated += 1
		except frappe.DoesNotExistError:
			pass  # Skip notifications not belonging to this user
	return {"updated": updated}


@frappe.whitelist(methods=["POST"])
def mark_all_read_endpoint() -> dict:
	"""Mark all unread notifications as read for the authenticated user.

	Response: { "updated": <count> }
	"""
	require_mobile_session()
	return mark_all_read(frappe.session.user)


@frappe.whitelist(methods=["GET"])
def unread_count_endpoint() -> dict:
	"""Return the count of unread notifications.

	Response: { "count": 5 }
	"""
	require_mobile_session()
	return unread_count(frappe.session.user)
