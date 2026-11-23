from __future__ import annotations

import json
import frappe
from frappe.utils import cint, flt


def execute() -> None:
	"""Idempotently backfill Geolocation, coordinates_text, and google_maps_url on Mobile Location."""
	if not frappe.db.table_exists("Mobile Location"):
		return

	# Reload doctype to ensure new columns exist in MariaDB
	frappe.reload_doc("primer_mobile_app", "doctype", "mobile_location")

	locations = frappe.get_all(
		"Mobile Location",
		fields=["name", "latitude", "longitude", "radius_meters", "location", "coordinates_text", "google_maps_url"],
	)

	for loc in locations:
		lat = flt(loc.get("latitude"))
		lon = flt(loc.get("longitude"))
		raw_geo = loc.get("location")
		radius = cint(loc.get("radius_meters")) or 100

		updates = {}

		# Case 1: Has raw_geo but missing lat/lon
		if raw_geo and (not lat or not lon):
			try:
				geo = json.loads(raw_geo) if isinstance(raw_geo, str) else raw_geo
				features = geo.get("features", []) or ([geo] if geo.get("geometry") else [])
				if features:
					coords = features[0].get("geometry", {}).get("coordinates", [])
					if len(coords) >= 2:
						lon = round(flt(coords[0]), 7)
						lat = round(flt(coords[1]), 7)
						updates["longitude"] = lon
						updates["latitude"] = lat
			except Exception:
				pass

		# Case 2: Has lat/lon
		if (lat or lon) and not (lat == 0 and lon == 0):
			lat = round(lat, 7)
			lon = round(lon, 7)
			coords_str = f"{lat:.7f}, {lon:.7f}"
			maps_url = f"https://www.google.com/maps?q={lat:.7f},{lon:.7f}"

			if loc.get("coordinates_text") != coords_str:
				updates["coordinates_text"] = coords_str
			if loc.get("google_maps_url") != maps_url:
				updates["google_maps_url"] = maps_url

			if not raw_geo:
				updates["location"] = json.dumps(
					{
						"type": "FeatureCollection",
						"features": [
							{
								"type": "Feature",
								"properties": {
									"point_type": "circle",
									"radius": radius,
								},
								"geometry": {
									"type": "Point",
									"coordinates": [lon, lat],
								},
							}
						],
					}
				)

		if updates:
			frappe.db.set_value("Mobile Location", loc["name"], updates, update_modified=False)
