"""Region profiles: saved region sets, independent of any document, for
reusing layout rules across a document series. JSON files in the app data
profiles directory."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from rewriteocr.config import profiles_dir
from rewriteocr.core.models import Region


class ProfileError(Exception):
    pass


@dataclass
class RegionProfile:
    name: str
    description: str
    regions: list[Region]


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\- ]", "", name).strip().replace(" ", "-")
    if not cleaned:
        raise ProfileError("Profile name must contain letters or digits.")
    return cleaned + ".json"


def save_profile(name: str, description: str, regions: list[Region]) -> Path:
    path = profiles_dir() / _safe_filename(name)
    data = {
        "name": name,
        "description": description,
        "regions": [
            {
                "scope": r.scope, "scope_arg": r.scope_arg, "kind": r.kind,
                "heading_level": r.heading_level, "order_index": r.order_index,
                "x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1,
            }
            for r in regions
        ],
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def list_profiles() -> list[RegionProfile]:
    out: list[RegionProfile] = []
    for path in sorted(profiles_dir().glob("*.json")):
        try:
            out.append(load_profile(path))
        except ProfileError:
            continue
    return out


def load_profile(path: Path) -> RegionProfile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        regions = [
            Region(
                scope=r["scope"], scope_arg=r.get("scope_arg"), kind=r["kind"],
                heading_level=r.get("heading_level"),
                order_index=r["order_index"],
                x0=r["x0"], y0=r["y0"], x1=r["x1"], y1=r["y1"],
            )
            for r in data.get("regions", [])
        ]
        return RegionProfile(
            name=data.get("name", path.stem),
            description=data.get("description", ""),
            regions=regions,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ProfileError(f"Could not read profile {path.name}: {exc}") from exc
