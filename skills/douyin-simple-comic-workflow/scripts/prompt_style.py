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


def _layout_score(item: dict, story_function: str, theme: str) -> int:
    q = _tokens(f"{story_function} {theme}".strip())
    hay = " ".join([
        item.get("name", ""), item.get("name_en", ""),
        " ".join(item.get("keywords", [])), item.get("layout_structure", "")
    ])
    h = _tokens(hay)
    score = sum(1 for token in q if token in h)
    for phrase in (story_function, theme):
        if phrase and phrase in hay:
            score += 12
    return score


def select(pool: list[dict], story_function: str, theme: str, layout_id: str | None) -> tuple[dict, str]:
    if layout_id:
        item = next((x for x in pool if x["id"].upper() == layout_id.upper()), None)
        if item is None:
            raise ValueError(f"Unknown layout: {layout_id}")
        return item, "explicit layout requested; validated against bundled internal index"
    scored = [(_layout_score(item, story_function, theme), item) for item in pool]
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    score, item = scored[0]
    if score <= 0:
        item = next(x for x in pool if x["id"] == "SB-001")
        return item, "no direct term match; selected the bundled regular-grid template"
    return item, f"matched story-function/theme terms against bundled metadata (score={score})"


class PageSelectionBlocked(ValueError):
    def __init__(self, audit: dict):
        self.audit = audit
        super().__init__("Multi-page storyboard rhythm audit blocked: "
                         + "; ".join(str(error) for error in audit.get("errors", [])))


