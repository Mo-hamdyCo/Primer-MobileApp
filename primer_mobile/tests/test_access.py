"""Unit tests for profile resolution, rule weighting, and bootstrap data structure."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from primer_mobile.core.access import bootstrap, resolve_profile


class TestMobileAccess(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_single_value("Primers Mobile Settings", "enabled", 1)

		# Ensure default profile
		if not frappe.db.exists("Mobile Access Profile", "Standard Test Profile"):
			frappe.get_doc(
				{
					"doctype": "Mobile Access Profile",
					"profile_name": "Standard Test Profile",
					"enabled": 1,
					"is_default": 1,
					"allowed_features": "checkin\nattendance\nleave\nholidays\npayslip\napprovals",
					"show_salary_amounts": 1,
					"allow_payslip_pdf": 1,
					"allow_leave_cancellation": 1,
					"app_lock_timeout_minutes": 5,
				}
			).insert(ignore_permissions=True)

	def test_resolve_profile_fallback_to_default(self):
		profile = resolve_profile("Administrator")
		self.assertIsNotNone(profile)
		self.assertTrue(profile["enabled"])

	def test_bootstrap_payload_structure(self):
		data = bootstrap("Administrator")
		self.assertTrue(data.get("access_granted"))

		# Required contract keys
		required_keys = [
			"config_version",
			"server_timezone",
			"currency",
			"week_start",
			"user",
			"profile",
			"features",
			"feature_availability",
			"modules",
			"menu",
			"lock",
			"ui",
			"maps",
			"branding",
			"support",
			"notification_categories",
			"notification_prefs",
		]
		for key in required_keys:
			self.assertIn(key, data, f"Missing key in bootstrap: {key}")

		# User roles_flags
		user_dict = data["user"]
		self.assertIn("roles_flags", user_dict)
		flags = user_dict["roles_flags"]
		for f in ["is_manager", "is_hr", "is_accounts", "is_sales", "is_purchase", "is_stock"]:
			self.assertIn(f, flags)

		# UI preferences
		ui = data["ui"]
		self.assertIn("show_salary_amounts", ui)
		self.assertIn("allow_payslip_pdf", ui)
		self.assertIn("allow_leave_cancel", ui)
		self.assertIn("allow_quiet_hours", ui)
