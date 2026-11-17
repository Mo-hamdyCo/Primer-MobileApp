"""Configuration invalidation with no-op save protection."""

from __future__ import annotations

import frappe


def bump_version(doc, method: str | None = None) -> None:
	"""Advance bootstrap version only for a material insert/update/delete."""
	before_save = doc.get_doc_before_save()
	if method == "on_update" and before_save and _same_effective_config(doc, before_save):
		return
	cache_key = "primers_mobile:config_version"
	frappe.cache.delete_value(cache_key)
	# Single DocType values live in tabSingles, so use Frappe's supported API.
	current_version = frappe.db.get_single_value("Primers Mobile Settings", "config_version") or 0
	frappe.db.set_single_value("Primers Mobile Settings", "config_version", int(current_version) + 1)


def _same_effective_config(current, previous) -> bool:
	"""Ignore Frappe bookkeeping fields when detecting a no-op Desk save."""
	ignore = {"modified", "modified_by", "creation", "owner", "idx"}
	left = {key: value for key, value in current.as_dict().items() if key not in ignore}
	right = {key: value for key, value in previous.as_dict().items() if key not in ignore}
	return left == right
