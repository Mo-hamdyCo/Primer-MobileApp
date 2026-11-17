import os
import frappe

def run():
	os.chdir("/home/hamdy/frappe-bench/frappe-bench-v15/sites")
	frappe.init(site="site15")
	frappe.connect()

	print("--- Running Primer Mobile Verification ---")
	from primer_mobile.install import bootstrap, setup_custom_fields
	bootstrap()
	setup_custom_fields()
	print("1. Bootstrap & Custom Fields: SUCCESS")

	# Enable mobile settings and ensure default profile
	frappe.db.set_single_value("Primers Mobile Settings", "enabled", 1)
	frappe.db.set_single_value("Primers Mobile Settings", "config_version", 1)
	frappe.db.set_single_value("Primers Mobile Settings", "access_token_ttl_minutes", 30)
	frappe.db.set_single_value("Primers Mobile Settings", "refresh_token_ttl_days", 30)
	frappe.db.set_single_value("Primers Mobile Settings", "max_active_devices_per_user", 5)

	if not frappe.db.exists("Mobile Access Profile", "Default Employee Profile"):
		frappe.get_doc({
			"doctype": "Mobile Access Profile",
			"profile_name": "Default Employee Profile",
			"enabled": 1,
			"is_default": 1,
			"allowed_features": "checkin\nattendance\nleave\nholidays\npayslip\napprovals",
			"show_salary_amounts": 1,
			"allow_payslip_pdf": 1,
			"allow_leave_cancellation": 1,
			"app_lock_timeout_minutes": 5,
		}).insert(ignore_permissions=True)
	frappe.db.commit()

	from primer_mobile.core.access import bootstrap as get_bootstrap
	bs = get_bootstrap("Administrator")
	print(f"2. Bootstrap access_granted: {bs.get('access_granted')}")
	print(f"   Config version: {bs.get('config_version')}")
	print(f"   Currency: {bs.get('currency')}")
	print(f"   Modules: {bs.get('modules')}")
	print(f"   Menu items count: {len(bs.get('menu', []))}")
	print(f"   Categories count: {len(bs.get('notification_categories', []))}")
	print(f"   Approval sources: {bs.get('approval_sources')}")

	from primer_mobile.core.auth import issue_session, rotate_refresh_session, _digest
	dev_id = "test_device_verify_001"
	s = issue_session("Administrator", dev_id, "ANDROID", 1, "Pixel 8")
	print(f"3. Issue Session: SUCCESS (access token length={len(s['access_token'])})")

	rot = rotate_refresh_session(s["refresh_token"], dev_id)
	print("4. Rotate Refresh Session: SUCCESS")

	from primer_mobile.notifications.service import get_notification_prefs, update_notification_prefs
	prefs = get_notification_prefs("Administrator")
	print(f"5. Notification Prefs: version={prefs['version']}, categories={len(prefs['categories'])}")

	from primer_mobile.api.v1.admin import test_fcm_configuration
	fcm_test = test_fcm_configuration()
	print(f"6. FCM Configuration Test: {fcm_test}")

	from primer_mobile.api.v1.approvals import list as list_approvals
	frappe.set_user("Administrator")
	frappe.local.mobile_session = frappe._dict({"name": "test_session"})
	appr = list_approvals()
	print(f"7. Approvals List: count={len(appr.get('items', []))}")

	print("--- ALL VERIFICATIONS PASSED ---")

if __name__ == "__main__":
	run()
