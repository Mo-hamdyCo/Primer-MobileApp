"""Event handlers for triggering mobile push notifications from ERPNext/HRMS events.

All push notifications are enqueued to run AFTER the database transaction commits,
so failed transactions never trigger phantom push notifications.
"""

from __future__ import annotations

import frappe
from frappe.utils import strip_html


def on_pwa_notification_created(doc, method: str | None = None) -> None:
	"""Handler for PWA Notification inserted by HRMS PWANotificationsMixin.

	PWA Notification fields:
	  to_user: recipient User ID
	  from_user: sender User ID
	  message: text message (may contain <b> tags)
	  reference_document_type: e.g. "Leave Application"
	  reference_document_name: e.g. "HR-LAP-00001"
	"""
	if not doc.to_user:
		return

	from primer_mobile.notifications.builder import send_notification

	clean_message = strip_html(doc.message or "")
	ref_type = doc.reference_document_type or ""
	ref_name = doc.reference_document_name or ""

	# Classify notification type & category based on message content and reference
	is_approval_request = "raised a new" in clean_message or "for approval" in clean_message
	is_status_update = "Approved" in clean_message or "Rejected" in clean_message or "cancelled" in clean_message.lower()

	if is_approval_request:
		category_key = "approvals"
		notification_type = "approval_requested"
		route = f"approval/{ref_type}/{ref_name}" if ref_type and ref_name else "notifications"
		title_en = f"New {ref_type or 'Document'} for Approval"
		title_ar = f"طلب {ref_type or 'مستند'} جديد للاعتماد"
		body_en = clean_message
		body_ar = f"تم تقديم طلب {ref_type or ''} جديد ({ref_name}) للاعتماد."
	elif is_status_update:
		if ref_type == "Leave Application":
			category_key = "leave_status"
			notification_type = "leave_status_changed"
			route = f"leave/{ref_name}"
			title_en = "Leave Application Status Updated"
			title_ar = "تحديث حالة طلب الإجازة"
		else:
			category_key = "approvals"
			notification_type = "approval_requested"
			route = f"approval/{ref_type}/{ref_name}" if ref_type and ref_name else "notifications"
			title_en = f"{ref_type} Status Updated"
			title_ar = f"تحديث حالة {ref_type}"

		body_en = clean_message
		body_ar = clean_message
	else:
		category_key = "system"
		notification_type = "system"
		route = f"approval/{ref_type}/{ref_name}" if ref_type and ref_name else "notifications"
		title_en = ref_type or "Notification"
		title_ar = "إشعار جديد"
		body_en = clean_message
		body_ar = clean_message

	send_notification(
		user=doc.to_user,
		category_key=category_key,
		notification_type=notification_type,
		title_en=title_en,
		title_ar=title_ar,
		body_en=body_en,
		body_ar=body_ar,
		source_doctype=ref_type or None,
		source_name=ref_name or None,
		route=route,
		enqueue=True,
	)


def on_salary_slip_submitted(doc, method: str | None = None) -> None:
	"""Handler for Salary Slip on_submit.

	Notifies the employee that their payslip is available.
	CRITICAL SECURITY: Never include salary amounts in the push notification!
	"""
	if not doc.employee:
		return

	user_id = frappe.db.get_value("Employee", doc.employee, "user_id")
	if not user_id:
		return

	from primer_mobile.notifications.builder import send_notification

	month_label = doc.get("month_name") or str(doc.get("start_date") or "")

	title_en = "Payslip Available"
	title_ar = "تم إصدار قسيمة الراتب"
	body_en = f"Your payslip for {month_label} is now available."
	body_ar = f"تم إصدار قسيمة الراتب الخاصة بك لشهر {month_label}."

	send_notification(
		user=user_id,
		category_key="payroll",
		notification_type="salary_slip_submitted",
		title_en=title_en,
		title_ar=title_ar,
		body_en=body_en,
		body_ar=body_ar,
		source_doctype="Salary Slip",
		source_name=doc.name,
		route=f"payslip/{doc.name}",
		enqueue=True,
	)
