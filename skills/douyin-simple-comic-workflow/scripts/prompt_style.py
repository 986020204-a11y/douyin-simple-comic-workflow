#!/usr/bin/env python3
"""Select and compile one of the bundled comic storyboard templates.

The executable YAML template is the geometry authority. This module must not
invent a grid when a template has not been visually annotated.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from template_contract import executable_text_containers, CANVAS_BINDING

from template_canvas import compile_adapted_template

SKILL_ROOT = Path(__file__).resolve().parents[1]
POOL = SKILL_ROOT / "references" / "comic-layouts"
INDEX = POOL / "layouts.json"
TEMPLATE_DIR = POOL / "executable-templates"
CANVAS_W, CANVAS_H = 1080, 1440
MATCH_POLICIES = {"structure_exact", "pixel_reference", "adapted"}


def _load_template(layout_id: str) -> tuple[dict, Path]:
    lid = layout_id.upper()
    path = TEMPLATE_DIR / f"{lid}.yaml"
    if not path.exists():
        raise ValueError(f"Missing executable template for {lid}: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ValueError(f"Cannot parse executable template {path}: {exc}") from exc
    if data.get("layout_id", "").upper() != lid:
        raise ValueError(f"Template layout_id mismatch in {path}: {data.get('layout_id')!r}")
    return data, path


def _number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must contain numeric values") from exc
    return result


def _bounds_to_pixels(bounds: Any, field: str, width: int = CANVAS_W,
                      height: int = CANVAS_H) -> tuple[list[float], list[int]]:
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise ValueError(f"{field} must be normalized [x, y, width, height]")
    vals = [_number(v, field) for v in bounds]
    if any(v < 0 for v in vals) or vals[2] <= 0 or vals[3] <= 0:
        raise ValueError(f"{field} contains an invalid rectangle: {bounds!r}")
    if vals[0] + vals[2] > 1.001 or vals[1] + vals[3] > 1.001:
        raise ValueError(f"{field} falls outside normalized canvas: {bounds!r}")
    px = [round(vals[0] * width), round(vals[1] * height),
          round(vals[2] * width), round(vals[3] * height)]
    return [round(v, 6) for v in vals], px


def _polygon_to_pixels(polygon: Any, field: str, width: int = CANVAS_W,
                       height: int = CANVAS_H) -> tuple[list[list[float]], list[list[int]]]:
    if not isinstance(polygon, (list, tuple)) or len(polygon) < 3:
        raise ValueError(f"{field} must contain at least three [x, y] points")
    norm: list[list[float]] = []
    px: list[list[int]] = []
    for i, point in enumerate(polygon):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError(f"{field}[{i}] must be [x, y]")
        x, y = _number(point[0], field), _number(point[1], field)
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f"{field}[{i}] falls outside normalized canvas")
        norm.append([round(x, 6), round(y, 6)])
        px.append([round(x * width), round(y * height)])
    return norm, px


def _template_units(template: dict) -> list[dict]:
    """Return the executable units, accepting the legacy panels field and
    the richer structure.units field used for nested/phone/broken-frame SBs."""
    structure = template.get("structure") or {}
    panels = template.get("panels") or structure.get("units") or []
    if panels:
        return panels
    structure = template.get("structure") or {}
    return structure.get("units") or []


def _validate_template(template: dict, match_policy: str, requested_count: int | None) -> list[dict]:
    if match_policy not in MATCH_POLICIES:
        raise ValueError(f"match_policy must be one of {sorted(MATCH_POLICIES)}")
    source = template.get("source") or {}
    preview = source.get("preview_image")
    if not preview or not (POOL / preview).exists():
        raise ValueError(f"Template {template.get('layout_id')} has no existing preview_image")
    panels = _template_units(template)
    if not panels:
        raise ValueError(
            f"Template {template.get('layout_id')} has no observed panel geometry; "
            "annotate the preview before execution"
        )
    if requested_count is not None and requested_count != len(panels):
        raise ValueError(
            f"Requested panel_count={requested_count} does not match template "
            f"{template.get('layout_id')} panel count={len(panels)}"
        )
    orders = [p.get("order") for p in panels]
    if orders != list(range(1, len(panels) + 1)):
        raise ValueError(f"Template {template.get('layout_id')} panel order is not continuous: {orders}")
    seen: set[str] = set()
    for panel in panels:
        pid = panel.get("panel_id")
        if not pid or pid in seen:
            raise ValueError(f"Template {template.get('layout_id')} has duplicate/empty panel_id")
        seen.add(pid)
        _bounds_to_pixels(panel.get("bounds"), f"{pid}.bounds")
        if panel.get("geometry_type") in {"polygon", "approximate_polygon"}:
            if not panel.get("polygon"):
                raise ValueError(f"{pid} declares polygon geometry without polygon points")
            _polygon_to_pixels(panel["polygon"], f"{pid}.polygon")
    annotation = str(source.get("annotation_status", ""))
    if match_policy in {"structure_exact", "pixel_reference"} and annotation.startswith("pending"):
        raise ValueError(
            f"Template {template.get('layout_id')} is not review-ready for {match_policy}: "
            f"annotation_status={annotation!r}, review_status={template.get('review_status')!r}"
        )
    return panels


def _compile_panel(panel: dict, width: int = CANVAS_W, height: int = CANVAS_H) -> dict:
    normalized, px = _bounds_to_pixels(panel["bounds"], f"{panel['panel_id']}.bounds", width, height)
    result = {
        "panel_id": panel["panel_id"],
        "order": int(panel["order"]),
        "geometry_type": panel.get("geometry_type", "rect"),
        "bounds": normalized,
        "x": px[0], "y": px[1], "width": px[2], "height": px[3],
        # Visual ratio belongs to the selected canvas, not normalized xywh.
        "ratio": round(px[2] / px[3], 4),
        "rect_format": "xywh",
        "role": panel.get("role"),
        "cross_panel_allowed": bool(panel.get("cross_panel_allowed", False)),
        "evidence": panel.get("evidence", (panel.get("field_evidence") or {}).get("polygon" if panel.get("polygon") else "bounds", "unknown")),
        "field_evidence": copy.deepcopy(panel.get("field_evidence") or {}),
    }
    if panel.get("polygon"):
        norm, polygon_px = _polygon_to_pixels(panel["polygon"], f"{panel['panel_id']}.polygon", width, height)
        result["polygon"] = norm
        result["polygon_px"] = polygon_px
        result["polygon_status"] = panel.get("polygon_status", "observed")
    for key in ("parent_id", "parent_panel_id", "visible", "nested_units", "border", "border_visible", "z_index", "layer", "alpha_required", "asset_alpha_required"):
        if key in panel:
            result[key] = panel[key]
    return result


def _compile_bubble(bubble: dict, width: int = CANVAS_W, height: int = CANVAS_H) -> dict:
    result = copy.deepcopy(bubble)
    if bubble.get("bounds"):
        norm, px = _bounds_to_pixels(bubble["bounds"], f"{bubble.get('bubble_id')}.bounds", width, height)
        result["bounds"] = norm
        result["bounds_px"] = px
    if bubble.get("polygon"):
        _, result["polygon_px"] = _polygon_to_pixels(bubble["polygon"], f"{bubble.get('bubble_id')}.polygon", width, height)
    tail = result.get("tail") or {}
    if tail.get("polygon"):
        _, tail["polygon_px"] = _polygon_to_pixels(tail["polygon"], f"{bubble.get('bubble_id')}.tail.polygon", width, height)
    if isinstance(tail.get("anchor"), (list, tuple)) and len(tail["anchor"]) == 2:
        tail["anchor_px"] = [round(tail["anchor"][0] * width), round(tail["anchor"][1] * height)]
    return result


def compile_execution_contract(item: dict, panel_count: int | None = None,
                               match_policy: str = "structure_exact", *,
                               approved_3_4_adaptation: bool = False) -> dict:
    """Compile geometry directly from executable-templates/SB-###.yaml."""
    template, template_path = _load_template(item["id"])
    source_template = copy.deepcopy(template)
    _validate_template(source_template, match_policy, panel_count)
    transform = None
    if approved_3_4_adaptation:
        template, transform = compile_adapted_template(template, CANVAS_W, CANVAS_H, approved=True)
        match_policy = "adapted"
        width, height = CANVAS_W, CANVAS_H
    else:
        # A source-native exact contract must not independently stretch x/y
        # onto the delivery ratio or silently remove the instructional header.
        source_size = (template.get("preview_contract") or {}).get("source_size")
        if not isinstance(source_size, (list, tuple)) or len(source_size) != 2:
            raise ValueError("Source-native compilation requires preview_contract.source_size; approve a target adaptation explicitly only after source annotation")
        width, height = [int(v) for v in source_size]
        if width <= 0 or height <= 0:
            raise ValueError("Invalid source preview canvas dimensions")
    structure = template.get("structure") or {}
    panels = _validate_template(template, match_policy, panel_count)
    compiled_panels = [_compile_panel(panel, width, height) for panel in panels]
    panel_ids = [p["panel_id"] for p in compiled_panels]
    bubbles = [_compile_bubble(b, width, height) for b in executable_text_containers(template)]
    bubble_ids = [b.get("bubble_id") for b in bubbles]
    if any(not bid for bid in bubble_ids) or len(set(bubble_ids)) != len(bubble_ids):
        raise ValueError("Executable bubble instances require unique, non-empty bubble_id values")
    for bubble in bubbles:
        if bubble.get("panel_id") not in panel_ids and bubble.get('canvas_binding_id') != CANVAS_BINDING:
            raise ValueError(f"Bubble {bubble.get('bubble_id')} is not bound to a template panel")
    # Reserve the annotated text geometry before generating scene assets.
    # The image model draws the scene only; post-layout composition owns the
    # bubble body, border, tail and glyphs.  Keep preview style/type metadata
    # attached so the reservation never becomes a generic long-box default.
    reserved_zones = [
        {
            "bubble_id": bubble.get("bubble_id"),
            "panel_id": bubble.get("panel_id"),
            "bounds": bubble.get("bounds"),
            "bounds_px": bubble["bounds_px"],
            "rect_format": "xywh",
            "reserved_for": "post_layout_text_and_bubble",
            "excluded_subject_content": ["faces", "hands", "key_props"],
            "shape": bubble.get("shape"),
            "visual_style": bubble.get("visual_style") or {},
            "allowed_text_types": bubble.get("allowed_text_types") or [],
            "avoid": bubble.get("avoid") or [],
            "polygon_px": bubble.get("polygon_px"),
            "tail": copy.deepcopy(bubble.get("tail") or {}),
            "field_evidence": copy.deepcopy(bubble.get("field_evidence") or {}),
        }
        for bubble in bubbles if bubble.get("bounds_px")
    ]
    constraints = dict(template.get("constraints") or {})
    constraints.update({
        "panel_count": len(compiled_panels),
        "panel_count_exact": True,
        "preserve_panel_geometry": True,
        "preserve_reading_order": True,
        "allow_add_panels": False,
        "allow_delete_panels": False,
        "allow_merge_panels": False,
        "allow_split_panels": False,
        "no_text_in_base_image": True,
        "no_bubbles_in_base_image": True,
        "preserve_reserved_no_subject_zones": True,
        "text_preflight_required_before_generation": True,
        "full_layout_proof_required_before_new_scene_generation": True,
        "model_owns_panel_geometry": False,
    })
    return {
        "template_path": str(template_path),
        "template_version": template.get("version"),
        "layout_id": template.get("layout_id"),
        "match_policy": match_policy,
        "execution_status": "compiled_not_rendered",
        "source_template_path": str(template_path),
        "source_template_sha256": hashlib.sha256(template_path.read_bytes()).hexdigest(),
        "source_template_modified": False,
        "resolved_template": template,
        "user_approved_adaptation": approved_3_4_adaptation,
        "canvas_transform": transform,
        "source_target_deviation": template.get("source_target_deviation") or [],
        "source_reference_geometry_match": "failed" if approved_3_4_adaptation else "not-checked",
        "source_annotation_uncertainties": source_template.get("annotation_uncertainties") or [],
        "annotation_coverage": source_template.get("annotation_coverage") or {},
        "canvas": {
            "width": width, "height": height,
            "aspect_ratio": "3:4" if approved_3_4_adaptation else f"{width}:{height}",
            "coordinate_space": "approved_target" if approved_3_4_adaptation else "native_full_preview",
            "coordinate_system": template.get("canvas", {}).get(
                "coordinate_system", "normalized_xywh_0_to_1"
            ),
        },
        "reference_inputs": {
            "preview_image": str(POOL / template["source"]["preview_image"]),
            "preview_image_required": approved_3_4_adaptation or match_policy in {"structure_exact", "pixel_reference"},
            "visual_reference_only": bool(template.get("source", {}).get("visual_reference_only", True)),
        },
        "panel_geometry": compiled_panels,
        "reading_order": panel_ids,
        "bubbles": bubbles,
        "reserved_no_subject_zones": reserved_zones,
        "text_reservation_policy": {
            "stage": "before_scene_generation",
            "requires_text_semantics_and_capacity_preflight": True,
            "draw_text_in_base": False,
            "draw_bubbles_in_base": False,
            "cannot_change_panel_geometry": True,
            "complete_template_instance_coverage_required": True,
            "synthetic_proof_bindings_are_not_actual_scene_evidence": True,
        },
        "style_contract": template.get("style_contract") or {},
        "execution_requirements":template.get('execution_requirements') or [],
        "structure": template.get("structure") or {},
        "nested_units": (template.get("structure") or {}).get("nested_units", template.get("nested_units") or []),
        "overlays": template.get("overlays") or (template.get("structure") or {}).get("overlays") or [],
        "preview_contract": template.get("preview_contract") or template.get("preview") or {},
        "generator_constraints": constraints,
        "fallback": template.get("fallback") or {},
        "evidence": template.get("evidence") or {},
    }


