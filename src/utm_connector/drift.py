"""Mission comparison and drift classification."""

from __future__ import annotations

from typing import List, Set

from .domain import Mission, MissionDriftClassification, MissionDriftReport


def compare_missions(submitted: Mission, current: Mission) -> MissionDriftReport:
    """Compare two canonical missions without guessing missing semantics.

    A report is deliberately conservative: a change spanning more than one
    operational category is classified as ``UNKNOWN_CHANGE`` rather than
    pretending that one category fully explains it.
    """

    if submitted.vehicle_id != current.vehicle_id:
        changed_fields = ["vehicle_id"]
        classification = MissionDriftClassification.UNKNOWN_CHANGE
    else:
        changed_fields = _changed_fields(submitted, current)
        categories = _categories(changed_fields)
        if not categories:
            classification = MissionDriftClassification.NO_CHANGE
        elif len(categories) == 1 and "route" in categories:
            classification = MissionDriftClassification.ROUTE_CHANGED
        elif len(categories) == 1 and "altitude" in categories:
            classification = MissionDriftClassification.ALTITUDE_CHANGED
        elif len(categories) == 1 and "time" in categories:
            classification = MissionDriftClassification.TIME_CHANGED
        elif categories == {"other"}:
            classification = MissionDriftClassification.NON_OPERATIONAL_CHANGE
        else:
            classification = MissionDriftClassification.UNKNOWN_CHANGE

    return MissionDriftReport(
        vehicle_id=submitted.vehicle_id,
        classification=classification,
        submitted_mission_hash=submitted.canonical_hash(),
        current_mission_hash=current.canonical_hash(),
        changed_fields=changed_fields,
    )


def _changed_fields(submitted: Mission, current: Mission) -> List[str]:
    changed: List[str] = []
    if submitted.valid_from != current.valid_from:
        changed.append("valid_from")
    if submitted.valid_until != current.valid_until:
        changed.append("valid_until")
    if submitted.corridor_radius_m != current.corridor_radius_m:
        changed.append("corridor_radius_m")
    if submitted.source != current.source:
        changed.append("source")

    for index, (submitted_waypoint, current_waypoint) in enumerate(
        zip(submitted.waypoints, current.waypoints, strict=False)
    ):
        if submitted_waypoint.sequence != current_waypoint.sequence:
            changed.append(f"waypoints[{index}].sequence")
        if submitted_waypoint.latitude != current_waypoint.latitude:
            changed.append(f"waypoints[{index}].latitude")
        if submitted_waypoint.longitude != current_waypoint.longitude:
            changed.append(f"waypoints[{index}].longitude")
        if submitted_waypoint.altitude.meters != current_waypoint.altitude.meters:
            changed.append(f"waypoints[{index}].altitude.meters")
        if submitted_waypoint.altitude.datum != current_waypoint.altitude.datum:
            changed.append(f"waypoints[{index}].altitude.datum")

    if len(submitted.waypoints) != len(current.waypoints):
        changed.append("waypoints.length")
    return changed


def _categories(changed_fields: List[str]) -> Set[str]:
    categories: Set[str] = set()
    for field in changed_fields:
        if field in {"valid_from", "valid_until"}:
            categories.add("time")
        elif field.endswith(".altitude.meters") or field.endswith(".altitude.datum"):
            categories.add("altitude")
        elif field.startswith("waypoints["):
            categories.add("route")
        else:
            categories.add("other")
    return categories
