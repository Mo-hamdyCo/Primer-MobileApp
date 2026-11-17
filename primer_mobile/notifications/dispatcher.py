"""Push notification dispatcher — decides whether to send, then delegates to FCM.

Architecture:
  dispatcher.dispatch_push(notification_name, device_name)
      ↓ checks category, user preference, quiet hours, dedup
      ↓ calls fcm.send_data_message(token, payload)
      ↓ writes Mobile Push Log
      ↓ on InvalidTokenError → deactivates device FCM token
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, time

import frappe
from frappe.utils import add_to_date, cint, get_datetime, get_system_timezone, now_datetime

logger = logging.getLogger(__name__)

# Maximum push attempts before giving up
MAX_ATTEMPTS = 4
# Backoff multiplier in minutes: attempt 1→2min, 2→8min, 3→32min
_BACKOFF_BASE = 2
_BACKOFF_FACTOR = 4


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def dispatch_push(notification_name: str, device_name: str) -> str:
	"""Evaluate preferences and send one push notification to one device.

	Returns the final status: 'SENT', 'SKIPPED', or 'FAILED'.
	Always writes a Mobile Push Log entry.
	Must be called AFTER the source transaction has committed.
	"""
	try:
		notif = frappe.get_doc("Mobile Notification", notification_name)
		device = frappe.get_doc("Mobile Device", device_name)
	except frappe.DoesNotExistError:
		logger.warning("dispatch_push: missing notification %s or device %s", notification_name, device_name)
		return "FAILED"

	# --- Gate: device must be active and belong to the notification's user ---
	if not cint(device.enabled) or device.user != notif.user:
		return _write_log(notif, device, "SKIPPED", "DEVICE_INACTIVE_OR_MISMATCH")

	# --- Gate: FCM token must exist ---
	raw_token = _get_fcm_token(device)
	if not raw_token:
		return _write_log(notif, device, "SKIPPED", "NO_FCM_TOKEN")

	# --- Resolve category ---
	category = frappe.get_doc("Mobile Notification Category", notif.category) if notif.category else None

	# --- Gate: deduplication ---
	dedup_key = _build_dedup_key(device.name, notif)
	if _already_sent(dedup_key):
		return _write_log(notif, device, "SKIPPED", "DUPLICATE", dedup_key=dedup_key)

	# --- Gate: user preference (mandatory categories always pass) ---
	if category and not _user_has_enabled(notif.user, category):
		return _write_log(notif, device, "SKIPPED", "PREFERENCE_DISABLED", dedup_key=dedup_key)

	# --- Gate: quiet hours (unless bypass_quiet_hours) ---
	if category and not cint(category.bypass_quiet_hours):
		if _in_quiet_hours(notif.user, device.name):
			return _write_log(notif, device, "SKIPPED", "QUIET_HOURS", dedup_key=dedup_key)

	# --- Build payload ---
	high_priority = (category.importance == "high") if category else False
	payload = _build_payload(notif, category)

	# --- Send ---
	log_name = _write_log(notif, device, "PENDING", dedup_key=dedup_key)
	return _attempt_send(log_name, raw_token, payload, high_priority=high_priority)


def retry_pending_pushes() -> None:
	"""Called by the scheduler; retries FAILED logs that are past next_retry_at."""
	now = now_datetime()
	pending = frappe.get_all(
		"Mobile Push Log",
		filters={"status": "FAILED", "attempt_count": ["<", MAX_ATTEMPTS], "next_retry_at": ["<=", now]},
		fields=["name", "notification", "device"],
		limit_page_length=200,
	)
	for row in pending:
		try:
			_retry_log(row.name, row.notification, row.device)
		except Exception:
			frappe.log_error(title=f"Push retry failed for log {row.name}")


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


def _build_payload(notif, category) -> dict[str, str]:
	"""Build an FCM data-only payload. All values must be strings.
	Never include salary amounts, tokens, or sensitive data.
	"""
	lang = frappe.local.lang or "en"
	title = notif.title_ar if lang == "ar" else notif.title_en
	body = notif.body_ar if lang == "ar" else notif.body_en

	payload: dict[str, str] = {
		"type": notif.notification_type or "system",
		"category": category.category_key if category else "",
		"title_ar": notif.title_ar or "",
		"title_en": notif.title_en or "",
		"body_ar": notif.body_ar or "",
		"body_en": notif.body_en or "",
		"ts": now_datetime().isoformat(),
		"notification_name": notif.name,
	}

	# Source identity: always (doctype, name) pair to avoid ambiguity
	if notif.reference_doctype and notif.reference_name:
		payload["doctype"] = notif.reference_doctype
		payload["docname"] = notif.reference_name

	if notif.route:
		payload["route"] = notif.route

	# Quick actions: only for approve_reject categories
	if category and category.action_set == "approve_reject":
		payload["actions"] = "approve,reject"

	# Silent flags
	if notif.notification_type == "config_changed":
		payload["config_changed"] = "1"
		payload["silent"] = "1"

	if notif.notification_type == "session_revoked":
		payload["session_revoked"] = "1"

	return payload


# ---------------------------------------------------------------------------
# Preference and quiet-hours checks
# ---------------------------------------------------------------------------


def _user_has_enabled(user: str, category) -> bool:
	"""Returns True if the user has this category enabled (or category is mandatory)."""
	if cint(category.mandatory):
		return True
	pref = frappe.db.get_value(
		"Mobile Notification Preference",
		{"user": user, "category": category.name},
		"enabled",
		as_dict=False,
	)
	if pref is None:
		# No explicit preference → use the category default
		return bool(cint(category.default_enabled))
	return bool(cint(pref))


def _in_quiet_hours(user: str, device_name: str) -> bool:
	"""Returns True if the current server time falls within the user's quiet hours."""
	# Collect all active quiet-hours preferences for this user
	prefs = frappe.get_all(
		"Mobile Notification Preference",
		filters={"user": user, "quiet_hours_enabled": 1},
		fields=["quiet_hours_start", "quiet_hours_end", "timezone"],
	)
	if not prefs:
		return False

	now_utc = now_datetime()
	for pref in prefs:
		if not pref.quiet_hours_start or not pref.quiet_hours_end:
			continue
		# Use user's timezone if set, else site timezone
		tz_name = pref.timezone or get_system_timezone()
		try:
			import pytz

			tz = pytz.timezone(tz_name)
			local_now = now_utc.astimezone(tz)
		except Exception:
			local_now = now_utc

		current_time = local_now.time().replace(second=0, microsecond=0)
		start = _parse_time(pref.quiet_hours_start)
		end = _parse_time(pref.quiet_hours_end)
		if start is None or end is None:
			continue
		# Handle midnight-crossing intervals (e.g. 22:00 → 07:00)
		if start <= end:
			if start <= current_time <= end:
				return True
		else:  # crosses midnight
			if current_time >= start or current_time <= end:
				return True
	return False


