"""Reusable post-layout text compositor for douyin-simple-comic-workflow.

This module is intentionally image-based: it accepts a rendered base PNG and a
generic text_blocks plan, then emits a final PNG plus machine-readable reports.
It does not generate or modify the base artwork.  When a block carries a
``bubble_id``, the matching executable SB template is loaded and its observed
visual_style/bounds contract drives the text overlay.  The command-line
interface is the formal Skill entry point; callers can also import
compose_page().
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import yaml
from template_contract import executable_text_containers, canvas_text_binding
from PIL import Image, ImageChops, ImageDraw, ImageFont


STYLE_NAMES = {
    "narration_box",
    "rounded_speech",
    "thought_bubble",
    "phone_dialogue",
    "shout_burst",
    "note_embedded",
    "emphasis_box",
    # Preview-native aliases.  These remain separate from the legacy styles
    # in reports so the style audit can tell whether a template contract was
    # actually consumed.
    "preview_rounded_speech",
    "preview_caption",
    "preview_impact",
    "preview_display",
    "preview_phone",
    "caption_box",
    "impact_burst",
    "display_text",
    "preview_caption_box",
    "preview_impact_burst",
    "preview_phone_message",
    "preview_brush_display_text",
    "preview_vertical_note",
    "preview_caption_note",
    "preview_ellipse_speech", "preview_display_text", "preview_polygon", "preview_surface_text",
}
PREVIEW_STYLE_ALIASES = {
    "preview_rounded_speech": "rounded_speech",
    "preview_caption": "narration_box",
    "caption_box": "preview_caption",
    "preview_impact": "shout_burst",
    "impact_burst": "preview_impact",
    "preview_display": "narration_box",
    "display_text": "preview_display",
    "preview_phone": "phone_dialogue",
    "preview_rounded_speech": "rounded_speech",
    "preview_caption_box": "preview_caption",
    "preview_impact_burst": "preview_impact",
    "preview_phone_message": "preview_phone",
    "preview_brush_display_text": "preview_display",
    "preview_vertical_note": "narration_box",
    "preview_caption_note": "narration_box",
    "preview_ellipse_speech": "rounded_speech",
    "preview_display_text": "narration_box",
    "preview_polygon": "shout_burst",
    "preview_surface_text": "note_embedded",
}
TYPE_STYLES = {
    "narration": "narration_box",
    "caption": "narration_box",
    "dialogue": "rounded_speech",
    "thought": "thought_bubble",
    "phone_dialogue": "phone_dialogue",
    "shout": "shout_burst",
    "note": "note_embedded",
    "emphasis": "emphasis_box",
}
LEGACY_FIELDS = ("narration_text", "dialogue_text", "note_text", "text_placement")
DEFAULT_STYLE = "narration_box"
DEFAULT_FONT = "C:/Windows/Fonts/msyh.ttc"
INK = (31, 27, 23, 255)
V0_FILL = (255, 253, 247, 245)
V0_BORDER = (43, 38, 33, 255)
LAYOUT_CONSTRAINTS_PATH = Path(__file__).resolve().parents[1] / "references" / "comic-layouts" / "bubble-constraints.yaml"
BUBBLE_EXECUTION_PROFILES_PATH = Path(__file__).resolve().parents[1] / "references" / "comic-layouts" / "bubble-execution-profiles.yaml"
EXECUTABLE_TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "references" / "comic-layouts" / "executable-templates"


def load_layout_profile(layout_id: str | None, layout_constraints: str | Path | None = None) -> dict[str, Any]:
    """Load the selected SB's source adapter and executable bubble contract.

    ``bubble-constraints.yaml`` records what the bundled SB description says
    (and may therefore be visual-reference-only).  The companion execution
    profile is a workflow-authored contract consumed by the compositor.  The
    two layers are kept separate so a preview image is never presented as
    executable geometry.
    """
    if not layout_id:
        return {"layout_id": None, "status": "unavailable", "source": None, "profile": {}}
    path = Path(layout_constraints) if layout_constraints else LAYOUT_CONSTRAINTS_PATH
    if not path.exists():
        return {"layout_id": layout_id, "status": "missing", "source": str(path), "profile": {}}
    try:
        data = load_yaml(path) or {}
        profiles = data.get("profiles") or []
        profile = next((item for item in profiles if item.get("layout_id") == layout_id), None)
        if not profile:
            return {"layout_id": layout_id, "status": "not-indexed", "source": str(path), "profile": {}}
        merged = copy.deepcopy(profile)
        execution_path = path.parent / "bubble-execution-profiles.yaml"
        if path.resolve() == LAYOUT_CONSTRAINTS_PATH.resolve() and BUBBLE_EXECUTION_PROFILES_PATH.exists():
            execution_path = BUBBLE_EXECUTION_PROFILES_PATH
        execution_profile: dict[str, Any] = {}
        execution_status = "missing"
        if execution_path.exists():
            execution_data = load_yaml(execution_path) or {}
            execution_profiles = execution_data.get("profiles") or []
            execution_profile = next((item for item in execution_profiles if item.get("layout_id") == layout_id), {})
            execution_status = "loaded" if execution_profile else "not-indexed"
        merged["execution_profile"] = execution_profile
        merged["execution_profile_status"] = execution_status
        merged["bubble_profile_id"] = execution_profile.get("profile_id") or f"{layout_id}-source-adapter"
        merged["visual_reference_only"] = bool(execution_profile.get("visual_reference_only", True))
        merged["execution_profile_source"] = str(execution_path)
        return {"layout_id": layout_id, "status": "loaded", "source": str(path), "profile": merged}
    except Exception as exc:  # preserve rendering compatibility while reporting the problem
        return {"layout_id": layout_id, "status": "invalid", "source": str(path), "profile": {}, "error": str(exc)}


def validate_layout_bubble_map(layout_constraints: str | Path | None = None) -> dict[str, Any]:
    """Validate the bundled 68-SB index, descriptions, and bubble adapter.

    This is an integrity check only.  It does not infer a bubble from a preview
    image and it never rewrites the original SB descriptions.
    """
    map_path = Path(layout_constraints) if layout_constraints else LAYOUT_CONSTRAINTS_PATH
    layout_dir = map_path.parent
    expected = [f"SB-{i:03d}" for i in range(1, 69)]
    errors: list[str] = []
    warnings: list[str] = []
    index_count = None
    index_ids: list[str] = []
    execution_profiles: list[dict[str, Any]] = []
    execution_ids: list[str] = []
    try:
        data = load_yaml(map_path) or {}
        profiles = data.get("profiles") or []
        profile_ids = [item.get("layout_id") for item in profiles]
        if len(profiles) != 68:
            errors.append(f"bubble map profile count is {len(profiles)}, expected 68")
        if sorted(profile_ids) != expected:
            errors.append("bubble map IDs do not equal SB-001..SB-068")
        execution_path = layout_dir / "bubble-execution-profiles.yaml"
        required_execution_fields = {
            "bubble_style",
            "bubble_bounds",
            "allowed_zone",
            "max_width",
            "tail_anchor",
            "speaker_direction",
            "text_type",
            "fallback",
        }
        if not execution_path.exists():
            errors.append("bubble-execution-profiles.yaml missing")
        else:
            execution_data = load_yaml(execution_path) or {}
            execution_profiles = execution_data.get("profiles") or []
            execution_ids = [item.get("layout_id") for item in execution_profiles]
            if len(execution_profiles) != 68 or sorted(execution_ids) != expected:
                errors.append("bubble execution profile IDs do not equal SB-001..SB-068")
            for item in execution_profiles:
                missing = sorted(required_execution_fields - set(item))
                if missing:
                    errors.append(f"{item.get('layout_id')}: execution fields missing: {','.join(missing)}")
                if item.get("visual_reference_only") is not True:
                    errors.append(f"{item.get('layout_id')}: visual_reference_only must be true for preview/source geometry")
                if item.get("executable") is not True:
                    errors.append(f"{item.get('layout_id')}: executable execution profile missing")
        index_path = layout_dir / "layouts.json"
        if not index_path.exists():
            errors.append("layouts.json missing")
        else:
            index_data = json.loads(index_path.read_text(encoding="utf-8"))
            index_count = len(index_data) if isinstance(index_data, list) else len(index_data.get("layouts", []))
            index_entries = index_data if isinstance(index_data, list) else index_data.get("layouts", [])
            index_ids = [item.get("id") for item in index_entries]
            if index_count != 68 or sorted(index_ids) != expected:
                errors.append("layouts.json is not the exact 68-entry SB pool")
        for item in profiles:
            layout_id = item.get("layout_id")
            source_file = item.get("source_file") or f"references/comic-layouts/{layout_id}.md"
            source_name = Path(source_file).name
            if not (layout_dir / source_name).exists():
                errors.append(f"{layout_id}: source description missing ({source_name})")
            if item.get("source_rule_level") not in {"explicit", "none"}:
                errors.append(f"{layout_id}: source_rule_level must be explicit or none")
            if not item.get("placement_constraints"):
                errors.append(f"{layout_id}: placement_constraints missing")
            if item.get("visual_reference_only") is not True:
                errors.append(f"{layout_id}: visual_reference_only must be true for source/preview-only SB evidence")
            if item.get("source_rule_level") == "none":
                warnings.append(f"{layout_id}: no SB-specific bubble evidence; generic rules only")
    except Exception as exc:
        errors.append(f"bubble map validation error: {exc}")
    return {
        "status": "valid" if not errors else "invalid",
        "map_path": str(map_path),
        "index_path": str(layout_dir / "layouts.json"),
        "profile_count": len(profile_ids) if 'profile_ids' in locals() else 0,
        "execution_profile_path": str(layout_dir / "bubble-execution-profiles.yaml"),
        "execution_profile_count": len(execution_profiles),
        "execution_profile_ids": execution_ids,
        "index_count": index_count,
        "index_ids": index_ids,
        "errors": errors,
        "warnings": warnings,
        "source_boundary": "Only explicit wording in SB descriptions is source evidence; adaptation_rule is workflow-added.",
    }


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _canonical_style(style: Any) -> str | None:
    """Return the legacy renderer style for a preview-native style alias."""
    if style in (None, ""):
        return None
    value = str(style)
    seen: set[str] = set()
    while value in PREVIEW_STYLE_ALIASES and value not in seen:
        seen.add(value)
        value = PREVIEW_STYLE_ALIASES[value]
    return value


def _load_template_bubble(layout_id: str | None, bubble_id: Any) -> dict[str, Any]:
    """Load one observed bubble contract from the executable SB template.

    Templates use normalized ``xywh`` coordinates.  The compositor keeps this
    lookup deliberately small and side-effect free; callers decide whether a
    contract should replace an explicitly supplied anchor.
    """
    if not layout_id or bubble_id in (None, ""):
        return {}
    path = EXECUTABLE_TEMPLATES_DIR / f"{layout_id}.yaml"
    if not path.exists():
        return {}
    try:
        data = load_yaml(path) or {}
        for bubble in executable_text_containers(data):
            if str(bubble.get("bubble_id")) == str(bubble_id):
                return copy.deepcopy(bubble)
    except Exception:
        return {}
    return {}


def _normalise_contract_bounds(bounds: Any, width: int, height: int) -> tuple[int, int, int, int] | None:
    """Convert normalized template bounds to final canvas ``xywh`` pixels."""
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        return None
    try:
        values = [float(v) for v in bounds]
    except (TypeError, ValueError):
        return None
    # Executable templates declare normalized_xywh_0_to_1.  Accept pixel-like
    # values as a convenience for hand-authored text plans.
    if max(abs(v) for v in values) <= 1.5:
        x, y, w, h = values
        values = [x * width, y * height, w * width, h * height]
    x, y, w, h = [int(round(v)) for v in values]
    # Preserve out-of-canvas coordinates.  Clamping would conceal an invalid
    # template placement; the safety check must block it explicitly.
    return x, y, w, h


def _source_canvas(transform: dict[str, Any] | None, width: int, height: int) -> tuple[int, int]:
    value = (transform or {}).get("source_canvas") or [width, height]
    if isinstance(value, dict):
        return int(value.get("width", width)), int(value.get("height", height))
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return int(value[0]), int(value[1])
    return width, height


def _transform_contract_bounds(bounds: tuple[int, int, int, int], transform: dict[str, Any] | None) -> tuple[int, int, int, int]:
    if not transform:
        return bounds
    x, y, w, h = bounds
    scale = float(transform.get("scale", 1.0))
    # Crop before resize and after resize are separate operations, even when
    # one happens to be zero.  Both offsets must be applied.
    pre_left = float(transform.get("crop_left_before_resize_px", transform.get("source_crop_left_px", 0.0)))
    pre_top = float(transform.get("crop_top_px", transform.get("source_crop_top_px", 0.0)))
    after_left = float(transform.get("crop_left_px", 0.0))
    after_top = float(transform.get("crop_top_after_resize_px", 0.0))
    return tuple(int(round(v)) for v in ((x - pre_left) * scale - after_left, (y - pre_top) * scale - after_top, w * scale, h * scale))


def _transform_contract_point(point: Any, width: int, height: int, transform: dict[str, Any] | None,
                              coordinate_space: str = "template_normalized") -> list[int] | None:
    """Map a measured tail point using exactly the body's source/crop transform."""
    if not isinstance(point, (list, tuple)) or len(point) != 2:
        return None
    try:
        x, y = map(float, point)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None
    if coordinate_space != "final_canvas_px":
        source_w, source_h = _source_canvas(transform, width, height)
        x, y = x * source_w, y * source_h
        mapped = _transform_contract_bounds((x, y, 0, 0), transform)
        x, y = mapped[:2]
    return [int(round(x)), int(round(y))]


def _resolve_contract_tail(tail: Any, width: int, height: int, transform: dict[str, Any] | None,
                           coordinate_space: str) -> dict[str, Any]:
    resolved = copy.deepcopy(tail) if isinstance(tail, dict) else {}
    space = str(resolved.get("coordinate_space") or coordinate_space)
    anchor = resolved.get("anchor")
    if isinstance(anchor, dict):
        anchor = anchor.get("point") or anchor.get("tip")
    if isinstance(anchor, (list, tuple)):
        resolved["anchor"] = _transform_contract_point(anchor, width, height, transform, space)
    polygon = resolved.get("polygon")
    if isinstance(polygon, list):
        resolved["polygon"] = [_transform_contract_point(p, width, height, transform, space) for p in polygon]
    if resolved.get('mode') == 'observed_dots':
        dots=[]
        for dot in resolved.get('dots') or []:
            if isinstance(dot,dict):dot=dot.get('bounds')
            if not isinstance(dot,(list,tuple)) or len(dot)!=4:
                continue
            rect=tuple(int(round(v)) for v in dot) if space=='final_canvas_px' else _normalise_contract_bounds(dot,*_source_canvas(transform,width,height))
            if rect and space!='final_canvas_px':rect=_transform_contract_bounds(rect,transform)
            if rect:dots.append(list(rect))
        resolved['dots']=dots
        resolved['dot_format']='xywh'
    if resolved.get("mode") in {"observed_polygon",'observed_dots'}:
        resolved["coordinate_space"] = "final_canvas_px"
    return resolved


