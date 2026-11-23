from __future__ import annotations

import json
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate


class MobileLocation(Document):
	def validate(self) -> None:
		self._sync_coordinates_and_geojson()
		self._validate_ranges_and_dates()

	def _sync_coordinates_and_geojson(self) -> None:
		raw_location = self.location
		if raw_location:
			if isinstance(raw_location, str):
				try:
					geo = json.loads(raw_location)
				except Exception:
					geo = None
			elif isinstance(raw_location, dict):
				geo = raw_location
			else:
				geo = None

			if geo:
				features = geo.get("features", [])
				if not features and geo.get("geometry"):
					features = [geo]

				if len(features) > 1:
					frappe.throw(_("Please place only a single point or circle location marker on the map."))

				if features:
					feat = features[0]
					geometry = feat.get("geometry", {})
					geom_type = geometry.get("type")
					coords = geometry.get("coordinates")

					if geom_type != "Point" or not coords or len(coords) < 2:
						frappe.throw(_("Location marker must be a single Point or Circle."))

					# GeoJSON standard: [longitude, latitude]
					lon = round(flt(coords[0]), 7)
					lat = round(flt(coords[1]), 7)

					self.longitude = lon
					self.latitude = lat

					props = feat.get("properties") or {}
					circle_radius = props.get("radius")
					if circle_radius and (not self.radius_meters or cint(self.radius_meters) <= 0):
						self.radius_meters = int(round(flt(circle_radius)))

		# If location is empty but coordinates are manually provided, build GeoJSON
		if not self.location and self.latitude is not None and self.longitude is not None:
			rad = cint(self.radius_meters) if self.radius_meters else 100
			lat = round(flt(self.latitude), 7)
			lon = round(flt(self.longitude), 7)
			self.latitude = lat
			self.longitude = lon
			self.location = json.dumps(
				{
					"type": "FeatureCollection",
					"features": [
						{
							"type": "Feature",
							"properties": {
								"point_type": "circle",
								"radius": rad,
							},
							"geometry": {
								"type": "Point",
								"coordinates": [lon, lat],
							},
						}
					],
				}
			)

		# Synchronize derived read-only fields
		if self.latitude is not None and self.longitude is not None and (flt(self.latitude) != 0 or flt(self.longitude) != 0):
			lat = round(flt(self.latitude), 7)
			lon = round(flt(self.longitude), 7)
			self.coordinates_text = f"{lat:.7f}, {lon:.7f}"
			self.google_maps_url = f"https://www.google.com/maps?q={lat:.7f},{lon:.7f}"
		else:
			self.coordinates_text = None
			self.google_maps_url = None

	def _validate_ranges_and_dates(self) -> None:
		has_coords = self.latitude is not None and self.longitude is not None and (flt(self.latitude) != 0 or flt(self.longitude) != 0)

		if has_coords:
			if not -90 <= flt(self.latitude) <= 90:
				frappe.throw(_("Latitude must be between -90 and 90."))
			if not -180 <= flt(self.longitude) <= 180:
				frappe.throw(_("Longitude must be between -180 and 180."))
		elif cint(self.enabled):
			frappe.msgprint(
				_("Warning: Mobile Location '{0}' has no coordinates set and will be skipped by check-in.").format(
					self.location_name or self.name
				),
				alert=True,
			)

		if not self.radius_meters or cint(self.radius_meters) <= 0:
			self.radius_meters = 100

		if self.valid_from and self.valid_to and getdate(self.valid_from) > getdate(self.valid_to):
			frappe.throw(_("Valid From cannot be after Valid To."))
