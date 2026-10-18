#!/usr/bin/env python3
"""Validate every prepared page and write run-local delivery metadata.

This is a reusable replacement for story-specific finalizers. It never generates,
modifies, copies or packages images. --check-only performs no filesystem writes,
including temporary manifests or Python bytecode. Actual visual/story acceptance
must already exist; this program validates that evidence, never invents reviews.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from typing import Any

sys.dont_write_bytecode = True
import yaml

import production_delivery as delivery


def local(value: str | Path, root: Path) -> Path:
    path = delivery.resolve(str(value), root)
    if not path.is_relative_to(root):
        raise ValueError(f"run-local metadata path required: {path}")
    return path


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                     dir=path.parent, prefix=".production-finalize-",
                                     suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def finalize(run_root: Path, production_manifest: Path | None = None,
             generation_requests: Path | None = None, manifest_path: Path | None = None,
             output_manifest: Path | None = None, check_only: bool = False,
             diagnostic: bool = False) -> dict[str, Any]:
    """Validate a complete snapshot, optionally persist accepted metadata only."""
    root = Path(run_root).resolve()
    if not root.is_dir():
        raise ValueError("run root must already exist")
    source_manifest = local(manifest_path or (
        "delivery-input.pending.yaml" if (root / "delivery-input.pending.yaml").exists()
        else "delivery-input.yaml"), root)
    draft = delivery.load_mapping(source_manifest)
    draft_hash = delivery.sha256(source_manifest)
    accepted = copy.deepcopy(draft)
    production_path = local(production_manifest or draft.get("production_manifest_path", "production.yaml"), root)
    coverage_path = local(draft.get("content_coverage_path"), root)
    requests_path = local(generation_requests or draft.get("generation_requests_path",
                                                           coverage_path.parent / "generation-requests.json"), root)
    production = delivery.load_mapping(production_path)
    ids = [page.get("page_id") for page in production.get("pages", [])]
    if not ids or [p.get("page_id") for p in draft.get("pages", [])] != ids:
        raise ValueError("delivery draft must preserve the complete prepared page set and order")
    for page in accepted["pages"]:
        pid = page["page_id"]
        actual_plan = local(page.get("actual_text_plan", f"plans/actual/{pid}.yaml"), root)
        page["actual_text_plan"] = relative(actual_plan, root)
        page["actual_text_plan_sha256"] = delivery.sha256(actual_plan)
    source = local(draft.get("source_path"), root)
    story_value = draft.get("story_review")
    if not isinstance(story_value, str):
        raise ValueError("finalization requires a separately saved actual story review file")
    story_path = local(story_value, root)
    accepted.update({"production_manifest_path": relative(production_path, root),
                     "production_manifest_sha256": delivery.sha256(production_path),
                     "generation_requests_path": relative(requests_path, root),
                     "generation_requests_sha256": delivery.sha256(requests_path),
                     "source_sha256": delivery.sha256(source),
                     "coverage_sha256": delivery.sha256(coverage_path),
                     "story_review_sha256": delivery.sha256(story_path),
                     "expected_page_ids": ids, "text_policy": production.get("text_policy", "excerpts"),
                     "artifact_status": "ready_for_local_delivery", "base_image_modified": False,
                     "published": False})
    destination = local(output_manifest or "delivery-input.yaml", root)
    if (destination.parent != root or not destination.name.startswith("delivery-input")
            or destination.suffix not in (".yaml", ".yml", ".json")):
        raise ValueError("output manifest must be a delivery-input metadata file directly inside the run root")
    # All manifest paths use the run root. In-memory validation avoids the
    # temporary-file loophole that used to make --check-only write files.
    result = delivery.validate_manifest(destination, diagnostic=diagnostic, manifest_data=accepted)
    result.update({"writes_performed": False, "packaged": False, "published": False,
                   "base_image_modified": False, "check_only": check_only})
    if result["status"] != "passed":
        return result
    layouts, counts = [], []
    decision = delivery.load_mapping(local(production["storyboard_decision_path"], root))
    planned = {p["page_id"]: p for p in decision.get("pages", [])}
    for row, page in zip(result["pages"], accepted["pages"]):
        pid = row["page_id"]
        audit_path = local(page["final_layout_audit"], root) if page.get("final_layout_audit") else None
        audit = delivery.load_mapping(audit_path) if audit_path else delivery.load_mapping(
            local(page["render_report"], root))["final_layout_audit"]
        layout = {"page_id": pid, **{key: copy.deepcopy(audit[key]) for key in delivery.LAYOUT_FIELDS}}
        for key in ("adapted_target_match", "source_reference_geometry_match", "match_policy",
                    "execution_geometry_match", "execution_style_match", "text_container_execution_match",
                    "full_template_execution", "source_mapping_evidence", "preview_structure_match",
                    "preview_style_match", "source_pixel_reference_match"):
            if key in audit:
                layout[key] = copy.deepcopy(audit[key])
        layout.update({"base_image_sha256": row["base_image_sha256"],
                       "final_image_sha256": row["final_image_sha256"]})
        layouts.append(layout)
        planned_count = planned[pid].get("panel_count", len(planned[pid].get("panels", [])))
        if planned_count != row["actual_panel_count"]:
            result.update(status="blocked", errors=[{"scope": pid,
                "reason": "visible panel count differs from immutable handoff; explicit planning reconciliation required"}])
            return result
        counts.append({"page_id": pid, "planned_panel_count": planned_count,
                       "visible_panel_count": row["actual_panel_count"], "panel_count_delta": 0})
        page.update({"base_image_sha256": row["base_image_sha256"],
                     "final_image_sha256": row["final_image_sha256"],
                     "layout_id": row["selected_layout"], "panel_count": planned_count,
                     "final_image_count": 1, "generated_variants": 0,
                     "retained_final_image": f"{pid}-final.png"})
    panel_count = sum(p["visible_panel_count"] for p in counts)
    if "planned_panel_count" in decision and decision["planned_panel_count"] != panel_count:
        result.update(status="blocked", errors=[{"scope": "panel_count_reconciliation",
            "reason": "aggregate panel count differs from immutable storyboard handoff"}])
        return result
    reconciliation = {"status": "passed", "planned_panel_count": panel_count,
                      "visible_panel_count": panel_count, "panel_count_delta": 0,
                      "planning_counts_rewritten": False, "pages": counts}
    accepted.update(planned_panel_count=panel_count, visible_panel_count=panel_count,
                    panel_count_delta=0, panel_count_reconciliation=reconciliation)
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), "page_count": len(ids),
               "strict_source_match_counts": {status: sum(p["storyboard_layout_match"] == status for p in layouts)
                                               for status in ("passed", "failed", "pending")},
               "adapted_target_passed_count": sum(p.get("adapted_target_match") == "passed" for p in layouts),
               "pages": layouts, "base_image_modified": False, "published": False}
    result.update({"page_count": len(ids), "panel_count": panel_count,
                   "frozen_bindings_checked": len(result["frozen_bindings"]),
                   "strict_source_passed": summary["strict_source_match_counts"]["passed"],
                   "strict_source_failed": summary["strict_source_match_counts"]["failed"],
                   "adapted_target_passed": summary["adapted_target_passed_count"],
                   "manifest": str(destination)})
    if check_only:
        return result
    # A final freshness check happens before the first output write. The source
    # draft itself is also protected even though validation used an in-memory copy.
    if str(destination) in result["input_hashes"]:
        raise ValueError("output manifest may not overwrite a source, production proof or review input")
    report_paths = {name: local(root / "reports" / name, root) for name in (
        "storyboard-layout-summary.json", "panel-count-reconciliation.json",
        "final-delivery-preflight.json", "finalization-status.json")}
    if any(str(path) in result["input_hashes"] or path == source_manifest for path in report_paths.values()):
        raise ValueError("finalization report destination collides with an accepted input")
    snapshot = {**result["input_hashes"], str(source_manifest): draft_hash}
    for filename, expected in snapshot.items():
        if delivery.sha256(Path(filename)) != expected:
            raise ValueError("an accepted input changed during finalization; no metadata written")
    atomic_write(destination, yaml.safe_dump(accepted, allow_unicode=True, sort_keys=False))
    result.update(writes_performed=True, manifest_sha256=delivery.sha256(destination))
    for name, value in (("storyboard-layout-summary.json", summary),
                        ("panel-count-reconciliation.json", reconciliation),
                        ("final-delivery-preflight.json", result),
                        ("finalization-status.json", {key: value for key, value in result.items()
                                                       if key not in ("pages", "input_hashes", "text_integrity")})):
        atomic_write(report_paths[name], json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", "--run-dir", dest="run_root", type=Path, required=True)
    parser.add_argument("--production-manifest", type=Path)
    parser.add_argument("--generation-requests", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output-manifest", type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    try:
        result = finalize(args.run_root, args.production_manifest, args.generation_requests,
                          args.manifest, args.output_manifest, args.check_only, args.diagnostic)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        result = {"status": "blocked", "errors": [{"scope": "finalization", "reason": str(exc)}],
                  "writes_performed": False, "packaged": False, "base_image_modified": False,
                  "published": False}
    print(json.dumps({key: value for key, value in result.items()
                      if key not in ("pages", "input_hashes", "text_integrity", "frozen_bindings")},
                     ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