def _parse_time(value) -> time | None:
	"""Parse 'HH:MM:SS' or 'HH:MM' string to a time object."""
	if not value:
		return None
	try:
		parts = str(value).split(":")
		return time(int(parts[0]), int(parts[1]))
	except (ValueError, IndexError):
		return None


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _build_dedup_key(device_name: str, notif) -> str:
	"""SHA-256 of (device, category, source_doctype, source_name, notification_type)."""
	raw = "|".join(
		[
			device_name,
			str(notif.category or ""),
			str(notif.reference_doctype or ""),
			str(notif.reference_name or ""),
			str(notif.notification_type or ""),
		]
	)
	return hashlib.sha256(raw.encode()).hexdigest()


def _already_sent(dedup_key: str) -> bool:
	"""True if a SENT Push Log already exists for this dedup key."""
	return bool(
		frappe.db.exists("Mobile Push Log", {"dedup_key": dedup_key, "status": "SENT"})
	)


# ---------------------------------------------------------------------------
# Sending helpers
# ---------------------------------------------------------------------------


def _attempt_send(log_name: str, fcm_token: str, payload: dict, *, high_priority: bool) -> str:
	"""Call FCM, update Push Log, return final status string."""
	from primer_mobile.notifications.fcm import FCMError, InvalidTokenError, send_data_message

	attempt_count = (frappe.db.get_value("Mobile Push Log", log_name, "attempt_count") or 0) + 1
	try:
		message_id = send_data_message(fcm_token, payload, high_priority=high_priority)
		frappe.db.set_value(
			"Mobile Push Log",
			log_name,
			{
				"status": "SENT",
				"attempt_count": attempt_count,
				"provider_message_id": (message_id or "")[:255],
				"sent_at": now_datetime(),
				"error_code": None,
				"next_retry_at": None,
			},
			update_modified=False,
		)
		return "SENT"
	except InvalidTokenError:
		# Deactivate the stale token on the device
		_deactivate_fcm_token(fcm_token)
		frappe.db.set_value(
			"Mobile Push Log",
			log_name,
			{"status": "FAILED", "attempt_count": attempt_count, "error_code": "INVALID_TOKEN"},
			update_modified=False,
		)
		return "FAILED"
	except FCMError as exc:
		next_retry = add_to_date(now_datetime(), minutes=_backoff_minutes(attempt_count)) if exc.retryable else None
		frappe.db.set_value(
			"Mobile Push Log",
			log_name,
			{
				"status": "FAILED",
				"attempt_count": attempt_count,
				"error_code": exc.code[:100],
				"next_retry_at": next_retry,
			},
			update_modified=False,
		)
		return "FAILED"
	except Exception:
		frappe.log_error(title=f"Unexpected FCM error for push log {log_name}")
		frappe.db.set_value(
			"Mobile Push Log",
			log_name,
			{"status": "FAILED", "attempt_count": attempt_count, "error_code": "UNEXPECTED"},
			update_modified=False,
		)
		return "FAILED"


