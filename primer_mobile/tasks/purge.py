"""Scheduled maintenance tasks — session expiry, push retry, data purge."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, now_datetime


def expire_mobile_sessions() -> None:
	"""Disable sessions whose refresh token has expired. Runs hourly."""
	frappe.db.set_value(
		"Mobile Session",
		{"enabled": 1, "refresh_expires_at": ["<", now_datetime()]},
		"enabled",
		0,
		update_modified=False,
	)


def retry_failed_pushes() -> None:
	"""Retry FAILED push log entries that are past their next_retry_at. Runs every 15 min."""
	try:
		from primer_mobile.notifications.dispatcher import retry_pending_pushes
		retry_pending_pushes()
	except Exception:
		frappe.log_error(title="Primers Mobile: push retry job failed")


def purge_expired_mobile_data() -> None:
	"""Delete old operational records per configured retention settings. Runs daily."""
	settings = frappe.get_single("Primers Mobile Settings")
	now = now_datetime()

	# Sessions
	retention_sessions = int(settings.retention_days_sessions or 90)
	frappe.db.delete("Mobile Session", {"modified": ["<", add_days(now, -retention_sessions)]})

	# Check-in Attempts
	retention_attempts = int(settings.retention_days_checkin_attempts or 90)
	frappe.db.delete(
		"Mobile Checkin Attempt",
		{"modified": ["<", add_days(now, -retention_attempts)]},
	)

	# Push Logs (use same session retention or a sensible default)
	retention_push = int(getattr(settings, "retention_days_push_logs", None) or retention_sessions)
	frappe.db.delete(
		"Mobile Push Log",
		{"status": ["in", ["SENT", "SKIPPED", "FAILED"]], "modified": ["<", add_days(now, -retention_push)]},
	)

	# Notifications older than retention period
	frappe.db.delete(
		"Mobile Notification",
		{"modified": ["<", add_days(now, -retention_push)]},
	)
