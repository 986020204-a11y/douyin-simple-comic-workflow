#!/usr/bin/env python3
"""Validate a complete comic set once, then build a portable local delivery.

No image generation, image modification, publication, or semantic image analysis
occurs here. Hash-bound producer evidence and an explicit visual/story review are
required. Metadata coverage is reported separately from semantic story coverage.

Manifest: source_path, content_coverage_path, story_review (mapping or file path),
pages:[{page_id,base_image,final_image,base_audit,render_report,bubble_audit,
visual_review,final_layout_audit}]. Paths resolve relative to the manifest.
The final layout audit may instead be an inline mapping in the render report.
Visual review uses the same seven checks as production_queue's pilot review.
Use --check-only for aggregation without any delivery writes. --diagnostic permits
explicit diagnostic_test_only fixtures and labels every resulting artifact.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any
import zipfile

sys.dont_write_bytecode = True
from PIL import Image, ImageChops
import yaml
from template_contract import executable_text_containers
from production_queue import validate_visual_provenance, _glyph_evidence_valid, _validate_storyboard_rhythm


VERSION = "1.2"
LAYOUT_FIELDS = (
    "selected_layout", "target_panel_count", "actual_panel_count",
    "target_panel_geometry", "actual_panel_geometry", "reading_order_match",
    "storyboard_layout_match", "layout_deviation", "base_image_modified",
)
REVIEW_CHECKS = (
    "full_size_readability", "character_continuity", "speaker_binding",
    "text_integrity", "critical_occlusion", "full_template_execution",
    "execution_style_match",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"mapping required: {path}")
    return value


def resolve(value: Any, root: Path) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("a nonempty file path is required")
    path = Path(value)
    return (path if path.is_absolute() else root / path).resolve()


def passed(value: Any) -> bool:
    return value is True or value == "passed"


def _diagnostic(value: Any) -> bool:
    if isinstance(value, dict):
        return value.get("diagnostic_test_only") is True or any(_diagnostic(v) for v in value.values())
    return isinstance(value, list) and any(_diagnostic(v) for v in value)


def _rect(row: dict[str, Any]) -> tuple[float, float, float, float]:
    if all(key in row for key in ("x", "y", "width", "height")):
        values = [row[key] for key in ("x", "y", "width", "height")]
    elif row.get("rect_format") == "xywh" and isinstance(row.get("bounds"), list):
        values = row["bounds"]
    else:
        raise ValueError("panel geometry requires explicit pixel xywh")
    if len(values) != 4 or any(isinstance(v, bool) for v in values):
        raise ValueError("invalid panel xywh")
    numbers = tuple(float(v) for v in values)
    if any(not math.isfinite(v) for v in numbers) or min(numbers[2:]) <= 0:
        raise ValueError("nonfinite or empty panel geometry")
    return numbers


def _geometry(report: dict[str, Any], base_hash: str) -> None:
    if any(field not in report for field in LAYOUT_FIELDS) or not report.get("selected_layout"):
        raise ValueError("layout audit lacks required layout fields or selected_layout")
    evidence = report.get("measurement_evidence") or {}
    if (report.get("image_geometry_measurement_verified") is not True
            or evidence.get("geometry_observed_from_image") is not True
            or evidence.get("image_sha256") != base_hash):
        raise ValueError("missing actual hash-bound base geometry evidence")
    count = report.get("target_panel_count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("invalid target_panel_count")
    actual, target = report.get("actual_panel_geometry"), report.get("target_panel_geometry")
    if (report.get("actual_panel_count") != count or not isinstance(actual, list)
            or not isinstance(target, list) or len(actual) != count or len(target) != count):
        raise ValueError("actual/target panel counts and geometry lengths disagree")
    for rows in (actual, target):
        ids = [row.get("panel_id") or row.get("unit_id") for row in rows]
        orders = [row.get("order") for row in rows]
        if None in ids or len(set(ids)) != count or sorted(orders) != list(range(1, count + 1)):
            raise ValueError("panel IDs must be unique and reading order continuous")
    expected = {(r.get("panel_id") or r.get("unit_id")): r for r in target}
    for row in actual:
        key = row.get("panel_id") or row.get("unit_id")
        if key not in expected or row["order"] != expected[key]["order"]:
            raise ValueError("actual reading order/panel identity differs from target")
        if any(abs(a - b) > 1.01 for a, b in zip(_rect(row), _rect(expected[key]))):
            raise ValueError("actual panel bounds differ from approved target")
        if row.get("geometry_type", "rect") != expected[key].get("geometry_type", "rect"):
            raise ValueError("actual panel geometry type differs from target")
        for field in ("polygon", "vertices", "points"):
            if field in row or field in expected[key]:
                if row.get(field) != expected[key].get(field):
                    raise ValueError("actual nonrectangular panel boundary differs from target")
    if (not passed(report.get("reading_order_match"))
            or report.get("execution_geometry_match") != "passed"
            or report.get("base_image_modified") is not False):
        raise ValueError("base layout/order was not passed, or base modification is undeclared")
    if report.get("synthetic") is True or report.get("synthetic_input") is True:
        raise ValueError("synthetic proof cannot stand in for actual base audit")
    if report.get("match_policy") == "adapted":
        if report.get("user_approved_adaptation") is not True or report.get("adapted_target_match") != "passed":
            raise ValueError("adapted target lacks explicit approval and successful execution")
        if (report.get("source_reference_geometry_match") != "passed"
                and report.get("storyboard_layout_match") != "failed"):
            raise ValueError("source mismatch must remain storyboard_layout_match: failed")
    elif report.get("storyboard_layout_match") != "passed":
        raise ValueError("original storyboard did not pass")


def _generation_inputs(manifest: dict[str, Any], root: Path, ids: list[str],
                       source: Path, coverage: Path, bind: Any,
                       diagnostic: bool = False) -> dict[str, Any] | None:
    """Check the immutable source/handoff/plan/target preparation snapshot.

    Legacy manifests can use production.yaml beside the manifest and the
    generation-requests.json beside coverage. This is discovery, not a bypass:
    missing or stale bindings block production packaging.
    """
    explicit = manifest.get("production_manifest_path") or manifest.get("generation_requests_path")
    if diagnostic and not explicit:
        return None
    production_path = resolve(manifest.get("production_manifest_path", "production.yaml"), root)
    request_path = resolve(manifest.get("generation_requests_path", str(coverage.parent / "generation-requests.json")), root)
    production = load_mapping(production_path)
    requests = load_mapping(request_path)
    bind(production_path)
    bind(request_path)
    for field, path in (("production_manifest_sha256", production_path),
                        ("generation_requests_sha256", request_path)):
        if field in manifest and manifest[field] != sha256(path):
            raise ValueError(f"{field} is stale")
    prepared = production.get("pages")
    request_pages = requests.get("pages")
    if (not isinstance(prepared, list) or not isinstance(request_pages, list)
            or [p.get("page_id") for p in prepared] != ids
            or [p.get("page_id") for p in request_pages] != ids
            or requests.get("expected_page_ids") != ids):
        raise ValueError("production/request page set or order differs from the complete preparation")
    if resolve(production.get("source_path"), production_path.parent) != source:
        raise ValueError("delivery source differs from the frozen production source")
    decision = resolve(production.get("storyboard_decision_path"), production_path.parent)
    decision_hash = bind(decision)
    coverage_binding = load_mapping(coverage).get("storyboard_binding") or {}
    if (resolve(coverage_binding.get("path"), coverage.parent) != decision
            or coverage_binding.get("sha256") != decision_hash):
        raise ValueError("coverage and production bind different storyboard handoffs")
    if not diagnostic:
        rhythm = _validate_storyboard_rhythm(requests.get('storyboard_rhythm_binding'),
                                             request_path.parent, expected_page_ids=ids)
        if rhythm['decision_path'] != decision:
            raise ValueError('Delivery and rhythm audit bind different storyboard handoffs')
        bind(rhythm['report_path'])
    policy = production.get("text_policy", "excerpts")
    if policy not in ("excerpts", "verbatim"):
        raise ValueError("unknown production text policy")
    frozen, pages = [], {}
    for page, requested in zip(prepared, request_pages):
        pid = page["page_id"]
        proof = requested.get("proof") or {}
        proof_path = resolve(proof.get("report_path"), request_path.parent)
        if bind(proof_path) != proof.get("sha256"):
            raise ValueError(f"{pid}: preparation readiness proof changed")
        readiness = load_mapping(proof_path)
        if readiness.get("generation_ready") is not True or readiness.get("page_id") != pid:
            raise ValueError(f"{pid}: complete text preparation is not ready")
        if not diagnostic and readiness.get('storyboard_rhythm_binding') != requests.get('storyboard_rhythm_binding'):
            raise ValueError(f'{pid}: preparation differs from the audited whole-story rhythm')
        supplied = readiness.get("input_bindings")
        if not isinstance(supplied, list):
            raise ValueError(f"{pid}: readiness input bindings missing")
        table = {}
        for item in supplied:
            path = resolve(item.get("path"), proof_path.parent)
            if path in table:
                raise ValueError(f"{pid}: duplicate readiness binding")
            table[path] = item.get("sha256")
        if not diagnostic and table.get(rhythm['report_path']) != sha256(rhythm['report_path']):
            raise ValueError(f'{pid}: readiness inputs do not bind the current whole-story rhythm audit')
        paths = {"text_plan_path": resolve(page.get("text_plan_path"), production_path.parent),
                 "template_path": resolve(page.get("template_path"), production_path.parent),
                 "text_layout_path": resolve(page.get("text_layout_path"), production_path.parent)}
        if resolve(requested.get("template_path"), request_path.parent) != paths["template_path"]:
            raise ValueError(f"{pid}: request target differs from frozen production target")
        for kind, path in {"source_path": source, "storyboard_decision_path": decision, **paths}.items():
            actual = bind(path)
            if table.get(path) != actual:
                raise ValueError(f"{pid}: frozen {kind} changed or has no preparation binding")
            if kind in ("text_plan_path", "template_path"):
                frozen.append({"page_id": pid, "kind": kind, "path": str(path),
                               "sha256": actual, "status": "passed"})
        target, plan = load_mapping(paths["template_path"]), load_mapping(paths["text_plan_path"])
        if not diagnostic:
            selected = next(p for p in rhythm['decision']['pages'] if p['page_id'] == pid)
            if target.get('layout_id') != selected.get('layout_id'):
                raise ValueError(f'{pid}: delivery target differs from the audited page layout')
        config = load_mapping(paths["text_layout_path"])
        minimum = config.get("minimum_readable_font_size", 24)
        if (isinstance(minimum, bool) or not isinstance(minimum, (int, float))
                or not math.isfinite(minimum) or minimum <= 0):
            raise ValueError(f"{pid}: minimum_readable_font_size must be a positive finite number")
        if (plan.get("page_id") != pid or not target.get("layout_id")
                or plan.get("layout_id", plan.get("selected_layout")) != target["layout_id"]):
            raise ValueError(f"{pid}: frozen plan/target identity disagrees")
        pages[pid] = {**paths, "plan": plan, "template": target,
                     "minimum_readable_font_size": minimum}
    return {"pages": pages, "bindings": frozen, "text_policy": policy,
            "production_manifest_path": str(production_path), "generation_requests_path": str(request_path)}


def _text_integrity(page: dict[str, Any], root: Path, frozen: dict[str, Any],
                    render: dict[str, Any], source: Path, base_hash: str,
                    final_hash: str, bind: Any, policy: str) -> dict[str, Any]:
    pid = page["page_id"]
    plan_path = resolve(page.get("actual_text_plan", f"plans/actual/{pid}.yaml"), root)
    plan_hash = bind(plan_path)
    plan = load_mapping(plan_path)
    if (plan.get("page_id") != pid or plan.get("actual_image_checked") is not True
            or plan.get("synthetic", plan.get("synthetic_input")) is not False
            or plan.get("base_image_sha256") != base_hash):
        raise ValueError(f"{pid}: actual text plan is missing real-image/hash evidence")
    if page.get("actual_text_plan_sha256", plan_hash) != plan_hash:
        raise ValueError(f"{pid}: actual text plan binding is stale")
    for field, path in (("generation_plan", frozen["text_plan_path"]),
                        ("generation_template", frozen["template_path"])):
        if f"{field}_path" in plan and (resolve(plan[f"{field}_path"], plan_path.parent) != path
                                         or plan.get(f"{field}_sha256") != sha256(path)):
            raise ValueError(f"{pid}: actual plan has a stale {field} binding")
    original = frozen["plan"].get("text_blocks")
    blocks, raster = plan.get("text_blocks"), render.get("rendered_blocks")
    if (not isinstance(blocks, list) or not blocks or not isinstance(original, list)
            or not isinstance(raster, list) or len(blocks) != len(original) or len(raster) != len(blocks)):
        raise ValueError(f"{pid}: frozen/actual/rendered text block counts disagree")
    ids = [b.get("id") for b in blocks]
    if not all(ids) or len(set(ids)) != len(ids) or ids != [b.get("id") for b in original]:
        raise ValueError(f"{pid}: text IDs/order differ from the frozen generation plan")
    rendered = {b.get("id"): b for b in raster}
    if set(rendered) != set(ids) or len(rendered) != len(raster):
        raise ValueError(f"{pid}: rendered text IDs are missing or duplicated")
    article = source.read_text(encoding="utf-8-sig")
    panel_ids = {p.get("panel_id") for p in frozen["template"].get("panels", [])}
    minimum = frozen["minimum_readable_font_size"]
    rows = []
    immutable = ("id", "bubble_id", "text", "type", "source_type", "speaker", "panel_id", "source_article_range")
    for old, block in zip(original, blocks):
        bid = block["id"]
        if any(old.get(k) != block.get(k) for k in immutable):
            raise ValueError(f"{pid}/{bid}: text, channel, speaker, source or panel differs from frozen preparation")
        if block.get("panel_id") == "CANVAS":
            _canvas_text_owner(frozen["template"], block, pid, bid)
        elif block.get("panel_id") not in panel_ids:
            raise ValueError(f"{pid}/{bid}: text binds a nonexistent frozen panel")
        span = block.get("source_article_range")
        if policy in ("excerpts", "verbatim"):
            if (not isinstance(span, list) or len(span) != 2
                    or any(isinstance(v, bool) or not isinstance(v, int) for v in span)
                    or not 0 <= span[0] < span[1] <= len(article)
                    or block.get("source_excerpt_verbatim") is not True
                    or article[span[0]:span[1]] != block.get("text")):
                raise ValueError(f"{pid}/{bid}: exact approved-source excerpt does not match")
        rb = rendered[bid]
        if (rb.get("rendered") is not True or rb.get("text") != block.get("text")
                or rb.get("type") != block.get("type") or rb.get("speaker") != block.get("speaker")
                or rb.get("panel_id") != block.get("panel_id")):
            raise ValueError(f"{pid}/{bid}: rendered text/channel/speaker/panel differs from actual plan")
        font = rb.get("font_raster_evidence") or {}
        sizes = rb.get("actual_font_sizes")
        if (font.get("retained_in_output") is not True or font.get("output_image_sha256") != final_hash
                or font.get("base_image_sha256") != base_hash or not isinstance(sizes, list)
                or not sizes or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                    or not math.isfinite(v) or v < minimum for v in sizes)):
            raise ValueError(f"{pid}/{bid}: readable actual glyph evidence does not bind both images")
        font_policy = block.get("font_size_policy", "fixed")
        if font_policy not in ("fixed", "fit"):
            raise ValueError(f"{pid}/{bid}: unknown font size policy")
        if font_policy == "fixed" and (set(sizes) != {block.get("font_size")} or rb.get("font_size_adjusted") is not False):
            raise ValueError(f"{pid}/{bid}: silently changed a fixed font size")
        rows.append({"block_id": bid, "panel_id": block["panel_id"], "source_article_range": span,
                     "source_excerpt_match": "passed", "actual_font_sizes": sizes})
    return {"status": "passed", "actual_text_plan": str(plan_path), "sha256": plan_hash,
            "text_policy": policy, "minimum_readable_font_size": minimum,
            "text_layout_path": str(frozen["text_layout_path"]),
            "text_layout_sha256": sha256(frozen["text_layout_path"]),
            "text_block_count": len(rows), "blocks": rows}


def _canvas_text_owner(template: dict[str, Any], block: dict[str, Any], pid: str, bid: str) -> None:
    """CANVAS is an explicit source lettering zone, never an invented panel."""
    bubble_id = block.get("bubble_id")
    matches = [container for container in executable_text_containers(template)
               if container.get("bubble_id") == bubble_id]
    if len(matches) != 1:
        raise ValueError(f"{pid}/{bid}: CANVAS text has no unique executable source container")
    contract = matches[0]
    source_id = contract.get("source_text_zone_id")
    zones = [zone for zone in template.get("text_zones", []) or []
             if isinstance(zone, dict) and (zone.get("zone_id") or zone.get("text_zone_id")) == source_id]
    if (len(zones) != 1 or zones[0].get("executable") is not True
            or zones[0].get("canvas_binding_id") != "CANVAS"
            or contract.get("source_container_kind") != "canvas_text_zone"
            or contract.get("panel_id") != "CANVAS" or contract.get("canvas_binding_id") != "CANVAS"):
        raise ValueError(f"{pid}/{bid}: CANVAS ownership requires an original explicit executable canvas text zone")
    bounds = zones[0].get("bounds")
    if (not isinstance(bounds, list) or len(bounds) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bounds)
            or min(bounds[2:]) <= 0):
        raise ValueError(f"{pid}/{bid}: CANVAS zone must have explicit source bounds; no full-page default")
    binding = block.get("bubble_contract") or {}
    if (binding.get("bubble_id") != bubble_id or binding.get("panel_id") != "CANVAS"
            or binding.get("canvas_binding_id") != "CANVAS"
            or binding.get("source_container_kind") != "canvas_text_zone"
            or binding.get("source_text_zone_id") != source_id):
        raise ValueError(f"{pid}/{bid}: actual CANVAS text contract is not bound to its original source zone")
    if block.get("type") not in contract.get("allowed_text_types", []):
        raise ValueError(f"{pid}/{bid}: CANVAS source zone does not allow this semantic text type")


def _frozen_geometry(target: dict[str, Any], audit: dict[str, Any]) -> None:
    panels = target.get("panels", [])
    measured = audit.get("target_panel_geometry", [])
    if len(panels) != len(measured):
        raise ValueError("audit target count differs from the frozen executable target")
    table = {p.get("panel_id"): p for p in measured}
    normalized = "normalized" in target.get("canvas", {}).get("coordinate_system", "")
    width = target.get("canvas", {}).get("width", 1080)
    height = target.get("canvas", {}).get("height", 1440)
    for panel in panels:
        row = table.get(panel.get("panel_id"))
        bounds = panel.get("bounds")
        if not row or row.get("order") != panel.get("order") or not isinstance(bounds, list) or len(bounds) != 4:
            raise ValueError("audit target identity/order differs from the frozen target")
        expected = [bounds[0] * width, bounds[1] * height, bounds[2] * width, bounds[3] * height] if normalized else bounds
        if any(abs(a-b) > 1.01 for a, b in zip(_rect(row), expected)):
            raise ValueError("audit target geometry differs from the frozen target")


def validate_manifest(manifest_path: Path, diagnostic: bool = False,
                      manifest_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return factual aggregation. Passing coverage declarations never imply image understanding."""
    started = time.perf_counter()
    manifest_path = manifest_path.resolve()
    root = manifest_path.parent
    errors: list[dict[str, str]] = []
    bindings: dict[str, str] = {}
    rows: list[dict[str, Any]] = []

    def bind(path: Path) -> str:
        value = sha256(path)
        bindings[str(path)] = value
        return value

    def report(value: Any) -> tuple[dict[str, Any], Path]:
        path = resolve(value, root)
        bind(path)
        result = load_mapping(path)
        if not diagnostic and _diagnostic(result):
            raise ValueError("diagnostic fixture cannot be packaged as a production comic")
        return result, path

    try:
        manifest = load_mapping(manifest_path) if manifest_data is None else manifest_data
        if manifest_data is None:
            bind(manifest_path)
        if diagnostic and manifest.get("diagnostic_test_only") is not True:
            raise ValueError("--diagnostic requires diagnostic_test_only: true in the manifest")
        if not diagnostic and _diagnostic(manifest):
            raise ValueError("diagnostic manifest cannot be packaged as a production comic")
        source_path = resolve(manifest.get("source_path"), root)
        source_hash = bind(source_path)
        if manifest.get("source_sha256", source_hash) != source_hash:
            raise ValueError("manifest source hash is stale")
        coverage, coverage_path = report(manifest.get("content_coverage_path"))
        coverage_hash = bindings[str(coverage_path)]
        if manifest.get("coverage_sha256", coverage_hash) != coverage_hash:
            raise ValueError("manifest coverage hash is stale")
        if coverage.get("status") != "passed" or coverage.get("errors") not in (None, []):
            raise ValueError("declared content coverage has not passed")
        if coverage.get("source_sha256") != source_hash:
            raise ValueError("content coverage does not bind the current source text")
        pages = manifest.get("pages")
        if not isinstance(pages, list) or not pages:
            raise ValueError("pages must be a nonempty list")
        ids = [page.get("page_id") for page in pages if isinstance(page, dict)]
        if len(ids) != len(pages) or len(set(ids)) != len(ids) or any(not isinstance(pid, str) or not re.fullmatch(r"P\d{2,}", pid) for pid in ids):
            raise ValueError("page IDs must be unique canonical P01/P02/... IDs")
        # The prepared handoff owns page identity and order, including selected
        # nonconsecutive page IDs. Never silently renumber a prepared story.
        expected = manifest.get("expected_page_ids")
        if expected is not None and ids != expected:
            raise ValueError("page list differs from expected_page_ids")
        prepared_ids = coverage.get('expected_page_ids')
        if not diagnostic and prepared_ids is None:
            raise ValueError('production coverage must bind the complete prepared page list')
        if prepared_ids is not None and ids != prepared_ids:
            raise ValueError('delivery is missing pages from the complete preparation')
        storyboard_binding = coverage.get('storyboard_binding')
        if not diagnostic and not isinstance(storyboard_binding, dict):
            raise ValueError('production coverage must bind the complete storyboard handoff')
        if isinstance(storyboard_binding, dict):
            decision_path = resolve(storyboard_binding.get('path'), coverage_path.parent)
            if bind(decision_path) != storyboard_binding.get('sha256'):
                raise ValueError('storyboard handoff changed after preparation')
            decision_ids = [p.get('page_id') for p in load_mapping(decision_path).get('pages', [])]
            if not diagnostic and ids != decision_ids:
                raise ValueError('delivery page list differs from the complete storyboard handoff')
        coverage_pages: set[str] = set()
        beats = coverage.get("beats")
        if not isinstance(beats, list) or not beats:
            raise ValueError("coverage requires nonempty story beats")
        for beat in beats:
            if not isinstance(beat, dict) or not beat.get("beat_id") or not beat.get("bindings") or not beat.get("source_range"):
                raise ValueError("every covered beat requires identity, source range and page bindings")
            for item in beat["bindings"]:
                if not isinstance(item, dict) or item.get("page_id") not in ids:
                    raise ValueError("coverage binds a missing page")
                coverage_pages.add(item["page_id"])
        if coverage_pages != set(ids):
            raise ValueError("some delivered pages have no declared source beat coverage")
        generation = _generation_inputs(manifest, root, ids, source_path, coverage_path, bind,
                                        diagnostic=diagnostic)
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        return {"version": VERSION, "status": "blocked", "errors": [{"scope": "manifest", "reason": str(exc)}],
                "pages": [], "input_hashes": bindings, "published": False, "diagnostic_test_only": diagnostic,
                "elapsed_seconds": round(time.perf_counter() - started, 4)}

    final_paths: set[Path] = set()
    final_hashes: dict[str, str] = {}
    text_rows: dict[str, Any] = {}
    for page in pages:
        pid = page["page_id"]
        row: dict[str, Any] = {"page_id": pid, "status": "blocked"}
        try:
            base = resolve(page.get("base_image"), root)
            final = resolve(page.get("final_image"), root)
            if final in final_paths or final.name != f"{pid}-final.png" or base == final:
                raise ValueError("final must be unique canonical PAGE-final.png and separate from the base")
            final_paths.add(final)
            for path in (base, final):
                with Image.open(path) as picture:
                    if picture.format != "PNG" or picture.size != (1080, 1440):
                        raise ValueError("base and final must be real 1080x1440 PNG files")
                    picture.load()
            base_hash, final_hash = bind(base), bind(final)
            if final_hash in final_hashes.values():
                raise ValueError("duplicate final image pixels/file content across different pages")
            final_hashes[pid] = final_hash
            base_audit, base_audit_path = report(page.get("base_audit"))
            render, render_path = report(page.get("render_report"))
            bubbles, bubble_path = report(page.get("bubble_audit"))
            visual, visual_path = report(page.get("visual_review"))
            if generation is not None:
                target = generation["pages"][pid]["template"]
                if (base_audit.get("selected_layout") != target.get("layout_id")
                        or base_audit.get("target_panel_count") != len(target.get("panels", []))):
                    raise ValueError("actual selected layout/count differs from frozen generation target")
                _frozen_geometry(target, base_audit)
                text_rows[pid] = _text_integrity(page, root, generation["pages"][pid], render,
                                                source_path, base_hash, final_hash, bind,
                                                generation["text_policy"])
            _geometry(base_audit, base_hash)
            before = render.get("base_image_sha256_before", render.get("base_image_sha256"))
            after = render.get("base_image_sha256_after", render.get("base_image_sha256"))
            if (before != base_hash or after != base_hash or render.get("base_image_modified") is not False
                    or render.get("output_image_sha256") != final_hash
                    or render.get("page_acceptance_status") != "accepted"
                    or render.get("actual_image_checked") is not True
                    or render.get("synthetic_input") is not False
                    or render.get("unresolved_count") != 0
                    or not isinstance(render.get("rendered_count"), int)
                    or render.get("rendered_count") != render.get("canonical_block_count")
                    or render["rendered_count"] <= 0):
                raise ValueError("final render is incomplete, synthetic, unaccepted, or bound to different images")
            with Image.open(base) as a, Image.open(final) as b:
                if ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox() is None:
                    raise ValueError("final has no actual text-layer raster difference from base")
            evidence = bubbles.get("image_evidence") or {}
            if (bubbles.get("execution_bubble_match") != "passed"
                    or bubbles.get("actual_render_verified") is not True
                    or evidence.get("verified") is not True
                    or evidence.get("output_image_sha256") != final_hash
                    or evidence.get("base_hash_match") is not True):
                raise ValueError("bubble execution lacks actual final-image-bound raster evidence")
            if page.get("final_layout_audit"):
                final_audit, final_audit_path = report(page["final_layout_audit"])
            else:
                final_audit = render.get("final_layout_audit") or {}
                final_audit_path = None
            if (not isinstance(final_audit, dict)
                    or final_audit.get("full_template_execution") != "passed"
                    or final_audit.get("execution_style_match") != "passed"
                    or final_audit.get("text_container_execution_match") != "passed"):
                raise ValueError("final template geometry, style and text-container execution must pass")
            _geometry(final_audit, base_hash)
            def structure_signature(audit: dict[str, Any]) -> list[Any]:
                return [(r.get("panel_id") or r.get("unit_id"), r["order"], _rect(r), r.get("geometry_type", "rect"),
                         r.get("polygon"), r.get("vertices"), r.get("points"))
                        for r in audit["actual_panel_geometry"]]
            if (final_audit.get("selected_layout") != base_audit.get("selected_layout")
                    or structure_signature(final_audit) != structure_signature(base_audit)):
                raise ValueError("final execution structure differs from the checked no-text base")
            final_evidence = final_audit.get("final_text_evidence") or (final_audit.get("style_evidence") or {}).get("final_text_evidence") or {}
            # audit_storyboard_layout puts these bindings in style_measurement_evidence.
            if not final_evidence:
                for candidate in final_audit.values():
                    if isinstance(candidate, dict):
                        if "final_image_sha256" in candidate:
                            final_evidence = candidate
                        for nested in candidate.values():
                            if isinstance(nested, dict) and "final_image_sha256" in nested:
                                final_evidence = nested
            final_binding = final_audit.get("final_image_sha256", final_evidence.get("final_image_sha256"))
            base_binding = final_audit.get("base_image_sha256", final_evidence.get("base_image_sha256"))
            if final_binding != final_hash or base_binding != base_hash:
                raise ValueError("final template execution audit is not bound to both current images")
            if (visual.get("page_id") != pid or visual.get("actual_image_checked") is not True
                    or visual.get("synthetic", visual.get("synthetic_input")) is not False
                    or visual.get("review_status", visual.get("status")) not in ("passed", "passed_with_declared_adaptations")
                    or visual.get("image_sha256", visual.get("final_image_sha256")) != final_hash
                    or visual.get("base_image_sha256") != base_hash
                    or any(not passed(visual.get("checks", {}).get(key)) for key in REVIEW_CHECKS)):
                raise ValueError("actual visual QA is missing, incomplete, synthetic or image hash does not match")
            linked = visual.get("evidence_files") or {}
            for key, path in (("render_report", render_path), ("bubble_audit", bubble_path)):
                item = linked.get(key) or {}
                if resolve(item.get("path"), visual_path.parent) != path or item.get("sha256") != bindings[str(path)]:
                    raise ValueError(f"visual QA does not bind current {key}")
            if final_audit_path is None:
                raise ValueError("visual acceptance requires a separately saved current final-layout audit")
            provenance = validate_visual_provenance(visual_path, base, final,
                expected_evidence={"render_report": render_path, "bubble_audit": bubble_path,
                                   "base_audit": base_audit_path, "final_layout_audit": final_audit_path},
                expected_actual_plan_path=resolve(page.get("actual_text_plan", f"plans/actual/{pid}.yaml"), root),
                diagnostic=diagnostic)
            for path in provenance["bound_files"]:
                bind(path)
            font_path = provenance["evidence_paths"]["font_raster"]
            fonts = load_mapping(font_path)
            _glyph_evidence_valid(fonts, render, provenance["actual_plan"], base_hash, final_hash)
            row.update({"status": "passed", "selected_layout": base_audit.get("selected_layout"),
                        "target_panel_count": base_audit["target_panel_count"], "actual_panel_count": base_audit["actual_panel_count"],
                        "target_panel_geometry": base_audit["target_panel_geometry"], "actual_panel_geometry": base_audit["actual_panel_geometry"],
                        "reading_order_match": base_audit["reading_order_match"], "storyboard_layout_match": base_audit.get("storyboard_layout_match"),
                        "adapted_target_match": base_audit.get("adapted_target_match"),
                        "layout_deviation": base_audit.get("layout_deviation", base_audit.get("source_target_deviation", [])),
                        "base_image_modified": False, "base_image_sha256": base_hash, "final_image_sha256": final_hash,
                        "final_image": str(final), "full_template_execution": "passed", "execution_style_match": "passed"})
        except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
            errors.append({"scope": pid, "reason": str(exc)})
        rows.append(row)

    story_status = "pending_actual_image_review"
    try:
        story = manifest.get("story_review")
        if isinstance(story, str):
            story, story_path = report(story)
            if manifest.get("story_review_sha256", bindings[str(story_path)]) != bindings[str(story_path)]:
                raise ValueError("manifest story review hash is stale")
        if (not isinstance(story, dict) or story.get("status") != "passed"
                or story.get("source_sha256") != source_hash
                or story.get("coverage_sha256") != coverage_hash
                or story.get("reviewed_page_hashes") != final_hashes
                or set(final_hashes) != set(ids)
                or story.get("no_missing_required_beats") is not True
                or story.get("actual_image_checked") is not True
                or story.get("synthetic", story.get("synthetic_input")) is not False
                or not story.get("reviewer") or not story.get("semantic_observations")):
            raise ValueError("semantic story review must separately bind the source, coverage and every final page")
        story_status = "passed"
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        errors.append({"scope": "semantic_story_coverage", "reason": str(exc)})
    try:
        final_directory = root / "pages" / "final"
        expected_files = {f"{pid}-final.png" for pid in ids}
        if (any(resolve(p["final_image"], root).parent != final_directory.resolve() for p in pages)
                or {p.name for p in final_directory.iterdir() if p.is_file()} != expected_files):
            raise ValueError("pages/final must contain exactly the prepared canonical PNG set; move variants outside it")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append({"scope": "canonical_final_set", "reason": str(exc)})
    return {"version": VERSION, "status": "passed" if not errors else "blocked", "title": manifest.get("title", "漫画阅读册"),
            "pages": rows, "page_count": len(rows), "panel_count": sum(row.get("actual_panel_count", 0) for row in rows),
            "declared_content_coverage": "passed", "semantic_story_coverage": story_status,
            "frozen_generation_input_integrity": "passed" if generation is not None else "diagnostic_not_required",
            "frozen_bindings": generation["bindings"] if generation is not None else [],
            "text_integrity": text_rows,
            "image_understanding_performed_by_packager": False, "input_hashes": bindings,
            "errors": errors, "base_image_modified": False, "published": False,
            "diagnostic_test_only": diagnostic, "elapsed_seconds": round(time.perf_counter() - started, 4)}


