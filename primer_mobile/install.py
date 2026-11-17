"""Idempotent installation and migration helpers for Primers Mobile."""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

ROLE = "Mobile Admin"

CATEGORIES = [
	{
		"category_key": "approvals",
		"category_name": "Approvals",
		"label_en": "Approvals & Requests",
		"label_ar": "الموافقات والطلبات",
		"enabled": 1,
		"mandatory": 0,
		"default_enabled": 1,
		"user_configurable": 1,
		"importance": "high",
		"bypass_quiet_hours": 0,
		"action_set": "approve_reject",
		"description": "Requests waiting for your action (e.g. Leave, Expense, Shift approvals).",
	},
	{
		"category_key": "leave_status",
		"category_name": "Leave Status",
		"label_en": "Leave Status",
		"label_ar": "حالة طلبات الإجازة",
		"enabled": 1,
		"mandatory": 0,
		"default_enabled": 1,
		"user_configurable": 1,
		"importance": "default",
		"bypass_quiet_hours": 0,
		"action_set": "none",
		"description": "Updates when your leave application is approved, rejected, or cancelled.",
	},
	{
		"category_key": "payroll",
		"category_name": "Payroll",
		"label_en": "Payroll & Payslips",
		"label_ar": "الرواتب والمسيرات",
		"enabled": 1,
		"mandatory": 0,
		"default_enabled": 1,
		"user_configurable": 1,
		"importance": "default",
		"bypass_quiet_hours": 0,
		"action_set": "none",
		"description": "Alerts when your salary slip is processed and available for viewing.",
	},
	{
		"category_key": "attendance_reminder",
		"category_name": "Attendance Reminder",
		"label_en": "Attendance Reminders",
		"label_ar": "تذكيرات الحضور والانصراف",
		"enabled": 1,
		"mandatory": 0,
		"default_enabled": 1,
		"user_configurable": 1,
		"importance": "high",
		"bypass_quiet_hours": 0,
		"action_set": "none",
		"description": "Shift check-in and check-out reminders.",
	},
	{
		"category_key": "attendance_alert",
		"category_name": "Attendance Alert",
		"label_en": "Attendance Alerts",
		"label_ar": "تنبيهات الحضور",
		"enabled": 1,
		"mandatory": 0,
		"default_enabled": 1,
		"user_configurable": 1,
		"importance": "default",
		"bypass_quiet_hours": 0,
		"action_set": "none",
		"description": "Alerts about missing logs, late entries, or attendance discrepancies.",
	},
	{
		"category_key": "announcements",
		"category_name": "Announcements",
		"label_en": "Company Announcements",
		"label_ar": "تعميمات وإعلانات الشركة",
		"enabled": 1,
		"mandatory": 0,
		"default_enabled": 1,
		"user_configurable": 1,
		"importance": "default",
		"bypass_quiet_hours": 0,
		"action_set": "none",
		"description": "Broad company announcements and general updates.",
	},
	{
		"category_key": "system",
		"category_name": "System",
		"label_en": "System Notifications",
		"label_ar": "إشعارات النظام العامة",
		"enabled": 1,
		"mandatory": 1,
		"default_enabled": 1,
		"user_configurable": 0,
		"importance": "default",
		"bypass_quiet_hours": 0,
		"action_set": "none",
		"description": "Mandatory administrative and operational system notifications.",
	},
	{
		"category_key": "security",
		"category_name": "Security",
		"label_en": "Security Alerts",
		"label_ar": "تنبيهات الأمان والجلسات",
		"enabled": 1,
		"mandatory": 1,
		"default_enabled": 1,
		"user_configurable": 0,
		"importance": "high",
		"bypass_quiet_hours": 1,
		"action_set": "none",
		"description": "Immediate alerts for session revocation, new device login, or suspicious activity.",
	},
	{
		"category_key": "config",
		"category_name": "Configuration",
		"label_en": "Configuration Updates",
		"label_ar": "تحديثات الإعدادات والتكوين",
		"enabled": 1,
		"mandatory": 1,
		"default_enabled": 1,
		"user_configurable": 0,
		"importance": "low",
		"bypass_quiet_hours": 1,
		"action_set": "none",
		"description": "Silent background sync pushes when mobile settings or menus change.",
	},
]

