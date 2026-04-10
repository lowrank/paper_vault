"""Shared utility helpers."""
from typing import Any, Dict, Optional


def extract_version_id(info: Dict[str, Any]) -> Optional[str]:
    """Extract version ID from paper info dict, handling both API field name variants."""
    return info.get("versionId") or info.get("version_id")
