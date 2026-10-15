#!/usr/bin/env python3
"""Deterministic storyboard layout executor.

The image model is only responsible for the artwork inside each unit.  This
module owns the page geometry: it reads an executable SB template, places any
provided unit artwork into the declared rectangles/polygons, and draws the
structural borders/overlays.  The source artwork is never modified in place.

The executor intentionally accepts both the original ``panels`` schema and the
newer ``structure.units`` schema.  This lets the five reviewed templates use
polygon/phone/inset geometry while the remaining templates can be upgraded
incrementally.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import yaml
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageOps
from template_contract import executable_text_containers


DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1440
TRANSPARENT = (0, 0, 0, 0)
WHITE = (255, 255, 255, 255)
STRUCTURE_COLOR = (34, 34, 34, 255)


def load_template(path: str | Path) -> dict[str, Any]:
    """Load one executable SB YAML template and perform basic validation."""
    template_path = Path(path)
    data = yaml.safe_load(template_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"template must be a mapping: {template_path}")
    layout_id = str(data.get("layout_id", "")).strip()
    if not layout_id:
        raise ValueError(f"template missing layout_id: {template_path}")
    return data


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalized_bounds_to_pixels(bounds: Iterable[Any], width: int, height: int) -> list[int]:
    """Convert normalized xywh to integer pixel xywh.

    The bundled templates use normalized 0..1 coordinates.  Values outside the
    range are clipped only at render time, so the manifest still reports the
    declared target geometry.
    """
    values = list(bounds)
    if len(values) != 4:
        raise ValueError(f"bounds must contain four values: {bounds!r}")
    x, y, w, h = (_as_float(v) for v in values)
    return [round(x * width), round(y * height), round(w * width), round(h * height)]


def normalized_polygon_to_pixels(polygon: Iterable[Iterable[Any]], width: int, height: int) -> list[list[int]]:
    result: list[list[int]] = []
    for point in polygon:
        values = list(point)
        if len(values) != 2:
            raise ValueError(f"polygon point must contain x,y: {point!r}")
        result.append([round(_as_float(values[0]) * width), round(_as_float(values[1]) * height)])
    return result


def _unit_source(template: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    structure = template.get("structure") or {}
    units = structure.get("units") or template.get("panels") or []
    nested = structure.get("nested_units") or template.get("nested_units") or []
    if not isinstance(units, list):
        raise ValueError("template structure.units/panels must be a list")
    if not isinstance(nested, list):
        raise ValueError("template nested_units must be a list")
    return [u for u in units if isinstance(u, dict)], [u for u in nested if isinstance(u, dict)]


def _normalise_unit(unit: dict[str, Any], width: int, height: int, fallback_order: int) -> dict[str, Any]:
    unit_id = str(unit.get("unit_id") or unit.get("panel_id") or f"P{fallback_order:02d}")
    order = int(unit.get("order") or fallback_order)
    bounds = unit.get("bounds")
    if bounds is None:
        raise ValueError(f"unit {unit_id} is missing bounds")
    pixel_bounds = normalized_bounds_to_pixels(bounds, width, height)
    geometry_type = str(unit.get("geometry_type") or ("polygon" if unit.get("polygon") else "rect"))
    result = {
        "panel_id": unit_id,
        "unit_id": unit_id,
        "order": order,
        "x": pixel_bounds[0],
        "y": pixel_bounds[1],
        "width": pixel_bounds[2],
        "height": pixel_bounds[3],
        "ratio": round(pixel_bounds[2] / pixel_bounds[3], 4) if pixel_bounds[3] else None,
        "rect_format": "xywh",
        "normalized_bounds": [float(v) for v in bounds],
        "geometry_type": geometry_type,
        "role": unit.get("role"),
        "cross_panel_allowed": bool(unit.get("cross_panel_allowed", False)),
        "evidence": unit.get("evidence") or unit.get("polygon_status"),
        "border_visible": unit.get("border_visible", (unit.get("border") or {}).get("visible", True)),
        "field_evidence": unit.get("field_evidence") or {},
        "layer": unit.get("layer", unit.get("z_index", fallback_order)),
        "frame_segments":unit.get('frame_segments') or [],
        "mask":unit.get('mask') or {},
        "alpha_required":unit.get('alpha_required',False) or (unit.get('mask') or {}).get('type')=='native_asset_alpha',
    }
    if unit.get("polygon"):
        result["polygon"] = normalized_polygon_to_pixels(unit["polygon"], width, height)
        result["normalized_polygon"] = [[float(v) for v in point] for point in unit["polygon"]]
    parent_id = unit.get("parent_id") or unit.get("parent_unit_id") or unit.get('parent_panel_id')
    if parent_id:
        result["parent_id"] = str(parent_id)
    return result


def _canvas_size(template: dict[str, Any], width: int | None, height: int | None) -> tuple[int, int]:
    """Keep an explicit target or native preview canvas without hidden stretch."""
    declared = template.get("canvas") or {}
    candidates = [template.get("source_preview_size"),
                  (template.get("preview_contract") or {}).get("source_size")]
    defaults = [declared.get("width"), declared.get("height")]
    for candidate in candidates:
        if isinstance(candidate, (list, tuple)) and len(candidate) == 2:
            defaults = [current if current is not None else fallback
                        for current, fallback in zip(defaults, candidate)]
    values = [width if width is not None else defaults[0],
              height if height is not None else defaults[1]]
    values = [DEFAULT_WIDTH if values[0] is None else int(values[0]),
              DEFAULT_HEIGHT if values[1] is None else int(values[1])]
    if min(values) <= 0:
        raise ValueError("canvas width and height must be positive")
    return values[0], values[1]


def compile_template_contract(template: dict[str, Any], width: int | None = None, height: int | None = None) -> dict[str, Any]:
    """Compile YAML into the deterministic execution handoff.

    ``panel_geometry`` remains a pixel ``xywh`` list for compatibility with the
    existing audit reports.  Polygon and nested-unit data are retained beside
    it instead of being flattened away.
    """
    width, height = _canvas_size(template, width, height)
    units, nested_units = _unit_source(template)
    compiled_units = [_normalise_unit(unit, width, height, idx) for idx, unit in enumerate(units, 1)]
    compiled_nested = [_normalise_unit(unit, width, height, idx) for idx, unit in enumerate(nested_units, 1)]
    compiled_nested_ids = {u["unit_id"] for u in compiled_nested}
    unit_ids = {u["unit_id"] for u in compiled_units}
    for nested in compiled_nested:
        parent = nested.get("parent_id")
        if parent and parent not in unit_ids and parent not in compiled_nested_ids:
            raise ValueError(f"nested unit {nested['unit_id']} references missing parent {parent}")
    ordered_units = sorted(compiled_units, key=lambda u: (u["order"], u["unit_id"]))
    ids = [u["unit_id"] for u in ordered_units]
    constraints = dict(template.get("constraints") or {})
    exact = bool(constraints.get("panel_count_exact", True))
    annotation_status = str((template.get("source") or {}).get("annotation_status") or "unknown")
    missing_fields = list(template.get("missing_fields") or [])
    blocked = not ordered_units or any("panel" in str(x).lower() for x in missing_fields)
    return {
        "layout_id": template.get("layout_id"),
        "version": template.get("version"),
        "canvas": {"width": width, "height": height,
                   "aspect_ratio": f"{width // math.gcd(width,height)}:{height // math.gcd(width,height)}"},
        "panel_geometry": ordered_units,
        "nested_units": compiled_nested,
        "reading_order": ids,
        "structure": {
            "units": ordered_units,
            "nested_units": compiled_nested,
            "geometry_types": sorted({u["geometry_type"] for u in ordered_units}),
            "frame_segments":(template.get('structure') or {}).get('frame_segments') or [],
            "shared_canvas_art":(template.get('structure') or {}).get('shared_canvas_art') or {},
        },
        "preview_reference": {
            "preview_image": (template.get("source") or {}).get("preview_image"),
            "source_note": (template.get("source") or {}).get("source_note"),
            "visual_reference_only": bool((template.get("source") or {}).get("visual_reference_only", True)),
        },
        "preview_contract": template.get("preview_contract") or template.get("preview") or {},
        "style_contract": template.get("style_contract") or {},
        "overlays": template.get("overlays") or (template.get("structure") or {}).get("overlays") or [],
        "bubbles": executable_text_containers(template),
        "source_bubble_count": len(template.get("bubbles") or []),
        "source_executable_text_zone_count": sum(z.get('executable') is True for z in template.get('text_zones',[]) if isinstance(z,dict)),
        "generator_constraints": {
            "panel_count": len(ordered_units),
            "panel_count_exact": exact,
            "preserve_panel_geometry": True,
            "preserve_reading_order": bool(constraints.get("preserve_reading_order", True)),
            "allow_add_panels": bool(constraints.get("allow_add_panels", False)),
            "allow_delete_panels": bool(constraints.get("allow_delete_panels", False)),
            "allow_merge_panels": bool(constraints.get("allow_merge_panels", False)),
            "allow_split_panels": bool(constraints.get("allow_split_panels", False)),
            "no_text_in_base_image": True,
        },
        "annotation_status": annotation_status,
        "execution_requirements":template.get('execution_requirements') or [],
        "execution_status": "blocked_missing_geometry" if blocked else "ready",
        "base_image_modified": False,
    }


def compile_execution_contract(template_or_path: dict[str, Any] | str | Path, width: int | None = None, height: int | None = None) -> dict[str, Any]:
    """Public alias used by callers that need a compiled execution handoff."""
    template = load_template(template_or_path) if isinstance(template_or_path, (str, Path)) else template_or_path
    return compile_template_contract(template, width, height)


def _clip_box(box: list[int], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = box
    left, top = max(0, x), max(0, y)
    right, bottom = min(width, x + max(0, w)), min(height, y + max(0, h))
    return left, top, right, bottom


def _asset_for(unit: dict[str, Any], assets: dict[str, str] | None) -> Path | None:
    if not assets:
        return None
    value = assets.get(unit["unit_id"]) or assets.get(unit.get("panel_id", ""))
    return Path(value) if value else None


def _paste_asset(canvas: Image.Image, unit: dict[str, Any], asset_path: Path, width: int, height: int) -> bool:
    if not asset_path.exists():
        return False
    try:
        with Image.open(asset_path) as src:
            src = src.convert("RGBA")
            if unit.get('alpha_required'):
                hist=src.getchannel('A').histogram(); total=src.width*src.height
                if hist[0]<total*.01 or sum(hist[1:])<total*.01:
                    return False
            # A breakout polygon may extend outside its declared rectangular
            # envelope (for example SB-013's lower foreground crossing).  Fit
            # artwork to the polygon envelope in that case so the overhang is
            # preserved instead of being silently clipped to panel bounds.
            if unit.get("polygon"):
                xs = [point[0] for point in unit["polygon"]]
                ys = [point[1] for point in unit["polygon"]]
                polygon_box = [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
                box = _clip_box(polygon_box, width, height)
            else:
                box = _clip_box([unit["x"], unit["y"], unit["width"], unit["height"]], width, height)
            if box[2] <= box[0] or box[3] <= box[1]:
                return False
            fitted = ImageOps.fit(src, (box[2] - box[0], box[3] - box[1]), method=Image.Resampling.LANCZOS)
            if unit.get("polygon") or unit.get('geometry_type') == 'ellipse':
                mask = Image.new("L", (width, height), 0)
                if unit.get('geometry_type') == 'ellipse' and not unit.get('polygon'):
                    ImageDraw.Draw(mask).ellipse(box, fill=255)
                else:
                    ImageDraw.Draw(mask).polygon(unit["polygon"], fill=255)
                # Both masks are required. Copying RGBA with a polygon-only
                # paste mask would erase the background under transparent
                # source pixels instead of compositing the actual silhouette.
                fitted.putalpha(ImageChops.multiply(fitted.getchannel("A"), mask.crop(box)))
                canvas.alpha_composite(fitted, dest=(box[0], box[1]))
            else:
                canvas.alpha_composite(fitted, dest=(box[0], box[1]))
        return True
    except Exception:
        return False


def _draw_unit_boundary(draw: ImageDraw.ImageDraw, unit: dict[str, Any], color: tuple[int, int, int, int], width: int) -> None:
    if unit.get('border_visible') is False:
        return
    if unit.get("polygon"):
        points = [tuple(point) for point in unit["polygon"]]
        if len(points) >= 2:
            draw.line(points + [points[0]], fill=color, width=width, joint="curve")
    else:
        x, y, w, h = unit["x"], unit["y"], unit["width"], unit["height"]
        if unit.get('geometry_type') == 'ellipse':
            draw.ellipse((x,y,x+w,y+h),outline=color,width=width)
        elif unit.get('geometry_type') == 'phone_column':
            draw.rounded_rectangle((x,y,x+w,y+h),radius=max(8,round(min(w,h)*.09)),outline=color,width=width)
        else:
            draw.rectangle((x, y, x + w, y + h), outline=color, width=width)


def _draw_phone_shell(draw, unit, style):
    """Render a chat UI structurally; no model chooses phone frames or call UI."""
    x,y,w,h=[unit[k] for k in ('x','y','width','height')]
    radius=max(8,round(w*.09)); pad=max(5,round(w*.025))
    draw.rounded_rectangle((x,y,x+w,y+h),radius=radius,fill=(18,18,18,255))
    draw.rounded_rectangle((x+pad,y+pad,x+w-pad,y+h-pad),radius=max(4,radius-pad),fill=(244,246,246,255))
    shell=style.get('phone_shell') or {}
    header_color=(127,210,235,255) if 'left' in str(unit.get('role','')) else (247,163,191,255)
    header_h=min(100,round(h*.095))
    draw.rectangle((x+pad,y+pad+20,x+w-pad,y+header_h),fill=header_color)
    # Native UI controls only; never draw call accept/hangup buttons.
    cy=y+header_h*.57
    draw.line([(x+pad+14,cy-8),(x+pad+5,cy),(x+pad+14,cy+8)],fill=(30,40,45,255),width=3)
    draw.rounded_rectangle((x+pad+9,y+h-55,x+w-pad-9,y+h-14),radius=15,fill=(255,255,255,255),outline=(150,160,160,255),width=2)


def _draw_overlay(draw: ImageDraw.ImageDraw, overlay: dict[str, Any], width: int, height: int, color: tuple[int, int, int, int], line_width: int) -> None:
    if overlay.get('story_writable') is False or overlay.get('executable') is False:
        return
    # An unresolved foreground, afterimage, or carrier declaration is not a
    # rectangle. Only explicit line/frame geometry is drawable here.
    if overlay.get('type') not in {'inset_frame','frame','polygon_outline','polyline','arrow','reading_path','fold_line','film_perforation'}:
        return
    if overlay.get('points'):
        points=normalized_polygon_to_pixels(overlay['points'],width,height)
        if len(points)>=2:draw.line([tuple(p) for p in points],fill=color,width=line_width)
        return
    if overlay.get("polygon"):
        polygon = normalized_polygon_to_pixels(overlay["polygon"], width, height)
        if len(polygon) >= 2:
            draw.line([tuple(p) for p in polygon] + [tuple(polygon[0])], fill=color, width=line_width, joint="curve")
        return
    if overlay.get("bounds"):
        box = normalized_bounds_to_pixels(overlay["bounds"], width, height)
        x, y, w, h = box
        draw.rectangle((x, y, x + w, y + h), outline=color, width=line_width)


def _unit_mask(unit: dict[str, Any], width: int, height: int) -> Image.Image:
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    if unit.get("polygon"):
        draw.polygon(unit["polygon"], fill=255)
    elif unit.get('geometry_type') == 'ellipse':
        x,y,w,h=[unit[k] for k in ('x','y','width','height')]
        draw.ellipse((x,y,x+w,y+h),fill=255)
    else:
        x, y, w, h = [unit[k] for k in ("x", "y", "width", "height")]
        draw.rectangle((x, y, x+w, y+h), fill=255)
    return mask


def _mask_count(mask: Image.Image) -> int:
    return sum(mask.histogram()[1:])


def _overlay_rect(bounds: Any, name: str, width: int, height: int) -> list[int]:
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise ValueError(f"{name} must be normalized xywh")
    x, y, w, h = [float(v) for v in bounds]
    if not (0 <= x < 1 and 0 <= y < 1 and w > 0 and h > 0 and x+w <= 1.000001 and y+h <= 1.000001):
        raise ValueError(f"{name} must stay inside the canvas")
    return normalized_bounds_to_pixels(bounds, width, height)


def _paste_image_overlay(canvas: Image.Image, overlay: dict[str, Any],
                         units: list[dict[str, Any]], bubbles: list[dict[str, Any]],
                         assets: dict[str, str] | None, width: int, height: int,
                         border_width: int) -> dict[str, Any]:
    """Composite a real alpha silhouette after borders with bounded crossing.

    No background removal, color key, inferred cutout, or rectangular masking
    can substitute for an original alpha asset. Synthetic assets are accepted
    only when explicitly marked as algorithm tests in the resulting manifest.
    """
    oid = str(overlay.get("overlay_id") or "")
    if not oid:
        raise ValueError("image overlay requires overlay_id")
    value = (assets or {}).get(str(overlay.get("asset_id") or oid)) or (assets or {}).get(oid) or overlay.get("asset_path")
    if not value or not Path(value).is_file():
        if overlay.get("required", True):
            raise FileNotFoundError(f"required image overlay {oid} has no existing alpha asset")
        return {"overlay_id":oid,"status":"not-rendered","reason":"optional_asset_missing"}
    path = Path(value)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if overlay.get("asset_sha256") != digest:
        raise ValueError(f"image overlay {oid} requires matching asset_sha256")
    origin = overlay.get("alpha_origin")
    if origin not in {"native_generated_alpha", "user_supplied_alpha", "synthetic_geometry_test"}:
        raise ValueError(f"image overlay {oid} alpha provenance is unknown")
    by_id = {u['unit_id']: u for u in units}
    source_id = str(overlay.get("source_panel_id") or "")
    source = by_id.get(source_id)
    if not source or not source.get("cross_panel_allowed"):
        raise ValueError(f"image overlay {oid} source panel must explicitly allow crossing")
    allowed_ids = overlay.get("allowed_cross_panel_ids")
    if (not isinstance(allowed_ids, list) or not allowed_ids
            or any(pid not in by_id or pid == source_id for pid in allowed_ids)):
        raise ValueError(f"image overlay {oid} requires existing allowed_cross_panel_ids")
    cross_box = _overlay_rect(overlay.get("cross_panel_bounds"), f"{oid}.cross_panel_bounds", width, height)
    target_box = _overlay_rect(overlay.get("bounds"), f"{oid}.bounds", width, height)
    x, y, w, h = target_box
    if w < 1 or h < 1:
        raise ValueError(f"image overlay {oid} target has no raster area")
    with Image.open(path) as original:
        if "A" not in original.getbands() and "transparency" not in original.info:
            raise ValueError(f"image overlay {oid} original asset has no alpha channel")
        rgba = original.convert("RGBA")
        source_alpha = rgba.getchannel("A")
        hist = source_alpha.histogram()
        if hist[0] / (rgba.width*rgba.height) < .01 or sum(hist[240:]) == 0:
            raise ValueError(f"image overlay {oid} is not a genuine transparent foreground")
        source_alpha_bbox = source_alpha.getbbox()
        source_edge_contacts = [name for name, box in (
            ("left",(0,0,1,rgba.height)),("right",(rgba.width-1,0,rgba.width,rgba.height)),
            ("top",(0,0,rgba.width,1)),("bottom",(0,rgba.height-1,rgba.width,rgba.height)))
            if source_alpha.crop(box).point(lambda v:255 if v>16 else 0).getbbox()]
        source_size = list(rgba.size)
        # Preserve the complete silhouette and aspect ratio. Bounds describe a
        # contain box, not permission to stretch or crop an alpha character.
        fitted = ImageOps.contain(rgba,(w,h), Image.Resampling.LANCZOS)
    placed_x=x+(w-fitted.width)//2;placed_y=y+(h-fitted.height)//2
    layer = Image.new("RGBA", (width,height), TRANSPARENT)
    layer.alpha_composite(fitted, dest=(placed_x,placed_y))
    alpha = layer.getchannel("A")
    active = alpha.point(lambda v: 255 if v > 16 else 0)
    source_mask = _unit_mask(source,width,height)
    crossing = ImageChops.multiply(active,ImageChops.invert(source_mask))
    allowed_cross = Image.new("L",(width,height),0)
    cx,cy,cw,ch=cross_box
    ImageDraw.Draw(allowed_cross).rectangle((cx,cy,cx+cw,cy+ch),fill=255)
    if _mask_count(ImageChops.multiply(crossing,ImageChops.invert(allowed_cross))):
        raise ValueError(f"image overlay {oid} extends outside declared cross_panel_bounds")
    recipient_counts={}
    for uid,unit in by_id.items():
        if uid==source_id:continue
        count=_mask_count(ImageChops.multiply(crossing,_unit_mask(unit,width,height)))
        if count and uid not in allowed_ids:
            raise ValueError(f"image overlay {oid} crosses forbidden panel {uid}")
        if count:recipient_counts[uid]=count
    reserved=Image.new("L",(width,height),0);rd=ImageDraw.Draw(reserved)
    for b in bubbles:
        if not b.get("bounds"):continue
        bx,by,bw,bh=normalized_bounds_to_pixels(b['bounds'],width,height)
        rd.rectangle((bx,by,bx+bw,by+bh),fill=255)
    reservation_overlap=_mask_count(ImageChops.multiply(active,reserved))
    respect_reservations=overlay.get("respect_bubble_reservations",True)
    override_reason=overlay.get("bubble_reservation_override_reason")
    if respect_reservations and reservation_overlap:
        raise ValueError(f"image overlay {oid} occupies a reserved bubble body")
    if not respect_reservations and not (isinstance(override_reason,str) and override_reason.strip()):
        raise ValueError(f"image overlay {oid} bubble-reservation adaptation requires an explicit reason and separate actual protected-region review")
    before=canvas.copy()
    after=Image.alpha_composite(canvas,layer)
    diff=ImageChops.difference(before.convert('RGB'),after.convert('RGB'))
    channels=diff.split()
    changed=ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2]).point(lambda v:255 if v>2 else 0)
    visible_cross=ImageChops.multiply(crossing,changed)
    boundary=Image.new('L',(width,height),0)
    _draw_unit_boundary(ImageDraw.Draw(boundary),source,255,border_width)
    occluded_boundary=ImageChops.multiply(ImageChops.multiply(active,boundary),changed)
    cross_count=_mask_count(visible_cross);boundary_count=_mask_count(occluded_boundary)
    if overlay.get("require_visible_crossing",True) and (cross_count==0 or boundary_count==0):
        raise ValueError(f"image overlay {oid} has no visible source-boundary crossing")
    canvas.paste(after)
    return {"overlay_id":oid,"status":"rendered","render_source":"original_alpha_asset",
            "source_panel_id":source_id,"allowed_cross_panel_ids":allowed_ids,
            "cross_panel_bounds_px":cross_box,"bounds_px":target_box,
            "asset_source_size":source_size,"asset_fitted_size":list(fitted.size),
            "asset_placement_xy":[placed_x,placed_y],"fit_mode":"uniform_contain",
            "preserve_aspect_ratio":True,
            "asset_path":str(path.resolve()),"asset_sha256":digest,"asset_modified":False,
            "alpha_origin":origin,"synthetic_input":origin=='synthetic_geometry_test',
            "source_alpha_bbox_xyxy":list(source_alpha_bbox),"actual_alpha_bbox_xyxy":list(alpha.getbbox()),
            "source_alpha_edge_contacts":source_edge_contacts,
            "source_silhouette_completeness":"unverified" if source_edge_contacts else "contained_inside_asset",
            "visual_review_warning":"Review cropped silhouette edges placed inside the page" if source_edge_contacts else None,
            "source_transparent_pixel_fraction":hist[0]/(rgba.width*rgba.height),
            "respect_bubble_reservations":respect_reservations,
            "reserved_body_alpha_overlap_pixels":reservation_overlap,
            "bubble_reservation_override_reason":override_reason,
            "protected_region_acceptance":"requires_actual_image_annotation_and_text_collision_audit",
            "cross_alpha_pixels":_mask_count(crossing),"visible_cross_pixels":cross_count,
            "source_boundary_covered_pixels":boundary_count,"recipient_cross_alpha_pixels":recipient_counts,
            "actual_geometry_source":"alpha_raster_and_before_after_pixel_comparison"}


def _draw_bubble_outline(draw: ImageDraw.ImageDraw, bubble: dict[str, Any], width: int, height: int, color: tuple[int, int, int, int], line_width: int) -> None:
    bounds = bubble.get("bounds")
    if not bounds:
        return
    x, y, w, h = normalized_bounds_to_pixels(bounds, width, height)
    shape = str(bubble.get("shape") or "caption_box").lower()
    if "burst" in shape or "impact" in shape:
        import math
        points = []
        cx, cy = x + w / 2, y + h / 2
        for idx in range(16):
            angle = 2 * math.pi * idx / 16
            radius = (w if idx % 2 == 0 else w * 0.82) / 2
            points.append((round(cx + math.cos(angle) * radius), round(cy + math.sin(angle) * (h / 2))))
        draw.line(points + [points[0]], fill=color, width=line_width, joint="curve")
    elif "round" in shape or "speech" in shape or "phone" in shape:
        draw.rounded_rectangle((x, y, x + w, y + h), radius=max(2, min(w, h) // 5), outline=color, width=line_width)
    else:
        draw.rectangle((x, y, x + w, y + h), outline=color, width=line_width)


def render_layout(
    template: dict[str, Any],
    output: str | Path,
    *,
    assets: dict[str, str] | None = None,
    source_image: str | Path | None = None,
    width: int | None = None,
    height: int | None = None,
    include_bubbles: bool = False,
    strict_assets: bool = False,
) -> dict[str, Any]:
    """Render one deterministic page and return the geometry manifest."""
    width, height = _canvas_size(template, width, height)
    contract = compile_template_contract(template, width, height)
    if contract["execution_status"] != "ready":
        raise ValueError(f"{template.get('layout_id')} has no executable panel geometry")
    if source_image:
        with Image.open(source_image) as source:
            canvas = ImageOps.fit(source.convert("RGBA"), (width, height), method=Image.Resampling.LANCZOS)
    else:
        canvas = Image.new("RGBA", (width, height), WHITE)
    draw = ImageDraw.Draw(canvas)
    missing_assets: list[str] = []
    border_cfg = contract.get("style_contract", {}).get("border", {}) or {}
    line_width = max(1, round(_as_float(border_cfg.get("width_ratio"), 0.004) * min(width, height)))
    border_color = tuple(border_cfg.get("color_rgba", STRUCTURE_COLOR)) if border_cfg.get("color_rgba") else ((0,0,0,255) if border_cfg.get('color')=='black' else STRUCTURE_COLOR)
    snapshots={}; content_changes={}
    render_units=sorted(contract["panel_geometry"] + contract.get("nested_units", []),key=lambda u:u.get('layer',u['order']))
    for unit in render_units:
        asset = _asset_for(unit, assets)
        before=canvas.copy()
        if unit.get('geometry_type') == 'phone_column':
            _draw_phone_shell(draw,unit,contract.get('style_contract') or {})
        elif asset:
            if not _paste_asset(canvas, unit, asset, width, height):
                missing_assets.append(unit["unit_id"])
        elif assets is not None:
            missing_assets.append(unit["unit_id"])
        _draw_unit_boundary(draw,unit,border_color,line_width)
        snapshots[unit['unit_id']]=canvas.copy()
        content_changes[unit['unit_id']]=ImageChops.difference(before.convert('RGB'),canvas.convert('RGB')).getbbox() is not None
    gutter_cfg = contract.get("style_contract", {}).get("gutter", {}) or {}
    gutter_execution = {"required": gutter_cfg.get("required") is True,
                        "executed": False}
    if gutter_cfg.get("required") is True:
        # Page-wide source art may supply panel interiors, but only the
        # executor supplies declared gutters. Foreground overlays are applied
        # later and may visibly cross these already established boundaries.
        union = Image.new("L", (width,height), 0)
        for unit in contract["panel_geometry"]:
            union = ImageChops.lighter(union,_unit_mask(unit,width,height))
        gutter_mask = ImageChops.invert(union)
        gutter_color = tuple(gutter_cfg["color_rgba"]) if gutter_cfg.get("color_rgba") else ImageColor.getcolor(str(gutter_cfg.get("color") or "white"),"RGBA")
        canvas.paste(gutter_color,(0,0,width,height),gutter_mask)
        gutter_execution.update(executed=True,color_rgba=list(gutter_color),
                                raster_pixel_count=_mask_count(gutter_mask),
                                stage="after_panel_assets_before_borders_and_foreground")
    image_overlays=[]
    for segment in (contract.get('structure') or {}).get('frame_segments',[]):
        _draw_overlay(draw,dict(segment,type='polyline'),width,height,border_color,line_width)
    for overlay in contract.get("overlays", []):
        if isinstance(overlay, dict):
            if overlay.get("type") in {"image_overlay","foreground_breakout_image"}:
                image_overlays.append(_paste_image_overlay(canvas,overlay,contract['panel_geometry'],contract.get('bubbles') or [],assets,width,height,line_width))
            else:
                _draw_overlay(draw, overlay, width, height, border_color, line_width)
    if include_bubbles:
        for bubble in contract.get("bubbles", []):
            if isinstance(bubble, dict):
                _draw_bubble_outline(draw, bubble, width, height, border_color, line_width)
    if strict_assets and missing_assets:
        raise FileNotFoundError(f"missing unit assets: {', '.join(missing_assets)}")
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path)
    # Bind the actual draw trace to independently sampled raster border pixels.
    actual_units=[]; pixel_verifications=[]; content_verifications=[]
    with Image.open(output_path).convert('RGB') as saved:
        # A borderless/overlapped region needs visible asset pixels. A copied
        # bounds manifest or an empty white rectangle is insufficient evidence.
        for i,unit in enumerate(render_units):
            footprint=_unit_mask(unit,width,height)
            for later in render_units[i+1:]:
                footprint=ImageChops.subtract(footprint,_unit_mask(later,width,height))
            from PIL import ImageFilter
            footprint=footprint.filter(ImageFilter.MinFilter(max(3,line_width*2+3 if (line_width*2+3)%2 else line_width*2+4)))
            bounds=footprint.getbbox(); samples=[]; snap=snapshots[unit['unit_id']].convert('RGB')
            if bounds:
                for yy in range(bounds[1],bounds[3],max(1,(bounds[3]-bounds[1])//12)):
                    for xx in range(bounds[0],bounds[2],max(1,(bounds[2]-bounds[0])//12)):
                        if footprint.getpixel((xx,yy)):
                            expected=snap.getpixel((xx,yy))
                            if saved.getpixel((xx,yy))==expected:samples.append({'xy':[xx,yy],'rgb':list(expected)})
            visible=bool(len(samples)>=3 and content_changes[unit['unit_id']] and unit['unit_id'] not in missing_assets)
            content_verifications.append({'panel_id':unit['unit_id'],'visible_asset_pixels_verified':visible,
                'asset_present':bool(_asset_for(unit,assets)),'content_changed_during_unit_execution':content_changes[unit['unit_id']],
                'visible_mask_bbox':bounds,'verified_pixel_samples':samples[:100]})
        for unit in contract['panel_geometry']:
            mask=Image.new('L',(width,height),0)
            _draw_unit_boundary(ImageDraw.Draw(mask),unit,255,line_width)
            bbox=mask.getbbox(); points=[]
            if bbox:
                for yy in range(bbox[1],bbox[3],max(1,(bbox[3]-bbox[1])//100)):
                    for xx in range(bbox[0],bbox[2],max(1,(bbox[2]-bbox[0])//100)):
                        if mask.getpixel((xx,yy))>0:points.append((xx,yy))
            matched=sum(max(saved.getpixel(p))<100 for p in points)
            support=matched/len(points) if points else 0
            borderless=unit.get('border_visible') is False
            pixel_verifications.append({'panel_id':unit['panel_id'],'raster_mask_bbox':bbox,'sample_count':len(points),'border_pixel_match_ratio':support,
                                        'border_required':not borderless,'boundary_evidence':'explicit_unframed_region' if borderless else 'drawn_border_pixels'})
            actual_units.append(dict(unit,actual_geometry_evidence='executed_draw_trace_with_visible_asset_and_border_samples'))
    output_hash=hashlib.sha256(output_path.read_bytes()).hexdigest()
    manifest = {
        **contract,
        "actual_panel_geometry": actual_units,
        "panel_geometry": actual_units,
        "actual_nested_units": contract.get("nested_units", []),
        "reading_order": contract["reading_order"],
        "no_text": not include_bubbles,
        "missing_assets": missing_assets,
        "actual_image_overlays":image_overlays,
        "gutter_execution":gutter_execution,
        "synthetic_overlay_input":any(o.get('synthetic_input') for o in image_overlays),
        "output_image": str(output_path),
        "output_image_sha256": output_hash,
        "geometry_source": "deterministic_draw_trace_with_raster_border_verification",
        "measurement_evidence": {"method":"deterministic_render_with_pixel_verification","image_sha256":output_hash,
            "geometry_observed_from_image":all(p['border_pixel_match_ratio']>.25 or next((c['visible_asset_pixels_verified'] for c in content_verifications if c['panel_id']==p['panel_id']),False) for p in pixel_verifications),
            "raster_border_verification":pixel_verifications,"raster_content_verification":content_verifications},
        "match_policy":template.get('match_policy','structure_exact'),
        "user_approved_adaptation":template.get('user_approved_adaptation',False),
        "canvas_transform":template.get('canvas_transform'),
        "source_target_deviation":template.get('source_target_deviation',[]),
        "base_image_modified": False,
    }
    return manifest


def _parse_assets(path: Path | None) -> dict[str, str] | None:
    if not path:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("assets JSON must be an object mapping unit_id to image path")
    return {str(k): str(v) for k, v in data.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute an SB layout deterministically")
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--assets", type=Path, help="JSON mapping unit/panel IDs to artwork paths")
    parser.add_argument("--source-image", type=Path, help="Optional source image copied into a new canvas")
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--include-bubbles", action="store_true", help="Draw outlines only; no text is rendered")
    parser.add_argument("--strict-assets", action="store_true")
    args = parser.parse_args()
    template = load_template(args.template)
    result = render_layout(
        template,
        args.output,
        assets=_parse_assets(args.assets),
        source_image=args.source_image,
        width=args.width,
        height=args.height,
        include_bubbles=args.include_bubbles,
        strict_assets=args.strict_assets,
    )
    manifest_path = args.manifest or args.output.with_suffix(".manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