def _apply_bubble_contract(block: dict[str, Any], layout_id: str | None, width: int, height: int, canvas_transform: dict[str, Any] | None = None) -> dict[str, Any]:
    """Attach an executable/observed bubble contract without touching artwork.

    A block may provide ``bubble_contract`` explicitly.  Otherwise the
    matching bubble_id is loaded from the SB template.  Existing explicit
    anchors remain authoritative for backwards compatibility; a contract is
    used as geometry when ``geometry_source`` is ``bubble_contract`` or when
    the block has no anchor at all.
    """
    resolved = copy.deepcopy(block)
    contract = resolved.get("bubble_contract")
    if not isinstance(contract, dict):
        contract = _load_template_bubble(layout_id, resolved.get("bubble_id"))
    if not contract:
        return resolved
    resolved["bubble_contract"] = contract
    resolved["bubble_contract_source"] = "block" if block.get("bubble_contract") else "executable_template"
    for key in ('source_container_kind','source_text_zone_id','canvas_binding_id','scope','cross_panel_allowed'):
        if key in contract:
            resolved[key]=contract[key]
    shape = contract.get("shape")
    visual_style = contract.get("visual_style") if isinstance(contract.get("visual_style"), dict) else {}
    renderer = visual_style.get("renderer") or shape
    renderer_name = str(renderer) if renderer else ""
    renderer_name={'rounded_speech_oval':'preview_rounded_speech','preview_impact_bubble':'preview_impact_burst','note_embedded':'preview_surface_text'}.get(renderer_name,renderer_name)
    preview_style = renderer_name if renderer_name.startswith("preview_") else PREVIEW_STYLE_ALIASES.get(renderer_name, renderer_name or None)
    resolved["bubble_contract_visual_style"] = copy.deepcopy(visual_style)
    # Template visual_style is authoritative by default.  A legacy caller can
    # retain its old renderer with use_preview_contract: false.
    if preview_style and resolved.get("use_preview_contract", True) is not False:
        resolved["bubble_style"] = preview_style
    elif shape and not resolved.get("bubble_style"):
        resolved["bubble_style"] = PREVIEW_STYLE_ALIASES.get(str(shape), str(shape))
    # Preview contracts are the authoritative placement source whenever they
    # are enabled.  Set use_preview_contract:false to retain a legacy anchor.
    use_contract_geometry = resolved.get("use_preview_contract", True) is not False
    coordinate_space = str(resolved.get("coordinate_space") or contract.get("coordinate_space") or "template_normalized")
    explicit_geometry = resolved.get("bubble_geometry") if isinstance(resolved.get("bubble_geometry"), dict) else {}
    final_bounds = resolved.get("final_canvas_px") or explicit_geometry.get("final_canvas_px")
    if isinstance(final_bounds, dict):
        final_bounds = final_bounds.get("bounds") or final_bounds.get("rect")
    if final_bounds is not None or coordinate_space == "final_canvas_px":
        explicit_anchor = resolved.get("anchor") if isinstance(resolved.get("anchor"), dict) else {}
        explicit_value = final_bounds or explicit_geometry.get("bounds") or explicit_anchor.get("rect") or contract.get("bounds")
        # An explicit final-canvas value is always pixels, including a 1x1
        # rectangle; never run normalized-coordinate heuristics on it.
        pixel_bounds = tuple(int(round(float(v))) for v in explicit_value) if isinstance(explicit_value, (list, tuple)) and len(explicit_value) == 4 else None
        resolved["geometry_coordinate_space"] = "final_canvas_px"
    else:
        source_w, source_h = _source_canvas(canvas_transform, width, height)
        pixel_bounds = _normalise_contract_bounds(contract.get("bounds"), source_w, source_h)
        if pixel_bounds and canvas_transform:
            pixel_bounds = _transform_contract_bounds(pixel_bounds, canvas_transform)
        resolved["geometry_coordinate_space"] = "template_normalized_to_source_to_final"
    resolved["canvas_transform_applied"] = copy.deepcopy(canvas_transform) if coordinate_space != "final_canvas_px" and final_bounds is None else None
    if pixel_bounds and use_contract_geometry:
        resolved["anchor"] = {
            "kind": "bubble_contract",
            "panel_id": contract.get("panel_id") or resolved.get("panel_id"),
            "rect": list(pixel_bounds),
            "rect_format": "xywh",
        }
        if renderer_name=='preview_surface_text':
            resolved['anchor'].update(kind='carrier',carrier_id=(resolved.get('carrier') or {}).get('asset_id'))
        resolved["coordinate_source"] = "bubble_contract"
    if pixel_bounds:
        px, py, pw, ph = pixel_bounds
        # Keep the historical contract field in xyxy form because render
        # reports expose bubble_bounds as xyxy.  Preserve xywh explicitly for
        # consumers that need the source contract dimensions.
        resolved["bubble_contract_bounds"] = [px, py, px + pw, py + ph]
        resolved["bubble_contract_bounds_format"] = "xyxy"
        resolved["bubble_contract_bounds_xywh"] = list(pixel_bounds)
    else:
        resolved["bubble_contract_bounds"] = contract.get("bounds")
        resolved["bubble_contract_bounds_format"] = "normalized_xywh"
    resolved["bubble_contract_shape"] = shape
    if isinstance(contract.get("polygon"), list):
        polygon_space = str(contract.get("polygon_coordinate_space") or coordinate_space)
        resolved["bubble_contract_polygon"] = [_transform_contract_point(p, width, height, canvas_transform, polygon_space) for p in contract["polygon"]]
    if isinstance(contract.get("typography_regions"), list):
        mapped_regions = []
        for region in contract["typography_regions"]:
            if not isinstance(region, dict):
                continue
            region_space = str(region.get("coordinate_space") or coordinate_space)
            region_bounds = region.get("bounds")
            if region_space == "final_canvas_px":
                mapped_bounds = tuple(int(round(v)) for v in region_bounds) if isinstance(region_bounds, list) and len(region_bounds) == 4 else None
            else:
                sw, sh = _source_canvas(canvas_transform, width, height)
                mapped_bounds = _normalise_contract_bounds(region_bounds, sw, sh)
                if mapped_bounds:
                    mapped_bounds = _transform_contract_bounds(mapped_bounds, canvas_transform)
            if mapped_bounds:
                mapped_regions.append({"bounds": list(mapped_bounds), "coordinate_space": "final_canvas_px", "evidence": region.get("evidence")})
        resolved["bubble_contract_typography_regions"] = mapped_regions
    resolved["bubble_contract_renderer"] = renderer
    resolved["bubble_contract_tail"] = _resolve_contract_tail(contract.get("tail"), width, height, canvas_transform,
                                                             "final_canvas_px" if final_bounds is not None else coordinate_space)
    resolved["bubble_contract_position"] = contract.get("position")
    if resolved.get("use_preview_contract", True) is not False:
        resolved["avoid_regions"] = list(dict.fromkeys(list(resolved.get("avoid_regions") or []) + list(contract.get("avoid") or [])))
        resolved["preview_contract_strict"] = True
    return resolved


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _rgba_hex(value: str | None, default: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if not value:
        return default
    raw = value.lstrip("#")
    if len(raw) != 6:
        return default
    return tuple(int(raw[i : i + 2], 16) for i in (0, 2, 4)) + (255,)


def _font(config: dict[str, Any], size: int | None = None, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = config.get("font_file") or DEFAULT_FONT
    if bold and config.get("font_bold_file"):
        path = config["font_bold_file"]
    return ImageFont.truetype(path, size or int(config.get("font_size", 42)))


def _rect(value: Any, rect_format: str = "xywh") -> tuple[int, int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    x, y, a, b = [int(round(float(v))) for v in value]
    if rect_format.lower() == "xyxy":
        return x, y, a, b
    return x, y, x + max(0, a), y + max(0, b)


def _block_rect(block: dict[str, Any]) -> tuple[int, int, int, int] | None:
    anchor = block.get("anchor") or {}
    fmt = anchor.get("rect_format") or block.get("rect_format") or "xywh"
    return _rect(anchor.get("rect"), fmt)


def _block_id(block: dict[str, Any]) -> Any:
    """Accept the canonical ``id`` and the existing page-plan ``block_id``."""
    return block.get("id") if block.get("id") is not None else block.get("block_id")


def _area(rect: tuple[int, int, int, int]) -> int:
    return max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])


def _intersects(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def _clip(rect: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    return max(0, rect[0]), max(0, rect[1]), min(width, rect[2]), min(height, rect[3])


def _required_rect(value: Any, rect_format: str | None = None) -> tuple[int, int, int, int] | None:
    if not rect_format:
        return None
    rect = _rect(value, rect_format)
    if rect is None or rect[2] <= rect[0] or rect[3] <= rect[1]:
        return None
    return rect


def _bbox(rects: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int] | None:
    if not rects:
        return None
    return min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)


def _bbox_points(points: list[tuple[int, int]]) -> tuple[int, int, int, int] | None:
    if not points:
        return None
    return min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)


def _outside_body_rects(rect: tuple[int, int, int, int], body: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
    """Return visible rectangles of a connector drawn behind a bubble body.

    Speech tails are painted first and the body is painted over their attached
    portion.  Collision checks must use the visible part, otherwise the hidden
    attachment would be reported as covering the glyphs inside the body.
    """
    pieces: list[tuple[int, int, int, int]] = []
    if rect[1] < body[1]:
        pieces.append((rect[0], rect[1], rect[2], min(rect[3], body[1])))
    if rect[3] > body[3]:
        pieces.append((rect[0], max(rect[1], body[3]), rect[2], rect[3]))
    if rect[0] < body[0]:
        pieces.append((rect[0], rect[1], min(rect[2], body[0]), rect[3]))
    if rect[2] > body[2]:
        pieces.append((max(rect[0], body[2]), rect[1], rect[2], rect[3]))
    return [p for p in pieces if p[2] > p[0] and p[3] > p[1]]


def _contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def _speaker_rect(block: dict[str, Any]) -> tuple[int, int, int, int] | None:
    return _required_rect(block.get("speaker_region"), block.get("speaker_region_format"))


def _observed_tail_check(block: dict[str, Any], body: tuple[int, int, int, int]) -> dict[str, Any]:
    """A measured tail is executable only when its new-scene target is confirmed."""
    tail = block.get("bubble_contract_tail") or {}
    visual = block.get("bubble_contract_visual_style") or {}
    mode = tail.get("mode")
    required = bool(tail.get("required")) or mode not in (None, "", "none", "disabled") or visual.get("tail_shape") not in (None, "", "none", "disabled", "unknown")
    result = {"required": required, "mode": mode or "none", "status": "none", "anchor": None}
    if not required:
        return result
    if mode == 'observed_dots':
        dots=tail.get('dots') or []
        if not dots or any(not isinstance(q,(list,tuple)) or len(q)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in q) or min(q[2:])<=0 for q in dots):
            return dict(result,status='blocked',reason='observed_thought_dots_invalid')
        identity=block.get('thought_owner') or block.get('speaker')
        region=_required_rect(block.get('thought_owner_region') or block.get('speaker_region'),block.get('thought_owner_region_format') or block.get('speaker_region_format'))
        status=block.get('thought_owner_status') or block.get('speaker_status')
        panel=block.get('thought_owner_panel_id') or block.get('speaker_panel_id')
        if block.get('type')!='thought' or block.get('source_field')=='narration_text':
            return dict(result,status='blocked',reason='thought_dots_source_semantics_incompatible')
        if not identity or identity in {'unknown','narrator','remote'} or status not in {'confirmed','visible'} or not region or panel!=block.get('panel_id'):
            return dict(result,status='blocked',reason='thought_owner_region_unconfirmed')
        # A dot chain deliberately stops short of its owner. Do not invent an
        # anchor where the original preview's anchor is unknown.
        last=dots[-1];cx,cy=last[0]+last[2]/2,last[1]+last[3]/2
        distance=math.hypot(max(region[0]-cx,0,cx-region[2]),max(region[1]-cy,0,cy-region[3]))
        if distance>max(32,min(100,max(last[2:])*8)):
            return dict(result,status='blocked',reason='thought_dot_chain_not_near_confirmed_owner')
        rects=[_rect(q,'xywh') for q in dots]
        return dict(result,status='ready',dots=copy.deepcopy(dots),dot_format='xywh',bounds_xyxy=list(_bbox(rects)),coordinate_space='final_canvas_px',binding_kind='thought_owner',binding_id=identity,binding_panel_id=panel,target_region_xyxy=list(region))
    if tail.get("multiple_visible_points") is True and block.get("actual_regions_verified") is True and block.get("synthetic_input") is not True:
        bindings = tail.get("visible_point_bindings") or []
        count = tail.get("visible_point_count")
        expected_id = block.get("prop_id") if tail.get("anchor_kind") == "prop" else block.get("speaker")
        confirmed = (tail.get("all_visible_points_binding_confirmed") is True and isinstance(bindings, list)
                     and isinstance(count, int) and count >= 2 and len(bindings) == count)
        anchors = []
        for binding in bindings if isinstance(bindings, list) else []:
            point = binding.get("anchor") if isinstance(binding, dict) else None
            region = _required_rect(binding.get("region"), binding.get("region_format")) if isinstance(binding, dict) else None
            if (not isinstance(point, (list, tuple)) or len(point) != 2
                    or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in point) or not region
                    or binding.get("status") != "confirmed" or binding.get("panel_id") != block.get("panel_id")
                    or binding.get("binding_id") != expected_id):
                confirmed = False
                continue
            tolerance = max(3, min(12, round(min(region[2] - region[0], region[3] - region[1]) * .03)))
            near = region[0]-tolerance <= point[0] <= region[2]+tolerance and region[1]-tolerance <= point[1] <= region[3]+tolerance
            edge = min(abs(point[0]-region[0]), abs(point[0]-region[2]), abs(point[1]-region[1]), abs(point[1]-region[3]))
            if not near or edge > tolerance:
                confirmed = False
            anchors.append(tuple(point))
        if len(set(anchors)) != count:
            confirmed = False
        if not confirmed:
            return dict(result, status="blocked", reason="actual_auxiliary_tail_bindings_unconfirmed")
        result["auxiliary_tail_bindings_verified"] = True
    if mode != "observed_polygon":
        return dict(result, status="blocked", reason="required_tail_geometry_unknown_or_unsupported")
    polygon, anchor = tail.get("polygon"), tail.get("anchor")
    if not isinstance(polygon, list) or len(polygon) < 3 or not all(isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, (float, int)) and math.isfinite(v) for v in p) for p in polygon):
        return dict(result, status="blocked", reason="observed_tail_polygon_invalid")
    if not isinstance(anchor, (list, tuple)) or len(anchor) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in anchor):
        return dict(result, status="blocked", reason="observed_tail_anchor_invalid")
    if min(math.dist(anchor, p) for p in polygon) > 2.5:
        return dict(result, status="blocked", reason="tail_anchor_not_polygon_tip")
    signed_area = abs(sum(polygon[i][0] * polygon[(i + 1) % len(polygon)][1] - polygon[(i + 1) % len(polygon)][0] * polygon[i][1] for i in range(len(polygon)))) / 2
    if signed_area < 2 or not any(body[0] <= p[0] <= body[2] and body[1] <= p[1] <= body[3] for p in polygon):
        return dict(result, status="blocked", reason="tail_polygon_degenerate_or_detached")
    if tail.get("anchor_kind") == "chat_ui_nib":
        screen = _required_rect(block.get("phone_screen_region"), block.get("phone_screen_region_format"))
        channel = block.get("channel")
        if (block.get("type") != "phone_dialogue" or channel not in {"chat", "messaging", "phone", "phone_channel", "telephone"}
                or not screen or block.get("phone_screen_status") != "confirmed"
                or block.get("phone_screen_panel_id") != block.get("panel_id")):
            return dict(result, status="blocked", reason="chat_ui_nib_screen_binding_unconfirmed")
        tail_bbox = _bbox_points(polygon)
        distance = math.hypot(max(body[0] - anchor[0], 0, anchor[0] - body[2]), max(body[1] - anchor[1], 0, anchor[1] - body[3]))
        if not _contains(screen, tail_bbox) or distance > min(24, (body[3] - body[1]) * .35):
            return dict(result, status="blocked", reason="chat_ui_nib_outside_screen_or_too_long")
        return dict(result, status="ready", anchor=list(anchor), polygon=copy.deepcopy(polygon), coordinate_space="final_canvas_px",
                    bounds_xyxy=list(tail_bbox), binding_kind="chat_ui", binding_id=str(channel), binding_panel_id=block.get("panel_id"))
    prop = tail.get("anchor_kind") == "prop" or tail.get("prop_binding_required") is True
    if prop:
        identity = block.get("prop_id")
        confirmed = block.get("prop_status") == "confirmed"
        binding = block.get("prop_panel_id")
        target = _required_rect(block.get("prop_region"), block.get("prop_region_format"))
        allowed_semantics = block.get("type") in {"note", "caption", "narration"}
        target_kind = "prop"
    else:
        identity = block.get("speaker")
        confirmed = block.get("speaker_status") in {"confirmed", "visible"} and block.get("speaker_region_visibility") in {"confirmed", "visible"}
        binding = block.get("speaker_panel_id") or block.get("speaker_region_panel_id")
        target = _speaker_rect(block)
        source_type = block.get("source_type") or block.get("type")
        allowed_semantics = block.get("type") in {"dialogue", "shout", "emphasis"} and source_type in {"dialogue", "shout", "emphasis"} and block.get("source_field") != "narration_text"
        target_kind = "speaker"
    if not allowed_semantics:
        return dict(result, status="blocked", reason="tail_source_semantics_incompatible")
    if not identity or identity in {"unknown", "narrator", "remote"} or not confirmed or not target:
        return dict(result, status="blocked", reason=f"tail_{target_kind}_region_unconfirmed")
    if not binding or binding != block.get("panel_id"):
        return dict(result, status="blocked", reason=f"tail_{target_kind}_panel_binding_mismatch")
    tolerance = max(3, min(12, round(min(target[2] - target[0], target[3] - target[1]) * .03)))
    ax, ay = anchor
    near_target = target[0] - tolerance <= ax <= target[2] + tolerance and target[1] - tolerance <= ay <= target[3] + tolerance
    edge_distance = min(abs(ax - target[0]), abs(ax - target[2]), abs(ay - target[1]), abs(ay - target[3]))
    if not near_target or edge_distance > tolerance:
        return dict(result, status="blocked", reason=f"tail_anchor_not_at_{target_kind}_edge")
    return dict(result, status="ready", anchor=list(anchor), polygon=copy.deepcopy(polygon),
                coordinate_space="final_canvas_px", bounds_xyxy=list(_bbox_points(polygon)),
                binding_kind=target_kind, binding_id=identity, binding_panel_id=binding,
                target_region_xyxy=list(target), tip_contact_tolerance_px=tolerance)


def _brush_font_evidence(config: dict[str, Any]) -> dict[str, Any]:
    """Validate a reviewed brush font; font loading alone proves no style match."""
    path = Path(str(config.get("brush_font_file") or ""))
    verification = copy.deepcopy(config.get("brush_font_verification") or {})
    result = {"status": "blocked", "font_path": str(path), "verification": verification,
              "preview_font_pixel_match": "unverified"}
    if not path.is_file():
        return dict(result, reason="brush_font_unavailable")
    try:
        font = ImageFont.truetype(str(path), 24)
        family, style = font.getname()
    except (OSError, ValueError) as exc:
        return dict(result, reason="brush_font_load_failed", detail=str(exc))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result.update(font_path=str(path.resolve()), font_file_sha256=digest, font_family=family, font_style_name=style)
    ordinary = {"kaiti", "kai ti", "simkai", "楷体", "simhei", "黑体", "microsoft yahei", "microsoft yahei ui", "simsun", "宋体", "arial", "noto sans cjk sc", "noto serif cjk sc"}
    if family.casefold() in ordinary:
        return dict(result, reason="ordinary_font_cannot_claim_brush_calligraphy")
    if (verification.get("status") != "verified" or verification.get("family_class") != "brush_calligraphy"
            or verification.get("sha256") != digest or not verification.get("evidence")):
        return dict(result, reason="brush_font_style_verification_missing_or_mismatched")
    if verification.get("expected_family") and verification["expected_family"] != family:
        return dict(result, reason="brush_font_family_mismatch")
    return dict(result, status="verified")


