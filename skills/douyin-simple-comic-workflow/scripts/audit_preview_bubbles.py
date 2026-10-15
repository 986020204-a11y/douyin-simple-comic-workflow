#!/usr/bin/env python3
"""Compare original SB bubble targets with verified actual compositor drawing.

Plans/contracts are never actual render evidence. The auditor requires
accepted draw records, an output hash, unchanged base hashes, and raster
differences. Cropping transforms the target; it never clips or rewrites it.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any
from template_contract import executable_text_containers, canvas_text_binding

def _load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml
        return yaml.safe_load(text)
    return json.loads(text)

def _float(value: Any) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None

def _canvas_size(value: Any, default=(1080.0, 1440.0)) -> tuple:
    if isinstance(value, dict):
        value = [value.get("width"), value.get("height")]
    if isinstance(value, (list, tuple)) and len(value) == 2:
        w, h = _float(value[0]), _float(value[1])
        if w and h and w > 0 and h > 0:
            return w, h
    return default

def _rect(value: Any, canvas=(1080.0, 1440.0), fmt="xywh", *, allow_normalized=True) -> tuple | None:
    """Return xywh; actual body_rect records use explicit pixel xyxy."""
    if isinstance(value, dict):
        fmt = value.get("format") or value.get("rect_format") or fmt
        if all(k in value for k in ("x", "y", "width", "height")):
            value = [value[k] for k in ("x", "y", "width", "height")]
            fmt = "xywh"
        else:
            value = value.get("rect") or value.get("bounds")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    nums = [_float(x) for x in value]
    if any(x is None for x in nums):
        return None
    x, y, a, b = nums
    if allow_normalized and max(abs(x), abs(y), abs(a), abs(b)) <= 1.0001:
        x, y, a, b = x * canvas[0], y * canvas[1], a * canvas[0], b * canvas[1]
    if str(fmt).lower() in {"xyxy", "ltrb"}:
        a, b = a - x, b - y
    return (x, y, a, b) if a > 0 and b > 0 else None

def _transform_rect(rect: tuple | None, transform: dict | None) -> tuple | None:
    if rect is None or not transform:
        return rect
    scale = _float(transform.get("scale")) or 1.0
    sx = _float(transform.get("scale_x")) or scale
    sy = _float(transform.get("scale_y")) or scale
    left = _float(transform.get("crop_left_px")) or 0.0
    before = _float(transform.get("crop_top_px")) or 0.0
    after = _float(transform.get("crop_top_after_resize_px")) or 0.0
    x, y, w, h = rect
    offset_x = _float(transform.get("offset_x_px")) or 0.0
    offset_y = _float(transform.get("offset_y_px")) or 0.0
    return x * sx - left + offset_x, (y - before) * sy - after + offset_y, w * sx, h * sy

def _anchor(value: Any, canvas, *, normalized=True) -> tuple | None:
    if isinstance(value, dict):
        value = value.get("anchor") or value.get("point")
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    x, y = _float(value[0]), _float(value[1])
    if x is None or y is None:
        return None
    if normalized and max(abs(x), abs(y)) <= 1.0001:
        x, y = x * canvas[0], y * canvas[1]
    return x, y

def _transform_point(point: tuple | None, transform: dict | None) -> tuple | None:
    if point is None:
        return None
    return _transform_rect((*point, 1.0, 1.0), transform)[:2]

def _distance(a: tuple | None, b: tuple | None) -> float:
    return max(abs(a[i] - b[i]) for i in range(len(a))) if a is not None and b is not None else math.inf

def _polygon_points(value: Any, canvas, *, normalized=True) -> list[tuple]:
    if not isinstance(value, (list, tuple)):
        return []
    result = [_anchor(point, canvas, normalized=normalized) for point in value]
    return result if len(result) >= 3 and all(point is not None for point in result) else []

def _polygon_distance(want: list, got: list) -> float:
    """Vertex geometry must match; permit equivalent cyclic start/winding."""
    if len(want) < 3 or len(want) != len(got):
        return math.inf
    candidates = []
    for points in (got, list(reversed(got))):
        for offset in range(len(points)):
            shifted = points[offset:] + points[:offset]
            candidates.append(max(_distance(a, b) for a, b in zip(want, shifted)))
    return min(candidates)

def _local_raster_evidence(image_evidence: dict, polygon: list, body_rect: tuple | None = None, *, require_dark_ink=True) -> dict:
    """Independently check that the final file contains changed tail pixels.

    The renderer still supplies executed geometry; this is not semantic image
    recognition.  Hash-bound final pixels prevent a wholly empty tail from
    passing solely because a contract was copied into the draw report.
    """
    result = {"verified": False, "scope": "final_minus_base_inside_actual_tail_polygon"}
    if not polygon or not image_evidence.get("verified"):
        return result
    try:
        from PIL import Image, ImageChops, ImageDraw
        with Image.open(image_evidence["input_base_image"]) as source, Image.open(image_evidence["output_image"]) as output:
            source, output = source.convert("RGB"), output.convert("RGB")
            difference = ImageChops.difference(source, output)
            mask = Image.new("L", output.size, 0)
            ImageDraw.Draw(mask).polygon(polygon, fill=255)
            if body_rect:
                x, y, width, height = body_rect
                ImageDraw.Draw(mask).rectangle((x, y, x + width, y + height), fill=0)
            changed = Image.new("RGB", output.size)
            changed.paste(difference, mask=mask)
            bbox = changed.getbbox()
            # Border strokes are the most useful evidence on a white base.
            dark = output.convert("L").point(lambda value: 255 if value < 150 else 0)
            dark = ImageChops.multiply(dark, mask)
            dark_bbox = dark.getbbox()
            result.update(verified=bool(bbox and (dark_bbox or not require_dark_ink)), dark_ink_required=require_dark_ink,
                          pixel_difference_bbox=list(bbox) if bbox else None,
                          pixel_evidence_hash=hashlib.sha256(changed.tobytes()).hexdigest(),
                          dark_ink_bbox=list(dark_bbox) if dark_bbox else None)
    except Exception as exc:
        result["error"] = type(exc).__name__
    return result

def _font_family_evidence(expected: Any, visual: dict) -> dict:
    """A loaded brush font proves a family choice, never source glyph identity."""
    if _shape(expected) != "brush_calligraphy":
        return {"required": False, "status": "not_applicable"}
    verification = visual.get("brush_font_verification") or {}
    declared_hash = visual.get("font_file_sha256") or verification.get("sha256")
    filename = visual.get("font_file_path") or visual.get("font_path") or visual.get("font_file") or verification.get("font_file") or verification.get("path")
    path = Path(str(filename)) if filename else None
    file_hash_verified = bool(path and path.is_file() and declared_hash == _sha256(path))
    family_ok = bool(verification.get("status") == "verified"
                     and verification.get("family_class") == "brush_calligraphy"
                     and verification.get("sha256") == declared_hash
                     and file_hash_verified
                     and _shape(visual.get("font_style")) in {"brush_calligraphy", "brush_calligraphy_selected_font"})
    return {"required": True, "status": "passed" if family_ok else "failed", "font_file": str(path) if path else None,
            "font_file_sha256": declared_hash, "font_hash_verified": file_hash_verified,
            "source_glyph_pixel_match": "not_checked", "scope": "verified_selected_font_family"}

def _body_raster_evidence(image_evidence: dict, rect: tuple | None) -> dict:
    if rect is None or not image_evidence.get("verified"):
        return {"verified": False}
    try:
        from PIL import Image, ImageChops
        x, y, width, height = rect
        box = (round(x), round(y), round(x + width), round(y + height))
        with Image.open(image_evidence["input_base_image"]) as base, Image.open(image_evidence["output_image"]) as output:
            difference = ImageChops.difference(base.convert("RGB").crop(box), output.convert("RGB").crop(box))
            bbox = difference.getbbox()
        return {"verified": bool(bbox), "actual_body_crop_xyxy": box,
                "pixel_difference_bbox_within_crop": bbox,
                "pixel_evidence_hash": hashlib.sha256(difference.tobytes()).hexdigest(),
                "scope": "independently_recomputed_final_minus_base_inside_actual_body"}
    except Exception as exc:
        return {"verified": False, "error": type(exc).__name__}

def _inside(rect: tuple | None, canvas, tolerance=0.0) -> bool:
    return bool(rect is not None and rect[0] >= -tolerance and rect[1] >= -tolerance and rect[0] + rect[2] <= canvas[0] + tolerance and rect[1] + rect[3] <= canvas[1] + tolerance)

def _point_in_polygon(point: tuple, polygon: list, tolerance=1.0) -> bool:
    x, y = point
    inside = False
    for first, second in zip(polygon, polygon[1:] + polygon[:1]):
        ax, ay = first
        bx, by = second
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        if length2:
            t = min(1.0, max(0.0, ((x - ax) * dx + (y - ay) * dy) / length2))
            if math.hypot(x - ax - t * dx, y - ay - t * dy) <= tolerance:
                return True
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside

def _panel_evidence(template: dict, bubble: dict, rect: tuple | None, tail_polygon: list,
                    canvas, transform, target_source, tolerance) -> dict:
    units = ((template.get("structure") or {}).get("units") or template.get("panels") or [])
    panel = next((unit for unit in units if str(unit.get("unit_id") or unit.get("panel_id")) == str(bubble.get("panel_id"))), None)
    if canvas_text_binding(bubble):
        inside=bool(rect and _inside(rect,canvas,tolerance))
        return {'status':'passed' if inside else 'failed','reason':'explicit_canvas_lettering_binding_not_a_story_panel'}
    if panel is None:
        return {"status": "not_checked", "reason": "target_panel_geometry_not_available"}
    if bubble.get("cross_panel_allowed") is True or panel.get("cross_panel_allowed") is True:
        return {"status": "allowed", "reason": "template_explicit_cross_panel_permission"}
    panel_rect = _rect(panel.get("bounds") or panel, canvas)
    polygon = _polygon_points(panel.get("polygon"), canvas)
    if target_source:
        panel_rect = _transform_rect(panel_rect, transform)
        polygon = [_transform_point(point, transform) for point in polygon]
    if not polygon and panel_rect:
        x, y, w, h = panel_rect
        polygon = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    if not polygon or rect is None:
        return {"status": "failed", "reason": "panel_containment_geometry_missing"}
    x, y, w, h = rect
    # The actual body envelope and tail must fit.  Full polygon/ellipse
    # outlines are audited separately; using an envelope is conservative.
    points = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)] + tail_polygon
    outside = [point for point in points if not _point_in_polygon(point, polygon, tolerance)]
    return {"status": "failed" if outside else "passed", "outside_points": outside, "panel_polygon": polygon}

def _tail_binding_evidence(target_tail: dict, actual_tail: dict, block: dict, panel_id: str) -> dict:
    kind = target_tail.get("anchor_kind")
    if kind not in {"speaker", "prop", "chat_ui_nib",'thought_owner'}:
        return {"status": "not_required"}
    expected_kind = "chat_ui" if kind == "chat_ui_nib" else kind
    key = {"speaker": "speaker", "prop": "prop_id", "chat_ui_nib": "channel",'thought_owner':'thought_owner'}[kind]
    identity = block.get(key) or (block.get('speaker') if kind=='thought_owner' else None)
    valid = bool(identity and actual_tail.get("binding_kind") == expected_kind
                 and actual_tail.get("binding_id") == identity
                 and actual_tail.get("binding_panel_id") == panel_id)
    return {"status": "passed" if valid else "failed", "target_binding_kind": expected_kind,
            "target_binding_id": identity, "actual_binding_kind": actual_tail.get("binding_kind"),
            "actual_binding_id": actual_tail.get("binding_id"), "actual_binding_panel_id": actual_tail.get("binding_panel_id"),
            "scope": "executed_binding_vs_explicit_new_story_plan; speaker_visual_identity_requires_human_review"}

def _shape(value: Any) -> str | None:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_") if value is not None else None

def _canonical_style(value: Any) -> str | None:
    value = _shape(value)
    return {
        "preview_rounded_speech": "rounded_speech", "preview_phone_dialogue": "phone_dialogue",
        "preview_phone_message": "phone_dialogue", "preview_phone": "phone_dialogue",
        "preview_caption": "caption_box", "preview_caption_box": "caption_box",
        "preview_impact": "impact_burst", "preview_impact_burst": "impact_burst", "shout_burst": "impact_burst",
        "preview_display": "display_text", "preview_display_text": "display_text", "preview_brush_display_text": "display_text",
        "preview_vertical_note": "vertical_note", "preview_caption_note": "caption_note",
        'rounded_speech_oval':'rounded_speech','preview_ellipse_speech':'rounded_speech',
        'preview_impact_bubble':'impact_burst','preview_polygon':'impact_burst',
        'preview_surface_text':'display_text','note_embedded':'display_text',
    }.get(value, value)

def _canonical_color(value: Any) -> str | None:
    value = _shape(value)
    return {"#fff": "white", "#ffffff": "white", "rgb(255,255,255)": "white",
            "#000": "black", "#000000": "black", "rgb(0,0,0)": "black", "transparent": "none"}.get(value, value)

def _observed_phone_palette(template: dict, bubble: dict) -> list[str]:
    """Resolve this one explicit enum; arbitrary fills are never treated as palettes."""
    visual = bubble.get("visual_style") or {}
    phone = (template.get("style_contract") or {}).get("phone_message") or {}
    if (visual.get("fill") not in {"observed_palette", "alternating_observed"}
            or _canonical_style(visual.get("renderer")) != "phone_dialogue"
            or visual.get("evidence", "observed") != "observed"
            or phone.get("evidence") != "observed"):
        return []
    values = phone.get("fill_colors_observed")
    if not isinstance(values, list) or not values or any(not isinstance(x, str) for x in values):
        return []
    return list(dict.fromkeys(_canonical_color(x) for x in values))

def _phone_sequence(row: dict, palette: list[str], observed_sequence: Any = None) -> dict:
    """A palette does not require adjacent messages to alternate colors.

    Future repeat renderers may emit message_sequence_rendered containing
    per-message instance_id, order, rendered, body_rect, actual visual style
    and raster evidence. Compare only to explicitly observed source order.
    """
    if not isinstance(observed_sequence, dict) or observed_sequence.get("evidence") != "observed":
        return {"status": "not_checked", "required": False, "evidence": "unknown", "reason": "source_does_not_declare_an_observed_message_sequence"}
    expected_fills = observed_sequence.get("fill_order")
    if not isinstance(expected_fills, list) or len(expected_fills) < 2:
        return {"status": "not_checked", "required": True, "evidence": "unknown", "reason": "observed_sequence_has_no_executable_fill_order"}
    records = row.get("message_sequence_rendered")
    if not isinstance(records, list) or len(records) < 2:
        return {"status": "not_checked", "required": True, "evidence": "unknown", "reason": "at_least_two_actual_ordered_message_draws_required", "message_count": len(records) if isinstance(records, list) else 0}
    reasons, orders, instance_ids, fills, centers_y = [], [], [], [], []
    for item in records:
        if not isinstance(item, dict):
            reasons.append("message_record_invalid")
            continue
        order, instance_id = item.get("order"), item.get("instance_id")
        if not isinstance(order, int) or isinstance(order, bool) or order < 1:
            reasons.append("actual_repeat_order_missing_or_invalid")
        orders.append(order)
        instance_ids.append(instance_id)
        fill = (item.get("visual_style_rendered") or {}).get("fill")
        fills.append(_canonical_color(fill))
        if _canonical_color(fill) not in palette:
            reasons.append("actual_message_fill_outside_observed_palette")
        body = _actual_body(item)
        centers_y.append(body[1] + body[3] / 2 if body else None)
        pixel_hash = item.get("pixel_evidence_hash")
        if (item.get("rendered") is not True or item.get("unsafe_content_excluded")
                or body is None or item.get("pixel_difference_nonempty") is not True
                or _rect(item.get("pixel_difference_bbox"), fmt="xyxy", allow_normalized=False) is None
                or not isinstance(pixel_hash, str) or len(pixel_hash) != 64):
            reasons.append("actual_message_draw_or_raster_evidence_missing")
    if not all(isinstance(x, str) and x for x in instance_ids) or len(set(instance_ids)) != len(instance_ids):
        reasons.append("actual_message_instance_ids_missing_or_duplicate")
    if orders != list(range(1, len(records) + 1)):
        reasons.append("actual_repeat_order_not_contiguous")
    if observed_sequence.get("reading_order") == "top_to_bottom" and any(a is None or b is None or a >= b for a, b in zip(centers_y, centers_y[1:])):
        reasons.append("actual_repeat_order_does_not_follow_vertical_geometry")
    if fills != [_canonical_color(x) for x in expected_fills]:
        reasons.append("actual_message_fills_differ_from_observed_source_sequence")
    return {"status": "failed" if reasons else "passed", "required": True, "evidence": "renderer_draw_operations",
            "message_count": len(records), "actual_orders": orders, "actual_fills": fills,
            "observed_fill_order": expected_fills, "deviation": sorted(set(reasons))}

def _report_rows(report: Any) -> list[dict]:
    if not isinstance(report, dict):
        return []
    for key in ("rendered_blocks", "bubbles", "text_blocks"):
        if isinstance(report.get(key), list):
            return [dict(x) for x in report[key] if isinstance(x, dict) and x.get("selection_status") != "duplicate-skipped"]
    return []

def _actual_body(row: dict) -> tuple | None:
    # No fallback to anchor, bubble_contract_bounds or other planned geometry.
    value = row.get("body_rect")
    geometry = row.get("drawn_geometry")
    if value is None and isinstance(geometry, dict):
        value = geometry.get("body_rect") or geometry.get("body")
    if value is None and isinstance(geometry, list):
        value = next((p.get("rect") for p in geometry if isinstance(p, dict) and p.get("part") in {"body", "shape"}), None)
    return _rect(value, fmt="xyxy", allow_normalized=False)

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _image_evidence(report, deviations, report_dir=None) -> dict:
    result = {"verified": False}
    if not isinstance(report, dict):
        deviations.append("actual_render_report_missing")
        return result
    if report.get("page_acceptance_status") != "accepted":
        deviations.append("actual_page_not_accepted")
    paths = {}
    for key in ("output_image", "input_base_image"):
        value = report.get(key)
        path = Path(str(value)) if value else None
        if path is not None and not path.is_absolute() and report_dir:
            path = report_dir / path
        if path is None or not path.is_file():
            deviations.append(f"actual_{key}_file_missing")
        else:
            paths[key] = path
    if "output_image" not in paths or "input_base_image" not in paths:
        return result
    output_sha, base_sha = _sha256(paths["output_image"]), _sha256(paths["input_base_image"])
    output_hash_ok = report.get("output_image_sha256") == output_sha
    base_hash_ok = report.get("base_image_sha256_before") == base_sha == report.get("base_image_sha256_after")
    if not output_hash_ok:
        deviations.append("actual_output_image_hash_missing_or_mismatch")
    if not base_hash_ok or report.get("base_image_modified") is not False:
        deviations.append("base_image_unchanged_evidence_missing_or_mismatch")
    try:
        from PIL import Image, ImageChops
        with Image.open(paths["input_base_image"]) as base, Image.open(paths["output_image"]) as final:
            size_ok = base.size == final.size
            difference = ImageChops.difference(base.convert("RGB"), final.convert("RGB")) if size_ok else None
            bbox = difference.getbbox() if difference else None
            difference_hash = hashlib.sha256(difference.tobytes()).hexdigest() if difference else None
            result.update(actual_canvas=list(final.size), page_pixel_difference_bbox=bbox, page_pixel_evidence_hash=difference_hash)
        if not size_ok:
            deviations.append("actual_output_canvas_differs_from_base")
        if bbox is None:
            deviations.append("actual_output_has_no_text_layer_pixel_difference")
        page_raster_ok = bool(bbox is not None and report.get("pixel_difference_nonempty") is True
                              and report.get("pixel_evidence_hash") == difference_hash
                              and tuple(report.get("pixel_difference_bbox") or ()) == tuple(bbox))
        if not page_raster_ok:
            deviations.append("actual_page_raster_evidence_missing_or_mismatch")
    except Exception as exc:
        deviations.append(f"actual_output_image_unreadable: {type(exc).__name__}")
        size_ok, bbox, page_raster_ok = False, None, False
    result.update(output_image=str(paths["output_image"]), input_base_image=str(paths["input_base_image"]), output_image_sha256=output_sha, output_hash_match=output_hash_ok,
                  base_hash_match=base_hash_ok, page_raster_evidence_match=page_raster_ok,
                  verified=bool(size_ok and page_raster_ok and output_hash_ok and base_hash_ok and report.get("base_image_modified") is False))
    return result

def audit(template: dict, plan: Any, *, render_report: Any = None, transform: dict | None = None,
          tolerance=8.0, coordinate_space="target", target_coordinate_space="source", report_dir=None) -> dict:
    template_canvas = _canvas_size(template.get("canvas"))
    source_canvas = _canvas_size((transform or {}).get("source_canvas"), template_canvas)
    output_canvas = _canvas_size((transform or {}).get("fill_target_canvas"), template_canvas)
    target_source = bool(transform and target_coordinate_space == "source")
    target_canvas = source_canvas if target_source else output_canvas
    all_target = [dict(x) for x in executable_text_containers(template) if x.get("bubble_id")]
    plan = plan if isinstance(plan, dict) else {}
    plan_by_bubble = {str(block.get("bubble_id")): block for block in (plan.get("text_blocks") or []) if isinstance(block, dict) and block.get("bubble_id")}
    actual = _report_rows(render_report)
    deviations = []
    image_evidence = _image_evidence(render_report, deviations, report_dir)
    if isinstance(render_report, dict):
        actual_layout = render_report.get("selected_layout") or render_report.get("layout_id")
        if actual_layout != template.get("layout_id"):
            deviations.append(f"actual_selected_layout {actual_layout!r} != {template.get('layout_id')!r}")
    if image_evidence.get("actual_canvas") and tuple(image_evidence["actual_canvas"]) != output_canvas:
        deviations.append("actual_canvas_does_not_match_target_canvas")
    all_target_ids = [str(x["bubble_id"]) for x in all_target]
    if len(set(all_target_ids)) != len(all_target_ids):
        deviations.append("duplicate_template_bubble_ids")
    actual_ids = [str(x.get("bubble_id") or "") for x in actual]
    if any(not x for x in actual_ids):
        deviations.append("actual_bubble_id_missing")
    if len(set(actual_ids)) != len(actual_ids):
        deviations.append("duplicate_actual_bubble_ids")
    actual_by_id = {str(x.get("bubble_id")): x for x in actual if x.get("bubble_id")}
    active_ids = plan.get("bubble_active_ids")
    subset_requested = plan.get("bubble_selection_policy") == "story_subset" or plan.get("story_subset") is True
    explicit_subset = bool(subset_requested and isinstance(active_ids, list) and active_ids and plan.get("bubble_subset_reason"))
    if subset_requested and not explicit_subset:
        deviations.append("story_subset_requires_bubble_active_ids_and_bubble_subset_reason")
    active_set = {str(x) for x in active_ids} if explicit_subset else set(all_target_ids)
    if active_set - set(all_target_ids):
        deviations.append(f"active_bubble_ids_not_in_template: {sorted(active_set - set(all_target_ids))}")
    # Only an explicit optional template declaration permits silent omission.
    target = [x for x in all_target if str(x["bubble_id"]) in active_set and (x.get("optional") is not True or str(x["bubble_id"]) in actual_by_id)]
    target_ids = [str(x["bubble_id"]) for x in target]
    missing = [x for x in target_ids if x not in actual_by_id]
    extra = [x for x in actual_ids if x not in target_ids]
    if missing:
        deviations.append(f"missing_bubble_ids: {missing}")
    if extra:
        deviations.append(f"unexpected_bubble_ids: {extra}")
    bubble_reading_order_match = actual_ids == target_ids
    if (template.get("constraints") or {}).get("preserve_reading_order", True) and not bubble_reading_order_match:
        deviations.append(f"actual_bubble_draw_order {actual_ids} != target {target_ids}")
    omitted = [x for x in all_target_ids if x not in actual_by_id]
    shape_match = position_match = bounds_match = tail_match = binding_match = visual_style_match = body_shape_match = True
    actual_render_verified = image_evidence["verified"]
    phone_palette_matches, phone_sequences, unverified, font_evidence = [], [], [], []
    rows = []
    for want in target:
        bid = str(want["bubble_id"])
        got = actual_by_id.get(bid)
        if got is None:
            shape_match = position_match = bounds_match = tail_match = binding_match = visual_style_match = False
            actual_render_verified = False
            continue
        rendered_ok = got.get("rendered") is True and not got.get("unsafe_content_excluded")
        evidence_bbox = _rect(got.get("pixel_difference_bbox"), fmt="xyxy", allow_normalized=False)
        pixel_hash = got.get("pixel_evidence_hash")
        pixel_ok = bool(got.get("pixel_difference_nonempty") is True and evidence_bbox is not None and isinstance(pixel_hash, str) and len(pixel_hash) == 64 and all(c in "0123456789abcdef" for c in pixel_hash.lower()))
        actual_render_verified &= rendered_ok and pixel_ok
        if not rendered_ok:
            deviations.append(f"{bid}.actual_bubble_not_rendered")
        if not pixel_ok:
            deviations.append(f"{bid}.actual_raster_evidence_missing")
        want_rect = _rect(want.get("bounds"), target_canvas, str(want.get("bounds_format") or "xywh"))
        if target_source:
            want_rect = _transform_rect(want_rect, transform)
        got_rect = _actual_body(got)
        if coordinate_space == "source":
            got_rect = _transform_rect(got_rect, transform)
        body_pixel_evidence = _body_raster_evidence(image_evidence, got_rect)
        pixel_ok &= body_pixel_evidence["verified"]
        actual_render_verified &= body_pixel_evidence["verified"]
        if not body_pixel_evidence["verified"]:
            deviations.append(f"{bid}.actual_body_region_has_no_verified_pixel_difference")
        target_inside, actual_inside = _inside(want_rect, output_canvas), _inside(got_rect, output_canvas)
        if not target_inside:
            deviations.append(f"{bid}.target_bubble_clipped_by_canvas_transform: {want_rect}")
        if not actual_inside:
            deviations.append(f"{bid}.actual_body_missing_or_outside_canvas: {got_rect}")
        rect_ok = target_inside and actual_inside and _distance(want_rect, got_rect) <= tolerance
        bounds_match &= rect_ok
        if not rect_ok:
            deviations.append(f"{bid}.bounds actual={got_rect} target={want_rect} tolerance={tolerance}")
        # Position comes from actual pixels/drawn bounds, never a copied label.
        pos_ok = rect_ok
        position_match &= pos_ok
        want_panel = str(want.get("panel_id") or "")
        got_panel = str(got.get("panel_id") or got.get("selected_panel") or "")
        bind_ok = bool(want_panel and got_panel == want_panel)
        binding_match &= bind_ok
        if not bind_ok:
            deviations.append(f"{bid}.panel_id {got_panel!r} != {want_panel!r}")
        want_visual = want.get("visual_style") if isinstance(want.get("visual_style"), dict) else {}
        got_visual = got.get("visual_style_rendered") if isinstance(got.get("visual_style_rendered"), dict) else {}
        expected_shape = _canonical_style(want_visual.get("renderer") or want.get("shape"))
        actual_shape = _canonical_style(got.get("shape_rendered"))
        shape_ok = bool(actual_shape and expected_shape == actual_shape)
        expected_body_shape = _shape((want.get("body") or {}).get("shape") or want.get("shape"))
        expected_body_shape = {"rectangle": "rect", "rounded_rectangle": "rounded_rect", "oval": "ellipse"}.get(expected_body_shape, expected_body_shape)
        actual_body_shape = _shape(got.get("body_shape_rendered"))
        actual_body_shape = {"rectangle": "rect", "rounded_rectangle": "rounded_rect", "oval": "ellipse"}.get(actual_body_shape, actual_body_shape)
        body_ok = True
        body_polygon_distance = None
        if expected_body_shape in {"ellipse", "rounded_rect", "rect", "polygon"}:
            body_ok = expected_body_shape == actual_body_shape
            if expected_body_shape == "polygon":
                wp_body = _polygon_points(want.get("polygon") or (want.get("body") or {}).get("polygon"), target_canvas)
                gp_body = _polygon_points(got.get("body_polygon_rendered"), output_canvas, normalized=False)
                if target_source:
                    wp_body = [_transform_point(point, transform) for point in wp_body]
                if coordinate_space == "source":
                    gp_body = [_transform_point(point, transform) for point in gp_body]
                body_polygon_distance = _polygon_distance(wp_body, gp_body)
                body_ok &= body_polygon_distance <= tolerance
            radius_ratio = _float(want_visual.get("corner_radius_ratio"))
            if expected_body_shape == "rounded_rect" and radius_ratio is not None and want_rect:
                expected_radius = min(want_rect[2:]) * radius_ratio
                actual_radius = _float(got.get("actual_corner_radius_px"))
                body_ok &= actual_radius is not None and abs(expected_radius - actual_radius) <= tolerance
            if not body_ok:
                deviations.append(f"{bid}.actual_body_instance_geometry_does_not_match_observed_shape: {actual_body_shape!r} != {expected_body_shape!r}; polygon_distance={body_polygon_distance}")
        body_shape_match &= body_ok
        shape_ok &= body_ok
        shape_match &= shape_ok
        if not shape_ok:
            deviations.append(f"{bid}.actual_shape {actual_shape!r} != {expected_shape!r}")
        visual_ok = bool(got_visual)
        palette = _observed_phone_palette(template, want)
        palette_ok = None
        sequence = {"status": "not_applicable"}
        if not got_visual:
            deviations.append(f"{bid}.actual_visual_style_missing")
        if want_visual and want_visual.get("evidence", "observed") == "observed":
            for key in ("renderer", "fill", "border", "tail_shape", "text_color", "font_style", "text_direction", "writing_direction", "rotation_degrees"):
                expected = want_visual.get(key)
                if expected is None:
                    continue
                actual_value = got_visual.get(key)
                if key == "font_style" and _shape(expected) == "brush_calligraphy":
                    font_result = _font_family_evidence(expected, got_visual)
                    font_evidence.append({"bubble_id": bid, **font_result})
                    if font_result["status"] != "passed":
                        visual_ok = False
                        deviations.append(f"{bid}.brush_font_family_not_verified_from_loaded_file")
                    continue
                if key == "fill" and expected in {"observed_palette", "alternating_observed"} and palette:
                    palette_ok = _canonical_color(actual_value) in palette
                    phone_palette_matches.append(palette_ok)
                    if not palette_ok:
                        visual_ok = False
                        deviations.append(f"{bid}.actual_visual_style.fill {actual_value!r} outside observed phone palette {palette}")
                    observed_sequence = ((template.get("style_contract") or {}).get("phone_message") or {}).get("sequence")
                    sequence = _phone_sequence(got, palette, observed_sequence)
                    phone_sequences.append({"bubble_id": bid, "observed_palette": palette,
                                            "actual_fill": actual_value, "palette_match": palette_ok, **sequence})
                    if sequence["status"] == "failed":
                        deviations.append(f"{bid}.phone_message_sequence_failed: {sequence['deviation']}")
                    elif sequence["status"] == "not_checked" and sequence.get("required"):
                        unverified.append(f"{bid}.phone_message_sequence_not_checked")
                    continue
                compare = _canonical_style if key == "renderer" else (_canonical_color if key in {"fill", "border", "text_color"} else _shape)
                if actual_value is None or compare(expected) != compare(actual_value):
                    visual_ok = False
                    deviations.append(f"{bid}.actual_visual_style.{key} {actual_value!r} != {expected!r}")
        visual_style_match &= visual_ok
        want_tail = want.get("tail") or {}
        got_tail = got.get("tail_rendered") if isinstance(got.get("tail_rendered"), dict) else {}
        wm, gm = _shape(want_tail.get("mode")), _shape(got_tail.get("mode"))
        wa, ga = _anchor(want_tail.get("anchor"), target_canvas), _anchor(got_tail.get("anchor"), output_canvas, normalized=False)
        if target_source:
            wa = _transform_point(wa, transform)
        if coordinate_space == "source":
            ga = _transform_point(ga, transform)
        wp = _polygon_points(want_tail.get("observed_polygon") or want_tail.get("polygon"), target_canvas)
        gp = _polygon_points(got_tail.get("polygon") or got_tail.get("observed_polygon"), output_canvas, normalized=False)
        if target_source:
            wp = [_transform_point(point, transform) for point in wp]
        if coordinate_space == "source":
            gp = [_transform_point(point, transform) for point in gp]
        tail_pixel_evidence = {"verified": False, "required": wm == "observed_polygon"}
        if wm in {None, "", "unknown", "none"}:
            tail_ok = bool(got_tail and gm in {"none", "unknown"} and ga is None and got_tail.get("status") != "drawn")
            if wm == "unknown":
                unverified.append(f"{bid}.source_tail_unknown")
        elif wm=='observed_dots':
            want_dots=[_rect(q,target_canvas) for q in want_tail.get('dots') or []]
            got_dots=[_rect(q,output_canvas,allow_normalized=False) for q in got_tail.get('dots') or []]
            if target_source:want_dots=[_transform_rect(q,transform) for q in want_dots]
            if coordinate_space=='source':got_dots=[_transform_rect(q,transform) for q in got_dots]
            matched=bool(want_dots and len(want_dots)==len(got_dots) and all(a and b and max(abs(x-y) for x,y in zip(a,b))<=tolerance for a,b in zip(want_dots,got_dots)))
            operations=[q for q in got.get('drawn_geometry') or [] if q.get('part')=='thought_connector']
            operations_ok=len(operations)==len(got_dots) and all(_rect(q.get('rect'),output_canvas,'xyxy',allow_normalized=False)==r for q,r in zip(operations,got_dots))
            dot_pixels=[]
            if image_evidence.get('verified'):
                from PIL import Image,ImageChops,ImageDraw
                with Image.open(image_evidence['input_base_image']) as base_im,Image.open(image_evidence['output_image']) as final_im:
                    diff=ImageChops.difference(base_im.convert('RGB'),final_im.convert('RGB'))
                    for dot in got_dots:
                        if not dot:dot_pixels.append(False);continue
                        mask=Image.new('L',final_im.size,0);x,y,dw,dh=dot
                        ImageDraw.Draw(mask).ellipse((x,y,x+dw,y+dh),fill=255)
                        changed=Image.composite(diff,Image.new('RGB',diff.size),mask)
                        dot_pixels.append(bool(changed.getbbox()))
            tail_pixel_evidence={'verified':bool(dot_pixels and all(dot_pixels)),'scope':'each_actual_thought_dot_final_minus_base','each_dot_changed':dot_pixels,'draw_operations_match':operations_ok}
            tail_ok=bool(matched and operations_ok and tail_pixel_evidence['verified'] and gm==wm and got_tail.get('status')=='drawn' and got_tail.get('pixel_difference_nonempty') is True and wa==ga)
            gp=[corner for q in got_dots if q for corner in [(q[0],q[1]),(q[0]+q[2],q[1]+q[3])]]
        elif wm == "observed_polygon":
            dark_ink_required = _canonical_color(got_visual.get("border")) == "black" or _canonical_color(got_visual.get("fill")) == "black"
            tail_pixel_evidence = _local_raster_evidence(image_evidence, gp, got_rect, require_dark_ink=dark_ink_required)
            # The tip is a separately observed vertex, not an arbitrary point
            # inferred from a speaker or copied from a text-plan anchor.
            tip_in_polygon = bool(ga and any(_distance(ga, vertex) <= tolerance for vertex in gp))
            polygon_inside_canvas = bool(gp and all(0 <= point[0] < output_canvas[0] and 0 <= point[1] < output_canvas[1] for point in gp))
            draw_geometry = got.get("drawn_geometry") or []
            actual_tail_draws = [part for part in draw_geometry if isinstance(part, dict) and part.get("part") == "tail"] if isinstance(draw_geometry, list) else []
            operation_polygon = _polygon_points(actual_tail_draws[0].get("polygon"), output_canvas, normalized=False) if actual_tail_draws else []
            if coordinate_space == "source":
                operation_polygon = [_transform_point(point, transform) for point in operation_polygon]
            operation_match = _polygon_distance(gp, operation_polygon) <= tolerance
            tail_ok = bool(got_tail and gm == wm and got_tail.get("status") == "drawn"
                           and wa is not None and ga is not None and _distance(wa, ga) <= tolerance
                           and _polygon_distance(wp, gp) <= tolerance and tip_in_polygon and polygon_inside_canvas
                           and operation_match and tail_pixel_evidence.get("verified")
                           and got_tail.get("pixel_difference_nonempty") is True)
            tail_pixel_evidence.update(target_polygon=wp, actual_polygon=gp, polygon_distance_px=_polygon_distance(wp, gp),
                                       tip_is_polygon_vertex=tip_in_polygon, polygon_inside_canvas=polygon_inside_canvas,
                                       tail_draw_operation_match=operation_match)
        else:
            tail_ok = bool(got_tail and wm == gm and got_tail.get("status") == "drawn" and ((wa is None and ga is None) or _distance(wa, ga) <= tolerance))
        tail_binding = _tail_binding_evidence(want_tail, got_tail, plan_by_bubble.get(bid) or {}, want_panel)
        if tail_binding["status"] == "failed":
            tail_ok = False
            deviations.append(f"{bid}.actual_tail_binding_differs_from_explicit_new_story_binding")
        tail_match &= tail_ok
        if not tail_ok:
            deviations.append(f"{bid}.actual_tail {got_tail} != {want_tail}")
        panel_containment = _panel_evidence(template, want, got_rect, gp, target_canvas, transform, target_source, tolerance)
        if canvas_text_binding(want) or want.get('cross_panel_allowed') is True:
            protection=got.get('global_protection_evidence') or {}
            if protection.get('status')!='ready' or protection.get('scope')!='canvas':
                deviations.append(f'{bid}.canvas_or_overflow_global_protection_evidence_missing')
                binding_match=False
        if _shape((want.get('visual_style') or {}).get('renderer')) in {'preview_surface_text','note_embedded'}:
            surface=got.get('surface_text_evidence') or {}
            if surface.get('status')!='ready' or surface.get('background_created') is not False or surface.get('carrier_polygon_verified') is not True:
                deviations.append(f'{bid}.actual_surface_carrier_evidence_missing')
                binding_match=False
        if panel_containment["status"] == "failed":
            deviations.append(f"{bid}.actual_body_or_tail_crosses_bound_panel_without_permission")
            binding_match = False
        rows.append({"bubble_id": bid, "target_panel_id": want_panel, "actual_panel_id": got_panel, "panel_binding_match": bind_ok,
                     "target_shape": expected_shape, "actual_shape": actual_shape, "shape_match": shape_ok,
                     "target_body_shape": expected_body_shape, "actual_body_shape": actual_body_shape,
                     "body_instance_geometry_match": body_ok, "body_polygon_distance_px": body_polygon_distance,
                     "target_position": want.get("position"), "actual_position_source": "drawn_body_rect", "position_match": pos_ok,
                     "target_bounds": want_rect, "actual_bounds": got_rect, "bounds_match": rect_ok,
                     "target_inside_canvas": target_inside, "actual_inside_canvas": actual_inside,
                     "target_tail": want_tail, "actual_tail": got_tail, "tail_match": tail_ok,
                     "tail_pixel_evidence": tail_pixel_evidence,
                     "tail_binding_evidence": tail_binding,
                     "panel_containment": panel_containment,
                     "phone_message_palette_match": palette_ok, "phone_message_sequence": sequence,
                     "visual_style_match": visual_ok, "rendered_verified": rendered_ok, "raster_evidence_verified": pixel_ok})
        rows[-1]["body_pixel_evidence"] = body_pixel_evidence
    has_bubble_evidence = bool(all_target or actual)
    active_match = bool(has_bubble_evidence and target and not deviations and actual_render_verified and binding_match and shape_match and position_match and bounds_match and tail_match and visual_style_match)
    mandatory_omitted = [str(x["bubble_id"]) for x in all_target if str(x["bubble_id"]) in omitted and x.get("optional") is not True]
    full_structure_match = bool(active_match and not mandatory_omitted and not explicit_subset and not unverified)
    mapping = template.get("source_mapping") or plan.get("canvas_transform") or transform or {}
    adapted = bool(template.get("match_policy") == "adapted" or plan.get("match_policy") == "adapted" or mapping.get("match_policy") == "adapted")
    approved = template.get("user_approved_adaptation") is True or plan.get("user_approved_adaptation") is True or mapping.get("user_approved_adaptation") is True
    source_deviation = template.get("source_target_deviation") or plan.get("source_target_deviation") or mapping.get("source_target_deviation") or []
    exact_source_match = full_structure_match and not adapted
    if explicit_subset:
        deviations.append("story_subset_is_not_full_preview_structure")
    return {"bubble_audit_version": "0.3-native-tail-and-source-mapping", "selected_layout": template.get("layout_id"),
            "bubble_count_target": len(all_target), "bubble_count_active_target": len(target), "bubble_count_actual": len(actual),
            "bubble_ids_match": not missing and not extra, "missing_bubble_ids": missing, "omitted_template_bubble_ids": omitted,
            "bubble_reading_order_match": bubble_reading_order_match,
            "unused_template_bubble_ids": omitted, "bubble_selection_policy": "story_subset" if explicit_subset else "all_template_bubbles",
            "active_bubbles_match": active_match, "full_bubble_structure_match": full_structure_match, "full_structure_match": full_structure_match,
            "execution_bubble_match": "passed" if full_structure_match else "failed",
            "adapted_target_match": "passed" if adapted and full_structure_match else "failed" if adapted else "not_applicable",
            "source_reference_bubble_match": "passed" if exact_source_match else "failed",
            "match_policy": "adapted" if adapted else "source_reference", "user_approved_adaptation": approved,
            "source_target_deviation": source_deviation,
            "panel_binding_match": binding_match, "preview_bubble_shape_match": shape_match if has_bubble_evidence else "not-checked",
            "preview_bubble_instance_shape_match": body_shape_match if has_bubble_evidence else "not-checked",
            "preview_bubble_position_match": position_match if has_bubble_evidence else "not-checked",
            "preview_bubble_bounds_match": bounds_match if has_bubble_evidence else "not-checked",
            "preview_bubble_tail_match": tail_match if has_bubble_evidence else "not-checked",
            "preview_bubble_visual_style_match": visual_style_match if has_bubble_evidence else "not-checked",
            "preview_phone_message_palette_match": all(phone_palette_matches) if phone_palette_matches else "not_applicable",
            "preview_phone_message_sequence_match": ("failed" if any(x["status"] == "failed" for x in phone_sequences)
                                                     else "not_checked" if any(x["status"] == "not_checked" for x in phone_sequences)
                                                     else "passed" if phone_sequences else "not_applicable"),
            "phone_message_sequence_required": any(x.get("required") for x in phone_sequences),
            "font_family_evidence": font_evidence, "source_font_pixel_match": "not_checked" if font_evidence else "not_applicable",
            "phone_message_sequences": phone_sequences, "bubble_unverified": unverified,
            "preview_style_match": "passed" if exact_source_match else ("not-checked" if active_match and unverified and not explicit_subset and not adapted else "failed" if has_bubble_evidence else "not-checked"),
            "actual_render_verified": actual_render_verified, "actual_geometry_source": "renderer_draw_operations",
            "image_evidence": image_evidence, "evidence_scope": "deterministic_draw_geometry_and_hash_bound_raster_difference; not independent semantic image recognition",
            "human_visual_review": "pending", "bubble_deviation": deviations, "bubbles": rows, "coordinate_space": coordinate_space,
            "target_coordinate_space": target_coordinate_space, "source_canvas": source_canvas, "target_canvas": output_canvas, "canvas_transform": transform,
            "base_image_modified": False if image_evidence.get("base_hash_match") else "unverified"}

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--template", type=Path, required=True)
    ap.add_argument("--text-plan", "--actual-report", "--text-report", dest="text_plan", type=Path, required=True)
    ap.add_argument("--render-report", type=Path, required=True, help="Actual compositor report, never a text plan")
    ap.add_argument("--transform", type=Path)
    ap.add_argument("--coordinate-space", choices=["target", "source"], default="target", help="Actual draw coordinate space")
    ap.add_argument("--target-coordinate-space", choices=["source", "target"], default="source", help="Apply crop/scale to original template without clipping")
    ap.add_argument("--tolerance", type=float, default=8.0)
    ap.add_argument("--accept-adapted-target", action="store_true", help="Exit successfully for an explicitly approved adapted target; source match remains failed")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    transform = _load(args.transform) if args.transform else None
    if isinstance(transform, dict) and isinstance(transform.get("canvas_transform"), dict):
        transform = transform["canvas_transform"]
    result = audit(_load(args.template) or {}, _load(args.text_plan), render_report=_load(args.render_report), transform=transform,
                   tolerance=args.tolerance, coordinate_space=args.coordinate_space, target_coordinate_space=args.target_coordinate_space,
                   report_dir=args.render_report.parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    accepted = result["preview_style_match"] == "passed" or (args.accept_adapted_target and result["user_approved_adaptation"] and result["adapted_target_match"] == "passed")
    raise SystemExit(0 if accepted else 2)

if __name__ == "__main__":
    main()