FEATURES = [
	("checkin", "Check-in", "AVAILABLE"),
	("attendance", "Attendance", "AVAILABLE"),
	("leave", "Leave", "AVAILABLE"),
	("holidays", "Holidays", "AVAILABLE"),
	("payslip", "Payslip", "AVAILABLE"),
	("approvals", "Approvals", "AVAILABLE"),
	("expense_claims", "Expense Claims", "COMING_SOON"),
	("shift_requests", "Shift Requests", "COMING_SOON"),
	("attendance_requests", "Attendance Requests", "COMING_SOON"),
	("accounts", "Accounts", "COMING_SOON"),
	("sales", "Sales", "COMING_SOON"),
	("purchase", "Purchase", "COMING_SOON"),
	("stock", "Stock", "COMING_SOON"),
]

MENU_ITEMS = [
	{
		"menu_key": "home",
		"label_en": "Home",
		"label_ar": "الرئيسية",
		"route_key": "home",
		"module_key": "common",
		"sort_order": 1,
		"release_state": "AVAILABLE",
		"icon": "home",
	},
	{
		"menu_key": "hr_checkin",
		"label_en": "Check-in",
		"label_ar": "تسجيل الحضور",
		"route_key": "hr_checkin",
		"module_key": "hr",
		"required_feature": "checkin",
		"sort_order": 10,
		"release_state": "AVAILABLE",
		"icon": "checkin",
	},
	{
		"menu_key": "hr_attendance",
		"label_en": "Attendance",
		"label_ar": "سجل الحضور",
		"route_key": "hr_attendance",
		"module_key": "hr",
		"required_feature": "attendance",
		"sort_order": 20,
		"release_state": "AVAILABLE",
		"icon": "calendar",
	},
	{
		"menu_key": "hr_leave",
		"label_en": "Leave Applications",
		"label_ar": "طلبات الإجازة",
		"route_key": "hr_leave",
		"module_key": "hr",
		"required_feature": "leave",
		"sort_order": 30,
		"release_state": "AVAILABLE",
		"icon": "leave",
	},
	{
		"menu_key": "hr_payslips",
		"label_en": "Payslips",
		"label_ar": "قسائم الراتب",
		"route_key": "hr_payslips",
		"module_key": "hr",
		"required_feature": "payslip",
		"sort_order": 40,
		"release_state": "AVAILABLE",
		"icon": "payslip",
	},
	{
		"menu_key": "approvals",
		"label_en": "Approvals",
		"label_ar": "الموافقات والطلبات",
		"route_key": "approvals",
		"module_key": "hr",
		"required_feature": "approvals",
		"sort_order": 50,
		"release_state": "AVAILABLE",
		"icon": "approvals",
		"badge_source": "pending_approvals_count",
	},
	{
		"menu_key": "notifications",
		"label_en": "Notifications",
		"label_ar": "صندوق الإشعارات",
		"route_key": "notifications",
		"module_key": "common",
		"sort_order": 60,
		"release_state": "AVAILABLE",
		"icon": "notifications",
		"badge_source": "unread_count",
	},
	{
		"menu_key": "expense_claims",
		"label_en": "Expense Claims",
		"label_ar": "مطالبات المصاريف",
		"route_key": "expense_claims",
		"module_key": "hr",
		"required_feature": "expense_claims",
		"sort_order": 70,
		"release_state": "COMING_SOON",
		"icon": "expense",
	},
	{
		"menu_key": "shift_requests",
		"label_en": "Shift Requests",
		"label_ar": "طلبات تغيير الورديات",
		"route_key": "shift_requests",
		"module_key": "hr",
		"required_feature": "shift_requests",
		"sort_order": 80,
		"release_state": "COMING_SOON",
		"icon": "shift",
	},
	{
		"menu_key": "attendance_requests",
		"label_en": "Attendance Requests",
		"label_ar": "طلبات تصحيح الحضور",
		"route_key": "attendance_requests",
		"module_key": "hr",
		"required_feature": "attendance_requests",
		"sort_order": 90,
		"release_state": "COMING_SOON",
		"icon": "correction",
	},
	{
		"menu_key": "accounts_kpis",
		"label_en": "Accounts & Finance",
		"label_ar": "الحسابات المالية",
		"route_key": "accounts_kpis",
		"module_key": "accounts",
		"required_feature": "accounts",
		"sort_order": 100,
		"release_state": "COMING_SOON",
		"icon": "accounts",
	},
	{
		"menu_key": "sales_docs",
		"label_en": "Sales",
		"label_ar": "المبيعات",
		"route_key": "sales_docs",
		"module_key": "sales",
		"required_feature": "sales",
		"sort_order": 110,
		"release_state": "COMING_SOON",
		"icon": "sales",
	},
	{
		"menu_key": "purchase_docs",
		"label_en": "Purchases",
		"label_ar": "المشتريات",
		"route_key": "purchase_docs",
		"module_key": "purchase",
		"required_feature": "purchase",
		"sort_order": 120,
		"release_state": "COMING_SOON",
		"icon": "purchase",
	},
	{
		"menu_key": "stock_lookup",
		"label_en": "Inventory & Stock",
		"label_ar": "المخزون والمستودعات",
		"route_key": "stock_lookup",
		"module_key": "stock",
		"required_feature": "stock",
		"sort_order": 130,
		"release_state": "COMING_SOON",
		"icon": "stock",
	},
]

