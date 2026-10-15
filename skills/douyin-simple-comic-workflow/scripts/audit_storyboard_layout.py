#!/usr/bin/env python3
"""Audit a generated no-text page against the selected storyboard template.

The old audit trusted ``actual.json``.  That made a copied target manifest look
like a successful render even when the PNG used rectangular clipping, omitted a
broken frame, or lost nested units.  This audit keeps the manifest as a useful
measurement input, but also inspects the supplied no-text image at expected
boundaries and checks executable-template geometry metadata.

The audit never edits the base image.  It is conservative: missing actual
geometry, required polygons/nested units, or an unreadable image fails the
storyboard match regardless of ``selected_layout``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any
from template_contract import executable_text_containers


def _load(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("PyYAML is required to read YAML templates") from exc
        value = yaml.safe_load(text)
    else:
        value = json.loads(text)
    return value or {}


def _contract(target: dict) -> dict:
    return target.get("execution_contract") or target


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _rect_from(value: Any, canvas: tuple[int, int] = (1080, 1440)) -> dict | None:
    """Normalize xywh, including normalized template bounds, to pixel xywh."""
    if isinstance(value, dict):
        if all(k in value for k in ("x", "y", "width", "height")):
            return {k: float(value[k]) for k in ("x", "y", "width", "height")}
        value = value.get("bounds")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    vals = [_as_float(v) for v in value]
    if any(v is None for v in vals):
        return None
    x, y, w, h = (float(v) for v in vals)
    if max(abs(x), abs(y), abs(w), abs(h)) <= 1.0001:
        return {"x": x * canvas[0], "y": y * canvas[1],
                "width": w * canvas[0], "height": h * canvas[1]}
    return {"x": x, "y": y, "width": w, "height": h}


def _template_units(target: dict, contract: dict) -> list[dict]:
    """Return target units, preserving structure metadata from a YAML template."""
    canvas = contract.get("canvas") or {}
    size = (int(canvas.get("width", 1080)), int(canvas.get("height", 1440)))
    rows = contract.get("panel_geometry") or []
    structured = contract.get("structure") or {}
    structured_units = structured.get("units") or structured.get("panels") or []
    by_id = {str(row.get("unit_id") or row.get("panel_id")): row
              for row in structured_units if isinstance(row, dict)}
    result: list[dict] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        panel_id = str(row.get("panel_id") or row.get("unit_id") or f"P{index + 1:02d}")
        merged = dict(row)
        merged.update(by_id.get(panel_id, {}))
        rect = _rect_from(merged, size)
        if rect:
            merged.update(rect)
        merged["panel_id"] = panel_id
        merged["order"] = int(merged.get("order", index + 1))
        result.append(merged)
    if not result:
        for index, row in enumerate(structured_units):
            if not isinstance(row, dict):
                continue
            merged = dict(row)
            rect = _rect_from(merged, size)
            if rect:
                merged.update(rect)
            merged["panel_id"] = str(merged.get("unit_id") or merged.get('panel_id') or f"P{index + 1:02d}")
            merged["order"] = int(merged.get("order", index + 1))
            result.append(merged)
    return sorted(result, key=lambda row: row["order"])


def _actual_units(actual: dict) -> list[dict]:
    rows = actual.get("panel_geometry") or actual.get("units") or []
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        out = dict(row)
        out["panel_id"] = str(out.get("panel_id") or out.get("unit_id") or f"P{index + 1:02d}")
        out["order"] = int(out.get("order", index + 1))
        result.append(out)
    return sorted(result, key=lambda row: row["order"])


def _polygon(row: dict, canvas=(1080, 1440)) -> list[tuple[float, float]]:
    if row.get('geometry_type')=='ellipse' and not row.get('polygon'):
        rect=_rect_from(row,canvas)
        if rect:
            x,y,w,h=[rect[k] for k in ('x','y','width','height')]
            return [(x+w/2+w/2*math.cos(i*math.tau/96),y+h/2+h/2*math.sin(i*math.tau/96)) for i in range(96)]
    points = row.get("polygon") or row.get("points") or []
    result: list[tuple[float, float]] = []
    for point in points:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            x, y = _as_float(point[0]), _as_float(point[1])
            if x is not None and y is not None:
                if max(abs(x), abs(y)) <= 1.0001:
                    x, y = x * canvas[0], y * canvas[1]
                result.append((x, y))
    return result


def _source_mapping_evidence(template: dict | None, contract: dict, target: dict, actual: dict,
                             actual_units: list[dict], tolerance: float) -> dict:
    """Keep approved 3:4 adaptation separate from original preview geometry.

    Removing a header and uniformly covering a new aspect ratio may crop
    panels.  An executable clipped target can be correct while the original
    panel rectangles are no longer complete.  Never call that source exact.
    """
    mapping = contract.get("source_mapping") or contract.get("canvas_transform") or target.get("source_mapping") or actual.get("source_mapping") or actual.get("canvas_transform") or {}
    if not isinstance(mapping, dict) or not mapping:
        return {"status": "not_checked", "reason": "no_source_to_target_mapping", "deviation": []}
    source_size = mapping.get("source_canvas") or ((template or {}).get("preview_contract") or {}).get("source_size")
    if isinstance(source_size, dict):
        source_size = [source_size.get("width"), source_size.get("height")]
    if not isinstance(source_size, (list, tuple)) or len(source_size) != 2:
        return {"status": "failed", "reason": "source_canvas_missing", "deviation": ["source_mapping_missing_real_source_dimensions"], "mapping": mapping}
    width, height = (_as_float(v, 0) for v in source_size)
    scale = _as_float(mapping.get("scale"), 1.0)
    sx, sy = _as_float(mapping.get("scale_x"), scale), _as_float(mapping.get("scale_y"), scale)
    deviation = []
    isotropic = bool(sx and sy and sx > 0 and sy > 0 and abs(sx - sy) <= max(sx, sy) * 1e-6)
    if not isotropic:
        deviation.append("source_mapping_nonuniform_scale_changes_panel_proportions")
    if width <= 0 or height <= 0:
        deviation.append("source_mapping_source_canvas_invalid")
    canvas = contract.get("canvas") or {}
    output_width, output_height = canvas.get("width", 1080), canvas.get("height", 1440)
    left = _as_float(mapping.get("crop_left_px"), 0)
    before = _as_float(mapping.get("crop_top_px"), 0)
    after = _as_float(mapping.get("crop_top_after_resize_px"), 0)
    offset_x = _as_float(mapping.get("offset_x_px"), 0)
    offset_y = _as_float(mapping.get("offset_y_px"), 0)
    units = ((template or {}).get("structure") or {}).get("units") or (template or {}).get("panels") or []
    by_id = {row.get("panel_id"): row for row in actual_units}
    rows = []
    for unit in units:
        source_rect = _rect_from(unit, (width, height))
        if source_rect is None:
            continue
        pid = str(unit.get("panel_id") or unit.get("unit_id"))
        original = [source_rect[k] for k in ("x", "y", "width", "height")]
        x, y, w, h = original
        transformed = [x * sx - left + offset_x, (y - before) * sy - after + offset_y, w * sx, h * sy]
        tx, ty, tw, th = transformed
        clipped = tx < -tolerance or ty < -tolerance or tx + tw > output_width + tolerance or ty + th > output_height + tolerance
        got = by_id.get(pid) or {}
        actual_values = [_as_float(got.get(k)) for k in ("x", "y", "width", "height")]
        full_rect_match = all(g is not None and abs(g - expected) <= tolerance for g, expected in zip(actual_values, transformed))
        if clipped:
            deviation.append(f"{pid}.source_panel_clipped_by_uniform_cover")
        if not full_rect_match:
            deviation.append(f"{pid}.actual_panel_differs_from_complete_transformed_source_panel")
        rows.append({"panel_id": pid, "source_bounds_px": original, "complete_transformed_bounds_px": transformed,
                     "source_panel_clipped": clipped, "complete_source_panel_match": full_rect_match})
    if not units:
        deviation.append("source_panel_geometry_unavailable")
    return {"status": "failed" if deviation else "passed", "isotropic_transform": isotropic, "mapping": mapping,
            "source_canvas": [width, height], "panels": rows, "deviation": deviation,
            "source_pixel_reference_match": "not_checked", "evidence_scope": "source_panel_geometry_and_declared_affine_transform"}


def _polygon_distance(want: list[tuple[float, float]], got: list[tuple[float, float]]) -> float:
    if not want or not got:
        return math.inf
    n = min(len(want), len(got))
    distances = [math.hypot(want[i][0] - got[i][0], want[i][1] - got[i][1])
                 for i in range(n)]
    return sum(distances) / len(distances) if distances else math.inf


def _image_edge_support(base_image: Path, units: list[dict]) -> dict:
    """Measure pixels around expected edges without editing the PNG.

    This is evidence, not a panel detector.  Coordinates still come from the
    actual geometry manifest when present; low support is reported so a caller
    can reject a render whose asserted border is absent from the image.
    """
    try:
        from PIL import Image
        import numpy as np  # type: ignore

        image = Image.open(base_image).convert("L")
        arr = np.asarray(image)
        height, width = arr.shape
    except Exception as exc:
        return {"status": "unreadable", "error": str(exc), "units": []}

    def support(a: tuple[float, float], b: tuple[float, float]) -> float:
        values = []
        radius = max(2, round(min(width, height) * 0.004))
        for t in np.linspace(0.02, 0.98, 180):
            x = int(round(a[0] * (1 - t) + b[0] * t))
            y = int(round(a[1] * (1 - t) + b[1] * t))
            x0, x1 = max(0, x - radius), min(width, x + radius + 1)
            y0, y1 = max(0, y - radius), min(height, y + radius + 1)
            local = arr[y0:y1, x0:x1]
            values.append(bool(local.size and (local < 105).any()))
        return round(sum(values) / len(values), 4) if values else 0.0

    output = []
    for unit in units:
        polygon = _polygon(unit)
        rect = _rect_from(unit, (width, height))
        if not polygon and rect:
            x, y, w, h = (rect[k] for k in ("x", "y", "width", "height"))
            polygon = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
        edges = [support(polygon[i], polygon[(i + 1) % len(polygon)])
                 for i in range(len(polygon))] if len(polygon) >= 2 else []
        output.append({"panel_id": unit.get("panel_id"), "edge_support": edges,
                       "mean_edge_support": round(sum(edges) / len(edges), 4) if edges else 0.0,
                       "edge_count": len(edges)})
    return {"status": "measured", "width": width, "height": height, "units": output}


def _nested_units(contract: dict) -> list[dict]:
    structure = contract.get("structure") or {}
    rows = structure.get("nested_units") or contract.get("nested_units") or []
    return [row for row in rows if isinstance(row, dict)]


def _default_template(layout_id: str | None) -> tuple[dict | None, Path | None]:
    """Resolve the bundled executable template when callers omit --template."""
    if not layout_id:
        return None, None
    candidate = Path(__file__).resolve().parent.parent / "references" / "comic-layouts" / "executable-templates" / f"{layout_id}.yaml"
    if not candidate.exists():
        return None, None
    try:
        template = _load(candidate)
    except Exception:
        return None, candidate
    preview_rel = ((template.get("source") or {}).get("preview_image"))
    preview = candidate.parent.parent / preview_rel if preview_rel else None
    return template, preview


def _foreground_crossing_evidence(record: dict, image: Path | None, image_hash: str | None,
                                  units: list[dict]) -> dict:
    """A slanted panel polygon is not evidence of a foreground crossing it."""
    if not record:
        return {"status": "not-checked", "reason": "required_foreground_breakout_has_no_actual_visible_evidence"}
    if not image or record.get("image_sha256") != image_hash:
        return {"status": "failed", "reason": "foreground_evidence_not_bound_to_actual_image"}
    boundary = record.get("crossing_boundary")
    if not isinstance(boundary, list) or len(boundary) != 2 or any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in boundary):
        return {"status": "failed", "reason": "foreground_crossing_boundary_missing"}
    try:
        a, b = [tuple(float(v) for v in p) for p in boundary]
        length = math.dist(a, b)
        if not length or not all(math.isfinite(v) for p in (a, b) for v in p):
            raise ValueError()
        def side(point):
            return ((b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]))/length
        edges=[]
        for unit in units:
            poly=_polygon(unit)
            rect=_rect_from(unit)
            if not poly and rect:
                x,y,w,h=[rect[k] for k in ('x','y','width','height')]
                poly=[(x,y),(x+w,y),(x+w,y+h),(x,y+h)]
            edges.extend(zip(poly,poly[1:]+poly[:1]))
        declared_real_edge=any((math.dist(a,e[0])<=3 and math.dist(b,e[1])<=3) or (math.dist(a,e[1])<=3 and math.dist(b,e[0])<=3) for e in edges)
        if not declared_real_edge:
            return {"status":"failed","reason":"foreground_crossing_line_is_not_an_executed_panel_edge"}
        if record.get('method')=='manual_visual_comparison':
            points=record.get('visible_foreground_points') or []
            distances=[side(p) for p in points if isinstance(p,(list,tuple)) and len(p)==2]
            valid=bool(record.get('visible_foreground_crossing') is True and record.get('geometry_observed_from_image') is True
                       and record.get('reviewer') and distances and min(distances)<-1 and max(distances)>1)
            return {'status':'passed' if valid else 'failed','method':'manual_visual_comparison',
                    'reason':'hash_bound_observed_foreground_on_both_sides' if valid else 'actual_crossing_visual_annotation_incomplete',
                    'crossing_boundary':boundary,'visible_foreground_points':points}
        if record.get('method')!='deterministic_foreground_overlay_with_pixel_verification':
            return {'status':'failed','reason':'unsupported_foreground_evidence_method'}
        from PIL import Image, ImageChops
        import numpy as np
        before=Path(str(record.get('before_overlay_image') or ''))
        mask_path=Path(str(record.get('overlay_mask') or ''))
        if not before.is_file() or not mask_path.is_file():
            return {'status':'failed','reason':'foreground_before_image_or_mask_missing'}
        if hashlib.sha256(before.read_bytes()).hexdigest()!=record.get('before_overlay_image_sha256') or hashlib.sha256(mask_path.read_bytes()).hexdigest()!=record.get('overlay_mask_sha256'):
            return {'status':'failed','reason':'foreground_before_image_or_mask_hash_mismatch'}
        with Image.open(before) as source, Image.open(image) as final, Image.open(mask_path) as raw_mask:
            if source.size!=final.size or raw_mask.size!=final.size:
                return {'status':'failed','reason':'foreground_evidence_canvas_mismatch'}
            mask=raw_mask.convert('L')
            diff=ImageChops.difference(source.convert('RGB'),final.convert('RGB'))
            visible=Image.new('RGB',final.size);visible.paste(diff,mask=mask)
            digest=hashlib.sha256(visible.tobytes()).hexdigest()
            changed=np.max(np.asarray(visible),axis=2)>0
            ys,xs=np.nonzero(changed)
            sides=((b[0]-a[0])*(ys-a[1])-(b[1]-a[1])*(xs-a[0]))/length
            crossing_pixels=int((abs(sides)<=2).sum())
            valid=bool(len(sides) and sides.min()<-1 and sides.max()>1 and crossing_pixels>0
                       and record.get('visible_foreground_crossing') is True and record.get('overlay_difference_sha256')==digest)
        return {'status':'passed' if valid else 'failed','method':record['method'],'actual_visible_difference_sha256':digest,
                'changed_pixel_count':len(sides),'changed_boundary_pixel_count':crossing_pixels,
                'reason':'visible_overlay_crosses_and_occludes_actual_panel_edge' if valid else 'foreground_mask_or_changed_pixels_do_not_prove_boundary_crossing'}
    except Exception as exc:
        return {'status':'failed','reason':'foreground_evidence_unreadable','error':type(exc).__name__}


def _text_execution_style(record: dict, base_hash: str | None, layout_id: str | None,
                          text_features: list[str], bubble_targets: list[dict]) -> dict:
    """Validate a linked final render separately from the no-text structure PNG."""
    if not record:
        return {'status':'not-checked','reason':'hash_bound_actual_text_container_evidence_missing'}
    try:
        from audit_preview_bubbles import _image_evidence, _report_rows
        audit_path=Path(str(record.get('bubble_audit_path') or record.get('audit_path') or ''))
        render_path=Path(str(record.get('render_report_path') or ''))
        if not audit_path.is_file() or not render_path.is_file():
            return {'status':'failed','reason':'linked_bubble_audit_or_render_report_missing'}
        if hashlib.sha256(audit_path.read_bytes()).hexdigest()!=(record.get('bubble_audit_sha256') or record.get('audit_sha256')) or hashlib.sha256(render_path.read_bytes()).hexdigest()!=record.get('render_report_sha256'):
            return {'status':'failed','reason':'linked_text_report_file_hash_mismatch'}
        bubble_audit,render=_load(audit_path),_load(render_path)
        deviations=[]; pixels=_image_evidence(render,deviations,render_path.parent)
        count_ok=bubble_audit.get('bubble_count_target')==bubble_audit.get('bubble_count_actual')==len(bubble_targets)
        match_ok=bubble_audit.get('execution_bubble_match')=='passed' or bubble_audit.get('full_bubble_structure_match') is True
        base_ok=render.get('base_image_sha256_before')==base_hash==render.get('base_image_sha256_after')
        final_ok=record.get('final_image_sha256')==render.get('output_image_sha256')==pixels.get('output_image_sha256')
        rows=_report_rows(render)
        by_id={str(row.get('bubble_id')):row for row in rows if row.get('rendered') is True}
        feature_evidence=[];missing=[]
        for feature in text_features:
            candidates=[]
            for bubble in bubble_targets:
                visual=bubble.get('visual_style') or {};renderer=visual.get('renderer') or ''
                match=((feature=='impact_text' and bubble.get('shape')=='display_text' and 'display' in renderer)
                       or (feature=='impact_burst' and 'impact_burst' in renderer)
                       or (feature=='display_brush_text' and (renderer=='preview_brush_display_text' or visual.get('font_style')=='brush_calligraphy'))
                       or (feature=='vertical_note' and renderer=='preview_vertical_note')
                       or (feature=='caption_note' and renderer=='preview_caption_note'))
                if match:candidates.append(bubble)
            checks=[{'bubble_id':bubble['bubble_id'],'target_renderer':bubble['visual_style']['renderer'],
                     'actual_renderer':(by_id.get(str(bubble['bubble_id']),{}).get('visual_style_rendered') or {}).get('renderer')} for bubble in candidates]
            verified=bool(checks) and all(row['target_renderer']==row['actual_renderer'] for row in checks)
            feature_evidence.append({'feature':feature,'verified':verified,'containers':checks})
            if not verified:missing.append(feature)
        valid=bool(pixels.get('verified') and not deviations and count_ok and match_ok and base_ok and final_ok
                   and bubble_audit.get('selected_layout')==layout_id and bubble_audit.get('actual_render_verified') is True and not missing)
        return {'status':'passed' if valid else 'failed','reason':'actual_final_text_containers_verified' if valid else 'linked_actual_text_container_verification_failed',
                'base_image_hash_match':base_ok,'final_image_hash_match':final_ok,'actual_container_count':len(rows),
                'required_text_features':text_features,'missing_text_feature_renderers':missing,'raster_deviation':deviations,
                'feature_container_renderer_evidence':feature_evidence,
                'base_image_sha256':base_hash,'final_image_sha256':pixels.get('output_image_sha256'),
                'scope':'actual_base_to_final_text_layer; final_hash_is_distinct_from_structure_base_hash'}
    except Exception as exc:
        return {'status':'failed','reason':'linked_text_evidence_unreadable','error':type(exc).__name__}


def _execution_style_gate(contract: dict, template: dict | None, actual: dict, image: Path | None,
                          units: list[dict], image_status: dict, measurement_verified: bool) -> dict:
    source_styles=(template or {}).get('style_contract') or {}
    styles={**source_styles,**(contract.get('style_contract') or {})}; records=actual.get('execution_style_evidence') or {}
    image_hash=hashlib.sha256(image.read_bytes()).hexdigest() if image and image.is_file() else None
    required=[key for key,value in styles.items() if (isinstance(value,dict) and value.get('required') is True)
              or (isinstance(source_styles.get(key),dict) and source_styles[key].get('required') is True)]
    excluded=((template or {}).get('annotation_coverage') or {}).get('excluded_source_decorations') or []
    results=[]; text_features=[]
    for key in required:
        if (key=='panel_label' and any('panel' in s and 'label' in s for s in excluded)) or (key=='panel_badge' and any('badge' in s for s in excluded)):
            results.append({'feature':key,'status':'excluded','reason':'explicit_source_annotation_excludes_explanatory_decoration'})
        elif key=='broken_frame':
            results.append({'feature':key,**_foreground_crossing_evidence(records.get(key) or {},image,image_hash,units)})
        elif key=='border':
            edges=(image_status.get('edge_evidence') or {}).get('required_edges') or []
            valid=measurement_verified and bool(edges) and all(row['mean_edge_support']>=row['threshold'] for row in edges)
            results.append({'feature':key,'status':'passed' if valid else 'failed','reason':'actual_hash_bound_border_pixel_support'})
        elif key in {'gutter','phone_shell'}:
            try:
                from PIL import Image,ImageDraw,ImageFilter
                import numpy as np
                with Image.open(image) as im: arr=np.asarray(im.convert('RGB'))
                if key=='gutter':
                    mask=Image.new('L',(arr.shape[1],arr.shape[0]),255); draw=ImageDraw.Draw(mask)
                    for unit in units:
                        poly=_polygon(unit); rect=_rect_from(unit)
                        if poly: draw.polygon(poly,fill=0)
                        elif rect:
                            x,y,w,h=[rect[k] for k in ('x','y','width','height')];draw.rectangle((x,y,x+w,y+h),fill=0)
                    # Panel strokes straddle the declared edge; exclude them
                    # from the gutter color sample instead of misclassifying
                    # a correct white gutter as partly black.
                    region=np.asarray(mask.filter(ImageFilter.MinFilter(9)))>0; white=np.all(arr>=235,axis=2)
                    support=float(white[region].mean()) if region.any() else 0.0
                    valid=measurement_verified and bool(region.any()) and support>=.8
                    results.append({'feature':key,'status':'passed' if valid else 'failed','white_pixel_support':support,'sample_count':int(region.sum()),'reason':'actual_uncovered_gutter_pixels'})
                else:
                    phones=[unit for unit in units if unit.get('geometry_type')=='phone_column']; checks=[]
                    for unit in phones:
                        x,y,w,h=[round(unit[k]) for k in ('x','y','width','height')]
                        crop=arr[max(0,y):min(arr.shape[0],y+round(h*.2)),max(0,x):min(arr.shape[1],x+w)].astype('int16')
                        left='left' in str(unit.get('role','')).lower()
                        color=((crop[:,:,1]>140)&(crop[:,:,2]>170)&(crop[:,:,0]<crop[:,:,1]-30)) if left else ((crop[:,:,0]>190)&(crop[:,:,2]>140)&(crop[:,:,0]>crop[:,:,1]+30))
                        checks.append({'panel_id':unit['panel_id'],'header_color':'cyan_blue' if left else 'pink','matching_header_pixels':int(color.sum())})
                    valid=measurement_verified and bool(phones) and all(row['matching_header_pixels']>=200 for row in checks)
                    results.append({'feature':key,'status':'passed' if valid else 'failed','phone_column_count':len(phones),'header_pixel_evidence':checks,'reason':'actual_phone_frames_and_observed_header_color_family'})
            except Exception as exc:
                results.append({'feature':key,'status':'failed','reason':'style_raster_evidence_unreadable','error':type(exc).__name__})
        elif key in {'impact_text','impact_burst','display_brush_text','vertical_note','caption_note'}:
            text_features.append(key)
        else:
            results.append({'feature':key,'status':'not-checked','reason':'required_style_has_no_actual_verifier'})
    bubbles=contract.get('bubbles') or executable_text_containers(template or {})
    if bubbles or text_features:
        text=_text_execution_style(records.get('text_containers') or {},image_hash,contract.get('layout_id') or actual.get('layout_id'),text_features,bubbles)
        results.append({'feature':'text_containers',**text})
    else:
        text={'status':'not_applicable'}
    requirements=contract.get('execution_requirements') or (template or {}).get('execution_requirements') or []
    if isinstance(requirements,dict):requirements=requirements.get('required_mechanisms') or []
    verified=actual.get('mechanism_verification') or {}
    for requirement in requirements:
        mechanism=(requirement.get('mechanism') or requirement.get('feature')) if isinstance(requirement,dict) else requirement
        record=verified.get(mechanism) or {}
        artifact=Path(str(record.get('evidence_path') or '__missing__'))
        artifact_bound=artifact.is_file() and record.get('evidence_sha256')==hashlib.sha256(artifact.read_bytes()).hexdigest()
        reviewed=record.get('method')=='manual_visual_comparison' and bool(record.get('reviewer'))
        verified_method=reviewed or (record.get('method')=='deterministic_raster_verification' and artifact_bound)
        if mechanism and not (record.get('status')=='passed' and record.get('image_sha256')==image_hash and verified_method):
            results.append({'feature':str(mechanism),'status':'not-checked','reason':'required_mechanism_has_no_hash_bound_actual_proof'})
    states=[row['status'] for row in results if row['status']!='excluded']
    status='failed' if 'failed' in states else 'not-checked' if 'not-checked' in states else 'passed'
    return {'status':status,'features':results,'text_container_execution_match':text['status'],
            'scope':'required_structural_effects_and_hash_bound_final_text_containers; no original_pixel_identity_claim'}


def audit(target: dict, actual: dict, base_image: Path | None = None,
          tolerance: int = 2, template: dict | None = None,
          preview: Path | None = None) -> dict:
    contract = _contract(target)
    if template is None:
        auto_template, auto_preview = _default_template(
            str(target.get("selected_layout") or target.get("layout_id") or "")
        )
        template = auto_template
        if preview is None:
            preview = auto_preview
    if template:
        contract = dict(contract)
        if not contract.get("structure"):
            contract["structure"] = {"units": template.get("panels") or []}
        if not contract.get("panel_geometry"):
            contract["panel_geometry"] = template.get("panels") or []
        if not contract.get("style_contract") and template.get("style_contract"):
            contract["style_contract"] = template["style_contract"]

    target_units = _template_units(target, contract)
    actual_units = _actual_units(actual)
    actual_geometry_source = actual.get("geometry_source") or actual.get("measurement_method") or ("actual_manifest" if actual_units else "missing")
    target_order = [p.get("panel_id") for p in target_units]
    actual_order = [p.get("panel_id") for p in actual_units]
    deviations: list[str] = []
    # A transformed target is still a target, even when named "actual".
    # Bind independent image measurements to the PNG being audited.  Dark
    # scene pixels near expected edges alone cannot identify comic panels.
    measurement = actual.get("measurement_evidence") or {}
    measurement_verified = False
    if base_image and base_image.exists():
        image_sha256 = hashlib.sha256(base_image.read_bytes()).hexdigest()
        measurement_verified = bool(
            measurement.get("image_sha256") == image_sha256
            and measurement.get("method") in {
                "manual_visual_annotation", "image_panel_detection",
                "deterministic_render_with_pixel_verification",
            }
            and measurement.get("geometry_observed_from_image") is True
        )
    if not measurement_verified:
        deviations.append("independent image geometry evidence missing or not bound to this PNG; target/transform metadata is insufficient")
    mapping = contract.get("source_mapping") or contract.get("canvas_transform") or target.get("source_mapping") or actual.get("source_mapping") or actual.get("canvas_transform") or {}
    adapted = contract.get("match_policy") == "adapted" or mapping.get("match_policy") == "adapted"
    approved_adaptation = contract.get("user_approved_adaptation") is True or mapping.get("user_approved_adaptation") is True
    if not actual_units:
        deviations.append("actual_panel_geometry missing; final PNG was not measured")
    if len(actual_units) != len(target_units):
        deviations.append(f"panel_count {len(actual_units)} != target {len(target_units)}")
    reading_order_match = actual_order == target_order and bool(actual_order)
    if not reading_order_match:
        deviations.append(f"reading_order {actual_order} != target {target_order}")

    polygon_geometry_match = True
    geometry_type_match = True
    for index, (want, got) in enumerate(zip(target_units, actual_units), 1):
        for key in ("x", "y", "width", "height"):
            w, g = _as_float(want.get(key)), _as_float(got.get(key))
            if w is None or g is None or abs(g - w) > tolerance:
                deviations.append(f"panel {index} {key} deviates: {got.get(key)} != {want.get(key)}")
        wr = _as_float(want.get("ratio"))
        gr = _as_float(got.get("ratio"))
        if wr is not None and gr is not None and abs(gr - wr) > 0.01:
            deviations.append(f"panel {index} ratio deviates: {got.get('ratio')} != {want.get('ratio')}")
        required_type = str(want.get("geometry_type") or "rect")
        actual_type = str(got.get("geometry_type") or "rect")
        if required_type not in {"rect", "rectangle", "xywh"} and actual_type != required_type:
            geometry_type_match = False
            deviations.append(f"panel {index} geometry_type missing/deviates: {actual_type} != {required_type}")
        want_poly, got_poly = _polygon(want), _polygon(got)
        if want_poly:
            if not got_poly:
                polygon_geometry_match = False
                deviations.append(f"panel {index} polygon geometry missing from actual manifest")
            elif len(got_poly) != len(want_poly) or _polygon_distance(want_poly, got_poly) > tolerance * 2:
                polygon_geometry_match = False
                deviations.append(f"panel {index} polygon geometry deviates from target")

    target_nested = _nested_units(contract)
    actual_nested = actual.get("nested_units") or actual.get("nested_geometry") or []
    nested_match = True
    if target_nested or actual_nested:
        if not isinstance(actual_nested, list) or len(actual_nested) != len(target_nested):
            nested_match = False
            deviations.append(f"nested_unit_count {len(actual_nested) if isinstance(actual_nested, list) else 0} != target {len(target_nested)}")
        else:
            want_ids = [str(row.get("unit_id") or row.get("panel_id")) for row in target_nested]
            got_ids = [str(row.get("unit_id") or row.get("panel_id")) for row in actual_nested if isinstance(row, dict)]
            if want_ids != got_ids:
                nested_match = False
                deviations.append(f"nested_unit_order {got_ids} != target {want_ids}")
            for want, got in zip(target_nested, actual_nested):
                wr, gr = _rect_from(want), _rect_from(got)
                if not wr or not gr or any(abs(wr[key] - gr[key]) > tolerance for key in ("x", "y", "width", "height")):
                    nested_match = False
                    deviations.append(f"nested unit {want.get('unit_id') or want.get('panel_id')} bounds missing/deviate")
                wp, gp = _polygon(want), _polygon(got)
                if wp and (len(wp) != len(gp) or _polygon_distance(wp, gp) > tolerance * 2):
                    nested_match = False
                    deviations.append(f"nested unit {want.get('unit_id') or want.get('panel_id')} polygon missing/deviates")

    image_status: dict = {"status": "not-provided"}
    if base_image:
        try:
            from PIL import Image
            with Image.open(base_image) as im:
                image_status = {"width": im.width, "height": im.height,
                                "format": im.format,
                                "no_text_claim": bool(actual.get("no_text", False))}
                declared=contract.get('canvas') or {}
                expected_size=(int(declared.get('width',1080)),int(declared.get('height',1440)))
                if (im.width, im.height) != expected_size:
                    deviations.append(f"base image dimensions {(im.width, im.height)} != {expected_size}")
                content_records={r.get('panel_id'):r for r in measurement.get('raster_content_verification',[])}
                validated_content={}; rgb=im.convert('RGB')
                for unit in target_units:
                    unframed=unit.get('border_visible',(unit.get('border') or {}).get('visible',True)) is False
                    if measurement.get('method')!='deterministic_render_with_pixel_verification':continue
                    record=content_records.get(unit.get('panel_id')) or {}; samples=record.get('verified_pixel_samples') or []
                    verified=record.get('visible_asset_pixels_verified') is True and len(samples)>=3
                    for sample in samples:
                        try:verified=verified and list(rgb.getpixel(tuple(sample['xy'])))==sample['rgb']
                        except Exception:verified=False
                    validated_content[unit.get('panel_id')]=verified
                    if (unframed or samples) and not verified:
                        deviations.append(f"panel {unit.get('panel_id')} has no verified visible asset pixels or samples mismatch actual PNG")
                        measurement_verified=False
            image_status["edge_evidence"] = _image_edge_support(base_image, target_units)
            if image_status["edge_evidence"].get("status") == "unreadable":
                deviations.append("base image unreadable; image-level structure audit failed")
            else:
                # A claimed panel boundary must be visible in the no-text PNG.
                # This catches a copied manifest whose base image has no frame.
                required_edges = []
                for unit, evidence in zip(target_units, image_status["edge_evidence"].get("units", [])):
                    if unit.get('border_visible',(unit.get('border') or {}).get('visible',True)) is False:
                        continue
                    required_type = str(unit.get("geometry_type") or "rect")
                    threshold = 0.35 if _polygon(unit) or required_type not in {"rect", "rectangle", "xywh"} else 0.25
                    mean_support = float(evidence.get("mean_edge_support", 0.0))
                    required_edges.append({"panel_id": unit.get("panel_id"), "threshold": threshold,
                                           "mean_edge_support": mean_support})
                    # Nested/overlapping units can cover an underlying frame.
                    # Verified visible artwork provides the independent raster
                    # evidence instead of inventing a line through that inset.
                    if mean_support < threshold and not validated_content.get(unit.get('panel_id'),False):
                        deviations.append(
                            f"panel {unit.get('panel_id')} boundary evidence too weak: "
                            f"{mean_support:.3f} < {threshold:.3f}")
                image_status["edge_evidence"]["required_edges"] = required_edges
        except Exception as exc:
            deviations.append(f"base image unreadable: {exc}")
    else:
        deviations.append("base image missing; image-level structure audit not performed")

    segment_checks=[]
    segments=(contract.get('structure') or {}).get('frame_segments') or []
    if segments and base_image and base_image.is_file():
        from PIL import Image
        with Image.open(base_image).convert('RGB') as raster:
            for segment in segments:
                points=segment.get('points') or [];hits=[]
                for a,b in zip(points,points[1:]):
                    ax,ay=a[0]*raster.width,a[1]*raster.height;bx,by=b[0]*raster.width,b[1]*raster.height
                    for i in range(1,100):
                        t=i/100;x=round(ax+(bx-ax)*t);y=round(ay+(by-ay)*t)
                        hits.append(any(max(raster.getpixel((xx,yy)))<60 for xx in range(max(0,x-1),min(raster.width,x+2)) for yy in range(max(0,y-1),min(raster.height,y+2))))
                support=sum(hits)/len(hits) if hits else 0
                segment_checks.append({'segment_id':segment.get('segment_id'),'dark_stroke_support':support,'passed':support>=.7})
                if support<.7:deviations.append(f"partial frame segment {segment.get('segment_id')} absent or incomplete in actual PNG")

    # A style contract describes the target; its presence is not observation
    # of actual rendering.  Style requires a separate visual review.
    execution_match = (not deviations) and polygon_geometry_match and nested_match and geometry_type_match
    execution_style=_execution_style_gate(contract,template,actual,base_image,target_units,image_status,measurement_verified)
    full_execution=("failed" if not execution_match or execution_style['status']=='failed'
                    else "not-checked" if execution_style['status']!='passed' else "passed")
    source_mapping_evidence = _source_mapping_evidence(template, contract, target, actual, actual_units, tolerance)
    if source_mapping_evidence["status"] == "failed":
        deviations.extend(source_mapping_evidence["deviation"])
    if adapted:
        deviations.append("match_policy adapted cannot be reported as an exact original storyboard match")
    structure_match = execution_match and source_mapping_evidence["status"] != "failed" and not adapted
    style_contract = contract.get("style_contract") or {}
    style_review = actual.get("style_verification") or {}
    style_review_valid = bool(measurement_verified and style_review.get("image_sha256") == measurement.get("image_sha256")
                              and style_review.get("method") == "manual_visual_comparison")
    preview_style_match = ("passed" if structure_match and style_review.get("matched") is True else "failed") if style_review_valid else "not-checked"
    preview_structure_match = "passed" if structure_match else "failed"
    if preview is not None and not preview.exists():
        preview_structure_match = "failed"
        deviations.append(f"preview image missing: {preview}")
        structure_match = False

    return {
        "selected_layout": target.get("selected_layout") or target.get("layout_id"),
        "target_panel_count": len(target_units),
        "actual_panel_count": len(actual_units),
        "target_panel_geometry": target_units,
        "actual_panel_geometry": actual_units,
        "actual_geometry_source": actual_geometry_source,
        "image_geometry_measurement_verified": measurement_verified,
        "measurement_evidence": measurement,
        "reading_order_match": reading_order_match,
        "nested_unit_match": nested_match,
        "polygon_geometry_match": polygon_geometry_match,
        "geometry_type_match": geometry_type_match,
        "partial_frame_segment_evidence":segment_checks,
        "execution_geometry_match": "passed" if execution_match else "failed",
        "execution_style_match": execution_style['status'],
        "execution_style_evidence": execution_style,
        "text_container_execution_match": execution_style['text_container_execution_match'],
        "full_template_execution": full_execution,
        "full_template_execution_scope": "declared_target_geometry_required_style_effects_and_final_text_containers; source_exactness_is_separate",
        "adapted_target_match": "passed" if adapted and execution_match else "failed" if adapted else "not_applicable",
        "match_policy": "adapted" if adapted else contract.get("match_policy", "structure_exact"),
        "user_approved_adaptation": approved_adaptation,
        "source_reference_geometry_match": source_mapping_evidence["status"],
        "source_mapping_evidence": source_mapping_evidence,
        "source_pixel_reference_match": "not_checked",
        "preview_structure_match": preview_structure_match,
        "preview_style_match": preview_style_match,
        "storyboard_layout_match": "passed" if structure_match else "failed",
        "layout_deviation": deviations,
        "base_image_modified": False,
        "base_image": image_status,
        "preview_image": str(preview) if preview else None,
        "generator_constraints": contract.get("generator_constraints", {}),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=Path, required=True)
    ap.add_argument("--actual", type=Path, required=True)
    ap.add_argument("--base-image", type=Path)
    ap.add_argument("--template", type=Path,
                    help="Optional executable SB YAML containing observed polygons/nested units")
    ap.add_argument("--preview", type=Path,
                    help="Optional preview image path; missing path is a hard failure")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--accept-adapted-target", action="store_true", help="Accept an explicitly approved target adaptation without reporting original-SB success")
    ap.add_argument("--geometry-only", action="store_true", help="Exit on geometry only for the pre-text stage; never implies complete template execution")
    args = ap.parse_args()
    auto_template, auto_preview = _default_template(
        str(_load(args.target).get("selected_layout") or _load(args.target).get("layout_id") or "")
    ) if not args.template else (None, None)
    loaded_template = _load(args.template) if args.template else auto_template
    selected_preview = args.preview if args.preview else auto_preview
    report = audit(_load(args.target), _load(args.actual), args.base_image,
                   template=loaded_template, preview=selected_preview)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    geometry_accepted = report["storyboard_layout_match"] == "passed" or (args.accept_adapted_target and report["user_approved_adaptation"] and report["adapted_target_match"] == "passed")
    accepted = geometry_accepted and (args.geometry_only or report["full_template_execution"] == "passed")
    raise SystemExit(0 if accepted else 2)


if __name__ == "__main__":
    main()
