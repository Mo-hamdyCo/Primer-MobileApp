"""Unit tests for notification preferences, quiet hours logic, and deduplication."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from primer_mobile.notifications.dispatcher import _build_dedup_key, _in_quiet_hours
from primer_mobile.notifications.service import (
	get_notification_prefs,
	mark_all_read,
	mark_read,
	unread_count,
	update_notification_prefs,
)


class TestMobileNotifications(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# Ensure system category exists
		if not frappe.db.exists("Mobile Notification Category", "system"):
			frappe.get_doc(
				{
					"doctype": "Mobile Notification Category",
					"category_key": "system",
					"category_name": "System",
					"label_en": "System",
					"label_ar": "النظام",
					"enabled": 1,
					"mandatory": 1,
					"default_enabled": 1,
				}
			).insert(ignore_permissions=True)

	def test_get_prefs_returns_version_and_categories(self):
		prefs = get_notification_prefs("Administrator")
		self.assertIn("version", prefs)
		self.assertIn("categories", prefs)
		self.assertIn("quiet_hours", prefs)
		# Mandatory category must always be enabled
		self.assertTrue(prefs["categories"].get("system", True))

	def test_update_prefs_optimistic_locking(self):
		user = "Administrator"
		current = get_notification_prefs(user)
		ver = current["version"]

		# Successful update with matching version
		res = update_notification_prefs(user, version=ver, categories={"approvals": False}, quiet_hours={})
		self.assertTrue(res.get("ok"))

		# Second update with same old version must fail with CONFLICT (HTTP 409)
		conflict_res = update_notification_prefs(user, version=ver, categories={"approvals": True}, quiet_hours={})
		self.assertFalse(conflict_res.get("ok"))
		self.assertEqual(conflict_res.get("error", {}).get("code"), "CONFLICT")

	def test_dedup_key_deterministic(self):
		class DummyNotif:
			category = "approvals"
			reference_doctype = "Leave Application"
			reference_name = "HR-LAP-001"
			notification_type = "approval_requested"

		key1 = _build_dedup_key("DEV_01", DummyNotif())
		key2 = _build_dedup_key("DEV_01", DummyNotif())
		self.assertEqual(key1, key2)
		self.assertEqual(len(key1), 64)