APPROVAL_SOURCES = [
	{
		"doctype_target": "Leave Application",
		"enabled": 1,
		"release_state": "AVAILABLE",
		"label_en": "Leave Application",
		"label_ar": "طلب إجازة",
		"mode": "AUTO",
		"pending_status_field": "status",
		"pending_status_value": "Open",
		"approver_field": "leave_approver",
		"requires_comment_on_reject": 1,
		"allow_self_approval": 0,
	},
	{
		"doctype_target": "Expense Claim",
		"enabled": 1,
		"release_state": "COMING_SOON",
		"label_en": "Expense Claim",
		"label_ar": "مطالبة مصاريف",
		"mode": "AUTO",
		"pending_status_field": "approval_status",
		"pending_status_value": "Draft",
		"approver_field": "expense_approver",
		"requires_comment_on_reject": 1,
		"allow_self_approval": 0,
	},
	{
		"doctype_target": "Shift Request",
		"enabled": 1,
		"release_state": "COMING_SOON",
		"label_en": "Shift Request",
		"label_ar": "طلب وردية",
		"mode": "AUTO",
		"pending_status_field": "status",
		"pending_status_value": "Draft",
		"approver_field": "approver",
		"requires_comment_on_reject": 1,
		"allow_self_approval": 0,
	},
]


def after_install() -> None:
	bootstrap()
	setup_custom_fields()


def after_migrate() -> None:
	bootstrap()
	setup_custom_fields()


