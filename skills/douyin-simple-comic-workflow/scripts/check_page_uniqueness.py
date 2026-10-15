#!/usr/bin/env python3
"""Check that a run delivers one final image per story page.

This is a metadata and filesystem check. It does not inspect pixels and it does
not generate, rename, or delete images. Retry renders belong in a page's
candidate directory; only the retained canonical ``<page_id>-final.png`` may be
listed in a delivery manifest.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


PAGE_ID_RE = re.compile(r"^(P\d+)$", re.IGNORECASE)
CANONICAL_FINAL_RE = re.compile(r"^(P\d+)-final\.png$", re.IGNORECASE)
VERSIONED_FINAL_RE = re.compile(r"^(P\d+)-final-v\d+\.png$", re.IGNORECASE)


def _as_int(value: Any, default: int | None = None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"manifest must contain a mapping: {path}")
    return value


def _story_beat_ids(page: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("story_beat_id", "story_beat_ids"):
        value = page.get(key)
        if isinstance(value, str) and value:
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str) and item)
    # A page storyboard often carries several required beats while the
    # delivery entry keeps one dominant ``story_beat_id``.  Use the planning
    # field only when the delivery entry did not copy an explicit ID.
    if not values:
        value = page.get("required_story_beats")
        if isinstance(value, str) and value:
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str) and item)
    # A delivery entry may carry both the dominant ID and the complete list;
    # do not count that repeated serialization as a second story occurrence.
    return list(dict.fromkeys(values))


def _normalise(value: Any) -> str:
    """Make panel metadata comparable without changing its source value."""

    if isinstance(value, (list, tuple, set)):
        parts = [_normalise(item) for item in value]
        return ",".join(sorted(part for part in parts if part))
    if isinstance(value, dict):
        return ",".join(
            f"{key}={_normalise(value[key])}"
            for key in sorted(value)
            if _normalise(value[key])
        )
    return str(value or "").strip().casefold()


def _panel_signature(panel: dict[str, Any]) -> tuple[str, str, str, str] | None:
    """Return action/expression/props/camera metadata for duplicate detection.

    Text is intentionally not part of this signature: changing a line of
    dialogue without changing the visible action, expression, prop, or camera
    still needs human review instead of silently becoming another formal page.
    """

    action = panel.get("visual_action", panel.get("action", ""))
    expression = panel.get("expression", panel.get("emotion", ""))
    props = panel.get(
        "key_objects",
        panel.get("props", panel.get("key_props", panel.get("objects", ""))),
    )
    camera = panel.get(
        "camera_function",
        panel.get("camera", panel.get("shot", "")),
    )
    values = tuple(_normalise(value) for value in (action, expression, props, camera))
    return values if any(values) else None


def _scan_final_files(run_dir: Path) -> dict[str, list[str]]:
    final_dir = run_dir / "pages" / "final"
    groups: dict[str, list[str]] = defaultdict(list)
    if not final_dir.is_dir():
        return groups
    for path in sorted(final_dir.glob("*.png")):
        match = CANONICAL_FINAL_RE.match(path.name) or VERSIONED_FINAL_RE.match(path.name)
        if match:
            groups[match.group(1).upper()].append(path.name)
    return groups


def check_manifest(run_dir: Path, manifest: dict[str, Any], allow_variants: bool = False) -> dict[str, Any]:
    pages = manifest.get("pages")
    errors: list[str] = []
    warnings: list[str] = []
    results: list[dict[str, Any]] = []
    if not isinstance(pages, list):
        return {"status": "failed", "errors": ["manifest.pages must be a list"], "warnings": [], "pages": []}

    seen_page_ids: set[str] = set()
    manifest_variants_requested = bool(manifest.get("variants_requested", False))
    variants_allowed = allow_variants or manifest_variants_requested
    beat_to_pages: dict[str, list[str]] = defaultdict(list)
    for raw_page in pages:
        if not isinstance(raw_page, dict):
            errors.append("each manifest page must be a mapping")
            continue
        page_id = str(raw_page.get("page_id", "")).upper()
        if not PAGE_ID_RE.match(page_id):
            errors.append(f"invalid page_id: {page_id!r}")
            continue
        if page_id in seen_page_ids:
            errors.append(f"duplicate page_id in manifest: {page_id}")
        seen_page_ids.add(page_id)

        final_count = _as_int(raw_page.get("final_image_count"))
        variants = _as_int(raw_page.get("generated_variants"))
        retained = raw_page.get("retained_final_image")
        final_path = raw_page.get("final_image")
        page_errors: list[str] = []
        page_warnings: list[str] = []
        if final_count != 1:
            page_errors.append("final_image_count must equal 1")
        if variants is None:
            page_errors.append("generated_variants is required")
        elif variants < 0:
            page_errors.append("generated_variants must be non-negative")
        elif variants != 0 and not variants_allowed:
            page_errors.append("generated_variants must equal 0 unless variants are explicitly requested")
        expected_name = f"{page_id}-final.png"
        if retained != expected_name:
            page_errors.append(f"retained_final_image must be {expected_name}")
        if isinstance(final_path, str):
            if Path(final_path).name != expected_name:
                page_errors.append("final_image must point to the canonical final filename")
            elif not (run_dir / final_path).is_file():
                page_errors.append(f"retained final image does not exist: {final_path}")
        else:
            page_errors.append("final_image is required")

        candidate_images = raw_page.get("candidate_images", [])
        if candidate_images is None:
            candidate_images = []
        if not isinstance(candidate_images, list):
            page_errors.append("candidate_images must be a list when present")
            candidate_images = []
        expected_prefix = ("pages", "candidates", page_id)
        for candidate in candidate_images:
            if not isinstance(candidate, str):
                page_errors.append("candidate_images entries must be relative paths")
                continue
            candidate_path = Path(candidate)
            if candidate_path.is_absolute() or candidate_path.parts[:3] != expected_prefix:
                page_errors.append(f"candidate must stay under pages/candidates/{page_id}: {candidate}")
            elif not (run_dir / candidate_path).is_file():
                page_errors.append(f"candidate image does not exist: {candidate}")

        discarded_candidates = raw_page.get("discarded_candidates", [])
        if discarded_candidates is None:
            discarded_candidates = []
        if not isinstance(discarded_candidates, list):
            page_errors.append("discarded_candidates must be a list when present")
            discarded_candidates = []
        for discarded in discarded_candidates:
            if not isinstance(discarded, str):
                page_errors.append("discarded_candidates entries must be relative paths")
                continue
            discarded_path = Path(discarded)
            if discarded_path.is_absolute():
                page_errors.append(f"discarded candidate must be a relative path: {discarded}")
            elif discarded == final_path:
                page_errors.append("retained final image cannot also be discarded")

        candidate_count = _as_int(raw_page.get("candidate_image_count"))
        if candidate_count is None:
            candidate_count = len(candidate_images) + len(discarded_candidates)
            page_warnings.append("candidate_image_count missing; computed from candidate records")
        elif candidate_count < 0:
            page_errors.append("candidate_image_count must be non-negative")
        elif candidate_count < len(candidate_images) + len(discarded_candidates):
            page_errors.append("candidate_image_count is smaller than recorded candidate files")

        beats = _story_beat_ids(raw_page)
        for beat in beats:
            beat_to_pages[beat].append(page_id)

        adjacent_duplicates: list[str] = []
        panels = raw_page.get("panels", [])
        if isinstance(panels, list):
            signatures = [_panel_signature(panel) if isinstance(panel, dict) else None for panel in panels]
            for index in range(1, len(signatures)):
                if signatures[index] is not None and signatures[index] == signatures[index - 1]:
                    adjacent_duplicates.append(f"{index - 1}->{index}")
        duplicate_story_check = "needs_review" if adjacent_duplicates else "passed"
        declared_duplicate_check = raw_page.get("duplicate_story_check")
        if declared_duplicate_check == "passed" and duplicate_story_check == "needs_review":
            page_errors.append("duplicate_story_check cannot be passed when adjacent panels repeat")
        elif declared_duplicate_check not in (None, "passed", "needs_review"):
            page_errors.append("duplicate_story_check must be passed or needs_review")
        if page_errors:
            errors.extend(f"{page_id}: {message}" for message in page_errors)
        warnings.extend(f"{page_id}: {message}" for message in page_warnings)
        results.append(
            {
                "page_id": page_id,
                "story_beat_id": beats[0] if beats else None,
                "story_beat_ids": beats,
                "final_image_count": final_count,
                "candidate_image_count": candidate_count,
                "generated_variants": variants,
                "duplicate_story_check": duplicate_story_check,
                "adjacent_panel_duplicates": adjacent_duplicates,
                "retained_final_image": retained,
                "candidate_images": candidate_images,
                "discarded_candidates": discarded_candidates,
                "errors": page_errors,
                "warnings": page_warnings,
            }
        )

    for beat, page_ids in sorted(beat_to_pages.items()):
        distinct = sorted(set(page_ids))
        if len(distinct) > 1:
            warnings.append(f"story beat {beat} appears on multiple pages: {', '.join(distinct)}")
            for result in results:
                if result["page_id"] in distinct:
                    result["duplicate_story_check"] = "needs_review"

    status = "failed" if errors else ("needs_review" if warnings or any(r["duplicate_story_check"] == "needs_review" for r in results) else "passed")
    return {
        "status": status,
        "variants_requested": manifest_variants_requested,
        "errors": errors,
        "warnings": warnings,
        "pages": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--allow-variants", action="store_true", help="Only use when the user explicitly requested variants")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of YAML")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    manifest_path = args.manifest.resolve()
    manifest = _load_yaml(manifest_path)
    result = check_manifest(run_dir, manifest, allow_variants=args.allow_variants)

    filesystem = _scan_final_files(run_dir)
    legacy_variants = {
        page_id: names
        for page_id, names in filesystem.items()
        if len(names) > 1 or any(not CANONICAL_FINAL_RE.match(name) for name in names)
    }
    result["filesystem_final_scan"] = {
        "final_directory": str((run_dir / "pages" / "final").resolve()),
        "files_by_page": dict(filesystem),
        "legacy_or_unfiltered_variants": legacy_variants,
        "status": "needs_review" if legacy_variants else "passed",
    }
    if legacy_variants:
        result["errors"].append("versioned or multiple files exist in pages/final; retries must be moved to pages/candidates and excluded from delivery")
        result["status"] = "failed"

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
