#!/usr/bin/env python3
"""Check a source-linked preview text plan before scene generation.

This gate never edits a plan, generates artwork, or writes an image. Font
measurement shares the raster renderer's inset/wrapping calculation, not a
render pass or a substitute for actual artwork checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import yaml
from template_contract import executable_text_containers, CANVAS_BINDING
from text_compositor import _apply_bubble_contract, _observed_tail_check, _brush_font_evidence, _surface_text_check, _global_protection_check, _preview_support_errors, measure_preview_text_capacity, STYLE_NAMES, PREVIEW_STYLE_ALIASES

SOURCE_TYPES = {
    "narration_text": {"narration", "caption"},
    "dialogue_text": {"dialogue", "phone_dialogue", "thought", "shout", "emphasis"},
    "note_text": {"note"},
}
DEFAULT_FONT = "C:/Windows/Fonts/msyh.ttc"
UNKNOWN = {None, "", "unknown", "inferred_unknown"}


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping: {path}")
    return data


def _entries(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        value = entry.get("text")
        return value if isinstance(value, str) else None
    return None


def _rect(bounds: Any, width: float, height: float) -> list[float] | None:
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        return None
    try:
        vals = [float(v) for v in bounds]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in vals) or min(vals[:2]) < 0 or min(vals[2:]) <= 0:
        return None
    return [vals[0] * width, vals[1] * height, vals[2] * width, vals[3] * height]


def _transform(rect: list[float], transform: dict) -> list[float]:
    x, y, width, height = rect
    scale = float(transform.get("scale", 1))
    crop_top = float(transform.get("crop_top_px", 0))
    pre_left = float(transform.get("crop_left_before_resize_px", transform.get("source_crop_left_px", 0)))
    return [(x - pre_left) * scale - float(transform.get("crop_left_px", 0)),
            (y - crop_top) * scale - float(transform.get("crop_top_after_resize_px", 0)),
            width * scale, height * scale]


def _path(value: Any, config_dir: Path) -> Path | None:
    if not value or not isinstance(value, str):
        return None
    path = Path(value)
    return path if path.is_absolute() else config_dir / path


def _capacity(text: str, bounds: list[float], bubble: dict, block: dict,
              config: dict, config_dir: Path) -> dict:
    visual = bubble.get("visual_style") or {}
    renderer = str(visual.get("renderer") or bubble.get("shape") or "")
    effective = dict(config)
    for key in ("font_file", "font_bold_file", "brush_font_file"):
        if config.get(key):
            resolved = _path(config[key], config_dir)
            effective[key] = str(resolved) if resolved else None
    brush = "brush" in renderer or "brush" in str(visual.get("font_style", ""))
    brush_evidence = None
    if brush:
        brush_evidence = _brush_font_evidence(effective)
        if brush_evidence["status"] != "verified":
            return {"status": "not-checked", "reason": brush_evidence["reason"],
                    "brush_font_evidence": brush_evidence, "guaranteed": False}
    font_path = _path(effective.get("brush_font_file") if brush else effective.get("font_file", DEFAULT_FONT), Path.cwd())
    if font_path is None or not font_path.is_file():
        return {"status": "not-checked", "reason": "brush_font_unavailable" if brush else "font_unavailable",
                "font_path": str(font_path) if font_path else None, "guaranteed": False}
    try:
        fit = measure_preview_text_capacity(text, bounds, bubble, block, effective)
    except (TypeError, ValueError, OSError) as exc:
        return {"status": "not-checked", "reason": "font_measurement_failed", "detail": str(exc), "guaranteed": False}
    return dict(fit, status="passed" if fit.get("fit_ok") else "failed",
                reason=fit.get("failure_reason"), method="shared_raster_padding_and_wrapping",
                font_path=str(font_path), capacity_stage="preliminary", guaranteed=False,
                brush_font_evidence=brush_evidence)


def preflight(template: dict, plan: dict, config: dict | None = None,
              config_dir: Path | None = None) -> dict:
    config = config or {}
    config_dir = config_dir or Path.cwd()
    errors: list[str] = []
    exact_blockers: list[str] = []
    warnings: list[str] = []
    page_id = plan.get("page_id")
    layout_id = template.get("layout_id")
    if not isinstance(page_id, str) or not re.fullmatch(r"P\d{2,}", page_id):
        errors.append("missing_or_invalid_page_id")
    if plan.get("layout_id") != layout_id or (plan.get("selected_layout") not in (None, layout_id)):
        errors.append("layout_id_mismatch")
    panels = template.get("panels") or (template.get("structure") or {}).get("units") or []
    panel_ids = [p.get("panel_id") or p.get("unit_id") for p in panels]
    if not panel_ids or None in panel_ids or len(set(panel_ids)) != len(panel_ids):
        errors.append("template_panel_ids_missing_or_duplicate")
    bubbles = executable_text_containers(template)
    if any(b.get('canvas_binding_id')==CANVAS_BINDING for b in bubbles):
        panel_ids.append(CANVAS_BINDING)
    bubble_ids = [b.get("bubble_id") for b in bubbles]
    if None in bubble_ids or len(set(bubble_ids)) != len(bubble_ids):
        errors.append("template_bubble_ids_missing_or_duplicate")
    by_id = {b.get("bubble_id"): b for b in bubbles if b.get("bubble_id")}
    blocks = plan.get("text_blocks") or []
    if not isinstance(blocks, list):
        errors.append("text_blocks_must_be_list")
        blocks = []
    aliases = [plan.get(key) for key in ("bubble_selection_policy", "bubble_usage_policy", "bubble_coverage_policy") if plan.get(key)]
    policy = aliases[0] if aliases else "all_template_bubbles"
    if len(set(aliases)) > 1:
        errors.append("conflicting_bubble_selection_policies")
    if policy not in {"all_template_bubbles", "story_subset"}:
        errors.append("unknown_bubble_selection_policy")
    used: set[str] = set()
    block_ids: set[str] = set()
    sources: set[tuple[str, int]] = set()
    rows = []
    transform = plan.get("canvas_transform") or {}
    canvas = plan.get("canvas") or {}
    target_w, target_h = float(canvas.get("width", 1080)), float(canvas.get("height", 1440))
    source_size = transform.get("source_canvas") or [target_w, target_h]
    if isinstance(source_size, dict):
        source_size = [source_size.get("width", target_w), source_size.get("height", target_h)]
    source_w, source_h = float(source_size[0]), float(source_size[1])
    for block in blocks:
        if not isinstance(block, dict):
            errors.append("non_mapping_text_block")
            continue
        bid, bubble_id = block.get("id"), block.get("bubble_id")
        label = str(bid or bubble_id or "unnamed_block")
        if not bid or bid in block_ids:
            errors.append(f"{label}: missing_or_duplicate_block_id")
        block_ids.add(bid)
        if block.get("page_id") not in (None, page_id) or block.get("layout_id") not in (None, layout_id):
            errors.append(f"{label}: page_or_layout_binding_mismatch")
        if block.get("selected_layout") not in (None, layout_id):
            errors.append(f"{label}: selected_layout_mismatch")
        if not bubble_id or bubble_id not in by_id:
            errors.append(f"{label}: missing_or_nonexistent_bubble_id")
        elif bubble_id in used:
            errors.append(f"{label}: duplicate_bubble_id")
        if bubble_id:
            used.add(bubble_id)
        bubble = by_id.get(bubble_id)
        if not bubble:
            continue
        pid = bubble.get("panel_id")
        if pid not in panel_ids or block.get("panel_id") != pid or block.get("selected_panel") not in (None, pid):
            errors.append(f"{label}: panel_binding_mismatch")
        if isinstance(block.get("anchor"), dict) and block["anchor"].get("panel_id") not in (None, pid):
            errors.append(f"{label}: anchor_panel_mismatch")
        field, index = block.get("source_field"), block.get("source_index")
        source = None
        if field not in SOURCE_TYPES or not isinstance(index, int) or isinstance(index, bool) or index < 0:
            errors.append(f"{label}: invalid_source_link")
        else:
            link = (field, index)
            if link in sources:
                errors.append(f"{label}: duplicate_source_link")
            sources.add(link)
            entries = _entries(plan.get(field))
            if index >= len(entries):
                errors.append(f"{label}: source_index_out_of_range")
            else:
                source = entries[index]
                if _text(source) != block.get("text"):
                    errors.append(f"{label}: source_text_mismatch")
            permitted = SOURCE_TYPES[field]
            if isinstance(source, dict) and source.get("type"):
                # Caption is a narration display type, not character speech.
                permitted = {"narration", "caption"} if source["type"] in {"narration", "caption"} else {source["type"]}
            if block.get("type") not in permitted:
                errors.append(f"{label}: source_semantic_type_changed")
            if isinstance(source, dict) and source.get("speaker") is not None and block.get("speaker") != source["speaker"]:
                errors.append(f"{label}: source_speaker_changed")
        source_type, block_type = block.get("source_type"), block.get("type")
        same_narration_semantics = source_type in {"narration", "caption"} and block_type in {"narration", "caption"}
        if source_type not in (None, block_type) and not same_narration_semantics:
            errors.append(f"{label}: declared_source_type_changed")
        allowed_types = bubble.get("allowed_text_types") or []
        if block.get("type") not in allowed_types:
            errors.append(f"{label}: text_type_not_allowed_by_template")
        text = block.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(f"{label}: empty_or_invalid_text")
            text = ""
        resolved_input = dict(block)
        resolved_input["synthetic_input"] = bool(plan.get("synthetic") or plan.get("synthetic_input"))
        resolved_input['_base_image_sha256']=plan.get('base_image_sha256') or block.get('_base_image_sha256')
        resolved_input.setdefault("bubble_contract", bubble)
        resolved_block = _apply_bubble_contract(resolved_input, layout_id, int(target_w), int(target_h), transform)
        resolved_block['_all_panel_ids']=[p.get('panel_id') for p in template.get('panels',[])]
        resolved_bounds = resolved_block.get("bubble_contract_bounds_xywh")
        bounds = [float(v) for v in resolved_bounds] if resolved_bounds else None
        renderer=resolved_block.get('bubble_style')
        for unsupported in _preview_support_errors(resolved_block.get('bubble_contract_visual_style') or {}):
            errors.append(f'{label}: {unsupported}')
        if renderer not in STYLE_NAMES and renderer not in PREVIEW_STYLE_ALIASES:
            errors.append(f'{label}: unknown_preview_renderer_blocked ({renderer})')
        protection=_global_protection_check(resolved_block)
        if protection['status']=='blocked':errors.append(f"{label}: {protection['reason']}")
        surface=None
        if renderer=='preview_surface_text':
            surface=_surface_text_check(resolved_block,tuple([bounds[0],bounds[1],bounds[0]+bounds[2],bounds[1]+bounds[3]]) if bounds else None)
            if surface['status']=='blocked':errors.append(f"{label}: {surface['reason']}")
        tail_result = _observed_tail_check(resolved_block, (bounds[0], bounds[1], bounds[0] + bounds[2], bounds[1] + bounds[3])) if bounds else {"required": False, "status": "blocked", "reason": "invalid_bubble_bounds"}
        tail_required = tail_result.get("required") is True
        if tail_result.get("status") == "blocked":
            # A missing or misbound required tail is not executable, including
            # adapted mode. Adapting geometry requires an explicit new contract.
            errors.append(f"{label}: {tail_result.get('reason')}")
        capacity = {"status": "not-checked", "reason": "invalid_bubble_bounds", "guaranteed": False}
        if bounds is None:
            errors.append(f"{label}: invalid_bubble_bounds")
        else:
            x, y, width, height = bounds
            if x < -.5 or y < -.5 or x + width > target_w + .5 or y + height > target_h + .5:
                errors.append(f"{label}: transformed_bubble_outside_canvas")
            capacity = _capacity(text, bounds, resolved_block.get("bubble_contract") or bubble, resolved_block, config, config_dir)
            if capacity["status"] == "failed":
                errors.append(f"{label}: preliminary_capacity_failed ({capacity.get('reason', 'text_does_not_fit')})")
            elif capacity["status"] == "not-checked":
                errors.append(f"{label}: capacity_unverified ({capacity.get('reason')})")
        rows.append({"block_id": bid, "bubble_id": bubble_id, "panel_id": pid,
                     "source_field": field, "source_index": index, "source_type": block.get("type"),
                     "target_bounds_xywh": bounds, "tail_required": tail_required, "tail_execution": tail_result, "capacity": capacity,
                     'global_protection_evidence':protection,'surface_text_evidence':surface})
    missing = [bubble_id for bubble_id in bubble_ids if bubble_id not in used]
    if policy == "all_template_bubbles" and missing:
        errors.append("missing_required_bubbles: " + ", ".join(missing))
    if policy == "story_subset":
        active = plan.get("bubble_active_ids")
        if not isinstance(active, list) or len(active) != len(set(active)) or set(active) != used or not plan.get("bubble_subset_reason"):
            errors.append("story_subset_requires_matching_active_ids_and_reason")
        exact_blockers.append("story_subset_cannot_be_exact")
    for field in SOURCE_TYPES:
        for index, entry in enumerate(_entries(plan.get(field))):
            if _text(entry) and (field, index) not in sources:
                errors.append(f"unlinked_source_text: {field}[{index}]")
    if not bubbles and blocks:
        errors.append("preview_has_no_bubbles_cannot_invent_template")
    annotation = str((template.get("source") or {}).get("annotation_status", ""))
    if not annotation or annotation.startswith("pending"):
        exact_blockers.append("template_annotation_not_ready")
    match_policy = plan.get("match_policy", "structure_exact")
    if match_policy not in {"structure_exact", "pixel_reference", "adapted"}:
        errors.append("unknown_match_policy")
    elif match_policy == "adapted":
        exact_blockers.append("adapted_match_policy_cannot_be_exact")
    strict = match_policy in {"structure_exact", "pixel_reference"}
    ready = not errors and (not strict or not exact_blockers)
    warnings.append("Capacity shares raster font metrics, padding, and wrapping; actual artwork avoidance, glyph contours, tails, and full-size readability still require render/visual checks.")
    return {"preflight_version": "0.2-executable-tail-brush", "page_id": page_id, "selected_layout": layout_id,
            "match_policy": match_policy, "bubble_selection_policy": policy,
            "generation_ready": ready, "exact_ready": not errors and not exact_blockers,
            "status": "passed" if ready else "blocked", "errors": errors,
            "exact_blockers": exact_blockers, "warnings": warnings,
            "template_bubble_count": len(bubbles), "planned_bubble_count": len(used),
            "missing_bubble_ids": missing, "semantic_evidence_scope": "legacy_source_fields_and_explicit_source_metadata",
            "capacity_check_stage": "preliminary", "capacity_guaranteed": False,
            "base_image_modified": False, "images_generated": False, "blocks": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--text-plan", type=Path, required=True)
    parser.add_argument("--text-layout", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        template, plan = _load(args.template), _load(args.text_plan)
        config = _load(args.text_layout) if args.text_layout else {}
        report = preflight(template, plan, config, args.text_layout.parent if args.text_layout else Path.cwd())
        report["input_sha256"] = {"template": hashlib.sha256(args.template.read_bytes()).hexdigest(),
                                  "text_plan": hashlib.sha256(args.text_plan.read_bytes()).hexdigest()}
    except Exception as exc:
        report = {"preflight_version": "0.1", "generation_ready": False, "exact_ready": False,
                  "status": "blocked", "errors": [f"invalid_input: {type(exc).__name__}: {exc}"],
                  "base_image_modified": False, "images_generated": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in ("page_id", "selected_layout", "status", "generation_ready", "exact_ready", "errors", "exact_blockers")}, ensure_ascii=False))
    return 0 if report["generation_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
