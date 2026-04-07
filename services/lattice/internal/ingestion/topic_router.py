from __future__ import annotations


def topic_for_metric_name(metric_name: str) -> str:
    """
    Route canonical Lattice metrics to stable domain topics.

    This keeps Kafka topics predictable and lets downstream consumers
    subscribe only to the domains they care about.
    """
    if metric_name.startswith("lattice_bgp_"):
        return "lattice.telemetry.bgp"

    if metric_name.startswith("lattice_interface_"):
        return "lattice.telemetry.interfaces"

    if metric_name.startswith("lattice_optics_"):
        return "lattice.telemetry.optics"

    if metric_name.startswith("lattice_system_"):
        return "lattice.telemetry.system"

    return "lattice.telemetry.enriched"