def load_pool() -> list[dict]:
    if not INDEX.exists():
        raise RuntimeError(f"Missing bundled layout index: {INDEX}")
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    if len(data) != 68 or any(x.get("category") != "comic-storyboard" for x in data):
        raise RuntimeError(
            f"Bundled comic layout pool must contain exactly 68 comic-storyboard entries; got {len(data)}"
        )
    for x in data:
        pf = POOL / x["prompt_file"]
        if not pf.exists():
            raise RuntimeError(f"Missing bundled prompt file for {x['id']}: {pf}")
    return data


def verify() -> dict:
    pool = load_pool()
    return {
        "status": "passed",
        "pool_size": len(pool),
        "category": "comic-storyboard",
        "all_prompt_files_present": True,
        "layout_source": "bundled-internal-comic-layouts",
        "executable_template_dir": str(TEMPLATE_DIR),
        "external_runtime_dependency": False,
        "ids": [x["id"] for x in pool],
    }


def _tokens(text: str) -> set[str]:
    text = (text or "").lower()
    parts = re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", text)
    grams = set(parts)
    for n in (2, 3, 4):
        grams.update(text[i:i+n] for i in range(max(0, len(text)-n+1)) if text[i:i+n].strip())
    return grams


def select(pool: list[dict], story_function: str, theme: str, layout_id: str | None) -> tuple[dict, str]:
    if layout_id:
        item = next((x for x in pool if x["id"].upper() == layout_id.upper()), None)
        if item is None:
            raise ValueError(f"Unknown layout: {layout_id}")
        return item, "explicit layout requested; validated against bundled internal index"
    query = f"{story_function} {theme}".strip()
    q = _tokens(query)
    scored=[]
    for item in pool:
        hay = " ".join([
            item.get("name", ""), item.get("name_en", ""),
            " ".join(item.get("keywords", [])), item.get("layout_structure", "")
        ])
        h = _tokens(hay)
        score = sum(1 for t in q if t in h)
        for phrase in (story_function, theme):
            if phrase and phrase in hay:
                score += 12
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    score, item = scored[0]
    if score <= 0:
        item = next(x for x in pool if x["id"] == "SB-001")
        return item, "no direct term match; selected the bundled regular-grid template"
    return item, f"matched story-function/theme terms against bundled metadata (score={score})"