def _retry_log(log_name: str, notification_name: str, device_name: str) -> None:
	try:
		notif = frappe.get_doc("Mobile Notification", notification_name)
		device = frappe.get_doc("Mobile Device", device_name)
	except frappe.DoesNotExistError:
		frappe.db.set_value("Mobile Push Log", log_name, {"status": "FAILED", "error_code": "DOC_MISSING"})
		return

	raw_token = _get_fcm_token(device)
	if not raw_token or not cint(device.enabled):
		frappe.db.set_value("Mobile Push Log", log_name, {"status": "SKIPPED", "error_code": "NO_TOKEN_OR_DISABLED"})
		return

	category = frappe.get_doc("Mobile Notification Category", notif.category) if notif.category else None
	high_priority = (category.importance == "high") if category else False
	payload = _build_payload(notif, category)
	_attempt_send(log_name, raw_token, payload, high_priority=high_priority)


def _backoff_minutes(attempt: int) -> int:
	"""Exponential backoff: 2, 8, 32, 128 minutes."""
	return _BACKOFF_BASE * (_BACKOFF_FACTOR ** (attempt - 1))


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _get_fcm_token(device) -> str | None:
	"""Retrieve the FCM token from the Password field. Returns None if unset."""
	try:
		token = frappe.get_doc("Mobile Device", device.name).get_password("fcm_token")
		return token if token else None
	except Exception:
		return None


def _deactivate_fcm_token(token: str) -> None:
	"""Clear the FCM token on any device that holds this exact token (by hash)."""
	import hashlib

	token_hash = hashlib.sha256(token.encode()).hexdigest()
	devices = frappe.get_all(
		"Mobile Device",
		filters={"fcm_token_hash": token_hash, "enabled": 1},
		pluck="name",
	)
	for device_name in devices:
		try:
			dev_doc = frappe.get_doc("Mobile Device", device_name)
			# Clear the stored token; device remains active for other operations
			dev_doc.set_password("fcm_token", "")
			frappe.db.set_value(
				"Mobile Device",
				device_name,
				{"fcm_token_hash": ""},
				update_modified=False,
			)
		except Exception:
			frappe.log_error(title=f"Failed to deactivate FCM token on device {device_name}")


# ---------------------------------------------------------------------------
# Push Log writer
# ---------------------------------------------------------------------------


def _write_log(
	notif,
	device,
	status: str,
	error_code: str | None = None,
	dedup_key: str | None = None,
) -> str:
	"""Insert a Mobile Push Log record and return its name."""
	log = frappe.get_doc(
		{
			"doctype": "Mobile Push Log",
			"notification": notif.name,
			"device": device.name,
			"user": notif.user,
			"category": notif.category,
			"notification_type": notif.notification_type,
			"source_doctype": notif.reference_doctype,
			"source_name": notif.reference_name,
			"dedup_key": dedup_key or "",
			"status": status,
			"error_code": (error_code or "")[:100],
			"attempt_count": 0,
			"sent_at": now_datetime() if status == "SENT" else None,
		}
	)
	log.insert(ignore_permissions=True)
	return log.name