def _text_type(block: dict[str, Any]) -> tuple[str | None, str]:
    value = block.get("type")
    if value in TYPE_STYLES:
        return value, "explicit block type"
    if value not in (None, ""):
        return None, "explicit unsupported type"
    field = block.get("source_field")
    if field == "narration_text":
        return "narration", "source_field narration_text"
    if field == "note_text":
        return "note", "source_field note_text"
    if field == "dialogue_text":
        return "dialogue", "source_field dialogue_text; explicit type absent"
    return None, "missing or unsupported type"


def _carrier_rect(block: dict[str, Any]) -> tuple[int, int, int, int] | None:
    carrier = block.get("carrier") or {}
    writable = carrier.get("writable_rect") or carrier.get("target_region")
    fmt = carrier.get("writable_rect_format") or carrier.get("target_region_format") or "xywh"
    return _rect(writable, fmt) if writable else None


def _carrier_polygon_rect(block: dict[str, Any]) -> tuple[int, int, int, int] | None:
    polygon = (block.get("carrier") or {}).get("polygon")
    points = [(int(p[0]), int(p[1])) for p in polygon or [] if isinstance(p, (list, tuple)) and len(p) >= 2]
    return _bbox_points(points)


def _surface_text_check(block: dict[str, Any], rect: tuple[int,int,int,int] | None) -> dict[str,Any]:
    """Only write onto a confirmed existing carrier, never create its surface."""
    carrier=block.get('carrier') or {};anchor=block.get('anchor') or {}
    polygon=carrier.get('polygon');writable=_carrier_rect(block)
    if not rect or not writable or not _contains(writable,rect) or not isinstance(polygon,list) or len(polygon)<3:
        return {'status':'blocked','reason':'surface_carrier_polygon_or_safe_rect_missing'}
    if (anchor.get('kind')!='carrier' or not carrier.get('asset_id') or anchor.get('carrier_id')!=carrier.get('asset_id')
            or carrier.get('panel_id')!=block.get('panel_id') or not carrier.get('kind')
            or carrier.get('status')!='confirmed'):
        return {'status':'blocked','reason':'surface_carrier_identity_or_panel_unconfirmed'}
    # Bounding boxes cannot establish writable containment on a rotated note.
    if not all(isinstance(q,(list,tuple)) and len(q)==2 and all(isinstance(v,(int,float)) and math.isfinite(v) for v in q) for q in polygon):
        return {'status':'blocked','reason':'surface_carrier_polygon_invalid'}
    rect=tuple(int(round(v)) for v in rect)
    mask=Image.new('L',(rect[2]-rect[0]+1,rect[3]-rect[1]+1),0)
    ImageDraw.Draw(mask).polygon([(q[0]-rect[0],q[1]-rect[1]) for q in polygon],fill=255)
    if mask.getextrema()[0]!=255:
        return {'status':'blocked','reason':'surface_writable_rect_outside_carrier_polygon'}
    synthetic=block.get('synthetic_input') is True
    if not synthetic and (block.get('actual_regions_verified') is not True or carrier.get('actual_image_checked') is not True
            or not carrier.get('image_sha256') or carrier.get('image_sha256')!=block.get('_base_image_sha256')):
        return {'status':'blocked','reason':'surface_carrier_actual_image_evidence_missing_or_mismatched'}
    return {'status':'ready','carrier_id':carrier['asset_id'],'synthetic':synthetic,'background_created':False,
            'carrier_polygon_verified':True,'safe_rect_xyxy':list(writable),'image_sha256':carrier.get('image_sha256')}


def _global_protection_check(block: dict[str,Any]) -> dict[str,Any]:
    contract=block.get('bubble_contract') or {}
    needed=canvas_text_binding(contract) or contract.get('cross_panel_allowed') is True
    if not needed:return {'status':'not_applicable'}
    evidence=block.get('protected_regions_evidence') or {}
    expected=block.get('_all_panel_ids') or []
    covered=evidence.get('protected_panel_ids') or []
    if (block.get('avoid_region_scope')!='canvas' or evidence.get('scope')!='canvas' or not expected
            or not set(expected).issubset(set(covered))):
        return {'status':'blocked','reason':'canvas_or_overflow_requires_global_protected_regions'}
    if block.get('synthetic_input') is not True and (block.get('actual_regions_verified') is not True
            or evidence.get('actual_image_checked') is not True or not evidence.get('image_sha256')
            or evidence.get('image_sha256')!=block.get('_base_image_sha256')):
        return {'status':'blocked','reason':'global_protected_regions_actual_image_evidence_missing_or_mismatched'}
    return {'status':'ready','scope':'canvas','protected_panel_ids':covered,'synthetic':block.get('synthetic_input') is True}


def _resolved_avoid_rects(block: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str], str]:
    """Resolve semantic avoid labels to concrete coordinate regions.

    Existing page plans use labels such as ``face`` while their coordinates are
    keyed by concrete names (``face_c01_upper``).  Keep that contract while
    requiring every requested label to resolve to at least one valid rectangle.
    """
    source = block.get("avoid_region_rects") or {}
    if not isinstance(source, dict):
        return {}, [], list(block.get("avoid_regions") or []), "invalid"
    resolved: dict[str, Any] = {}
    missing: list[str] = []
    malformed: list[str] = []
    labels = list(block.get("avoid_regions") or [])
    confirmed_absent = set(block.get("confirmed_absent_regions") or [])
    for label in labels:
        if label in confirmed_absent:
            continue
        candidates = []
        for key, value in source.items():
            key_text = str(key).casefold()
            label_text = str(label).casefold()
            matches = key_text == label_text or key_text.startswith(label_text + "_") or ("_" + label_text + "_") in key_text or key_text.endswith("_" + label_text)
            if matches:
                if _rect(value, "xywh") is None:
                    malformed.append(str(key))
                else:
                    candidates.append(str(key))
        if not candidates:
            if label in source and source[label]:
                malformed.append(str(label))
            else:
                missing.append(str(label))
        for key in candidates:
            resolved[key] = source[key]
    # Concrete keys not named by a semantic label remain useful protected
    # regions only when explicitly listed in avoid_regions.
    return resolved, missing, malformed, "semantic-prefix" if labels else "none"


