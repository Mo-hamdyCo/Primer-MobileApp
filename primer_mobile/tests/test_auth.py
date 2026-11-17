"""Unit tests for mobile authentication, sessions, and bearer token validation."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from primer_mobile.core.auth import (
	_digest,
	issue_session,
	revoke_current_session,
	rotate_refresh_session,
)


class TestMobileAuth(FrappeTestCase):
	def setUp(self):
		super().setUp()
		# Ensure settings are enabled
		frappe.db.set_single_value("Primers Mobile Settings", "enabled", 1)
		frappe.db.set_single_value("Primers Mobile Settings", "access_token_ttl_minutes", 30)
		frappe.db.set_single_value("Primers Mobile Settings", "refresh_token_ttl_days", 30)
		frappe.db.set_single_value("Primers Mobile Settings", "max_active_devices_per_user", 3)

		# Ensure default profile exists
		if not frappe.db.exists("Mobile Access Profile", "Test Default Profile"):
			frappe.get_doc(
				{
					"doctype": "Mobile Access Profile",
					"profile_name": "Test Default Profile",
					"enabled": 1,
					"is_default": 1,
					"allowed_features": "checkin\nattendance\nleave",
				}
			).insert(ignore_permissions=True)

	def test_token_digest_is_sha256(self):
		token = "sample_test_token_12345"
		hashed = _digest(token)
		self.assertEqual(len(hashed), 64)
		# Deterministic
		self.assertEqual(hashed, _digest(token))
		self.assertNotEqual(hashed, token)

	def test_issue_session_creates_device_and_session(self):
		user = "Administrator"
		device_id = "test_dev_001"
		res = issue_session(user, device_id, platform="ANDROID", app_version_code=1, device_name="Pixel 8")

		self.assertIn("access_token", res)
		self.assertIn("refresh_token", res)
		self.assertEqual(res["device_id"], device_id)

		# Verify raw tokens are NOT stored in the database
		session = frappe.db.get_value(
			"Mobile Session",
			{"access_token_hash": _digest(res["access_token"])},
			["name", "user", "enabled", "refresh_token_hash"],
			as_dict=True,
		)
		self.assertIsNotNone(session)
		self.assertEqual(session.user, user)
		self.assertEqual(session.enabled, 1)
		self.assertEqual(session.refresh_token_hash, _digest(res["refresh_token"]))

	def test_rotate_refresh_session(self):
		user = "Administrator"
		device_id = "test_dev_rot_01"
		res1 = issue_session(user, device_id, platform="ANDROID", app_version_code=1)

		# Rotate
		res2 = rotate_refresh_session(res1["refresh_token"], device_id)
		self.assertIn("access_token", res2)
		self.assertIn("refresh_token", res2)
		self.assertNotEqual(res1["access_token"], res2["access_token"])
		self.assertNotEqual(res1["refresh_token"], res2["refresh_token"])

		# Old refresh token must be invalidated
		with self.assertRaises(frappe.AuthenticationError):
			rotate_refresh_session(res1["refresh_token"], device_id)

	def test_device_binding_mismatch_fails(self):
		user = "Administrator"
		device_id = "test_dev_bind_01"
		res = issue_session(user, device_id, platform="ANDROID", app_version_code=1)

		# Attempting to refresh with a mismatched device ID must fail
		with self.assertRaises(frappe.AuthenticationError):
			rotate_refresh_session(res["refresh_token"], "completely_different_device_id")
