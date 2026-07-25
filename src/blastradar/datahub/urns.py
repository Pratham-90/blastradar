"""Small pure helpers for reading DataHub URNs. No network, no SDK imports."""

from __future__ import annotations


def urn_type(urn: str) -> str:
    """Entity type token of a URN (``urn:li:<type>:...`` -> ``<type>``)."""
    parts = urn.split(":", 3)
    return parts[2] if len(parts) >= 3 else ""


def dataset_platform(urn: str) -> str:
    """Platform of a dataset/schemaField URN (``...dataPlatform:<p>,...`` -> ``<p>``)."""
    marker = "dataPlatform:"
    return urn.split(marker, 1)[1].split(",", 1)[0] if marker in urn else ""


def dataset_name(urn: str) -> str:
    """The dataset name inside a dataset URN (the part between the first two commas)."""
    if "," not in urn:
        return urn
    return urn.split(",")[1]


def short_name(urn: str) -> str:
    """A readable short name: last dotted/slashed segment of a URN's name part.

    Strips a trailing ``)`` so mlFeature URNs like ``(customer_features,days_since_signup)``
    render as ``days_since_signup`` rather than ``days_since_signup)``.
    """
    name = dataset_name(urn)
    return name.split(".")[-1].split("/")[-1].rstrip(")")


def last_segment(name: str) -> str:
    """Last dotted/slashed segment of a plain (non-URN) table name."""
    return name.split(".")[-1].split("/")[-1]


def simple_name(urn: str) -> str:
    """Name of a simple ``urn:li:<type>:<name>`` URN (tag, corpGroup, corpuser).

    ``urn:li:tag:Tier1`` -> ``Tier1``; ``urn:li:corpGroup:ml-platform`` -> ``ml-platform``.
    """
    return urn.split(":")[-1]


def dataset_of_schema_field(schema_field_urn: str) -> str | None:
    """Extract the parent dataset URN from a schemaField URN.

    ``urn:li:schemaField:(urn:li:dataset:(...,PROD),customer_since)`` ->
    ``urn:li:dataset:(...,PROD)``. Returns None if the shape is not a schemaField URN.
    """
    if not schema_field_urn.startswith("urn:li:schemaField:("):
        return None
    inner = schema_field_urn[schema_field_urn.index("(") + 1 : schema_field_urn.rfind(")")]
    # inner == "<dataset_urn>,<field>"; the dataset URN ends at the last top-level comma.
    cut = inner.rfind(",")
    return inner[:cut] if cut != -1 else None
