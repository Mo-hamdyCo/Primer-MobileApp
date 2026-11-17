"""Generic read-only screens and KPI infrastructure.

SECURITY REQUIREMENT:
- Only explicitly configured and enabled DocConfigs/KPIs are exposed.
- User permissions are enforced on every record read.
- Coming Soon modules (Accounts, Sales, Purchase, Stock) are rejected with FEATURE_COMING_SOON.
- No generic create/update/delete endpoint exists.
"""

from __future__ import annotations

import json
import frappe
from frappe import _
from frappe.utils import cint

from primer_mobile.core.access import resolve_profile
from primer_mobile.core.mobile_api import require_mobile_session


def _require_module_feature(feature_key: str) -> None:
	require_mobile_session()
	profile = resolve_profile(frappe.session.user)
	if not profile:
		frappe.local.response.http_status_code = 403
		frappe.throw(_("No active mobile access profile."), title="NO_ACCESS_PROFILE")

	from primer_mobile.core.access import profile_features

	features = profile_features(profile)
	matched = next((f for f in features if f.feature_key == feature_key), None)
	if not matched or matched.release_state == "HIDDEN":
		frappe.local.response.http_status_code = 403
		frappe.throw(_("Module is not available."), title="FEATURE_DISABLED")

	if matched.release_state == "COMING_SOON":
		frappe.local.response.http_status_code = 403
		frappe.throw(_("This module is coming soon."), title="FEATURE_COMING_SOON")


@frappe.whitelist(methods=["POST"])
def get_kpis(module: str) -> dict:
	"""Fetch configured KPIs for an available module."""
	_require_module_feature(module)

	kpis = frappe.get_all(
		"Mobile KPI",
		filters={"module_key": module, "enabled": 1, "release_state": "AVAILABLE"},
		fields=["kpi_key", "label_en", "label_ar", "number_card", "currency"],
		order_by="sort_order asc",
	)

	out = []
	for k in kpis:
		val = 0
		if k.number_card:
			try:
				card = frappe.get_doc("Number Card", k.number_card)
				# Evaluate card using Frappe Number Card helper if permitted
				from frappe.desk.doctype.number_card.number_card import get_result

				val = get_result(card.name)
			except Exception:
				val = 0

		out.append(
			{
				"kpi_key": k.kpi_key,
				"label_en": k.label_en,
				"label_ar": k.label_ar,
				"value": val,
				"currency": k.currency,
			}
		)

	return {"kpis": out}


@frappe.whitelist(methods=["POST"])
def list_docs(
	module: str,
	doc_key: str,
	search: str | None = None,
	filters: dict | None = None,
	page: int = 1,
	page_size: int = 20,
) -> dict:
	"""Fetch paginated read-only document lists using configured Mobile Doc Config."""
	_require_module_feature(module)

	cfg = frappe.db.get_value(
		"Mobile Doc Config",
		{"config_key": doc_key, "module_key": module, "enabled": 1, "release_state": "AVAILABLE"},
		["target_doctype", "title_field", "subtitle_field", "status_field", "base_filters_json", "allowed_sort_field"],
		as_dict=True,
	)
	if not cfg:
		frappe.local.response.http_status_code = 404
		frappe.throw(_("Doc configuration not found: {0}").format(doc_key), title="NOT_FOUND")

	target_dt = cfg.target_doctype
	if not frappe.has_permission(target_dt, "read"):
		frappe.local.response.http_status_code = 403
		frappe.throw(_("You do not have permission to view {0}.").format(target_dt), title="PERMISSION_DENIED")

	page = max(cint(page), 1)
	page_size = min(max(cint(page_size), 1), 50)

	base_filters = {}
	if cfg.base_filters_json:
		try:
			base_filters = json.loads(cfg.base_filters_json)
		except Exception:
			pass

	combined_filters = {**base_filters, **(filters or {})}

	# Fetch only permitted fields
	fields = ["name", cfg.title_field]
	if cfg.subtitle_field:
		fields.append(cfg.subtitle_field)
	if cfg.status_field:
		fields.append(cfg.status_field)

	rows = frappe.get_list(
		target_dt,
		filters=combined_filters,
		fields=fields,
		order_by=f"{cfg.allowed_sort_field or 'modified'} desc",
		start=(page - 1) * page_size,
		page_length=page_size + 1,
	)

	return {
		"schema": {
			"title_field": cfg.title_field,
			"subtitle_field": cfg.subtitle_field,
			"status_field": cfg.status_field,
		},
		"rows": [{"name": r.name, "values": r} for r in rows[:page_size]],
		"page": page,
		"page_size": page_size,
		"has_more": len(rows) > page_size,
	}


@frappe.whitelist(methods=["POST"])
def get_doc(module: str, doc_key: str, name: str) -> dict:
	"""Fetch single read-only document details."""
	_require_module_feature(module)

	cfg = frappe.db.get_value(
		"Mobile Doc Config",
		{"config_key": doc_key, "module_key": module, "enabled": 1, "release_state": "AVAILABLE"},
		["target_doctype", "title_field", "subtitle_field", "status_field"],
		as_dict=True,
	)
	if not cfg:
		frappe.local.response.http_status_code = 404
		frappe.throw(_("Doc configuration not found."), title="NOT_FOUND")

	doc = frappe.get_doc(cfg.target_doctype, name)
	if not doc.has_permission("read"):
		frappe.local.response.http_status_code = 403
		frappe.throw(_("Permission denied."), title="PERMISSION_DENIED")

	return {
		"schema": {
			"title_field": cfg.title_field,
			"subtitle_field": cfg.subtitle_field,
			"status_field": cfg.status_field,
		},
		"name": doc.name,
		"values": doc.as_dict(),
	}


@frappe.whitelist(methods=["POST"])
def search_items(query: str | None = None, page: int = 1, page_size: int = 20) -> dict:
	"""Item lookup (Coming Soon in v1 unless Stock module is enabled)."""
	_require_module_feature("stock")
	# If stock feature is marked AVAILABLE in Desk:
	page = max(cint(page), 1)
	page_size = min(max(cint(page_size), 1), 50)
	filters = {"disabled": 0}
	if query:
		filters["item_name"] = ["like", f"%{query}%"]

	items = frappe.get_list(
		"Item",
		filters=filters,
		fields=["item_code", "item_name", "stock_uom", "image"],
		start=(page - 1) * page_size,
		page_length=page_size + 1,
	)
	return {
		"items": items[:page_size],
		"page": page,
		"page_size": page_size,
		"has_more": len(items) > page_size,
	}


@frappe.whitelist(methods=["POST"])
def item_stock(item_code: str) -> dict:
	"""Item warehouse stock summary (Coming Soon in v1 unless Stock module is enabled)."""
	_require_module_feature("stock")

	item = frappe.get_doc("Item", item_code)
	bins = frappe.get_all(
		"Bin",
		filters={"item_code": item_code},
		fields=["warehouse", "actual_qty", "reserved_qty", "projected_qty"],
	)
	total = sum(flt(b.actual_qty) for b in bins)
	return {
		"item_code": item.item_code,
		"item_name": item.item_name,
		"uom": item.stock_uom,
		"total_qty": total,
		"warehouses": [
			{
				"warehouse": b.warehouse,
				"qty": flt(b.actual_qty),
				"reserved_qty": flt(b.reserved_qty),
				"projected_qty": flt(b.projected_qty),
			}
			for b in bins
		],
	}
