"""Server-side entitlement, profile resolution, and full bootstrap builder.

Enforces:
- Least privilege access
- Strict role and entitlement validation
- Deterministic profile rule resolution
- Separation of feature availability from profile entitlement
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, get_system_timezone


MATCH_WEIGHT = {
	"Employee": 60,
	"User": 50,
	"Branch": 40,
	"Department": 30,
	"Company": 20,
	"Designation": 10,
	"Everyone": 0,
}


def get_employee(user: str) -> dict | None:
	"""Fetch the active Employee linked to this user, if any."""
	rows = frappe.get_list(
		"Employee",
		filters={"user_id": user, "status": "Active"},
		fields=[
			"name",
			"employee_name",
			"company",
			"branch",
			"department",
			"designation",
			"status",
			"image",
		],
		limit_page_length=1,
	)
	return rows[0] if rows else None


def resolve_profile(user: str) -> dict | None:
	"""Resolve the highest-priority matching Mobile Access Profile for this user."""
	# 1. Check if user is enabled
	if not frappe.db.get_value("User", user, "enabled"):
		return None

	employee = get_employee(user)
	rules = frappe.get_all(
		"Mobile Profile Rule",
		filters={"enabled": 1},
		fields=[
			"name",
			"priority",
			"profile",
			"match_type",
			"user",
			"employee",
			"company",
			"branch",
			"department",
			"designation",
		],
		order_by="priority asc, creation asc",
	)

	candidates = []
	for rule in rules:
		if _matches(rule, user, employee):
			weight = MATCH_WEIGHT.get(rule.match_type, -1)
			candidates.append((-weight, cint(rule.priority), rule.name, rule.profile))

	if candidates:
		# Sorted by highest weight (-weight ascending), then priority ascending, then name
		best_profile_name = sorted(candidates)[0][3]
		doc = frappe.get_doc("Mobile Access Profile", best_profile_name)
		return doc.as_dict() if cint(doc.enabled) else None

	# Fallback to default enabled profile
	default = frappe.get_all(
		"Mobile Access Profile",
		filters={"enabled": 1, "is_default": 1},
		pluck="name",
		limit_page_length=1,
	)
	if default:
		return frappe.get_doc("Mobile Access Profile", default[0]).as_dict()

	return None


def _matches(rule: dict, user: str, employee: dict | None) -> bool:
	match rule.match_type:
		case "Everyone":
			return True
		case "User":
			return rule.user == user
		case "Employee":
			return bool(employee and rule.employee == employee.name)
		case "Company":
			return bool(employee and rule.company == employee.company)
		case "Branch":
			return bool(employee and rule.branch == employee.branch)
		case "Department":
			return bool(employee and rule.department == employee.department)
		case "Designation":
			return bool(employee and rule.designation == employee.designation)
	return False


def profile_features(profile: dict) -> list[dict]:
	"""Return the list of features enabled for this profile."""
	allowed = {
		item.strip()
		for item in (profile.get("allowed_features") or "").splitlines()
		if item.strip()
	}
	features = frappe.get_all(
		"Mobile Feature",
		filters={"enabled": 1},
		fields=["feature_key", "feature_name", "release_state"],
		order_by="feature_name",
	)
	return [f for f in features if f.feature_key in allowed]


def resolve_checkin_policy(employee: dict | None, profile: dict) -> dict | None:
	"""Find the applicable check-in policy for this employee and profile."""
	if not employee:
		return None
	filters = {"enabled": 1}
	policies = frappe.get_all(
		"Mobile Checkin Policy",
		filters=filters,
		fields=[
			"name",
			"policy_name",
			"priority",
			"employee",
			"company",
			"branch",
			"department",
			"profile",
			"validation_mode",
			"checkin_scope",
			"require_reason",
			"require_selfie",
			"block_mock_location",
			"max_gps_accuracy_meters",
			"minimum_interval_minutes",
			"allowed_clock_skew_minutes",
			"allow_manual_log_type",
		],
		order_by="priority asc, creation asc",
	)
	for row in policies:
		if row.employee and row.employee != employee.get("name"):
			continue
		if row.company and row.company != employee.get("company"):
			continue
		if row.branch and row.branch != employee.get("branch"):
			continue
		if row.department and row.department != employee.get("department"):
			continue
		if row.profile and row.profile != profile.get("name"):
			continue
		return row

	default_name = profile.get("default_checkin_policy")
	if default_name:
		return frappe.get_doc("Mobile Checkin Policy", default_name).as_dict()

	return None


def get_user_roles_flags(user: str) -> dict[str, bool]:
	"""Derive boolean role flags for the user."""
	roles = set(frappe.get_roles(user))
	return {
		"is_manager": bool(
			{"Projects Manager", "Leave Approver", "Expense Approver"} & roles
		),
		"is_hr": bool({"HR Manager", "HR User"} & roles),
		"is_accounts": bool({"Accounts Manager", "Accounts User"} & roles),
		"is_sales": bool({"Sales Manager", "Sales User"} & roles),
		"is_purchase": bool({"Purchase Manager", "Purchase User"} & roles),
		"is_stock": bool({"Stock Manager", "Stock User"} & roles),
	}


def bootstrap(user: str) -> dict:
	"""Construct the complete, authoritative Bootstrap payload for the client."""
	profile = resolve_profile(user)
	if not profile:
		return {"access_granted": False, "reason": "NO_ACCESS_PROFILE"}

	settings = frappe.get_single("Primers Mobile Settings")
	employee = get_employee(user)
	entitled_features = profile_features(profile)
	entitled_keys = {f.feature_key for f in entitled_features}

	# Feature availability map: only include features the profile is entitled to
	all_features = frappe.get_all(
		"Mobile Feature",
		filters={"enabled": 1},
		fields=["feature_key", "release_state"],
	)
	feature_availability = {
		f.feature_key: f.release_state
		for f in all_features
		if f.feature_key in entitled_keys
	}

	# Menu items
	all_menu_items = frappe.get_all(
		"Mobile App Menu Item",
		filters={"enabled": 1},
		fields=[
			"menu_key",
			"parent_menu_item",
			"module_key",
			"label_ar",
			"label_en",
			"icon",
			"route_key",
			"release_state",
			"required_feature",
			"sort_order",
			"badge_source",
		],
		order_by="sort_order asc",
	)
	menu = []
	for item in all_menu_items:
		# If required_feature is set, user must be entitled to it
		if item.required_feature and item.required_feature not in entitled_keys:
			continue
		if item.release_state == "HIDDEN":
			continue
		menu.append(
			{
				"key": item.menu_key,
				"parent_key": item.parent_menu_item,
				"module": item.module_key,
				"label_ar": item.label_ar,
				"label_en": item.label_en,
				"icon": item.icon,
				"route_key": item.route_key,
				"availability": item.release_state,
				"sort_order": cint(item.sort_order),
				"badge_source": item.badge_source,
			}
		)

	# Modules
	modules = sorted(list({item["module"] for item in menu if item["module"] != "common"}))

	# Policy
	checkin_policy = resolve_checkin_policy(employee, profile)

	# Notification prefs & categories
	from primer_mobile.notifications.service import get_notification_prefs

	prefs = get_notification_prefs(user)

	# Doc configs (read-only schemas)
	doc_configs = frappe.get_all(
		"Mobile Doc Config",
		filters={"enabled": 1, "release_state": ["!=", "HIDDEN"]},
		fields=["config_key", "module_key", "label_ar", "label_en", "icon"],
	)

	# KPIs
	kpis = frappe.get_all(
		"Mobile KPI",
		filters={"enabled": 1, "release_state": ["!=", "HIDDEN"]},
		fields=["kpi_key", "module_key", "label_ar", "label_en"],
	)

	# Approval sources
	approval_sources = frappe.get_all(
		"Mobile Approval Source",
		filters={"enabled": 1, "release_state": "AVAILABLE"},
		fields=["doctype_target", "label_ar", "label_en", "mode"],
	)
	formatted_approval_sources = [
		{
			"doctype": src.doctype_target,
			"label_ar": src.label_ar,
			"label_en": src.label_en,
			"mode": src.mode.lower(),
		}
		for src in approval_sources
	]

	# User brief
	user_doc = frappe.get_doc("User", user)
	roles_flags = get_user_roles_flags(user)

	return {
		"access_granted": True,
		"config_version": cint(settings.config_version),
		"server_timezone": get_system_timezone(),
		"currency": frappe.db.get_default("currency") or "EGP",
		"week_start": cint(frappe.db.get_single_value("System Settings", "first_day_of_the_week") or 0),
		"user": {
			"id": user,
			"full_name": user_doc.full_name or user,
			"image": user_doc.user_image,
			"roles_flags": roles_flags,
		},
		"employee": (
			{
				"id": employee["name"],
				"name": employee.get("employee_name") or employee["name"],
				"department": employee.get("department"),
				"designation": employee.get("designation"),
				"branch": employee.get("branch"),
				"company": employee.get("company"),
				"status": employee.get("status"),
				"image": employee.get("image"),
			}
			if employee
			else None
		),
		"profile": profile.get("name"),
		"features": list(entitled_keys),
		"feature_availability": feature_availability,
		"modules": modules,
		"menu": menu,
		"checkin_policy": checkin_policy,
		"lock": {
			"required": True,
			"timeout_min": cint(profile.get("app_lock_timeout_minutes") or 5),
			"max_timeout_min": 30,
		},
		"ui": {
			"show_salary_amounts": bool(cint(profile.get("show_salary_amounts", 0))),
			"allow_payslip_pdf": bool(cint(profile.get("allow_payslip_pdf", 0))),
			"allow_leave_cancel": bool(cint(profile.get("allow_leave_cancellation", 0))),
			"allow_quiet_hours": bool(cint(profile.get("allow_quiet_hours", 1))),
		},
		"maps": {
			"tile_url_template": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
			"attribution": "© OpenStreetMap contributors",
			"min_zoom": 3,
			"max_zoom": 19,
		},
		"branding": {
			"name": settings.app_display_name or "Primers Mobile",
			"logo_url": None,
			"accent_color": settings.accent_color or "#1e88e5",
		},
		"firebase": {
			"project_id": getattr(settings, "firebase_project_id", None),
			"app_id": getattr(settings, "firebase_app_id", None),
			"api_key": getattr(settings, "firebase_api_key", None),
			"sender_id": getattr(settings, "firebase_sender_id", None),
		},
		"support": {
			"email": settings.support_email,
			"phone": settings.support_phone,
		},
		"notification_categories": prefs["categories_detail"],
		"notification_prefs": prefs,
		"doc_configs": doc_configs,
		"kpis": kpis,
		"approval_sources": formatted_approval_sources,
	}