def bootstrap() -> None:
	"""Create only app-owned defaults; safe to call from install and migrate."""
	# 1. Role
	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1}).insert(
			ignore_permissions=True
		)

	# 2. Singles defaults
	if not frappe.db.exists("Singles", {"doctype": "Primers Mobile Settings", "field": "api_version"}):
		frappe.db.set_single_value("Primers Mobile Settings", "api_version", 1)
		frappe.db.set_single_value("Primers Mobile Settings", "config_version", 1)

	# 3. Features
	for feature, label, state in FEATURES:
		if not frappe.db.exists("Mobile Feature", feature):
			frappe.get_doc(
				{
					"doctype": "Mobile Feature",
					"feature_key": feature,
					"feature_name": label,
					"release_state": state,
					"enabled": 1,
				}
			).insert(ignore_permissions=True)

	# 4. Notification Categories (idempotent insert or update missing bilingual fields)
	for cat in CATEGORIES:
		key = cat["category_key"]
		if not frappe.db.exists("Mobile Notification Category", key):
			frappe.get_doc({"doctype": "Mobile Notification Category", **cat}).insert(
				ignore_permissions=True
			)
		else:
			# Update fields if empty
			update_dict = {}
			for field in [
				"label_en",
				"label_ar",
				"importance",
				"bypass_quiet_hours",
				"action_set",
				"user_configurable",
			]:
				val = frappe.db.get_value("Mobile Notification Category", key, field)
				if val is None or val == "":
					update_dict[field] = cat[field]
			if update_dict:
				frappe.db.set_value(
					"Mobile Notification Category", key, update_dict, update_modified=False
				)

	# 5. Mobile App Menu Items
	for item in MENU_ITEMS:
		key = item["menu_key"]
		if not frappe.db.exists("Mobile App Menu Item", key):
			frappe.get_doc({"doctype": "Mobile App Menu Item", **item}).insert(
				ignore_permissions=True
			)

	# 6. Mobile Approval Sources
	for src in APPROVAL_SOURCES:
		dt = src["doctype_target"]
		if not frappe.db.exists("Mobile Approval Source", dt):
			frappe.get_doc({"doctype": "Mobile Approval Source", **src}).insert(
				ignore_permissions=True
			)


def setup_custom_fields() -> None:
	"""Add custom fields on Employee Checkin and User idempotently."""
	custom_fields = {
		"Employee Checkin": [
			{
				"fieldname": "pm_mobile_device",
				"label": "Mobile Device",
				"fieldtype": "Link",
				"options": "Mobile Device",
				"insert_after": "device_id",
				"read_only": 1,
			},
			{
				"fieldname": "pm_accuracy_m",
				"label": "GPS Accuracy (Meters)",
				"fieldtype": "Float",
				"insert_after": "pm_mobile_device",
				"read_only": 1,
			},
			{
				"fieldname": "pm_client_time_utc",
				"label": "Client Capture Time (UTC)",
				"fieldtype": "Data",
				"insert_after": "pm_accuracy_m",
				"read_only": 1,
			},
			{
				"fieldname": "pm_reason",
				"label": "Check-in Reason",
				"fieldtype": "Small Text",
				"insert_after": "pm_client_time_utc",
			},
			{
				"fieldname": "pm_selfie_file",
				"label": "Selfie Photo",
				"fieldtype": "Attach",
				"insert_after": "pm_reason",
			},
			{
				"fieldname": "pm_source",
				"label": "Check-in Source",
				"fieldtype": "Select",
				"options": "Mobile\nBiometric\nManual\nOther",
				"default": "Mobile",
				"insert_after": "pm_selfie_file",
			},
			{
				"fieldname": "pm_is_mock_reported",
				"label": "Mock Location Reported",
				"fieldtype": "Check",
				"default": "0",
				"insert_after": "pm_source",
				"read_only": 1,
			},
			{
				"fieldname": "pm_mobile_location",
				"label": "Matched Mobile Location",
				"fieldtype": "Link",
				"options": "Mobile Location",
				"insert_after": "pm_is_mock_reported",
				"read_only": 1,
			},
			{
				"fieldname": "pm_distance_m",
				"label": "Distance to Location (Meters)",
				"fieldtype": "Float",
				"insert_after": "pm_mobile_location",
				"read_only": 1,
			},
		],
		"User": [
			{
				"fieldname": "pm_mobile_access",
				"label": "Has Mobile Access",
				"fieldtype": "Check",
				"default": "0",
				"insert_after": "enabled",
				"description": "Explicit entitlement to use Primers Mobile app.",
			}
		],
	}

	create_custom_fields(custom_fields, update=True)