def _contract_prompt(contract: dict) -> str:
    lines = [
        "EXECUTABLE STORYBOARD CONTRACT (compiled from the selected YAML template; obey exactly):",
        f"match_policy: {contract['match_policy']}",
        f"Canvas: {contract['canvas']['width']}x{contract['canvas']['height']} ({contract['canvas']['aspect_ratio']})",
        f"Exact panel count: {len(contract['panel_geometry'])}",
        f"Exact target text-container count: {len(contract.get('bubbles') or [])}; enumerate every instance, not only repeatable style samples.",
        f"source_reference_geometry_match: {contract['source_reference_geometry_match']}; target compliance is a separate result.",
        "Reading order: " + " > ".join(contract["reading_order"]),
        "Do not add, delete, merge, or split panels. Do not move, resize, or reinterpret panel boundaries.",
        "Before generating scene assets, verify source-linked text semantics and readable capacity against each bound template bubble.",
        "First render a complete layout-and-text proof and pass preflight; synthetic proof speaker/prop regions cannot establish actual scene ownership.",
        "Generate scene assets per declared unit and assemble them with the deterministic layout executor; the image model never draws the page grid.",
        "Generate only no-text scene art: do not draw text, letters, numbers, bubble bodies, bubble borders, or bubble tails.",
        "Reserve every declared bubble zone as quiet scene space for post-layout composition. Keep faces, hands, and key props outside reserved_no_subject_zones.",
        "The bubble shape and visual_style below are post-layout contracts, not instructions to paint bubbles into the base image.",
        "Do not move bubble zones or change panel geometry to fit subjects; unresolved text capacity or semantic compatibility blocks generation.",
    ]
    if contract.get("user_approved_adaptation"):
        lines.append("Approved 3:4 content-cover adaptation: apply only this compiled target. Preserve the source template and report every source-target deviation; do not claim source-exact agreement.")
        lines.append("source_target_deviation: " + json.dumps(contract["source_target_deviation"], ensure_ascii=False, sort_keys=True))
    for panel in contract["panel_geometry"]:
        lines.append(
            f"{panel['panel_id']} order={panel['order']} geometry={panel['geometry_type']} "
            f"xywh_px=({panel['x']},{panel['y']},{panel['width']},{panel['height']}) "
            f"bounds_norm={panel['bounds']} ratio={panel['ratio']} "
            f"cross_panel_allowed={panel['cross_panel_allowed']}"
        )
        if panel.get("polygon"):
            lines.append(f"  polygon_norm={panel['polygon']} polygon_px={panel['polygon_px']}")
    for nested in contract.get("nested_units", []):
        lines.append(
            f"Nested unit {nested.get('unit_id', nested.get('panel_id'))} "
            f"parent={nested.get('parent_id', nested.get('parent_panel_id'))} "
            f"order={nested.get('order')} bounds={nested.get('bounds')} "
            f"geometry={nested.get('geometry_type', 'rect')} evidence={nested.get('evidence', 'unknown')}"
        )
    for overlay in contract.get("overlays", []):
        lines.append(
            f"Structural overlay {overlay.get('overlay_id', overlay.get('id'))} "
            f"type={overlay.get('type')} bounds={overlay.get('bounds')} "
            f"evidence={overlay.get('evidence', 'unknown')}"
        )
    if contract.get("preview_contract"):
        lines.append(f"Preview structural contract: {json.dumps(contract['preview_contract'], ensure_ascii=False, sort_keys=True)}")
    for bubble in contract.get("bubbles", []):
        lines.append(
            f"Bubble {bubble.get('bubble_id')} belongs only to {bubble.get('panel_id')}; "
            f"shape={bubble.get('shape')}; bounds_norm={bubble.get('bounds')}; "
            f"bounds_px={bubble.get('bounds_px')}; rect_format=xywh; "
            f"position={bubble.get('position')}; "
            f"visual_style={json.dumps(bubble.get('visual_style') or {}, ensure_ascii=False, sort_keys=True)}; "
            f"allowed_text_types={bubble.get('allowed_text_types') or []}; "
            f"avoid={bubble.get('avoid') or []}; "
            f"tail={json.dumps(bubble.get('tail') or {}, ensure_ascii=False, sort_keys=True)}; "
            f"body_polygon_px={bubble.get('polygon_px')}"
        )
    lines.append(
        "reserved_no_subject_zones: "
        + json.dumps(contract.get("reserved_no_subject_zones") or [], ensure_ascii=False, sort_keys=True)
    )
    if contract.get("reference_inputs", {}).get("preview_image_required"):
        lines.append("Use the supplied preview image as a structural reference input; it is not optional.")
    return "\n".join(lines)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap=argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--layout")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--story-function", default="")
    ap.add_argument("--theme", default="")
    ap.add_argument("--panel-count", type=int)
    ap.add_argument("--match-policy", choices=sorted(MATCH_POLICIES), default="structure_exact")
    ap.add_argument("--approved-3-4-adaptation", action="store_true",
                    help="Use only after user selected 3:4 content cover; compile an adapted target with explicit source deviations")
    ap.add_argument("--output", type=Path)
    args=ap.parse_args()
    if args.verify:
        result=verify()
    else:
        pool=load_pool()
        if args.list:
            result={"pool_size":len(pool),"layouts":[
                {"id":x["id"],"name":x["name"],"panel_count":x["panel_count"],"prompt_file":x["prompt_file"]}
                for x in pool
            ]}
        else:
            if not args.auto and not args.layout:
                raise SystemExit("Use --layout SB-xxx, --auto, or --verify.")
            item,reason=select(pool,args.story_function,args.theme,args.layout)
            prompt=(POOL/item["prompt_file"]).read_text(encoding="utf-8")
            execution = compile_execution_contract(item, args.panel_count, args.match_policy,
                                                   approved_3_4_adaptation=args.approved_3_4_adaptation)
            prompt += "\n\n" + _contract_prompt(execution)
            result={
                "selected_by":"douyin-simple-comic-workflow",
                "layout_source":"bundled-internal-comic-layouts",
                "internal_layout_pool":68,
                "layout_id":item["id"],
                "layout_name":item["name"],
                "layout_name_en":item["name_en"],
                "panel_count":len(execution["panel_geometry"]),
                "selection_reason":reason,
                "prompt_file":str(POOL/item["prompt_file"]),
                "prompt_text":prompt,
                "execution_contract":execution,
            }
    payload=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(payload+"\n",encoding="utf-8")
    print(payload)

if __name__ == "__main__":
    main()