def _read_pages(path: Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError("--pages must contain a YAML/JSON mapping with a pages list")
    return document


def select_pages(document: dict, pool: list[dict], match_policy: str = "structure_exact", *,
                 approved_3_4_adaptation: bool = False) -> dict:
    """Select each page independently, then audit the complete reading rhythm.

    Near-scoring executable candidates may break a repeat. A distinctly better
    narrative match remains selected, leaving any repeated run to explicit
    narrative justification or a recorded user request in the rhythm audit.
    """
    pages = document.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("--pages requires a non-empty pages list")
    policy = document.get("layout_policy", "narrative_variety")
    if policy not in {"narrative_variety", "uniform_by_user_request"}:
        raise ValueError("layout_policy must be narrative_variety or uniform_by_user_request")
    request = document.get("uniform_layout_request")
    if request is not None or policy == "uniform_by_user_request":
        if (not isinstance(request, dict) or request.get("source") != "user"
                or not isinstance(request.get("instruction_excerpt"), str)
                or not request["instruction_excerpt"].strip()):
            raise ValueError("A uniform layout requires uniform_layout_request with "
                             "source: user and a non-empty instruction_excerpt")
    result = copy.deepcopy(document)
    result.update({
        "selected_by": "douyin-simple-comic-workflow",
        "layout_source": "bundled-internal-comic-layouts",
        "internal_layout_pool": len(pool),
        "selection_scope": "per_page",
        "layout_policy": policy,
        "match_policy": match_policy,
        "pages": [],
    })
    compiled: dict[tuple[str, int], tuple[dict | None, str]] = {}
    seen: set[str] = set()
    previous_layout: str | None = None
    repeat_length = 0
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("Each page must be a mapping")
        page_id = page.get("page_id")
        if not isinstance(page_id, str) or not page_id.strip() or page_id in seen:
            raise ValueError("Each page requires a unique, non-empty page_id")
        seen.add(page_id)
        narrative = page.get("narrative_function")
        if not isinstance(narrative, str) or not narrative.strip():
            raise ValueError(f"{page_id} requires its own narrative_function")
        if not isinstance(page.get("panel_count_reason"), str) or not page["panel_count_reason"].strip():
            raise ValueError(f"{page_id} requires a narrative panel_count_reason")
        panels = page.get("panels")
        if not isinstance(panels, list) or not panels:
            raise ValueError(f"{page_id} requires non-empty panels")
        for panel in panels:
            if not isinstance(panel, dict) or any(
                not isinstance(panel.get(key), str) or not panel[key].strip()
                for key in ("focus", "main_action_or_emotion")
            ):
                raise ValueError(f"{page_id} panels require focus and main_action_or_emotion")
        count = len(panels)
        if "panel_count" in page and page["panel_count"] != count:
            raise ValueError(f"{page_id} panel_count disagrees with its actual story units")
        theme = page.get("theme", "")
        if not isinstance(theme, str):
            raise ValueError(f"{page_id} theme must be text")
        content = " ".join([theme] + [panel[key] for panel in panels
                                     for key in ("focus", "main_action_or_emotion")])
        candidates = []
        for item in pool:
            key = (item["id"], count)
            if key not in compiled:
                try:
                    contract = compile_execution_contract(
                        item, count, match_policy,
                        approved_3_4_adaptation=approved_3_4_adaptation)
                    compiled[key] = (contract, f"Native {count}-unit execution contract compiled")
                except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                    compiled[key] = (None, str(exc))
            contract, reason = compiled[key]
            score = _layout_score(item, narrative, content)
            penalty = min(repeat_length, 2) if item["id"] == previous_layout else 0
            candidate_reason = (f"{page_id} 叙事功能“{narrative}”：{reason}; narrative score={score}")
            candidates.append({"layout_id": item["id"], "score": score,
                               "compatible": contract is not None, "reason": candidate_reason,
                               "repetition_penalty": penalty, "adjusted_score": score - penalty})
        compatible = [candidate for candidate in candidates if candidate["compatible"]]
        compatible.sort(key=lambda candidate: (-candidate["score"], candidate["layout_id"]))
        if not compatible:
            raise ValueError(f"{page_id}: no executable native template matches {count} story units")
        explicit = page.get("layout_id")
        if explicit is not None:
            if not isinstance(explicit, str):
                raise ValueError(f"{page_id} layout_id must be text")
            chosen = next((candidate for candidate in compatible
                           if candidate["layout_id"].upper() == explicit.upper()), None)
            if chosen is None:
                diagnostic = next((candidate["reason"] for candidate in candidates
                                   if candidate["layout_id"].upper() == explicit.upper()), "unknown layout")
                raise ValueError(f"{page_id} requested {explicit} is incompatible: {diagnostic}")
            reason = (f"本页“{narrative}”采用页内明确指定的 {chosen['layout_id']}；"
                      f"已验证 {count} 个叙事单元与模板原生结构一致")
        else:
            best_score = compatible[0]["score"]
            # A maximum two-point semantic gap prevents variety from overriding
            # a substantially stronger narrative match or a zero-match fallback.
            near = [candidate for candidate in compatible
                    if candidate["score"] >= max(1, best_score - 2)] if best_score > 0 else compatible[:1]
            chosen = min(near, key=lambda candidate: (-candidate["adjusted_score"],
                                                     -candidate["score"], candidate["layout_id"]))
            reason = (f"本页“{narrative}”及其场景内容匹配 {chosen['layout_id']} 元数据 "
                      f"(score={chosen['score']})；仅在叙事分差不超过 2 分且原生 {count} 格可执行的候选内考虑连续重复")
        selected_id = chosen["layout_id"]
        contract = copy.deepcopy(compiled[(selected_id, count)][0])
        item = next(item for item in pool if item["id"] == selected_id)
        output_page = copy.deepcopy(page)
        mapped_panels = []
        for panel, native in zip(panels, contract["panel_geometry"]):
            mapped = copy.deepcopy(panel)
            if mapped.get("panel_id") and mapped["panel_id"] != native["panel_id"]:
                mapped["source_panel_id"] = mapped["panel_id"]
            mapped["panel_id"] = native["panel_id"]
            mapped_panels.append(mapped)
        evidence = {"page_id": page_id, "selected_layout_id": selected_id,
                    "narrative_function": narrative, "selection_scope": "per_page",
                    "candidates": candidates, "selection_reason": reason,
                    "compatible_candidate_count": len(compatible)}
        if len(compatible) < 3:
            evidence["fewer_than_three_candidates_reason"] = (
                f"Only {len(compatible)} bundled templates compile for this page's {count} native story units "
                f"under match_policy={match_policy}; rejected candidates retain their incompatibility reasons")
        # Keep compatible alternatives first, with their true narrative scores.
        evidence["candidates"] = sorted(candidates, key=lambda candidate: (
            not candidate["compatible"], -candidate["score"], candidate["layout_id"]))
        prompt_file = POOL / item["prompt_file"]
        output_page.update({
            "layout_id": selected_id, "layout_name": item["name"],
            "layout_name_en": item.get("name_en"), "panel_count": count,
            "panel_count_policy": page.get("panel_count_policy", "minimum_sufficient"),
            "panels": mapped_panels, "selected_by": "douyin-simple-comic-workflow",
            "layout_source": "bundled-internal-comic-layouts", "internal_layout_pool": len(pool),
            "selection_scope": "per_page", "selection_reason": reason, "selection_evidence": evidence,
            "match_policy": contract["match_policy"], "execution_contract": contract,
            "prompt_file": str(prompt_file),
            "prompt_text": prompt_file.read_text(encoding="utf-8") + "\n\n" + _contract_prompt(contract),
        })
        result["pages"].append(output_page)
        repeat_length = repeat_length + 1 if previous_layout == selected_id else 1
        previous_layout = selected_id
    result["page_count"] = len(result["pages"])
    result["planned_story_units"] = sum(len(page["panels"]) for page in result["pages"])
    result["planned_panel_count"] = sum(page["panel_count"] for page in result["pages"])
    from audit_storyboard_rhythm import audit_decision
    audit = audit_decision(result)
    if audit.get("status") != "passed":
        raise PageSelectionBlocked(audit)
    result["storyboard_rhythm_audit"] = audit
    return result


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
    ap.add_argument("--pages", type=Path,
                    help="Select and audit each page independently from a YAML/JSON story-unit plan")
    ap.add_argument("--story-function", default="")
    ap.add_argument("--theme", default="")
    ap.add_argument("--panel-count", type=int)
    ap.add_argument("--match-policy", choices=sorted(MATCH_POLICIES), default="structure_exact")
    ap.add_argument("--approved-3-4-adaptation", action="store_true",
                    help="Use only after user selected 3:4 content cover; compile an adapted target with explicit source deviations")
    ap.add_argument("--output", type=Path)
    args=ap.parse_args()
    if args.pages:
        if (args.verify or args.list or args.auto or args.layout or args.panel_count is not None
                or args.story_function or args.theme):
            ap.error("--pages supplies per-page decisions; do not combine it with single-page selection options")
        try:
            result = select_pages(_read_pages(args.pages), load_pool(), args.match_policy,
                                  approved_3_4_adaptation=args.approved_3_4_adaptation)
        except (ValueError, RuntimeError, ImportError, OSError) as exc:
            diagnostic = {"status": "blocked", "errors": [str(exc)]}
            if isinstance(exc, PageSelectionBlocked):
                diagnostic["storyboard_rhythm_audit"] = exc.audit
            print(json.dumps(diagnostic, ensure_ascii=False, indent=2), file=sys.stderr)
            raise SystemExit(2) from exc
    elif args.verify:
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
