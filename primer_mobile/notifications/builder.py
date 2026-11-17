"""High-level notification builder and enqueue helper.

Usage:
    from primer_mobile.notifications.builder import send_notification

    send_notification(
        user="user@example.com",
        category_key="approvals",
        notification_type="approval_requested",
        title_en="New Leave Request",
        title_ar="طلب إجازة جديد",
        body_en="Ahmad Hassan requested 2 days annual leave.",
        body_ar="طلب أحمد حسن إجازة سنوية لمدة يومين.",
        source_doctype="Leave Application",
        source_name="HR-LAP-00001",
        route="approval/Leave Application/HR-LAP-00001",
    )

The function:
  1. Creates a Mobile Notification record owned by the user.
  2. Enqueues a background job to dispatch FCM to each active device.
  Must be called AFTER the source transaction has committed (use frappe.enqueue
  or call from an after_commit hook/event handler).
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime


def send_notification(
	user: str,
	category_key: str,
	notification_type: str,
	title_en: str,
	title_ar: str,
	*,
	body_en: str = "",
	body_ar: str = "",
	source_doctype: str | None = None,
	source_name: str | None = None,
	route: str | None = None,
	enqueue: bool = True,
) -> str | None:
	"""Create a Mobile Notification and dispatch FCM to all active devices.

	Args:
		user: Frappe User ID (the notification owner/recipient).
		category_key: Mobile Notification Category.category_key.
		notification_type: One of the defined notification type values.
		title_en / title_ar: Bilingual push title.
		body_en / body_ar: Bilingual push body (optional).
		source_doctype / source_name: Source document identity (use as a pair).
		route: Static client route key (e.g. "leave/HR-LAP-00001").
		enqueue: If True, dispatch is queued as a background job (default).
			     Set False only in tests or scheduler jobs that run in background already.

	Returns:
		The name of the created Mobile Notification record, or None on error.
	"""
	# Validate category exists and is enabled
	category_name = frappe.db.get_value(
		"Mobile Notification Category",
		{"category_key": category_key, "enabled": 1},
		"name",
	)
	if not category_name:
		frappe.log_error(
			title=f"send_notification: unknown or disabled category '{category_key}'"
		)
		return None

	# Create the Mobile Notification record
	notif_doc = frappe.get_doc(
		{
			"doctype": "Mobile Notification",
			"user": user,
			"category": category_name,
			"notification_type": notification_type,
			"title_en": (title_en or "")[:255],
			"title_ar": (title_ar or "")[:255],
			"body_en": (body_en or "")[:1000],
			"body_ar": (body_ar or "")[:1000],
			"reference_doctype": source_doctype,
			"reference_name": source_name,
			"route": (route or "")[:500],
			"sent_at": now_datetime(),
		}
	)
	notif_doc.insert(ignore_permissions=True)
	notification_name = notif_doc.name

	# Enqueue dispatch to all active devices for this user
	if enqueue:
		frappe.enqueue(
			"primer_mobile.notifications.builder._dispatch_to_user_devices",
			notification_name=notification_name,
			user=user,
			queue="short",
			enqueue_after_commit=True,
		)
	else:
		_dispatch_to_user_devices(notification_name, user)

	return notification_name


def _dispatch_to_user_devices(notification_name: str, user: str) -> None:
	"""Background job: send push to every active device that has an FCM token."""
	from primer_mobile.notifications.dispatcher import dispatch_push

	devices = frappe.get_all(
		"Mobile Device",
		filters={"user": user, "enabled": 1, "fcm_token_hash": ["!=", ""]},
		pluck="name",
	)
	for device_name in devices:
		try:
			dispatch_push(notification_name, device_name)
		except Exception:
			frappe.log_error(
				title=f"dispatch_push failed for notification {notification_name} device {device_name}"
			)