def _tail_geometry(block: dict[str, Any], rect: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    if not block.get("tail_enabled"):
        return None
    speaker = _speaker_rect(block)
    if not speaker:
        return None
    x0, y0, x1, y1 = rect
    sx = (speaker[0] + speaker[2]) // 2
    sy = speaker[1]
    base_x = x0 + max(20, min(x1 - x0 - 60, (x1 - x0) // 4))
    return _bbox_points([(base_x, y1 - 2), (base_x + 36, y1 - 2), (sx, sy)])


def _thought_geometry(block: dict[str, Any], rect: tuple[int, int, int, int]) -> tuple[int, int, int, int] | None:
    if not block.get("tail_enabled"):
        return None
    speaker = _speaker_rect(block)
    if not speaker:
        return None
    x0, y0, x1, y1 = rect
    sx = (speaker[0] + speaker[2]) // 2
    sy = max(y1 + 14, speaker[1] - 14)
    start_x = x0 + (x1 - x0) // 3
    start_y = y1 - 2
    dots = []
    for index, radius in enumerate((11, 7, 4)):
        t = (index + 1) / 4
        cx = int(start_x + (sx - start_x) * t)
        cy = int(start_y + (sy - start_y) * t)
        dots.append((cx - radius, cy - radius, cx + radius, cy + radius))
    return _bbox(dots)


def _render_geometry(block: dict[str, Any], rect: tuple[int, int, int, int], text_bounds: tuple[int, int, int, int], used_style: str) -> list[dict[str, Any]]:
    # Geometry must describe what was actually drawn, including compact body
    # rectangles and any connector/tail.  The original anchor remains only the
    # placement contract; it is not a collision shape.
    shape_rect = block.get("_render_body_rect") or rect
    geometry: list[dict[str, Any]] = [{"part": "text", "rect": list(text_bounds)}]
    if _canonical_style(used_style) == "note_embedded":
        carrier_rect = _carrier_polygon_rect(block) or _carrier_rect(block) or rect
        geometry.append({"part": "carrier", "rect": list(carrier_rect)})
    else:
        body_geometry = {"part": "shape", "rect": list(shape_rect)}
        if block.get("_render_body_polygon"):
            body_geometry["polygon"] = copy.deepcopy(block["_render_body_polygon"])
        geometry.append(body_geometry)
    observed_tail = block.get("_render_observed_tail") or {}
    if observed_tail.get("status") == "drawn" and observed_tail.get('mode')=='observed_dots':
        for dot in observed_tail['dots']:
            geometry.append({'part':'thought_connector','rect':list(_rect(dot,'xywh')),'ellipse':list(_rect(dot,'xywh')),'draw_order':'behind_body','binding_kind':'thought_owner'})
    elif observed_tail.get("status") == "drawn":
        geometry.append({"part": "tail", "rect": observed_tail["bounds_xyxy"],
                         "polygon": copy.deepcopy(observed_tail["polygon"]), "hidden_body_rect": list(shape_rect),
                         "anchor": observed_tail["anchor"], "binding_kind": observed_tail.get("binding_kind"),
                         "target_region_xyxy": observed_tail.get("target_region_xyxy"),
                         "tip_contact_tolerance_px": observed_tail.get("tip_contact_tolerance_px", 0), "draw_order": "behind_body"})
    elif _canonical_style(used_style) == "rounded_speech":
        tail = _tail_geometry(block, shape_rect)
        visible_tails = _outside_body_rects(tail, shape_rect) if tail else []
        for visible_tail in visible_tails:
            geometry.append({"part": "tail", "rect": list(visible_tail), "draw_order": "behind_body"})
    if _canonical_style(used_style) == "thought_bubble" and not observed_tail.get('dots'):
        dots = _thought_geometry(block, shape_rect)
        if dots:
            geometry.append({"part": "thought_connector", "rect": list(dots)})
    return geometry


def _tail_visible_mask(part: dict[str, Any], size: tuple[int, int]) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    if part.get('dots'):
        for dot in part['dots']:draw.ellipse(_rect(dot,'xywh'),fill=255)
    elif part.get('polygon'):
        draw.polygon([tuple(p) for p in part['polygon']], fill=255)
    body = part.get("hidden_body_rect")
    if body:
        draw.rectangle(tuple(body), fill=0)
    return mask


def _part_intersects_rect(part: dict[str, Any], rect: tuple[int, int, int, int], *, permit_tip_contact: bool = False) -> bool:
    bbox = _rect(part.get("rect"), "xyxy")
    if not bbox or not _intersects(bbox, rect):
        return False
    if not part.get("polygon"):
        return True
    left, top = max(0, max(bbox[0], rect[0])), max(0, max(bbox[1], rect[1]))
    right, bottom = min(bbox[2], rect[2]), min(bbox[3], rect[3])
    if right <= left or bottom <= top:
        return False
    mask = Image.new("L", (right - left + 1, bottom - top + 1), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([(p[0] - left, p[1] - top) for p in part["polygon"]], fill=255)
    body = part.get("hidden_body_rect")
    if body:
        draw.rectangle((body[0] - left, body[1] - top, body[2] - left, body[3] - top), fill=0)
    if permit_tip_contact and part.get("anchor"):
        ax, ay = part["anchor"]
        radius = min(12, max(0, int(part.get("tip_contact_tolerance_px", 0))))
        draw.ellipse((ax - left - radius, ay - top - radius, ax - left + radius, ay - top + radius), fill=0)
    return bool(mask.getbbox())


def _text_geometry_safety(block: dict[str, Any], geometry: list[dict[str, Any]], used_style: str) -> dict[str, Any]:
    """Check text containment and record draw order for tails/connectors.

    Shapes and tails are painted before glyphs in the speech branches. This
    keeps a border or connector from covering a glyph even when their
    conservative bounding boxes touch. Other blocks are still checked by the
    normal inter-block collision pass.
    """
    text_parts = [_rect(item.get("rect"), "xyxy") for item in geometry if item.get("part") == "text"]
    text_parts = [item for item in text_parts if item]
    body = block.get("_render_body_rect")
    text_inside_body = bool(text_parts and body and all(_contains(body, item) for item in text_parts))
    polygon = block.get("_render_body_polygon")
    text_inside_polygon = True
    if polygon:
        for text_rect in text_parts:
            if text_rect[2] <= text_rect[0] or text_rect[3] <= text_rect[1]:
                text_inside_polygon = False
                continue
            mask = Image.new("L", (text_rect[2] - text_rect[0], text_rect[3] - text_rect[1]), 0)
            ImageDraw.Draw(mask).polygon([(p[0] - text_rect[0], p[1] - text_rect[1]) for p in polygon], fill=255)
            text_inside_polygon = text_inside_polygon and mask.getextrema()[0] == 255
    connector_parts = [item for item in geometry if item.get("part") in {"tail", "thought_connector"}]
    connector_text_overlaps = []
    for connector in connector_parts:
        connector_rect = _rect(connector.get("rect"), "xyxy")
        if connector_rect and any(_part_intersects_rect(connector, text_rect) for text_rect in text_parts):
            connector_text_overlaps.append(connector.get("part"))
    return {
        "text_inside_body": text_inside_body,
        "text_inside_observed_polygon": text_inside_polygon,
        "connector_parts_present": bool(connector_parts),
        "connector_drawn_before_text": True,
        "border_drawn_before_text": True,
        "glyph_occlusion_by_own_shape": bool(connector_text_overlaps),
        "connector_text_overlaps": connector_text_overlaps,
        "tail_hidden_attachment_clipped": _canonical_style(used_style) == "rounded_speech",
        "safe": text_inside_body and text_inside_polygon and not connector_text_overlaps,
        "style": used_style,
    }


CLOSING_PUNCTUATION = frozenset("，。！？；：、）》】〕〉」』’”％‰…,.!?;:)]}%")


def _wrap_text_lines(text: str, width: float, measure: Any) -> list[str]:
    """Wrap without placing closing CJK punctuation at the start of a line.

    When a closing mark does not fit, move its preceding character (and any
    trailing closing marks) with it. An indivisible group wider than the
    available width remains oversized so the capacity gate rejects it.
    """
    lines: list[str] = []
    for paragraph in str(text).split("\n"):
        current = ""
        for char in paragraph:
            candidate = current + char
            if measure(candidate) <= max(1, width):
                current = candidate
            elif current and char in CLOSING_PUNCTUATION:
                cut = len(current) - 1
                while cut > 0 and current[cut] in CLOSING_PUNCTUATION:
                    cut -= 1
                if current[:cut]:
                    lines.append(current[:cut])
                current = current[cut:] + char
            else:
                if current:
                    lines.append(current)
                current = char
        lines.append(current)
    return lines or [""]


def _has_closing_line_start(lines: list[str]) -> bool:
    return any(line and line[0] in CLOSING_PUNCTUATION for line in lines)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    return _wrap_text_lines(text, width, lambda value: draw.textbbox((0, 0), value, font=font)[2])


class _TextFitError(ValueError):
    """A measured text block cannot be drawn without breaking its contract."""

    def __init__(self, fit: dict[str, Any]):
        self.fit = fit
        super().__init__(str(fit.get("failure_reason") or "text_does_not_fit_at_declared_font_size"))


def _measure_text_layout(draw: ImageDraw.ImageDraw, text: str, rect: tuple[int, int, int, int], config: dict[str, Any], *, size: int, bold: bool = False, vertical: bool = False) -> dict[str, Any]:
    """One padding/wrapping calculation shared by preflight and raster output.

    Explicit block sizes are fixed unless ``font_size_policy: fit`` is
    deliberately selected. Legacy config-only callers retain reported fitting.
    No search step may undershoot the minimum readable size.
    """
    padding = max(0, int(config.get("text_box_style", {}).get("padding", 22)))
    requested = int(size)
    minimum = int(config.get("minimum_readable_font_size", 24))
    policy = str(config.get("font_size_policy") or ("fixed" if config.get("_explicit_font_size") else "fit"))
    if policy not in {"fixed", "fit"}:
        return {"font_size": requested, "requested_font_size": requested, "fit_ok": False,
                "failure_reason": "invalid_font_size_policy", "font_size_policy": policy}
    if requested < minimum or minimum <= 0:
        return {"font_size": requested, "requested_font_size": requested, "fit_ok": False,
                "failure_reason": "font_below_readable_minimum", "minimum_readable_font_size": minimum}
    available_w, available_h = rect[2] - rect[0] - padding * 2, rect[3] - rect[1] - padding * 2
    font_size = requested
    while True:
        font = _font(config, size=font_size, bold=bold)
        lines = ([char for char in str(text) if char not in "\r\n"] or [""]) if vertical else _wrap(draw, text, font, max(0, available_w))
        boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
        heights = [box[3] for box in boxes]
        spacing = 4 if vertical else 8
        total = sum(heights) + max(0, len(lines) - 1) * spacing
        max_width = max((box[2] - min(0, box[0]) for box in boxes), default=0)
        punctuation_invalid = not vertical and _has_closing_line_start(lines)
        fits = available_w > 0 and available_h > 0 and total <= available_h and max_width <= available_w and not punctuation_invalid
        if fits or policy == "fixed" or font_size == minimum:
            break
        font_size = max(minimum, font_size - 2)
    return {"font_size": font_size, "requested_font_size": requested, "minimum_readable_font_size": minimum,
            "font_size_policy": policy, "font_size_adjusted": font_size != requested,
            "line_count": len(lines), "content_width": max_width, "content_height": total,
            "wrapped_lines": lines, "line_heights": heights, "line_spacing_px": spacing,
            "padding_px": padding, "available_size_px": [available_w, available_h],
            "closing_punctuation_line_start": punctuation_invalid, "fit_ok": fits,
            "failure_reason": None if fits else "text_does_not_fit_at_declared_font_size"}


def _draw_text(draw: ImageDraw.ImageDraw, text: str, rect: tuple[int, int, int, int], config: dict[str, Any], *, size: int | None = None, bold: bool = False, align: str = "left") -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    padding = int(config.get("text_box_style", {}).get("padding", 22))
    fit = _measure_text_layout(draw, text, rect, config, size=int(size or config.get("font_size", 42)), bold=bold)
    if not fit["fit_ok"]:
        raise _TextFitError(fit)
    font = _font(config, size=fit["font_size"], bold=bold)
    lines, heights, total = fit["wrapped_lines"], fit["line_heights"], fit["content_height"]
    yy = y0 + max(padding, ((y1 - y0) - total) // 2)
    ink = _rgba_hex(config.get("font_color"), INK)
    used: list[tuple[int, int, int, int]] = []
    for line, line_height in zip(lines, heights):
        bb = draw.textbbox((0, 0), line, font=font)
        line_width = bb[2] - bb[0]
        xx = x0 + padding if align == "left" else x0 + max(padding, ((x1 - x0) - line_width) // 2)
        draw.text((xx, yy), line, font=font, fill=ink)
        used.append((xx, yy, xx + line_width, yy + line_height))
        yy += line_height + 8
    return (
        min(r[0] for r in used),
        min(r[1] for r in used),
        max(r[2] for r in used),
        max(r[3] for r in used),
    )


def _draw_vertical_text(draw: ImageDraw.ImageDraw, text: str, rect: tuple[int, int, int, int], config: dict[str, Any], *, size: int | None = None, bold: bool = False, fill: tuple[int, int, int, int] = (255, 255, 255, 255)) -> tuple[int, int, int, int]:
    """Draw a compact top-to-bottom Chinese label in a preview note zone."""
    x0, y0, x1, y1 = rect
    padding = int(config.get("text_box_style", {}).get("padding", 22))
    fit = _measure_text_layout(draw, text, rect, config, size=int(size or config.get("font_size", 42)), bold=bold, vertical=True)
    if not fit["fit_ok"]:
        raise _TextFitError(fit)
    font = _font(config, size=fit["font_size"], bold=bold)
    chars, heights, total = fit["wrapped_lines"], fit["line_heights"], fit["content_height"]
    yy = y0 + max(padding, ((y1 - y0) - total) // 2)
    used: list[tuple[int, int, int, int]] = []
    for char, char_height in zip(chars, heights):
        bb = draw.textbbox((0, 0), char, font=font)
        char_width = bb[2] - bb[0]
        xx = x0 + max(padding, ((x1 - x0) - char_width) // 2)
        draw.text((xx, yy), char, font=font, fill=fill)
        used.append((xx, yy, xx + char_width, yy + char_height))
        yy += char_height + 4
    return min(r[0] for r in used), min(r[1] for r in used), max(r[2] for r in used), max(r[3] for r in used)


def _fit_text_in_rect(draw: ImageDraw.ImageDraw, text: str, rect: tuple[int, int, int, int], config: dict[str, Any], *, size: int, bold: bool = False) -> dict[str, Any]:
    return _measure_text_layout(draw, text, rect, config, size=size, bold=bold)


def _style_box(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], config: dict[str, Any], *, fill: tuple[int, int, int, int] | None = None, border: tuple[int, int, int, int] | None = None, width: int | None = None, radius: int | None = None) -> None:
    style = config.get("text_box_style", {})
    fill_color = fill or _rgba_hex(style.get("fill_color"), V0_FILL)
    opacity = int(style.get("fill_opacity", fill_color[3]))
    fill_color = fill_color[:3] + (opacity,)
    draw.rounded_rectangle(
        rect,
        radius=radius if radius is not None else int(style.get("corner_radius", 12)),
        fill=fill_color,
        outline=border or _rgba_hex(style.get("border_color"), V0_BORDER),
        width=width if width is not None else int(style.get("border_width", 3)),
    )


def _draw_thought(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], text: str, config: dict[str, Any], speaker_region: tuple[int, int, int, int] | None = None, text_size: int | None = None) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    fill = (255, 255, 255, 255)
    w, h = x1 - x0, y1 - y0
    circles = [
        (x0 + 4, y0 + 12, x0 + max(70, w // 3), y0 + h - 10),
        (x0 + w // 4, y0, x0 + (w * 2) // 3, y0 + h - 8),
        (x0 + (w * 3) // 5, y0 + 10, x1 - 4, y0 + h - 12),
    ]
    for circle in circles:
        draw.ellipse(circle, fill=fill, outline=V0_BORDER, width=3)
    if speaker_region:
        sx = (speaker_region[0] + speaker_region[2]) // 2
        sy = max(y1 + 14, speaker_region[1] - 14)
        start_x = x0 + w // 3
        start_y = y1 - 2
        for index, radius in enumerate((11, 7, 4)):
            t = (index + 1) / 4
            cx = int(start_x + (sx - start_x) * t)
            cy = int(start_y + (sy - start_y) * t)
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=fill, outline=V0_BORDER, width=2)
    return _draw_text(draw, text, (x0 + 12, y0 + 14, x1 - 12, y1 - 16), config, size=text_size or max(26, int(config.get("font_size", 42)) - 8), align="center")


def _draw_shout(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], text: str, config: dict[str, Any], text_size: int | None = None) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    points = []
    for i in range(20):
        angle = -math.pi / 2 + i * 2 * math.pi / 20
        factor = 1.0 if i % 2 == 0 else 0.78
        points.append((cx + math.cos(angle) * (x1 - x0) / 2 * factor, cy + math.sin(angle) * (y1 - y0) / 2 * factor))
    draw.polygon(points, fill=V0_FILL, outline=V0_BORDER)
    draw.line(points + [points[0]], fill=V0_BORDER, width=3, joint="curve")
    return _draw_text(draw, text, (x0 + 18, y0 + 14, x1 - 18, y1 - 14), config, size=text_size, bold=True, align="center")


def _draw_speech_tail(draw: ImageDraw.ImageDraw, body: tuple[int, int, int, int], speaker: tuple[int, int, int, int]) -> None:
    """Paint a short speech tail before the body so it cannot cover glyphs."""
    x0, y0, x1, y1 = body
    sx = (speaker[0] + speaker[2]) // 2
    sy = speaker[1]
    base_x = x0 + max(20, min(x1 - x0 - 60, (x1 - x0) // 4))
    draw.polygon([(base_x, y1 - 2), (base_x + 36, y1 - 2), (sx, sy)], fill=V0_FILL, outline=V0_BORDER)


def _compact_rect(draw: ImageDraw.ImageDraw, text: str, anchor: tuple[int, int, int, int], config: dict[str, Any], *, size: int | None = None, bold: bool = False, min_width: int = 150, min_height: int = 72) -> tuple[tuple[int, int, int, int], dict[str, Any]]:
    """Fit a text box to its content while staying inside the supplied anchor.

    Anchors are placement areas, not mandatory full-size shapes.  This keeps
    dialogue compact and lets narration width follow its actual text.
    """
    x0, y0, x1, y1 = anchor
    padding = int(config.get("text_box_style", {}).get("padding", 22))
    fit = _fit_text_in_rect(draw, text, anchor, config, size=int(size or config.get("font_size", 42)), bold=bold)
    if not fit["fit_ok"]:
        return anchor, fit
    max_line_w, total_h = fit["content_width"], fit["content_height"]
    desired_w = min(x1 - x0, max(min_width, max_line_w + padding * 2))
    desired_h = min(y1 - y0, max(min_height, total_h + padding * 2))
    # If the requested anchor is too short to contain the text at the minimum
    # readable size, keep the anchor and let the placement report block it.
    return (x0, y0, x0 + int(desired_w), y0 + int(desired_h)), fit


def _preview_color(value: Any, default: str) -> tuple[str, tuple[int, int, int, int] | None]:
    name = str(value or default).lower()
    named = {
        "white": (255, 255, 255, 255), "black": (0, 0, 0, 255),
        "green": (149, 236, 105, 255), "light_green": (198, 239, 188, 255),
        "light_blue": (204, 228, 245, 255),
        "red":(220,42,48,255),"blue":(40,105,205,255),"pink":(246,164,194,255),
        "pale_yellow":(255,244,201,255),"paper_yellow":(255,240,175,255),
    }
    if name in {"none", "transparent"}:
        return "none", None
    if name in named:
        return name, named[name]
    if name.startswith("#") and len(name) == 7:
        return name, _rgba_hex(name, named[default])
    raise ValueError(f'Unsupported observed color treatment: {name}')


def _preview_support_errors(visual: dict[str,Any]) -> list[str]:
    """Unimplemented source effects block composition instead of flattening."""
    errors=[]
    for key,default in [('fill','white'),('border','black'),('text_color','black')]:
        value=visual.get(key,default)
        if value is None:continue
        if str(value) in {'observed_palette','alternating_observed'} and key=='fill':continue
        try:_preview_color(value,default)
        except ValueError:errors.append(f'{key}_requires_explicit_color_region_renderer')
    if visual.get('rotation_degrees') not in (None,0,0.0):errors.append('source_rotated_glyph_renderer_not_implemented')
    return errors


def _preview_text_parameters(renderer: str, visual: dict[str, Any], rect: tuple[int, int, int, int], config: dict[str, Any]) -> tuple[tuple[int, int, int, int], dict[str, Any], bool, bool]:
    """Resolve the actual renderer's text inset and padding for both gates."""
    x0, y0, x1, y1 = rect
    text_config = copy.deepcopy(config)
    text_style = dict(text_config.get("text_box_style") or {})
    text_style["padding"] = max(4, int(round(min(x1 - x0, y1 - y0) * float(visual.get("padding_ratio", .04)))))
    text_config["text_box_style"] = text_style
    canonical = _canonical_style(renderer)
    bold = canonical == "shout_burst" or renderer in {"preview_display", "preview_display_text", "preview_brush_display_text"}
    if canonical == "rounded_speech":
        ix, iy = int((x1 - x0) * .13), int((y1 - y0) * .13)
        text_rect = x0 + ix, y0 + iy, x1 - ix, y1 - iy
    elif canonical == "shout_burst":
        ix, iy = int((x1 - x0) * .15), int((y1 - y0) * .17)
        text_rect = x0 + ix, y0 + iy, x1 - ix, y1 - iy
    else:
        text_rect = rect
    vertical = renderer == "preview_vertical_note" or visual.get("text_orientation") == "vertical" or visual.get("writing_direction") in {"vertical", "vertical_rl"}
    return text_rect, text_config, bold, vertical


def measure_preview_text_capacity(text: str, bounds: list[float], bubble: dict[str, Any], block: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Expose the raster measurement to preflight without painting an image."""
    visual = bubble.get("visual_style") or {}
    renderer = str(visual.get("renderer") or bubble.get("shape") or "")
    effective = copy.deepcopy(config)
    if block.get("font_size") is not None:
        effective["font_size"] = int(block["font_size"])
        effective["_explicit_font_size"] = True
    if block.get("font_size_policy") is not None:
        effective["font_size_policy"] = block["font_size_policy"]
    rect = _rect(bounds, "xywh")
    if not rect:
        return {"fit_ok": False, "failure_reason": "invalid_preview_body_geometry"}
    text_rect, effective, bold, vertical = _preview_text_parameters(renderer, visual, rect, effective)
    if renderer == "preview_brush_display_text":
        brush = _brush_font_evidence(effective)
        if brush["status"] != "verified":
            return {"fit_ok": False, "failure_reason": brush["reason"], "brush_font_evidence": brush}
        effective["font_file"] = effective["font_bold_file"] = brush["font_path"]
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    requested = int(effective.get("font_size", 42))
    if visual.get("typography_direction") == "diagonal_three_line_stack":
        regions = block.get("bubble_contract_typography_regions") or []
        lines = block.get("text_split_lines") or text.split("\n")
        if (not isinstance(lines, list) or len(lines) != 3 or len(regions) != 3
                or any(not isinstance(line, str) or not line for line in lines)
                or "".join(lines) != text.replace("\n", "")):
            return {"fit_ok": False, "failure_reason": "three_line_typography_requires_source_preserving_explicit_lines_and_regions"}
        fits = []
        for line, region in zip(lines, regions):
            region_rect = _rect(region.get("bounds"), "xywh")
            if not region_rect or not _contains(rect, region_rect):
                return {"fit_ok": False, "failure_reason": "typography_region_outside_body"}
            fits.append(_measure_text_layout(draw, line, region_rect, effective, size=requested, bold=bold))
        return {"font_size": min(row["font_size"] for row in fits), "fit_ok": all(row["fit_ok"] for row in fits), "line_fits": fits}
    return _measure_text_layout(draw, text, text_rect, effective, size=requested, bold=bold, vertical=vertical)


def _draw_preview_native(draw: ImageDraw.ImageDraw, block: dict[str, Any], rect: tuple[int, int, int, int], config: dict[str, Any]) -> tuple[tuple[int, int, int, int], dict[str, Any]]:
    """Render observed preview styles and report what the raster branch drew.

    The actual report is intentionally built from resolved colors and executed
    primitives, rather than copied from the target contract.
    """
    renderer = str(block.get("bubble_style"))
    visual = block.get("bubble_contract_visual_style") or {}
    unsupported=_preview_support_errors(visual)
    if unsupported:
        return rect,{'rendered':False,'selection_status':'blocked','failure_reason':'unsupported_source_visual_treatment','unsupported_features':unsupported}
    text = str(block.get("text", ""))
    x0, y0, x1, y1 = rect
    result: dict[str, Any] = {"requested_style": renderer, "used_style": renderer, "fallback_used": False, "warnings": [], "body_rect": list(rect)}
    block["_render_body_rect"] = rect
    if x1 <= x0 or y1 <= y0:
        result.update({"rendered": False, "selection_status": "blocked", "failure_reason": "invalid_preview_body_geometry"})
        return rect, result
    fill_value = visual.get("fill", "white")
    if "fill" in visual and fill_value is None:
        fill_value = "none"
    chosen_fill_reason = None
    if str(fill_value) in {"observed_palette", "alternating_observed"}:
        # Pick an actually rendered member of the observed phone palette;
        # report the chosen color rather than claiming to draw "alternating".
        palette = visual.get("observed_fill_palette") or ["white", "green"]
        # Palette availability does not imply a forced alternation rule.
        # Keep one selected color unless the caller explicitly chooses one.
        palette_index = int(block.get("palette_color_index", 0))
        fill_value = block.get("phone_message_fill") or block.get("phone_fill") or palette[max(0, min(len(palette) - 1, palette_index))]
        chosen_fill_reason = "selected_member_of_observed_phone_palette"
    fill_name, fill_rgba = _preview_color(fill_value, "white")
    border_name, border_rgba = _preview_color(visual.get("border", "black"), "black")
    border_width = int(visual.get("border_width_px", 3)) if border_rgba else 0
    text_name, text_rgba = _preview_color(visual.get("text_color", "black"), "black")
    text_config = copy.deepcopy(config)
    text_config["font_color"] = "#" + "".join(f"{v:02x}" for v in (text_rgba or (0, 0, 0, 255))[:3])
    text_style = dict(text_config.get("text_box_style") or {})
    text_style["padding"] = max(4, int(round(min(x1 - x0, y1 - y0) * float(visual.get("padding_ratio", .04)))))
    text_config["text_box_style"] = text_style
    text_rect = rect
    canonical = _canonical_style(renderer)
    shape = "caption_box"
    primitive = "rectangle"
    bold = False
    tail = _observed_tail_check(block, rect)
    tail_shape = tail.get('mode') if tail.get("status") == "ready" else "none"
    if tail.get("status") == "blocked":
        result.update({"rendered": False, "selection_status": "blocked", "failure_reason": tail["reason"], "tail_rendered": tail})
        return rect, result
    if canonical == "rounded_speech":
        shape, primitive = "rounded_speech", "ellipse"
        inset_x, inset_y = int((x1 - x0) * .13), int((y1 - y0) * .13)
        text_rect = x0 + inset_x, y0 + inset_y, x1 - inset_x, y1 - inset_y
    elif canonical == "shout_burst":
        shape, primitive, bold = "impact_burst", "polygon_burst", True
        text_rect = x0 + int((x1 - x0) * .15), y0 + int((y1 - y0) * .17), x1 - int((x1 - x0) * .15), y1 - int((y1 - y0) * .17)
    elif canonical == "phone_dialogue":
        shape, primitive = "phone_dialogue", "rounded_rectangle"
    elif renderer in {"preview_display", "preview_display_text", "preview_brush_display_text",'preview_surface_text'}:
        shape, primitive, bold = "display_text", "text_only", True
        # Display text's fill is glyph fill, not a bubble background.
        text_name, text_rgba = fill_name, fill_rgba
        text_config["font_color"] = "#" + "".join(f"{v:02x}" for v in (text_rgba or (255, 255, 255, 255))[:3])
        border_name = "none"
        if renderer=='preview_surface_text':
            surface_check=_surface_text_check(block,rect)
            if surface_check['status']!='ready':
                result.update(rendered=False,selection_status='blocked',failure_reason=surface_check['reason'],surface_text_evidence=surface_check)
                return rect,result
            result['surface_text_evidence']=surface_check
            bold=False
    elif renderer == "preview_vertical_note":
        shape, primitive = "vertical_note", "rectangle_vertical_text"
    elif renderer == "preview_caption_note":
        shape, primitive = "caption_note", "rectangle"
    observed_body_shape = str(block.get("bubble_contract_shape") or visual.get("shape") or "")
    body_polygon = block.get("bubble_contract_polygon")
    if observed_body_shape == "rounded_rect":
        primitive = "rounded_rectangle"
    elif observed_body_shape == "ellipse":
        primitive = "ellipse"
    elif observed_body_shape == "polygon":
        if not isinstance(body_polygon, list) or len(body_polygon) < 3 or any(p is None for p in body_polygon):
            result.update({"rendered": False, "selection_status": "blocked", "failure_reason": "observed_body_polygon_invalid"})
            return rect, result
        primitive = "observed_polygon"
    elif observed_body_shape in {"rect", "rectangle"}:
        primitive = "rectangle"
    # Display lettering uses its explicit foreground color. A transparent
    # display zone's fill is not a text-color instruction.
    if primitive == "text_only":
        fill_name, fill_rgba, border_name, border_rgba, border_width = "none", None, "none", None, 0
        text_name, text_rgba = _preview_color(visual.get("text_color", "black"), "black")
        text_config["font_color"] = "#" + "".join(f"{v:02x}" for v in (text_rgba or (0, 0, 0, 255))[:3])
    text_rect, text_config, bold, vertical_text = _preview_text_parameters(renderer, visual, rect, text_config)
    requested_font = int(config.get("font_size", 42))
    brush_evidence = None
    if renderer == "preview_brush_display_text":
        brush_evidence = _brush_font_evidence(config)
        if brush_evidence["status"] != "verified":
            result.update({"rendered": False, "selection_status": "blocked", "failure_reason": brush_evidence["reason"], "brush_font_evidence": brush_evidence})
            return rect, result
        text_config["font_file"] = brush_evidence["font_path"]
        text_config["font_bold_file"] = brush_evidence["font_path"]
    typography_draw_lines = []
    if renderer == "preview_brush_display_text" and visual.get("typography_direction") == "diagonal_three_line_stack":
        regions = block.get("bubble_contract_typography_regions") or []
        lines = block.get("text_split_lines") or text.split("\n")
        if (not isinstance(lines, list) or len(lines) != 3 or len(regions) != 3
                or any(not isinstance(line, str) or not line for line in lines)
                or "".join(lines) != text.replace("\n", "")):
            result.update({"rendered": False, "selection_status": "blocked", "failure_reason": "three_line_typography_requires_source_preserving_explicit_lines_and_regions"})
            return rect, result
        for line, region in zip(lines, regions):
            region_rect = _rect(region["bounds"], "xywh")
            if not region_rect or not _contains(rect, region_rect):
                result.update({"rendered": False, "selection_status": "blocked", "failure_reason": "typography_region_outside_body"})
                return rect, result
            line_fit = _fit_text_in_rect(draw, line, region_rect, text_config, size=requested_font, bold=bold)
            typography_draw_lines.append((line, region_rect, line_fit))
    if typography_draw_lines:
        fit = {"font_size": min(row[2]["font_size"] for row in typography_draw_lines),
               "fit_ok": all(row[2]["fit_ok"] for row in typography_draw_lines),
               "line_fits": [row[2] for row in typography_draw_lines]}
    elif vertical_text:
        fit = _measure_text_layout(draw, text, text_rect, text_config, size=requested_font, bold=bold, vertical=True)
    else:
        fit = _fit_text_in_rect(draw, text, text_rect, text_config, size=requested_font, bold=bold)
    if not fit["fit_ok"]:
        result.update({"rendered": False, "selection_status": "blocked", "failure_reason": "text_does_not_fit_preview_body", "fit": fit})
        return rect, result
    tail_before = draw._image.copy() if tail.get("status") == "ready" else None
    if tail_before is not None:
        if tail.get('mode')=='observed_dots':
            for dot in tail['dots']:draw.ellipse(_rect(dot,'xywh'),fill=fill_rgba,outline=border_rgba,width=border_width)
        else:
            points = [tuple(p) for p in tail["polygon"]]
            draw.polygon(points, fill=fill_rgba)
            if border_rgba:
                draw.line(points + [points[0]], fill=border_rgba, width=border_width, joint="curve")
        tail["status"] = "drawn"
        block["_render_observed_tail"] = copy.deepcopy(tail)
    if primitive == "ellipse":
        draw.ellipse(rect, fill=fill_rgba, outline=border_rgba, width=border_width)
    elif primitive == "polygon_burst":
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        points = [(cx + math.cos(-math.pi / 2 + i * math.pi / 10) * (x1 - x0) * .5 * (1.0 if i % 2 == 0 else .76), cy + math.sin(-math.pi / 2 + i * math.pi / 10) * (y1 - y0) * .5 * (1.0 if i % 2 == 0 else .76)) for i in range(20)]
        draw.polygon(points, fill=fill_rgba)
        if border_rgba:
            draw.line(points + [points[0]], fill=border_rgba, width=border_width, joint="curve")
    elif primitive == "rounded_rectangle":
        radius = max(0, int(min(x1 - x0, y1 - y0) * float(visual.get("corner_radius_ratio", .12))))
        draw.rounded_rectangle(rect, radius=radius, fill=fill_rgba, outline=border_rgba, width=border_width)
    elif primitive == "observed_polygon":
        points = [tuple(p) for p in body_polygon]
        draw.polygon(points, fill=fill_rgba)
        if border_rgba:
            draw.line(points + [points[0]], fill=border_rgba, width=border_width, joint="curve")
    elif primitive != "text_only":
        draw.rectangle(rect, fill=fill_rgba, outline=border_rgba, width=border_width)
    if typography_draw_lines:
        typography_bounds = [_draw_text(draw, line, region_rect, text_config, size=line_fit["font_size"], bold=bold, align="center")
                             for line, region_rect, line_fit in typography_draw_lines]
        text_bounds = _bbox(typography_bounds)
        result["typography_regions_rendered"] = [{"text": row[0], "bounds_xyxy": list(row[1]), "text_bounds_xyxy": list(bb),
                                                   "font_size": row[2]["font_size"]} for row, bb in zip(typography_draw_lines, typography_bounds)]
    elif vertical_text:
        text_bounds = _draw_vertical_text(draw, text, text_rect, text_config, size=fit["font_size"], bold=bold, fill=text_rgba or (0, 0, 0, 255))
    else:
        text_bounds = _draw_text(draw, text, text_rect, text_config, size=fit["font_size"], bold=bold, align="center")
    actual_visual = {"renderer": renderer, "shape": shape, "primitive": primitive, "fill": fill_name, "fill_rgba": list(fill_rgba) if fill_rgba else None, "border": border_name, "border_width_px": border_width, "text_color": text_name, "tail_shape": tail_shape}
    if vertical_text:
        actual_visual["writing_direction"] = visual.get("writing_direction", "vertical_rl")
    if typography_draw_lines:
        actual_visual["typography_direction"] = "positioned_three_line_stack"
        actual_visual["typography_regions_executed"] = True
        actual_visual["glyph_rotation_match"] = "unverified_source_rotation_unknown"
    actual_body_shape = {"rounded_rectangle": "rounded_rect", "observed_polygon": "polygon", "polygon_burst": "polygon", "rectangle_vertical_text": "rectangle", "text_only": "display_text"}.get(primitive, primitive)
    result["body_shape_rendered"] = actual_body_shape
    actual_visual["body_shape_rendered"] = actual_body_shape
    if primitive == "observed_polygon":
        result["body_polygon_rendered"] = copy.deepcopy(body_polygon)
        actual_visual["body_polygon_rendered"] = copy.deepcopy(body_polygon)
        block["_render_body_polygon"] = copy.deepcopy(body_polygon)
    if primitive == "rounded_rectangle":
        actual_visual["corner_radius_px"] = radius
        actual_visual["corner_radius_ratio"] = float(visual.get("corner_radius_ratio", .12))
        result["actual_corner_radius_px"] = radius
    if chosen_fill_reason:
        actual_visual["fill_selection_reason"] = chosen_fill_reason
    if brush_evidence:
        actual_visual.update(font_style="brush_calligraphy_selected_font", font_style_status="verified_brush_font_loaded_visual_match_unverified",
                             font_file=brush_evidence["font_path"], font_file_sha256=brush_evidence["font_file_sha256"],
                             font_family=brush_evidence["font_family"], font_style_name=brush_evidence["font_style_name"],
                             brush_font_verification=brush_evidence["verification"], preview_font_pixel_match="unverified")
    if tail_before is not None:
        mask = _tail_visible_mask({"polygon": tail.get("polygon"), 'dots':tail.get('dots'),"hidden_body_rect": rect}, draw._image.size)
        difference = ImageChops.difference(tail_before.convert("RGB"), draw._image.convert("RGB"))
        difference = Image.composite(difference, Image.new("RGB", difference.size), mask)
        difference_bbox = difference.getbbox()
        tail.update(pixel_difference_nonempty=bool(difference_bbox), pixel_difference_bbox=list(difference_bbox) if difference_bbox else None,
                    pixel_evidence_hash=hashlib.sha256(difference.tobytes()).hexdigest() if difference_bbox else None,
                    pixel_evidence_scope="visible_tail_polygon_outside_body_actual_overlay_difference")
        if not difference_bbox:
            result.update({"rendered": False, "selection_status": "blocked", "failure_reason": "tail_has_no_visible_pixel_evidence", "tail_rendered": tail})
            return rect, result
    result.update({"rendered": True, "selection_status": "selected", "shape_rendered": shape, "visual_style_rendered": actual_visual, "tail_rendered": tail, "text_bounds": list(text_bounds), "fit": fit})
    block["tail_enabled"] = tail.get("status") == "drawn"
    return text_bounds, result


def _system_note_overlay_allowed(block: dict[str, Any], style: str) -> bool:
    """An explicitly adapted, tailless system caption is not a physical prop label."""
    contract = block.get('bubble_contract') or {}
    adaptation = contract.get('compatibility_adaptation') or {}
    tail = contract.get('tail') or {}
    return bool(
        block.get('type') == 'note' and block.get('source_type') == 'note'
        and block.get('speaker') == 'system'
        and block.get('use_preview_contract') is True
        and style in {'preview_caption_box', 'preview_caption_note', 'preview_caption'}
        and contract.get('shape') in {'rect', 'rounded_rect'}
        and contract.get('note_scope') == 'nonphysical_system_overlay'
        and 'note' in (contract.get('allowed_text_types') or [])
        and adaptation.get('kind') == 'system_note_semantic_adaptation'
        and adaptation.get('approved_for_run') is True
        and adaptation.get('origin') == 'workflow_adaptation'
        and bool(adaptation.get('reason'))
        and isinstance(adaptation.get('source_allowed_text_types'), list)
        and not contract.get('carrier') and not block.get('carrier')
        and tail.get('mode') == 'none' and tail.get('required') is not True
    )


def _draw_block(draw: ImageDraw.ImageDraw, block: dict[str, Any], rect: tuple[int, int, int, int], config: dict[str, Any]) -> tuple[tuple[int, int, int, int], dict[str, Any]]:
    """Draw one block and record the font objects passed to Pillow itself."""
    effective = dict(config)
    try:
        requested = int(block.get("font_size") if block.get("font_size") is not None else effective.get("font_size", 42))
        minimum = int(effective.get("minimum_readable_font_size", 24))
    except (TypeError, ValueError):
        return rect, {"rendered": False, "selection_status": "blocked", "failure_reason": "invalid_font_size"}
    effective["font_size"] = requested
    effective["_explicit_font_size"] = block.get("font_size") is not None
    if block.get("font_size_policy") is not None:
        effective["font_size_policy"] = block["font_size_policy"]
    if requested < minimum or minimum <= 0:
        return rect, {"rendered": False, "selection_status": "blocked", "failure_reason": "font_below_readable_minimum",
                      "requested_font_size": requested, "minimum_readable_font_size": minimum}
    calls: list[dict[str, Any]] = []
    original_text = draw.text

    def traced_text(xy: Any, text: Any, *args: Any, **kwargs: Any) -> Any:
        font = kwargs.get("font") or (args[1] if len(args) > 1 else None)
        # The entry is appended only after Pillow successfully paints it.
        value = original_text(xy, text, *args, **kwargs)
        calls.append({"text": str(text), "position_px": list(xy), "font_size": getattr(font, "size", None),
                      "font_file": str(getattr(font, "path", "")),
                      "glyph_bounds_xyxy": list(draw.textbbox(xy, text, font=font))})
        return value

    draw.text = traced_text
    try:
        bounds, result = _draw_block_content(draw, block, rect, effective)
    except _TextFitError as exc:
        bounds, result = rect, {"rendered": False, "selection_status": "needs-placement", "failure_reason": str(exc), "fit": exc.fit}
    finally:
        draw.text = original_text
    sizes = sorted({row["font_size"] for row in calls if row["font_size"] is not None})
    result["requested_font_size"] = requested
    result["minimum_readable_font_size"] = minimum
    result["actual_font_sizes"] = sizes
    result["font_size_policy"] = str(effective.get("font_size_policy") or ("fixed" if effective["_explicit_font_size"] else "fit"))
    result["font_size_adjusted"] = bool(sizes and sizes != [requested])
    result["font_raster_evidence"] = {"method": "pillow_draw_text_font_object", "draw_calls": calls,
                                      "actual_font_sizes": sizes, "evidence_scope": "executed_draw_calls_before_placement_rollback"}
    if result.get("rendered") and (not sizes or min(sizes) < minimum):
        result.update(rendered=False, selection_status="blocked", failure_reason="actual_font_below_readable_minimum_or_missing")
    return bounds, result


def _draw_block_content(draw: ImageDraw.ImageDraw, block: dict[str, Any], rect: tuple[int, int, int, int], config: dict[str, Any]) -> tuple[tuple[int, int, int, int], dict[str, Any]]:
    requested_style = block.get("bubble_style") or DEFAULT_STYLE
    report_aliases = {
        "caption_box": "preview_caption",
        "impact_burst": "preview_impact",
        "display_text": "preview_display",
        "phone_dialogue": "phone_dialogue",
    }
    report_style = report_aliases.get(str(requested_style), str(requested_style))
    style = _canonical_style(requested_style) or DEFAULT_STYLE
    result: dict[str, Any] = {"requested_style": requested_style, "used_style": report_style, "canonical_style": style, "fallback_used": False, "warnings": []}
    if requested_style not in STYLE_NAMES and requested_style not in PREVIEW_STYLE_ALIASES:
        style = DEFAULT_STYLE
        report_style = style
        result.update({"used_style": style, "fallback_used": True, "fallback_reason": "unknown_bubble_style"})
    text = str(block.get("text", ""))
    draw_config = dict(config)
    if block.get("font_size") is not None:
        draw_config["font_size"] = int(block["font_size"])

    if str(requested_style).startswith("preview_"):
        return _draw_preview_native(draw, block, rect, draw_config)

    # Physical carriers keep their own geometry; the text is checked against
    # the carrier writable area and is never moved into a generic bubble.
    if style == "note_embedded":
        anchor = block.get("anchor") or {}
        carrier = block.get("carrier") or {}
        if anchor.get("kind") != "carrier" or not anchor.get("carrier_id", carrier.get("asset_id")):
            result.update({"used_style": style, "selection_status": "needs-placement", "rendered": False, "fallback_used": False, "failure_reason": "note_carrier_missing"})
            return rect, result
        x0, y0, x1, y1 = rect
        carrier_polygon = carrier.get("polygon")
        if isinstance(carrier_polygon, list) and len(carrier_polygon) >= 3:
            points = [(int(p[0]), int(p[1])) for p in carrier_polygon if isinstance(p, (list, tuple)) and len(p) >= 2]
            if len(points) >= 3:
                draw.polygon(points, fill=None, outline=V0_BORDER)
        else:
            draw.polygon([(x0 + 10, y0), (x1 - 10, y0 + 4), (x1, y1 - 6), (x0 - 3, y1)], fill=(255, 246, 188, 255), outline=V0_BORDER)
        text_rect = rect
        carrier_size = int(draw_config.get("font_size", 42)) if draw_config.get("_explicit_font_size") else max(24, int(draw_config.get("font_size", 42)) - 8)
        carrier_fit = _fit_text_in_rect(draw, text, text_rect, draw_config, size=carrier_size)
        if not carrier_fit["fit_ok"]:
            result.update({"selection_status": "needs-placement", "rendered": False, "failure_reason": "text_does_not_fit_carrier_writable_rect"})
            return rect, result
        text_bounds = _draw_text(draw, text, text_rect, draw_config, size=carrier_fit["font_size"])
        block["_render_body_rect"] = rect
        result.update({"selection_status": "selected", "rendered": True, "anchor_kind": "carrier", "text_bounds": list(text_bounds), "carrier_id": anchor.get("carrier_id", carrier.get("asset_id")), "body_rect": list(rect)})
        return text_bounds, result

    # All non-carrier styles use a compact body inside the anchor.  This is
    # especially important for dialogue: a placement area can be wide while
    # the actual speech bubble should remain close to its text.
    bounds_contract = block.get("bubble_bounds") if isinstance(block.get("bubble_bounds"), dict) else {}
    profile_min_width = int(bounds_contract.get("min_width", 150)) if str(bounds_contract.get("min_width", "")).isdigit() else 150
    profile_min_height = int(bounds_contract.get("min_height", 72)) if str(bounds_contract.get("min_height", "")).isdigit() else 72
    # Legacy shapes also inset their glyph area after fitting. Include these
    # insets now so a compact body cannot trigger a second, smaller font.
    inset_left = inset_top = inset_right = inset_bottom = 0
    if style == "thought_bubble":
        inset_left, inset_top, inset_right, inset_bottom = 12, 14, 12, 16
    elif style == "shout_burst":
        inset_left, inset_top, inset_right, inset_bottom = 18, 14, 18, 14
    elif style == "phone_dialogue":
        inset_left = 10 if report_style in {"preview_phone", "preview_phone_message"} else 48
        inset_top, inset_right, inset_bottom = 6, 10, 6
    writable_anchor = (rect[0] + inset_left, rect[1] + inset_top, rect[2] - inset_right, rect[3] - inset_bottom)
    if block.get("coordinate_source") == "bubble_contract":
        # A preview-native bubble has a measured body rectangle.  Do not
        # compact it to the text width; doing so would erase the observed
        # bubble geometry before the style audit.
        compact = rect
        fit = _fit_text_in_rect(
            draw,
            text,
            writable_anchor,
            draw_config,
            size=max(26, int(draw_config.get("font_size", 42)) - 8) if style in {"phone_dialogue", "thought_bubble"} and not draw_config.get("_explicit_font_size") else int(draw_config.get("font_size", 42)),
            bold=style in {"emphasis_box", "shout_burst"},
        )
    else:
        inner_compact, fit = _compact_rect(
            draw,
            text,
            writable_anchor,
            draw_config,
            size=max(26, int(draw_config.get("font_size", 42)) - 8) if style in {"phone_dialogue", "thought_bubble"} and not draw_config.get("_explicit_font_size") else None,
            min_width=max(1, max(profile_min_width, 200 if style == "phone_dialogue" else profile_min_width) - inset_left - inset_right),
            min_height=max(1, max(profile_min_height, 112 if style == "phone_dialogue" else profile_min_height) - inset_top - inset_bottom),
            bold=style in {"emphasis_box", "shout_burst"},
        )
        compact = (inner_compact[0] - inset_left, inner_compact[1] - inset_top,
                   inner_compact[2] + inset_right, inner_compact[3] + inset_bottom)
    block["_render_body_rect"] = compact
    result["body_rect"] = list(compact)
    result["fit"] = fit
    if not fit["fit_ok"]:
        result.update({"selection_status": "needs-placement", "rendered": False, "failure_reason": "text_does_not_fit_anchor_at_readable_size"})
        return compact, result

    text_size = fit["font_size"]

    if report_style in {"preview_display", "preview_brush_display_text"}:
        # Display text is an observed text zone rather than a generic speech
        # bubble.  Keep the artwork visible and draw a compact, bold label.
        text_bounds = _draw_text(draw, text, compact, draw_config, size=text_size, bold=True, align="center")
        result["shape_rendered"] = "display_text"
    elif report_style in {"preview_caption", "preview_caption_box"}:
        _style_box(draw, compact, draw_config, fill=(255, 253, 247, 232), border=V0_BORDER, width=2, radius=8)
        text_bounds = _draw_text(draw, text, compact, draw_config, size=text_size, align="center")
        result["shape_rendered"] = "caption_box"
    elif report_style == "preview_vertical_note":
        draw.rectangle(compact, fill=(25, 22, 20, 245), outline=None)
        text_bounds = _draw_vertical_text(draw, text, compact, draw_config, size=text_size, fill=(255, 255, 255, 255))
        result["shape_rendered"] = "vertical_note"
    elif report_style == "preview_caption_note":
        draw.rectangle(compact, fill=(25, 22, 20, 245), outline=(255, 255, 255, 255), width=2)
        note_config = dict(draw_config)
        note_config["font_color"] = "FFFFFF"
        text_bounds = _draw_text(draw, text, compact, note_config, size=text_size, align="center")
        result["shape_rendered"] = "caption_note"
    elif style == "thought_bubble":
        speaker_rect = _rect(block.get("speaker_region"), block.get("speaker_region_format", "xywh")) if block.get("tail_enabled") else None
        text_bounds = _draw_thought(draw, compact, text, draw_config, speaker_rect, text_size=text_size)
        if speaker_rect:
            result["tail_target"] = block.get("speaker")
            result["connector"] = "thought_dots"
        else:
            result["warnings"].append("speaker_region_missing_no_thought_connector")
    elif style == "phone_dialogue":
        x0, y0, x1, y1 = compact
        visual = block.get("bubble_contract_visual_style") if isinstance(block.get("bubble_contract_visual_style"), dict) else {}
        fill_name = str(visual.get("fill", "white")).lower()
        phone_fill = (25, 22, 20, 245) if fill_name in {"black", "dark"} else V0_FILL
        border_name = str(visual.get("border", "black")).lower()
        phone_border = None if border_name in {"none", "transparent"} else V0_BORDER
        phone_border_width = 0 if phone_border is None else 3
        draw.rounded_rectangle(compact, radius=min(20, (y1 - y0) // 2), fill=phone_fill, outline=phone_border, width=phone_border_width)
        # Legacy phone_dialogue includes a small receiver/avatar marker.  The
        # preview-native phone message contract explicitly omits that marker.
        text_left = x0 + 10
        if report_style not in {"preview_phone", "preview_phone_message"}:
            draw.ellipse((x0 + 12, y0 + 20, x0 + 40, y0 + 48), outline=V0_BORDER, width=2)
            text_left = x0 + 48
        text_bounds = _draw_text(draw, text, (text_left, y0 + 6, x1 - 10, y1 - 6), draw_config, size=text_size)
        if report_style in {"preview_phone", "preview_phone_message"}:
            result["shape_rendered"] = "phone_dialogue"
    elif style == "shout_burst":
        if str(block.get("emotional_intensity", "")).lower() != "high" and report_style != "preview_impact":
            style = "rounded_speech" if block.get("speaker") else DEFAULT_STYLE
            report_style = style
            result.update({"used_style": style, "fallback_used": True, "fallback_reason": "shout_requires_high_intensity"})
            if style == "rounded_speech":
                speaker_rect = _rect(block.get("speaker_region"), block.get("speaker_region_format", "xywh")) if block.get("tail_enabled") else None
                if speaker_rect:
                    _draw_speech_tail(draw, compact, speaker_rect)
            _style_box(draw, compact, draw_config, fill=V0_FILL, border=V0_BORDER, width=3, radius=min(24, (compact[3] - compact[1]) // 2))
            if style == "rounded_speech":
                if speaker_rect:
                    result["tail_target"] = block.get("speaker")
                else:
                    result["warnings"].append("speaker_region_missing_no_tail")
            text_bounds = _draw_text(draw, text, compact, draw_config, size=text_size, align="center")
        else:
            # High-intensity form remains visibly distinct by silhouette, while
            # using the same white/ink palette as the repaired default.
            text_bounds = _draw_shout(draw, compact, text, draw_config, text_size=text_size)
            if report_style in {"preview_impact", "preview_impact_burst"}:
                result["shape_rendered"] = "impact_burst"
    elif style == "emphasis_box":
        # Result/info text is not a yellow alert.  It uses the configured
        # warm-white palette and a compact, thin dark outline.
        _style_box(draw, compact, draw_config, fill=V0_FILL, border=V0_BORDER, width=3, radius=14)
        text_bounds = _draw_text(draw, text, compact, draw_config, size=text_size, bold=True, align="center")
    else:
        # narration_box and rounded_speech both use the configured white/ink
        # palette; rounded_speech is a capsule when the body is short.
        radius = min(28, max(12, (compact[3] - compact[1]) // 2)) if style == "rounded_speech" else None
        speaker_rect = None
        if style == "rounded_speech":
            speaker_rect = _rect(block.get("speaker_region"), block.get("speaker_region_format", "xywh")) if block.get("tail_enabled") else None
            if speaker_rect:
                _draw_speech_tail(draw, compact, speaker_rect)
        _style_box(draw, compact, draw_config, fill=V0_FILL, border=V0_BORDER, width=3, radius=radius)
        if style == "rounded_speech":
            if speaker_rect:
                result["tail_target"] = block.get("speaker")
            else:
                result["warnings"].append("speaker_region_missing_no_tail")
        text_bounds = _draw_text(draw, text, compact, draw_config, size=text_size)
    # Keep the preview alias in the report while retaining the canonical style
    # used by the drawing implementation.  This is consumed by the preview
    # bubble style audit and preserves compatibility with older reports.
    if report_style.startswith("preview_") or requested_style in {"caption_box", "impact_burst", "display_text"}:
        result["used_style"] = report_style
    result.update({"selection_status": "selected", "rendered": True, "text_bounds": list(text_bounds), "body_rect": list(compact)})
    return text_bounds, result


def _resolve_block(block: dict[str, Any], layout_context: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any], tuple[int, int, int, int] | None]:
    resolved = copy.deepcopy(block)
    layout_context = layout_context or {"layout_id": None, "status": "unavailable", "source": None, "profile": {}}
    layout_profile = layout_context.get("profile") or {}
    execution_profile = layout_profile.get("execution_profile") or {}
    block_id = _block_id(block)
    text = block.get("text")
    selected_layout = layout_context.get("layout_id")
    selected_panel = block.get("panel_id")
    requested_style_value = block.get("bubble_style")
    result: dict[str, Any] = {
        "id": block_id,
        "bubble_id": block.get("bubble_id"),
        "panel_id": selected_panel,
        "selected_layout": selected_layout,
        "selected_panel": selected_panel,
        "bubble_profile_id": layout_profile.get("bubble_profile_id") or execution_profile.get("profile_id"),
        "visual_reference_only": bool(layout_profile.get("visual_reference_only", True)),
        "bubble_style_requested": requested_style_value if requested_style_value not in (None, "") else "auto",
        "bubble_style_resolved": None,
        "bubble_bounds": execution_profile.get("bubble_bounds"),
        "bubble_bounds_format": "xyxy",
        "allowed_zone": execution_profile.get("allowed_zone"),
        "tail_anchor": None,
        "tail_anchor_format": "xyxy",
        "fallback_used": False,
        "fallback_reason": None,
        "render_source": None,
        "source_field": block.get("source_field"),
        "source_index": block.get("source_index"),
        "type": block.get("type"),
        "text": "" if text is None else str(text),
        "speaker": block.get("speaker"),
        "requested_bubble_style": block.get("bubble_style"),
        "layout_id": layout_context.get("layout_id"),
        "layout_constraint_status": layout_context.get("status"),
        "layout_constraint_source": layout_context.get("source"),
        "layout_preferred_bubble_candidates": layout_profile.get("preferred_bubble_candidates", []),
        "warnings": [],
        "selection_status": "selected",
    }
    if isinstance(block.get("bubble_contract"), dict):
        result["bubble_contract"] = copy.deepcopy(block["bubble_contract"])
        result["bubble_contract_source"] = block.get("bubble_contract_source", "block")
        result["bubble_contract_bounds"] = block.get("bubble_contract_bounds") or block["bubble_contract"].get("bounds")
        result["bubble_contract_bounds_format"] = block.get("bubble_contract_bounds_format", "xyxy")
        result["bubble_contract_bounds_xywh"] = block.get("bubble_contract_bounds_xywh")
        result["bubble_contract_shape"] = block.get("bubble_contract_shape") or block["bubble_contract"].get("shape")
        result["bubble_contract_renderer"] = block.get("bubble_contract_renderer") or (block["bubble_contract"].get("visual_style") or {}).get("renderer")
        result["bubble_contract_visual_style"] = copy.deepcopy(block.get("bubble_contract_visual_style") or block["bubble_contract"].get("visual_style") or {})
        result["bubble_position"] = block.get("bubble_contract_position") or block["bubble_contract"].get("position")
        result["bubble_shape"] = block.get("bubble_contract_renderer") or block.get("bubble_contract_shape") or block["bubble_contract"].get("shape")
        result["bubble_tail"] = copy.deepcopy(block.get("bubble_contract_tail") or block["bubble_contract"].get("tail"))
    trace: list[dict[str, Any]] = []
    trace.append({
        "stage": "selected_layout",
        "input": selected_layout,
        "result": "loaded" if layout_context.get("status") == "loaded" else layout_context.get("status"),
        "reason": "selected SB layout is resolved before text type",
        "bubble_profile_id": result.get("bubble_profile_id"),
        "visual_reference_only": result.get("visual_reference_only"),
    })
    trace.append({
        "stage": "selected_panel",
        "input": selected_panel,
        "result": "bound" if selected_panel is not None else "missing",
        "reason": "bubble geometry must remain in the selected panel",
    })
    if layout_context.get("status") != "loaded" or not execution_profile or execution_profile.get("executable") is not True:
        result.update({
            "rendered": False,
            "selection_status": "blocked",
            "failure_reason": "bubble_profile_missing_or_non_executable",
            "fallback_used": False,
            "fallback_reason": None,
            "render_source": "fallback",
            "selection_trace": trace,
        })
        return resolved, result, None
    if selected_panel is None:
        result.update({
            "rendered": False,
            "selection_status": "needs-placement",
            "failure_reason": "selected_panel_missing",
            "selection_trace": trace,
        })
        return resolved, result, None
    if text is None or str(text) == "":
        result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "empty_or_null_text", "selection_trace": trace})
        return resolved, result, None

    semantic_type, type_reason = _text_type(block)
    trace.append({"stage": "type", "input": block.get("type"), "result": semantic_type, "reason": type_reason})
    requested_type = block.get("type")
    result["requested_type"] = requested_type
    result["type"] = semantic_type or requested_type
    if semantic_type is None:
        if block.get("preview_contract_strict"):
            result.update({"rendered": False, "selection_status": "blocked", "failure_reason": "unsupported_original_text_type", "original_text_type": requested_type, "selection_trace": trace})
            return resolved, result, None
        if requested_type not in (None, ""):
            semantic_type = "narration"
            result.update({"type": semantic_type, "selection_status": "fallback", "fallback_used": True, "fallback_reason": "unsupported_text_type"})
        else:
            result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "unsupported_text_type", "selection_trace": trace})
            return resolved, result, None
    contract = block.get("bubble_contract") if isinstance(block.get("bubble_contract"), dict) else {}
    if block.get("preview_contract_strict"):
        allowed_types = list(contract.get("allowed_text_types") or [])
        if semantic_type not in allowed_types:
            result.update({"rendered": False, "selection_status": "blocked", "failure_reason": "text_type_not_allowed_by_bubble_contract", "original_text_type": block.get("type"), "allowed_text_types": allowed_types, "selection_trace": trace})
            return resolved, result, None
        panel_bounds = _required_rect(block.get("actual_panel_bounds"), block.get("actual_panel_bounds_format"))
        if panel_bounds is None:
            result.update({"rendered": False, "selection_status": "blocked", "failure_reason": "actual_panel_bounds_required", "selection_trace": trace})
            return resolved, result, None
        if not isinstance(block.get("actual_region_evidence"), dict) or not block.get("actual_region_evidence"):
            result.update({"rendered": False, "selection_status": "blocked", "failure_reason": "actual_region_evidence_required", "selection_trace": trace})
            return resolved, result, None
        result["actual_panel_bounds"] = list(panel_bounds)
        result["actual_panel_bounds_format"] = "xyxy"
        result["actual_region_evidence"] = copy.deepcopy(block.get("actual_region_evidence"))
        result["original_text_type"] = block.get("type")
    requested_style = block.get("bubble_style")
    requested_style_canonical = _canonical_style(requested_style)
    auto_style = requested_style in (None, "", "auto")
    type_style = TYPE_STYLES[semantic_type]
    preferred_candidates = execution_profile.get("preferred_bubble_candidates") or layout_profile.get("preferred_bubble_candidates") or []
    profile_style = execution_profile.get("bubble_style")
    if auto_style:
        # The selected SB execution profile is authoritative for the first
        # style decision.  The semantic type is consulted only within the
        # profile's approved candidates; it is never an unconditional
        # long/narration-box default.
        if profile_style in STYLE_NAMES:
            effective_style = profile_style
        elif profile_style == "profile_preference" and type_style in preferred_candidates:
            effective_style = type_style
        else:
            result.update({
                "rendered": False,
                "selection_status": "blocked",
                "failure_reason": "bubble_profile_has_no_compatible_style",
                "fallback_used": False,
                "fallback_reason": None,
                "render_source": "fallback",
                "selection_trace": trace,
            })
            return resolved, result, None
        requested_style = "auto"
        style_selection_reason = "selected_profile_candidate" if effective_style != type_style else "selected_profile_candidate_for_semantic_type"
        render_source = "layout_profile"
    else:
        contract_shape = (block.get("bubble_contract") or {}).get("shape") if isinstance(block.get("bubble_contract"), dict) else None
        contract_style = _canonical_style((block.get('bubble_contract') or {}).get('visual_style',{}).get('renderer') or contract_shape)
        contract_style={'rounded_speech_oval':'rounded_speech','preview_impact_bubble':'shout_burst'}.get(contract_style,contract_style)
        contract_approved = bool(contract_shape and requested_style_canonical == contract_style)
        if requested_style in STYLE_NAMES and (contract_approved or not preferred_candidates or requested_style in preferred_candidates or requested_style_canonical in preferred_candidates):
            effective_style = requested_style
            style_selection_reason = "explicit_preview_contract_style" if contract_approved else "explicit_block_style_approved_by_profile"
            render_source = "layout_profile"
        elif block.get('preview_contract_strict'):
            effective_style=None
            style_selection_reason='unknown_or_incompatible_preview_renderer_blocked'
            render_source='blocked'
        elif type_style in preferred_candidates:
            effective_style = type_style
            style_selection_reason = "profile_rejected_explicit_style_using_semantic_candidate"
            render_source = "fallback"
        else:
            effective_style = None
            style_selection_reason = "profile_rejected_explicit_style"
            render_source = "fallback"
    result["requested_bubble_style"] = requested_style
    result["bubble_style_requested"] = requested_style
    fallback_reason = None
    if effective_style is None:
        result.update({
            "rendered": False,
            "selection_status": "blocked",
            "failure_reason": "bubble_profile_rejected_requested_style",
            "fallback_used": False,
            "fallback_reason": "profile_rejected_requested_style",
            "render_source": "fallback",
            "selection_trace": trace,
        })
        return resolved, result, None
    if not auto_style and requested_style not in STYLE_NAMES:
        fallback_reason = "unknown_bubble_style"
    elif not auto_style and requested_style_canonical != TYPE_STYLES[semantic_type]:
        contract_renderer = (block.get("bubble_contract") or {}).get("visual_style", {}).get("renderer") if isinstance(block.get("bubble_contract"), dict) else None
        contract_shape = (block.get("bubble_contract") or {}).get("shape") if isinstance(block.get("bubble_contract"), dict) else None
        contract_style_canonical = _canonical_style(contract_renderer or contract_shape)
        contract_requested_match = bool(contract_style_canonical and requested_style_canonical == contract_style_canonical)
        if not (
            (semantic_type == "shout" and requested_style_canonical == "shout_burst")
            or (semantic_type in {"shout", "emphasis"} and requested_style_canonical == "shout_burst")
            or contract_requested_match
        ):
            if TYPE_STYLES[semantic_type] in preferred_candidates:
                effective_style = TYPE_STYLES[semantic_type]
                fallback_reason = "style_type_mismatch"
            elif preferred_candidates:
                effective_style = preferred_candidates[0]
                fallback_reason = "style_type_mismatch_profile_candidate"
            else:
                result.update({
                    "rendered": False,
                    "selection_status": "blocked",
                    "failure_reason": "bubble_profile_rejected_style_type_mismatch",
                    "fallback_used": False,
                    "fallback_reason": "style_type_mismatch_no_profile_candidate",
                    "render_source": "fallback",
                    "selection_trace": trace,
                })
                return resolved, result, None
    resolved["type"] = semantic_type
    resolved["bubble_style"] = effective_style
    resolved["bubble_profile_id"] = result.get("bubble_profile_id")
    resolved["allowed_zone"] = execution_profile.get("allowed_zone")
    resolved["bubble_bounds"] = execution_profile.get("bubble_bounds")
    resolved["speaker_direction"] = execution_profile.get("speaker_direction")
    result["used_style"] = effective_style
    result["bubble_style_resolved"] = effective_style
    result["style_selection_reason"] = style_selection_reason
    result["layout_preference_applied"] = bool(render_source == "layout_profile")
    result["render_source"] = render_source
    if fallback_reason:
        prior_fallback = result.get("fallback_reason")
        combined = f"{prior_fallback};{fallback_reason}" if prior_fallback and prior_fallback != fallback_reason else fallback_reason
        result.update({"fallback_used": True, "fallback_reason": combined, "selection_status": "fallback", "render_source": "fallback", "bubble_style_resolved": effective_style})

    speaker = block.get("speaker")
    speaker_status = block.get("speaker_status") or ("narrator" if speaker == "narrator" else ("confirmed" if speaker else "missing"))
    speaker_region = _speaker_rect(block)
    speaker_identified = bool(speaker and speaker != "narrator" and speaker_status in {"confirmed", "visible"})
    speaker_valid = bool(speaker_identified and speaker_region)
    speaker_panel_id = block.get("speaker_panel_id") or block.get("speaker_region_panel_id")
    if speaker_panel_id is not None and block.get("panel_id") is not None and speaker_panel_id != block.get("panel_id"):
        result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "speaker_panel_binding_mismatch", "speaker_panel_id": speaker_panel_id})
        return resolved, result, None
    if block.get("speaker_region_visibility") not in (None, "visible", "confirmed"):
        result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "speaker_not_visible", "speaker_region_visibility": block.get("speaker_region_visibility")})
        return resolved, result, None
    trace.append({"stage": "speaker", "input": speaker, "result": "confirmed" if speaker_valid else speaker_status, "reason": "stable speaker_region in current panel" if speaker_valid else "no tail for narrator/remote channel or missing speaker region"})
    result["speaker_status"] = "confirmed" if speaker_valid else speaker_status
    effective_style_canonical = _canonical_style(effective_style)
    if speaker and speaker != "narrator" and effective_style_canonical in {"rounded_speech", "thought_bubble"} and not speaker_valid and not block.get("preview_contract_strict"):
        if not (semantic_type == "shout" and str(block.get("emotional_intensity", "")).lower() != "high" and effective_style == "rounded_speech" and speaker_identified):
            result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "speaker_region_missing_or_invalid", "selection_trace": trace})
            return resolved, result, None
    if effective_style_canonical == "shout_burst" and str(block.get("emotional_intensity", "")).lower() != "high" and effective_style != "preview_impact":
        effective_style = "rounded_speech" if speaker_identified else DEFAULT_STYLE
        resolved["bubble_style"] = effective_style
        prior_fallback = result.get("fallback_reason")
        combined = f"{prior_fallback};shout_requires_high_intensity" if prior_fallback and prior_fallback != "shout_requires_high_intensity" else "shout_requires_high_intensity"
        result.update({"used_style": effective_style, "bubble_style_resolved": effective_style, "fallback_used": True, "fallback_reason": combined, "selection_status": "fallback", "render_source": "fallback"})
    effective_style_canonical = _canonical_style(effective_style)
    result["tail_target"] = speaker if effective_style_canonical == "rounded_speech" and speaker_valid else None
    result["tail_anchor"] = list(speaker_region) if speaker_valid and execution_profile.get("tail_anchor") == "speaker_region" else None
    resolved["tail_anchor"] = result["tail_anchor"]
    resolved["bubble_style"] = effective_style
    resolved["speaker_status"] = "confirmed" if speaker_valid else speaker_status
    resolved["tail_enabled"] = bool(speaker_valid and effective_style_canonical in {"rounded_speech", "thought_bubble"})
    if effective_style_canonical == "thought_bubble":
        result["connector"] = "thought_dots" if speaker_valid else None
    result["tail_enabled"] = bool(speaker_valid and effective_style_canonical in {"rounded_speech", "thought_bubble"})
    trace.append({"stage": "emotional_intensity", "input": block.get("emotional_intensity"), "result": block.get("emotional_intensity") or "neutral", "reason": "high intensity required for shout_burst" if semantic_type == "shout" else "preserved type-specific style"})

    if semantic_type == "phone_dialogue":
        channel = str(block.get("channel") or "").lower()
        anchor_kind = str((block.get("anchor") or {}).get("kind") or "").lower()
        if channel not in {"telephone", "phone", "phone_channel", "chat", "messaging"} and anchor_kind != "phone_channel":
            result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "phone_channel_missing", "selection_trace": trace})
            return resolved, result, None

    anchor = block.get("anchor") or {}
    anchor_rect = _required_rect(anchor.get("rect"), anchor.get("rect_format"))
    if anchor.get("panel_id") is not None and block.get("panel_id") is not None and anchor.get("panel_id") != block.get("panel_id"):
        result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "anchor_panel_binding_mismatch", "selection_trace": trace})
        return resolved, result, None
    carrier = block.get("carrier") or {}
    carrier_rect = _carrier_rect(block)
    anchor_carrier_id = anchor.get("carrier_id")
    carrier_asset_id = carrier.get("asset_id")
    carrier_id = anchor_carrier_id or carrier_asset_id
    carrier_kind = carrier.get("kind")
    carrier_polygon = _carrier_polygon_rect(block)
    carrier_id_match = bool(anchor_carrier_id and carrier_asset_id and anchor_carrier_id == carrier_asset_id)
    if carrier.get("panel_id") is not None and block.get("panel_id") is not None and carrier.get("panel_id") != block.get("panel_id"):
        result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "carrier_panel_binding_mismatch", "selection_trace": trace})
        return resolved, result, None
    carrier_valid = bool(anchor.get("kind") == "carrier" and carrier_id_match and carrier_kind and carrier_rect and carrier_polygon and anchor_rect and _contains(carrier_rect, anchor_rect))
    trace.append({"stage": "physical_carrier", "input": carrier_kind or "none", "result": "confirmed" if carrier_valid else "none", "reason": "matched carrier_id, polygon, writable_rect and anchor" if carrier_valid else "no physical carrier required or carrier contract incomplete", "carrier_id_match": carrier_id_match})
    system_overlay = _system_note_overlay_allowed(block, effective_style)
    if system_overlay:
        result['note_scope'] = 'nonphysical_system_overlay'
        trace.append({'stage':'system_note_overlay','result':'explicit_adapted_caption',
                      'reason':'Preserve system-note semantics and declared caption geometry without inventing a physical carrier'})
    if (semantic_type == "note" and not system_overlay) or effective_style == "note_embedded" or effective_style=='preview_surface_text':
        if not carrier_valid:
            result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "note_carrier_missing_or_not_writable", "selection_trace": trace})
            return resolved, result, None
        if effective_style!='preview_surface_text':
            resolved["bubble_style"] = "note_embedded"
            result["used_style"] = "note_embedded"
        else:
            surface_check=_surface_text_check(block,anchor_rect)
            result['surface_text_evidence']=surface_check
            if surface_check['status']!='ready':
                result.update(rendered=False,selection_status='blocked',failure_reason=surface_check['reason'],selection_trace=trace)
                return resolved,result,None
        result["carrier_id"] = carrier_id

    avoid_names = list(block.get("avoid_regions") or [])
    protection=_global_protection_check(block)
    result['global_protection_evidence']=protection
    if protection['status']=='blocked':
        result.update(rendered=False,selection_status='blocked',failure_reason=protection['reason'],selection_trace=trace)
        return resolved,result,None
    avoid_rects, missing_avoid, malformed_avoid, avoid_adapter = _resolved_avoid_rects(block)
    if not isinstance(block.get("avoid_region_rects") or {}, dict):
        result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "avoid_region_rects_not_mapping", "selection_trace": trace})
        return resolved, result, None
    trace.append({"stage": "whitespace_avoidance", "input": avoid_names, "result": "coordinates-resolved" if not (missing_avoid or malformed_avoid) else "needs-placement", "reason": "explicit panel coordinates supplied", "coordinate_adapter": avoid_adapter})
    if missing_avoid or malformed_avoid:
        result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "avoid_region_coordinates_missing_or_malformed", "missing_avoid_regions": missing_avoid, "malformed_avoid_regions": malformed_avoid, "selection_trace": trace})
        return resolved, result, None
    if anchor_rect is None:
        allowed_zone = execution_profile.get("allowed_zone") or {}
        failure_reason = "allowed_zone_requires_explicit_anchor" if allowed_zone.get("requires_explicit_anchor") else "anchor_rect_missing_or_ambiguous"
        result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": failure_reason, "selection_trace": trace})
        return resolved, result, None
    # The execution profile supplies a bounded placement contract.  The input
    # anchor remains the source of canvas coordinates, while max_width keeps a
    # profile-selected bubble compact inside that panel area.
    max_width = execution_profile.get("max_width") or {}
    if isinstance(max_width, dict) and max_width.get("unit") == "anchor_fraction" and block.get("coordinate_source") != "bubble_contract":
        try:
            fraction = float(max_width.get("value"))
        except (TypeError, ValueError):
            fraction = 1.0
        if 0 < fraction < 1 and anchor.get("kind") != "carrier":
            anchor_width = anchor_rect[2] - anchor_rect[0]
            limited_width = max(1, int(round(anchor_width * fraction)))
            anchor_rect = (anchor_rect[0], anchor_rect[1], anchor_rect[0] + limited_width, anchor_rect[3])
            result["profile_max_width_applied"] = {"value": fraction, "unit": "anchor_fraction"}
    result["placement_anchor"] = list(anchor_rect)
    result["allowed_zone_applied"] = bool((execution_profile.get("allowed_zone") or {}).get("requires_explicit_anchor"))
    result["selection_trace"] = trace
    result["anchor"] = anchor
    result["avoid_regions"] = avoid_names
    result["resolved_avoid_region_rects"] = avoid_rects
    resolved["avoid_region_rects"] = avoid_rects
    result["coordinate_adapter"] = avoid_adapter
    result["placement_reason"] = block.get("placement_reason", "")
    result["coordinate_source"] = block.get("coordinate_source", "declared_input")
    result["actual_regions_verified"] = block.get("actual_regions_verified") is True
    if result["actual_regions_verified"] is False:
        result["visual_confirmation_required"] = True
    return resolved, result, anchor_rect


def _avoidance(block: dict[str, Any], geometry: list[dict[str, Any]], placed: list[dict[str, Any]], canvas_width: int, canvas_height: int) -> dict[str, Any]:
    rects = block.get("avoid_region_rects") or {}
    if not isinstance(rects, dict):
        rects = {}
    protected = []
    unresolved = []
    for name, value in rects.items():
        r = _rect(value, "xywh") if isinstance(value, (list, tuple)) else None
        if r:
            protected.append((name, r))
        elif value:
            unresolved.append(name)
    carrier_rect = _carrier_rect(block)
    carrier_match = _canonical_style(block.get("bubble_style")) == "note_embedded" and carrier_rect is not None and all(_contains(carrier_rect, _rect(g.get("rect"), "xyxy")) for g in geometry if g.get("part") == "text")
    overlaps = []
    overlap_parts = []
    for name, protected_rect in protected:
        for part in geometry:
            part_rect = _rect(part.get("rect"), "xyxy")
            target = part.get("target_region_xyxy")
            own_target = bool(part.get("part") == "tail" and target and tuple(target) == protected_rect
                              and ((part.get("binding_kind") == "speaker" and str(name).startswith("speaker"))
                                   or (part.get("binding_kind") == "prop"
                                       and (str(name).startswith("prop") or str(name) == "key_props" or str(name).startswith("key_props_")))))
            if part_rect and _part_intersects_rect(part, protected_rect, permit_tip_contact=own_target):
                # The carrier is an existing object in the base art; only the
                # newly drawn note text must be tested against protected areas.
                if part.get("part") == "carrier":
                    continue
                carrier_id=str((block.get('carrier') or {}).get('asset_id') or '')
                own_carrier=(str(name)==f'carrier_{carrier_id}' or str(name)==f'key_props_{carrier_id}') and carrier_id
                if carrier_match and own_carrier and part.get("part") == "text" and _contains(carrier_rect, part_rect):
                    continue
                overlaps.append(name)
                overlap_parts.append(f"{part.get('part')}:{name}")
    same_panel = []
    for previous in placed:
        global_check=canvas_text_binding(block.get('bubble_contract') or {}) or (block.get('bubble_contract') or {}).get('cross_panel_allowed') is True or previous.get('global_text_scope') is True
        if previous.get("panel_id") != block.get("panel_id") and not global_check:
            continue
        for part in geometry:
            part_rect = _rect(part.get("rect"), "xyxy")
            if not part_rect:
                continue
            for old_part in previous.get("geometry", []):
                old_rect = _rect(old_part.get("rect"), "xyxy")
                if old_rect and _part_intersects_rect(part, old_rect) and _part_intersects_rect(old_part, part_rect):
                    same_panel.append(f"{part.get('part')}:{old_part.get('part')}:{previous.get('id')}")
    all_rects = [_rect(p.get("rect"), "xyxy") for p in geometry]
    all_rects = [r for r in all_rects if r]
    panel_bounds = _required_rect(block.get("actual_panel_bounds"), block.get("actual_panel_bounds_format"))
    allowed_crossing=(block.get('bubble_contract') or {}).get('cross_panel_allowed') is True
    canvas_scope=canvas_text_binding(block.get('bubble_contract') or {})
    inside_panel = bool((canvas_scope or panel_bounds) and (canvas_scope or allowed_crossing or all(_contains(panel_bounds, r) for r in all_rects))) if block.get("preview_contract_strict") else True
    return {
        "protected_region_names": list(rects),
        "unresolved_region_names": unresolved,
        "protected_overlaps": sorted(set(overlaps)),
        "overlap_parts": sorted(set(overlap_parts)),
        "same_panel_geometry_overlaps": sorted(set(same_panel)),
        "same_panel_text_overlap": bool(same_panel),
        "inside_canvas": all(r[0] >= 0 and r[1] >= 0 and r[2] <= canvas_width and r[3] <= canvas_height for r in all_rects),
        "inside_actual_panel": inside_panel,
        "actual_panel_bounds": list(panel_bounds) if panel_bounds else None,
        "carrier_overlap_allowed": carrier_match,
        "drawn_geometry": geometry,
    }


def _legacy_text_value(value: Any) -> str | None:
    if isinstance(value, dict):
        text = value.get("text")
        return None if text is None else str(text)
    if value is None:
        return None
    return str(value)


def _legacy_source_text(legacy_fields: dict[str, Any], source_field: Any, source_index: Any) -> str | None:
    if source_field not in legacy_fields:
        return None
    value = legacy_fields.get(source_field)
    if isinstance(value, list) and isinstance(source_index, int) and 0 <= source_index < len(value):
        return _legacy_text_value(value[source_index])
    if isinstance(value, dict) and source_index in value:
        return _legacy_text_value(value[source_index])
    if isinstance(value, dict) and str(source_index) in value:
        return _legacy_text_value(value[str(source_index)])
    if isinstance(value, dict) and "text" in value and source_index in (0, None):
        return _legacy_text_value(value)
    if isinstance(value, (str, int, float)) and source_index in (0, None):
        return _legacy_text_value(value)
    return None


def compose_page(base_image: str | Path, text_blocks: str | Path | list[dict[str, Any]], text_layout: str | Path | dict[str, Any], output_image: str | Path, render_report: str | Path, placement_report: str | Path, page_id: str | None = None, layout_constraints: str | Path | None = None) -> dict[str, Any]:
    """Resolve, validate, and compose linked text_blocks onto one existing PNG."""
    base_path = Path(base_image)
    if not base_path.exists():
        raise FileNotFoundError(f"base image not found: {base_path}")
    if Path(output_image).resolve() == base_path.resolve():
        raise ValueError("output_image must differ from the frozen base image")
    base_hash_before = hashlib.sha256(base_path.read_bytes()).hexdigest()
    raw_blocks = load_yaml(Path(text_blocks)) if isinstance(text_blocks, (str, Path)) else text_blocks
    layout_id = raw_blocks.get("layout_id") if isinstance(raw_blocks, dict) else None
    synthetic_plan = bool(raw_blocks.get("synthetic") or raw_blocks.get("synthetic_input")) if isinstance(raw_blocks, dict) else False
    layout_context = load_layout_profile(layout_id, layout_constraints)
    layout_map_validation = validate_layout_bubble_map(layout_constraints)
    if isinstance(raw_blocks, dict):
        blocks = raw_blocks.get("text_blocks", []) or []
        legacy_fields = dict(raw_blocks.get("legacy_source_fields") or {})
        for name in LEGACY_FIELDS:
            if name in raw_blocks:
                legacy_fields[name] = raw_blocks[name]
    else:
        blocks = raw_blocks or []
        legacy_fields = {}
    config = load_yaml(Path(text_layout)) if isinstance(text_layout, (str, Path)) else text_layout
    config = copy.deepcopy(config or {})
    if isinstance(text_layout, (str, Path)):
        for key in ("font_file", "font_bold_file", "brush_font_file"):
            if config.get(key) and not Path(str(config[key])).is_absolute():
                config[key] = str((Path(text_layout).parent / str(config[key])).resolve())
    image = Image.open(base_path).convert("RGBA")
    frozen_base_pixels = image.copy()
    # Resolve preview-native bubble contracts before duplicate detection and
    # placement.  This only enriches text blocks; the source/base image is
    # never changed in this step.
    canvas_transform = raw_blocks.get("canvas_transform") if isinstance(raw_blocks, dict) else None
    blocks = [_apply_bubble_contract(block, layout_id, image.width, image.height, canvas_transform) if isinstance(block, dict) else block for block in blocks]
    authoritative_panel_ids=[]
    template_path=(raw_blocks.get('execution_template_path') if isinstance(raw_blocks,dict) else None)
    if not template_path and layout_id:
        template_path=Path(__file__).resolve().parents[1]/'references/comic-layouts/executable-templates'/f'{layout_id}.yaml'
    if template_path and Path(template_path).is_file():
        actual_template=load_yaml(Path(template_path))
        authoritative_panel_ids=[p.get('panel_id') for p in actual_template.get('panels',[])]
    for block in blocks:
        if isinstance(block, dict):
            block['_all_panel_ids']=authoritative_panel_ids
            block["synthetic_input"] = synthetic_plan
            block['_base_image_sha256']=hashlib.sha256(base_path.read_bytes()).hexdigest()
    draw = ImageDraw.Draw(image)
    records: list[dict[str, Any]] = []
    placed: list[dict[str, Any]] = []
    duplicate_groups: dict[tuple[Any, Any, Any], list[int]] = {}
    id_groups: dict[Any, list[int]] = {}
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            records.append({"id": None, "rendered": False, "selection_status": "needs-placement", "failure_reason": "block_not_mapping"})
            continue
        block_key = _block_id(block)
        if block_key is not None:
            id_groups.setdefault(block_key, []).append(index)
        if block.get("source_field") is not None and block.get("source_index") is not None:
            duplicate_groups.setdefault((block.get("source_field"), block.get("source_index")), []).append(index)
    conflict_indices: set[int] = set()
    duplicate_indices: dict[int, int] = {}
    for indexes in id_groups.values():
        if len(indexes) > 1:
            canonical = indexes[0]
            comparable = ("text", "type", "speaker", "bubble_style", "anchor", "carrier", "source_field", "source_index", "panel_id")
            for duplicate in indexes[1:]:
                if all(blocks[canonical].get(key) == blocks[duplicate].get(key) for key in comparable):
                    duplicate_indices[duplicate] = canonical
                else:
                    conflict_indices.update(indexes)
    for indexes in duplicate_groups.values():
        if len(indexes) <= 1:
            continue
        canonical = indexes[0]
        canonical_block = blocks[canonical]
        for duplicate in indexes[1:]:
            duplicate_block = blocks[duplicate]
            comparable = ("text", "type", "speaker", "bubble_style", "anchor", "carrier")
            if all(canonical_block.get(key) == duplicate_block.get(key) for key in comparable):
                duplicate_indices[duplicate] = canonical
            else:
                conflict_indices.update(indexes)

    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        if index in duplicate_indices:
            records.append({"id": _block_id(block), "panel_id": block.get("panel_id"), "source_field": block.get("source_field"), "source_index": block.get("source_index"), "type": block.get("type"), "text": block.get("text", ""), "rendered": False, "selection_status": "duplicate-skipped", "dedupe_status": "deduped", "duplicate_of_index": duplicate_indices[index]})
            continue
        if index in conflict_indices:
            records.append({"id": _block_id(block), "panel_id": block.get("panel_id"), "source_field": block.get("source_field"), "source_index": block.get("source_index"), "type": block.get("type"), "text": block.get("text", ""), "rendered": False, "selection_status": "needs-placement", "dedupe_status": "blocked", "failure_reason": "duplicate_id_or_source_link_conflict"})
            continue
        legacy_text = _legacy_source_text(legacy_fields, block.get("source_field"), block.get("source_index"))
        if legacy_text is not None and legacy_text != str(block.get("text", "")):
            records.append({"id": _block_id(block), "panel_id": block.get("panel_id"), "source_field": block.get("source_field"), "source_index": block.get("source_index"), "type": block.get("type"), "text": block.get("text", ""), "rendered": False, "selection_status": "needs-placement", "dedupe_status": "blocked", "failure_reason": "legacy_structured_text_conflict", "legacy_text": legacy_text})
            continue
        resolved, plan, rect = _resolve_block(block, layout_context)
        if rect is None:
            plan.setdefault("dedupe_status", "clean")
            records.append(plan)
            continue
        before = image.copy()
        current_draw = ImageDraw.Draw(image)
        text_bounds, rendered_result = _draw_block(current_draw, resolved, rect, config)
        used_style = rendered_result.get("used_style", resolved.get("bubble_style"))
        draw_rendered = rendered_result.get("rendered") is True
        draw_selection_status = rendered_result.get("selection_status")
        draw_failure_reason = rendered_result.get("failure_reason")
        draw_fallback_used = rendered_result.get("fallback_used") is True
        draw_fallback_reason = rendered_result.get("fallback_reason")
        rendered_result.update(plan)
        if rendered_result.get("shape_rendered") is not None:
            # These outward-facing actual fields must describe the executed
            # draw branch.  Target evidence remains in bubble_contract only.
            rendered_result["bubble_shape"] = rendered_result["shape_rendered"]
        if rendered_result.get("tail_rendered") is not None:
            rendered_result["bubble_tail"] = copy.deepcopy(rendered_result["tail_rendered"])
            rendered_result["tail_anchor"] = rendered_result["tail_rendered"].get("anchor")
        # Resolver metadata must not overwrite an actual draw failure.  A
        # failed fit/carrier remains needs-placement and is rolled back below;
        # only a successful draw may inherit the resolver's fallback/status.
        if not draw_rendered:
            rendered_result.update({
                "rendered": False,
                "selection_status": draw_selection_status or "needs-placement",
                "failure_reason": draw_failure_reason or "draw_failed",
                "fallback_used": draw_fallback_used or rendered_result.get("fallback_used") is True,
                "fallback_reason": draw_fallback_reason or rendered_result.get("fallback_reason"),
            })
        elif draw_fallback_used:
            rendered_result.update({"fallback_used": True, "fallback_reason": draw_fallback_reason or rendered_result.get("fallback_reason"), "render_source": "fallback"})
        rendered_result["bubble_style_resolved"] = rendered_result.get("used_style") or plan.get("bubble_style_resolved") or resolved.get("bubble_style")
        rendered_result["bubble_bounds_format"] = "xyxy"
        if rendered_result.get("body_rect"):
            rendered_result["bubble_bounds"] = rendered_result.get("body_rect")
        rendered_result.setdefault("allowed_zone", plan.get("allowed_zone"))
        rendered_result.setdefault("tail_anchor", plan.get("tail_anchor"))
        if rendered_result.get("rendered"):
            geometry = _render_geometry(resolved, rect, text_bounds, used_style)
            geometry_safety = _text_geometry_safety(resolved, geometry, used_style)
            avoidance = _avoidance(resolved, geometry, placed, image.width, image.height)
            rendered_result["avoidance"] = avoidance
            rendered_result["drawn_geometry"] = geometry
            rendered_result["geometry_safety"] = geometry_safety
            rendered_result["dedupe_status"] = "clean"
            unsafe = bool(
                not geometry_safety.get("safe")
                or
                avoidance.get("protected_overlaps")
                or avoidance.get("same_panel_geometry_overlaps")
                or avoidance.get("unresolved_region_names")
                or not avoidance.get("inside_canvas")
                or not avoidance.get("inside_actual_panel", True)
            )
            if unsafe:
                image = before
                draw = ImageDraw.Draw(image)
                rendered_result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "unsafe_placement", "unsafe_content_excluded": True})
            else:
                placed.append({"id": resolved.get("id"), "panel_id": resolved.get("panel_id"), "geometry": geometry,
                               'global_text_scope':canvas_text_binding(resolved.get('bubble_contract') or {}) or (resolved.get('bubble_contract') or {}).get('cross_panel_allowed') is True})
        else:
            # A failed fit or missing carrier must not leave a partial outline
            # or glyph on the output image.
            image = before
            draw = ImageDraw.Draw(image)
        pixel_difference = ImageChops.difference(before.convert("RGB"), image.convert("RGB"))
        pixel_difference_bbox = pixel_difference.getbbox()
        rendered_result["pixel_difference_bbox"] = list(pixel_difference_bbox) if pixel_difference_bbox else None
        rendered_result["pixel_difference_nonempty"] = bool(pixel_difference_bbox)
        rendered_result["pixel_evidence_hash"] = hashlib.sha256(pixel_difference.tobytes()).hexdigest() if pixel_difference_bbox else None
        if rendered_result.get("rendered") and not pixel_difference_bbox:
            rendered_result.update({"rendered": False, "selection_status": "blocked", "failure_reason": "text_overlay_has_no_pixel_evidence"})
        actual_tail = rendered_result.get("tail_rendered") or {}
        if actual_tail.get("status") == "drawn" and not rendered_result.get("rendered"):
            actual_tail.update(status="rolled_back", pixel_difference_nonempty=False, pixel_difference_bbox=None, pixel_evidence_hash=None)
            rendered_result["bubble_tail"] = copy.deepcopy(actual_tail)
        rendered_result["tail_enabled"] = bool(rendered_result.get("rendered") and actual_tail.get("status") == "drawn")
        records.append(rendered_result)
    out = Path(output_image)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, format="PNG")
    base_hash_after = hashlib.sha256(base_path.read_bytes()).hexdigest()
    page_pixel_difference = ImageChops.difference(frozen_base_pixels.convert("RGB"), image.convert("RGB"))
    page_pixel_bbox = page_pixel_difference.getbbox()
    output_hash = hashlib.sha256(out.read_bytes()).hexdigest()
    for record in records:
        if record.get("font_raster_evidence") is not None:
            record["font_raster_evidence"].update(output_image_sha256=output_hash,
                                                  base_image_sha256=base_hash_before,
                                                  retained_in_output=record.get("rendered") is True)
    rendered = [r for r in records if r.get("rendered")]
    failed = [r for r in records if not r.get("rendered") and r.get("selection_status") != "duplicate-skipped"]
    dedupe_status = "blocked" if any(r.get("dedupe_status") == "blocked" for r in records) else ("deduped" if any(r.get("dedupe_status") == "deduped" for r in records) else "clean")
    aspect_ratio = "3:4" if image.width * 4 == image.height * 3 else f"{image.width}:{image.height}"
    canvas_valid = image.width == 1080 and image.height == 1440
    placement_checked = bool(
        canvas_valid
        and (not layout_id or layout_map_validation.get("status") == "valid")
        and records
        and not failed
        and not any(r.get("avoidance", {}).get("protected_overlaps") for r in records)
        and not any(r.get("avoidance", {}).get("same_panel_geometry_overlaps") for r in records)
        and not any(r.get("avoidance", {}).get("unresolved_region_names") for r in records)
        and all(r.get("avoidance", {}).get("inside_canvas", False) for r in rendered)
        and all(r.get("actual_regions_verified") is True for r in rendered)
    )
    render_data = {
        "compositor": "douyin-simple-comic-workflow/scripts/text_compositor.py",
        "compositor_version": "0.8-measured-font-raster",
        "page_id": page_id,
        "layout_id": layout_id,
        "selected_layout": layout_id,
        "bubble_profile_id": layout_context.get("profile", {}).get("bubble_profile_id"),
        "visual_reference_only": layout_context.get("profile", {}).get("visual_reference_only", True),
        "layout_constraint_status": layout_context.get("status"),
        "layout_constraint_source": layout_context.get("source"),
        "layout_profile": layout_context.get("profile", {}),
        "layout_map_validation": layout_map_validation,
        "input_base_image": str(base_path),
        "output_image": str(out),
        "base_image_sha256_before": base_hash_before,
        "base_image_sha256_after": base_hash_after,
        "base_image_modified": base_hash_before != base_hash_after,
        "output_image_sha256": output_hash,
        "pixel_difference_bbox": list(page_pixel_bbox) if page_pixel_bbox else None,
        "pixel_difference_nonempty": bool(page_pixel_bbox),
        "pixel_evidence_hash": hashlib.sha256(page_pixel_difference.tobytes()).hexdigest() if page_pixel_bbox else None,
        "canvas": {"width": image.width, "height": image.height, "aspect_ratio": aspect_ratio, "delivery_canvas_valid": canvas_valid},
        "legacy_fields_preserved": [name for name in LEGACY_FIELDS if name in legacy_fields],
        "legacy_source_fields_read": legacy_fields,
        "dedupe_status": dedupe_status,
        "canonical_block_count": sum(1 for r in records if r.get("selection_status") != "duplicate-skipped"),
        "duplicate_block_count": sum(1 for r in records if r.get("dedupe_status") == "deduped"),
        "page_acceptance_status": "accepted" if placement_checked else "blocked",
        "rendered_blocks": records,
        "rendered_count": len(rendered),
        "unresolved_count": len(failed),
        "render_status": "generated" if rendered else "not-generated",
        "final_status": "generated" if placement_checked else "not-checked",
        "check_status": "checked" if placement_checked else "not-checked",
        "actual_image_checked": not synthetic_plan,
        "synthetic_input": synthetic_plan,
        "published": False,
        "fallback_policy": "Only an explicit, reported fallback is allowed. Missing or non-executable SB bubble profiles block placement; no silent ordinary-box fallback is permitted.",
    }
    placement_data = {
        "compositor": "douyin-simple-comic-workflow/scripts/text_compositor.py",
        "page_id": page_id,
        "layout_id": layout_id,
        "selected_layout": layout_id,
        "bubble_profile_id": layout_context.get("profile", {}).get("bubble_profile_id"),
        "layout_constraint_status": layout_context.get("status"),
        "layout_constraint_source": layout_context.get("source"),
        "layout_map_validation": layout_map_validation,
        "output_image": str(out),
        "blocks": records,
        "text_blocks_overlap": any(r.get("avoidance", {}).get("same_panel_geometry_overlaps") for r in records),
        "protected_region_occlusion": any(r.get("avoidance", {}).get("protected_overlaps") for r in records),
        "inside_canvas": all(r.get("avoidance", {}).get("inside_canvas", False) for r in rendered),
        "unresolved_blocks": [r.get("id") for r in failed],
        "unresolved_region_names": sorted({name for r in records for name in r.get("avoidance", {}).get("unresolved_region_names", [])}),
        "drawn_shape_collision_checked": True,
        "text_geometry_safety_checked": True,
        "unsafe_text_geometry_blocks": [r.get("id") for r in records if r.get("geometry_safety") and not r.get("geometry_safety", {}).get("safe")],
        "actual_regions_verified": all(r.get("actual_regions_verified") is True for r in rendered),
        "actual_image_checked": not synthetic_plan,
        "synthetic_input": synthetic_plan,
        "visual_confirmation_required": not all(r.get("actual_regions_verified") is True for r in rendered),
        "check_status": "checked" if placement_checked else "not-checked",
        "page_acceptance_status": "accepted" if placement_checked else "blocked",
        "published": False,
    }
    write_yaml(Path(render_report), render_data)
    write_yaml(Path(placement_report), placement_data)
    return render_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Compose post-layout text_blocks onto a static comic PNG.")
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--text-blocks", required=True)
    parser.add_argument("--text-layout", required=True)
    parser.add_argument("--output-image", required=True)
    parser.add_argument("--render-report", required=True)
    parser.add_argument("--placement-report", required=True)
    parser.add_argument("--page-id", default=None)
    parser.add_argument("--layout-map", default=None, help="Optional layout-to-bubble constraint map; defaults to the bundled map.")
    args = parser.parse_args()
    result = compose_page(args.base_image, args.text_blocks, args.text_layout, args.output_image, args.render_report, args.placement_report, args.page_id, args.layout_map)
    print(json.dumps({"output_image": result["output_image"], "rendered_count": result["rendered_count"], "unresolved_count": result["unresolved_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