def _reader(title: str, pages: list[dict[str, Any]], diagnostic: bool) -> str:
    banner = "仅供流程诊断测试，不是漫画成品。" if diagnostic else ""
    figures = "\n".join(f'<figure><img loading="lazy" src="images/{row["page_id"]}-final.png" alt="{row["page_id"]}"><figcaption>{i + 1} / {len(pages)}</figcaption></figure>' for i, row in enumerate(pages))
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title><style>body{{margin:0;background:#262626;color:#fff;font-family:system-ui;text-align:center}}h1{{font-size:20px}}figure{{margin:16px auto;max-width:810px}}img{{display:block;width:100%;height:auto}}figcaption{{padding:8px}}p{{padding:0 16px}}</style><h1>{html.escape(title)}</h1><p>{banner}</p>{figures}</html>'''


def deliver(manifest_path: Path, output_dir: Path, diagnostic: bool = False, check_only: bool = False) -> dict[str, Any]:
    """Write only into a new/empty directory. Blocked inputs never receive a ZIP."""
    started = time.perf_counter()
    output_dir = output_dir.resolve()
    if not check_only and output_dir.exists() and (not output_dir.is_dir() or any(output_dir.iterdir())):
        raise FileExistsError(f"delivery destination must be new or empty: {output_dir}")
    result = validate_manifest(manifest_path, diagnostic)
    if check_only:
        return result
    if any(path == output_dir or output_dir in path.parents for path in map(Path, result["input_hashes"])):
        raise ValueError("delivery output may not contain any inputs")
    output_dir.mkdir(parents=True, exist_ok=True)
    if result["status"] != "passed":
        (output_dir / "validation-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    images = output_dir / "images"
    images.mkdir()
    for row in result["pages"]:
        dest = images / f'{row["page_id"]}-final.png'
        shutil.copyfile(row["final_image"], dest)
        if sha256(dest) != row["final_image_sha256"]:
            raise ValueError("copied final image hash mismatch; no ZIP created")
    # Recheck all inputs after copying: a concurrent edit invalidates acceptance.
    for name, expected_hash in result["input_hashes"].items():
        if sha256(Path(name)) != expected_hash:
            raise ValueError("an input changed while packaging; no ZIP created")
    (output_dir / "reader.html").write_text(_reader(result["title"], result["pages"], diagnostic), encoding="utf-8")
    result["created_utc"] = datetime.now(timezone.utc).isoformat()
    result["archive_compression"] = "ZIP_STORED; PNG images are already compressed"
    for row in result["pages"]:
        row["delivery_image"] = f'images/{row["page_id"]}-final.png'
    summary_path = output_dir / "manifest-summary.json"
    summary_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    zip_path = output_dir / ("diagnostic-only.zip" if diagnostic else "comic-images.zip")
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(images.iterdir()):
            archive.write(path, path.relative_to(output_dir).as_posix())
        for path in (output_dir / "reader.html", summary_path):
            archive.write(path, path.name)
    result["archive"] = {"path": str(zip_path), "sha256": sha256(zip_path), "bytes": zip_path.stat().st_size}
    result["elapsed_seconds"] = round(time.perf_counter() - started, 4)
    (output_dir / "delivery-report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--diagnostic", action="store_true")
    args = parser.parse_args()
    try:
        result = deliver(args.manifest, args.output_dir, args.diagnostic, args.check_only)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc), "published": False}, ensure_ascii=False))
        return 2
    print(json.dumps({key: value for key, value in result.items() if key not in ("pages", "input_hashes", "frozen_bindings", "text_integrity")}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
