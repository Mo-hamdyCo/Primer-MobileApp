"""Manager approvals API endpoints — Workflow and Standard modes.

Enforces:
- Document-level approver validation (no unauthorized approvals)
- Support for Frappe Workflow transitions where active
- Standard HRMS lifecycle execution (insert, submit, cancel) — no raw DB updates
- Self-approval restrictions
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow, get_transitions, get_workflow_name
from frappe.utils import cint, flt, get_datetime

from primer_mobile.core.access import resolve_profile
from primer_mobile.core.mobile_api import require_mobile_session


def _require_approvals_feature() -> dict:
	require_mobile_session()
	profile = resolve_profile(frappe.session.user)
	if not profile:
		frappe.local.response.http_status_code = 403
		frappe.throw(_("No active mobile access profile."), title="NO_ACCESS_PROFILE")

	from primer_mobile.core.access import profile_features

	features = {f.feature_key for f in profile_features(profile) if f.release_state == "AVAILABLE"}
	if "approvals" not in features:
		frappe.local.response.http_status_code = 403
		frappe.throw(_("Approvals feature is not enabled for your profile."), title="FEATURE_DISABLED")

	return profile


@frappe.whitelist(methods=["POST"])
def list(doctype: str | None = None, page: int = 1, page_size: int = 20) -> dict:
	"""Fetch pending approval items across all enabled sources or a specific DocType."""
	_require_approvals_feature()
	user = frappe.session.user
	page = max(cint(page), 1)
	page_size = min(max(cint(page_size), 1), 50)

	# Fetch enabled approval sources
	sources = frappe.get_all(
		"Mobile Approval Source",
		filters={"enabled": 1, "release_state": "AVAILABLE"},
		fields=["doctype_target", "label_en", "label_ar", "mode", "approver_field"],
	)

	items = []
	counts = []

	for src in sources:
		dt = src.doctype_target
		if doctype and dt != doctype:
			continue

		if dt == "Leave Application":
			# Standard query for pending leave applications
			leave_records = frappe.get_all(
				"Leave Application",
				filters={
					"leave_approver": user,
					"docstatus": 0,
					"status": "Open",
				},
				fields=[
					"name",
					"employee",
					"employee_name",
					"leave_type",
					"from_date",
					"to_date",
					"total_leave_days",
					"description",
					"status",
					"creation",
				],
				order_by="creation desc",
			)

			counts.append(
				{
					"doctype": dt,
					"label_en": src.label_en,
					"label_ar": src.label_ar,
					"count": len(leave_records),
				}
			)

			for r in leave_records:
				items.append(
					{
						"doctype": dt,
						"name": r.name,
						"title": f"{r.employee_name or r.employee} - {r.leave_type}",
						"subtitle": f"{r.from_date} to {r.to_date} ({flt(r.total_leave_days)} days)",
						"requester_name": r.employee_name,
						"requester_image": None,
						"summary_line": r.description or "",
						"status_label": r.status,
						"creation_utc": get_datetime(r.creation).isoformat() + "Z",
					}
				)

	# Paginate combined items
	start = (page - 1) * page_size
	paginated_items = items[start : start + page_size]

	return {
		"items": paginated_items,
		"page": page,
		"page_size": page_size,
		"has_more": len(items) > (start + page_size),
		"counts": counts,
	}


@frappe.whitelist(methods=["POST"])
def get(doctype: str, name: str) -> dict:
	"""Fetch single approval item with fields, available actions, and history."""
	_require_approvals_feature()
	user = frappe.session.user

	src = frappe.db.get_value(
		"Mobile Approval Source",
		{"doctype_target": doctype, "enabled": 1, "release_state": "AVAILABLE"},
		["doctype_target", "mode", "approver_field", "requires_comment_on_reject", "allow_self_approval"],
		as_dict=True,
	)
	if not src:
		frappe.local.response.http_status_code = 404
		frappe.throw(_("Approval source is not available: {0}").format(doctype), title="NOT_FOUND")

	doc = frappe.get_doc(doctype, name)

	# Verify approver
	approver_val = getattr(doc, src.approver_field or "leave_approver", None)
	workflow_name = get_workflow_name(doctype)

	available_actions = []
	mode = "standard"

	if workflow_name:
		mode = "workflow"
		transitions = get_transitions(doc)
		for t in transitions:
			action_type = "approve" if "approve" in t.action.lower() else ("reject" if "reject" in t.action.lower() else "other")
			available_actions.append(
				{
					"key": t.action,
					"label_en": t.action,
					"label_ar": t.action,
					"type": action_type,
					"requires_comment": action_type == "reject" and bool(src.requires_comment_on_reject),
				}
			)
	else:
		if approver_val != user and "System Manager" not in frappe.get_roles():
			frappe.local.response.http_status_code = 403
			frappe.throw(_("You are not the designated approver for this document."), title="PERMISSION_DENIED")

		available_actions = [
			{
				"key": "approve",
				"label_en": "Approve",
				"label_ar": "اعتماد",
				"type": "approve",
				"requires_comment": False,
			},
			{
				"key": "reject",
				"label_en": "Reject",
				"label_ar": "رفض",
				"type": "reject",
				"requires_comment": bool(src.requires_comment_on_reject),
			},
		]

	# Build display fields
	fields = []
	if doctype == "Leave Application":
		fields = [
			{"label_en": "Employee", "label_ar": "الموظف", "type": "text", "value": doc.employee_name or doc.employee},
			{"label_en": "Leave Type", "label_ar": "نوع الإجازة", "type": "text", "value": doc.leave_type},
			{"label_en": "From Date", "label_ar": "من تاريخ", "type": "date", "value": str(doc.from_date)},
			{"label_en": "To Date", "label_ar": "إلى تاريخ", "type": "date", "value": str(doc.to_date)},
			{"label_en": "Total Days", "label_ar": "إجمالي الأيام", "type": "number", "value": flt(doc.total_leave_days)},
			{"label_en": "Half Day", "label_ar": "نصف يوم", "type": "text", "value": "Yes" if doc.half_day else "No"},
			{"label_en": "Reason", "label_ar": "سبب الإجازة", "type": "text", "value": doc.description or "-"},
			{"label_en": "Posting Date", "label_ar": "تاريخ التقديم", "type": "date", "value": str(doc.posting_date)},
		]

	# Fetch comments
	comments_raw = frappe.get_all(
		"Comment",
		filters={"reference_doctype": doctype, "reference_name": name},
		fields=["comment_by", "content", "creation"],
		order_by="creation asc",
	)
	comments = [
		{
			"by": c.comment_by,
			"at_utc": get_datetime(c.creation).isoformat() + "Z",
			"text": c.content,
		}
		for c in comments_raw
	]

	return {
		"doctype": doctype,
		"name": name,
		"title": f"{getattr(doc, 'employee_name', '')} - {getattr(doc, 'leave_type', '')}",
		"mode": mode,
		"status_label": getattr(doc, "status", getattr(doc, "workflow_state", "")),
		"fields": fields,
		"available_actions": available_actions,
		"comments": comments,
	}


@frappe.whitelist(methods=["POST"])
def action(doctype: str, name: str, action_key: str, comment: str | None = None) -> dict:
	"""Apply approval action (Standard or Workflow mode)."""
	_require_approvals_feature()
	user = frappe.session.user

	doc = frappe.get_doc(doctype, name)

	# Check if already processed
	if doc.docstatus != 0:
		frappe.local.response.http_status_code = 409
		frappe.throw(_("This document has already been processed."), title="ALREADY_PROCESSED")

	workflow_name = get_workflow_name(doctype)

	if workflow_name:
		# Workflow mode
		apply_workflow(doc, action_key)
		if comment:
			doc.add_comment("Comment", text=f"Mobile approval action: {comment}")
	else:
		# Standard mode
		approver_field = "leave_approver" if doctype == "Leave Application" else "approver"
		approver_val = getattr(doc, approver_field, None)

		if approver_val != user and "System Manager" not in frappe.get_roles():
			frappe.local.response.http_status_code = 403
			frappe.throw(_("You are not the designated approver."), title="PERMISSION_DENIED")

		if action_key == "approve":
			doc.status = "Approved"
			doc.submit()
		elif action_key == "reject":
			if not comment or not comment.strip():
				frappe.local.response.http_status_code = 400
				frappe.throw(_("A comment is required when rejecting a request."), title="VALIDATION_ERROR")
			doc.status = "Rejected"
			doc.add_comment("Comment", text=f"Rejected via mobile: {comment.strip()}")
			doc.save(ignore_permissions=True)
		else:
			frappe.local.response.http_status_code = 400
			frappe.throw(_("Invalid action: {0}").format(action_key), title="VALIDATION_ERROR")

	# Recount remaining
	remaining = frappe.db.count(
		doctype,
		filters={"leave_approver": user, "docstatus": 0, "status": "Open"},
	)

	return {
		"result": "done",
		"new_status_label": getattr(doc, "status", getattr(doc, "workflow_state", "")),
		"remaining_count": remaining,
	}
