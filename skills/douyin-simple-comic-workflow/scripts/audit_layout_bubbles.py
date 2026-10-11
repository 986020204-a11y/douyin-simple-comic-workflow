"""Audit bundled SB descriptions against the layout-to-bubble adapter.

The audit is deliberately conservative: it records only text found in the
bundled SB markdown.  It does not inspect preview pixels or infer a shape,
position, tail, or writable area from an image.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml


EXPECTED_IDS = [f"SB-{index:03d}" for index in range(1, 69)]
EVIDENCE_TERMS = {
    "bubble_shape": re.compile(r"bubble|balloon|气泡|对话框", re.I),
    "bubble_position": re.compile(r"speech bubbles?\s+(?:for|over|within)|floating freely|white space|negative space|organic reading zones", re.I),
    "tail": re.compile(r"(?<!to-)\btails?\b|\bconnector\b|point(?:ed|ing)\s+(?:to|toward)", re.I),
    "text_whitespace": re.compile(r"white space|negative space|blank|caption|lettering|sparse dialogue|empty", re.I),
    "text_semantics": re.compile(r"dialogue|verbal|psychological duel|captions?|speech balloons?|comic thoughts?|phone messaging|lettering", re.I),
}


def _lines_for(pattern: re.Pattern[str], text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if pattern.search(line)]


def audit(layout_dir: Path, output: Path | None = None) -> dict[str, Any]:
    index_path = layout_dir / "layouts.json"
    map_path = layout_dir / "bubble-constraints.yaml"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    profiles_data = yaml.safe_load(map_path.read_text(encoding="utf-8")) or {}
    profiles = {item.get("layout_id"): item for item in profiles_data.get("profiles", [])}
    index_ids = [item.get("id") for item in index] if isinstance(index, list) else []
    errors: list[str] = []
    if len(index) != 68 or sorted(index_ids) != EXPECTED_IDS:
        errors.append("layouts.json is not the exact 68-entry SB pool")
    if sorted(profiles) != EXPECTED_IDS:
        errors.append("bubble-constraints.yaml does not contain exactly SB-001..SB-068")

    entries: list[dict[str, Any]] = []
    for layout_id in EXPECTED_IDS:
        source_path = layout_dir / f"{layout_id}.md"
        profile = profiles.get(layout_id, {})
        text = source_path.read_text(encoding="utf-8") if source_path.exists() else ""
        evidence: dict[str, Any] = {}
        for dimension, pattern in EVIDENCE_TERMS.items():
            matches = _lines_for(pattern, text)
            evidence[dimension] = {"status": "explicit" if matches else "missing", "source_lines": matches}
        explicit_dimensions = [name for name, value in evidence.items() if value["status"] == "explicit"]
        missing_dimensions = [name for name, value in evidence.items() if value["status"] == "missing"]
        source_level = profile.get("source_rule_level", "missing-profile")
        if source_level == "explicit" and not explicit_dimensions:
            errors.append(f"{layout_id}: map says explicit but audit found no source wording")
        if source_level == "none" and explicit_dimensions:
            errors.append(f"{layout_id}: map says none but audit found {explicit_dimensions}")
        entries.append(
            {
                "layout_id": layout_id,
                "layout_name_en": profile.get("layout_name_en"),
                "source_file": str(source_path),
                "source_rule_level": source_level,
                "source_evidence_from_map": profile.get("source_evidence"),
                "source_dimensions": evidence,
                "explicit_dimensions": explicit_dimensions,
                "missing_reference_dimensions": missing_dimensions,
                "adaptation_rule": profile.get("adaptation_rule"),
                "placement_constraints": profile.get("placement_constraints", []),
            }
        )

    result = {
        "audit": "douyin-simple-comic-workflow layout bubble audit",
        "schema_version": "0.2-draft",
        "layout_index": str(index_path),
        "bubble_map": str(map_path),
        "index_count": len(index),
        "profile_count": len(profiles),
        "source_boundary": "Only wording in the SB markdown is source evidence. Preview-only appearance is not claimed as recovered rule.",
        "classification": {
            "source_rule": "source_rule_level=explicit plus matching source wording",
            "adaptation_rule": "profile.adaptation_rule and placement_constraints are workflow additions",
            "missing_reference": "a dimension with no matching source wording; generic rules only",
        },
        "entries": entries,
        "summary": {
            "source_explicit_layouts": [item["layout_id"] for item in entries if item["source_rule_level"] == "explicit"],
            "no_sb_specific_bubble_evidence": [item["layout_id"] for item in entries if item["source_rule_level"] == "none"],
            "source_shape_mentions": [item["layout_id"] for item in entries if item["source_dimensions"]["bubble_shape"]["status"] == "explicit"],
            "source_position_mentions": [item["layout_id"] for item in entries if item["source_dimensions"]["bubble_position"]["status"] == "explicit"],
            "source_tail_mentions": [item["layout_id"] for item in entries if item["source_dimensions"]["tail"]["status"] == "explicit"],
            "source_text_whitespace_mentions": [item["layout_id"] for item in entries if item["source_dimensions"]["text_whitespace"]["status"] == "explicit"],
        },
        "validation": {"status": "valid" if not errors else "invalid", "errors": errors},
    }
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout-dir", default=str(Path(__file__).resolve().parents[1] / "references" / "comic-layouts"))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(Path(args.layout_dir), Path(args.output))
    print(json.dumps({"status": result["validation"]["status"], "entries": len(result["entries"]), "output": args.output}, ensure_ascii=False))


if __name__ == "__main__":
    main()
