"""Small FAST adapter to the original comic text compositor.

Only the selected page's authored/template guidance is consumed. Geometry from a
template is planning guidance; it is never reported as geometry seen in artwork.
The raster drawing and real-font fitting come from text_compositor, without its
STRICT template proof pipeline. This module performs no image generation.
"""
from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

import text_compositor as compositor


SEMANTIC_TYPES = {"narration", "dialogue", "thought", "shout", "note", "emphasis", "phone_dialogue"}
TYPE_STYLES = dict(compositor.TYPE_STYLES, note="preview_caption_note")
STYLE_TYPES = {
    "narration": {"narration_box", "preview_caption", "preview_caption_box", "preview_caption_note", "preview_vertical_note"},
    "dialogue": {"rounded_speech"}, "thought": {"thought_bubble"},
    "shout": {"shout_burst"}, "note": {"preview_caption_note", "note_embedded", "preview_vertical_note"},
    "emphasis": {"emphasis_box"}, "phone_dialogue": {"phone_dialogue"},
}


def normalized_bounds(value: Any, label: str = "bounds") -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4 or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value
    ):
        raise ValueError(f"{label}: bounds must be four finite normalized xywh numbers")
    x, y, width, height = value
    if min(x, y) < 0 or min(width, height) <= 0 or x + width > 1 + 1e-9 or y + height > 1 + 1e-9:
        raise ValueError(f"{label}: bounds must stay within the page")
    return [float(v) for v in value]


def _pixel_bounds(value: Any, size: tuple[int, int], label: str = "bounds") -> tuple[int, int, int, int]:
    x, y, w, h = normalized_bounds(value, label)
    return round(x * size[0]), round(y * size[1]), round((x + w) * size[0]), round((y + h) * size[1])


def _inside(outer: Any, inner: Any) -> bool:
    return all((outer[0] <= inner[0], outer[1] <= inner[1], outer[2] >= inner[2], outer[3] >= inner[3]))


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty identifier")
    return value


def _style(caption: dict[str, Any], kind: str) -> str:
    requested = caption.get("bubble_style")
    if not requested:
        requested = "note_embedded" if kind == "note" and caption.get("carrier_id") else TYPE_STYLES[kind]
    if requested not in STYLE_TYPES[kind]:
        raise ValueError(f"{kind}: bubble_style {requested!r} changes the source text semantics")
    return requested


def _native_align(style: str) -> str:
    return "center" if style in {"thought_bubble", "shout_burst", "emphasis_box", "preview_caption", "preview_caption_box",
                                  "preview_caption_note", "preview_vertical_note"} else "left"


def prepare_caption_plan(page: dict[str, Any], text_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make a semantic page plan; no global caption grid or layout-based retyping."""
    settings = copy.deepcopy(text_settings or {})
    settings.setdefault("font_size", 40)
    settings.setdefault("minimum_readable_font_size", 24)
    settings.setdefault("font_size_policy", "fixed")
    layout = page.get("layout") or {}
    guidance = layout.get("guidance") or {}
    panels = copy.deepcopy(guidance.get("panels") or page.get("panels") or [])
    panel_ids = [p.get("panel_id") for p in panels]
    if any(not isinstance(pid, str) or not pid.strip() for pid in panel_ids) or len(set(panel_ids)) != len(panel_ids):
        raise ValueError("caption planning needs unique authored panel_id values")
    zones = guidance.get("text_zones") or []
    captions = page.get("captions", [])
    if not isinstance(captions, list):
        raise ValueError("captions must be a list")
    result = []
    used_zone_indices: set[int] = set()
    for index, source in enumerate(captions, 1):
        if not isinstance(source, dict) or not isinstance(source.get("text"), str) or not source["text"].strip():
            raise ValueError(f"caption {index}: text must be nonempty")
        caption = copy.deepcopy(source)
        kind = caption.get("type")
        if kind not in SEMANTIC_TYPES:
            raise ValueError(f"caption {index}: unsupported source text type {kind!r}")
        panel_id = caption.get("panel_id")
        if panel_id is None and len(panel_ids) == 1:
            panel_id = panel_ids[0]
        if panel_id not in panel_ids:
            raise ValueError(f"caption {index}: an explicit panel_id belonging to this page is required")
        caption.update(caption_id=caption.get("caption_id", f"C{index:02d}"), type=kind, panel_id=panel_id,
                       source_text=source.get("source_text", source["text"]), bubble_style=_style(caption, kind))
        caption.setdefault("font_size", settings["font_size"])
        caption.setdefault("align", _native_align(caption["bubble_style"]))
        caption["font_size_policy"] = "fixed"
        caption.setdefault("placement_intention", "within authored panel; preserve faces, hands and key objects")
        if caption.get("bounds") is None:
            compatible = [(i, z) for i, z in enumerate(zones) if i not in used_zone_indices
                          and z.get("panel_id") == panel_id and z.get("bounds") is not None
                          and (not z.get("allowed_text_types") or kind in z["allowed_text_types"])]
            if not compatible:
                raise ValueError(f"caption {index}: author bounds or a compatible selected SB text zone is required")
            chosen_index, zone = compatible[0]
            used_zone_indices.add(chosen_index)
            caption["bounds"] = copy.deepcopy(zone["bounds"])
            caption["bounds_source"] = "selected_original_SB_guidance"
            caption.setdefault("placement_intention", zone.get("position", "within selected template panel"))
        else:
            caption["bounds_source"] = "authored"
        caption["bounds"] = normalized_bounds(caption["bounds"], f"caption {index}")
        _identifier(caption["caption_id"], "caption_id")
        result.append(caption)
    if len({c["caption_id"] for c in result}) != len(result):
        raise ValueError("caption_id values must be unique within a page")
    return {"schema_version": 2, "page_id": page["page_id"], "narrative_function": page.get("narrative_function", ""),
            "layout_id": layout.get("layout_id"), "panel_guidance": panels,
            "placement_review_required": True, "text_settings": settings, "captions": result}


def validate_font(font_path: Path | str) -> Path:
    path = Path(font_path).resolve()
    if not path.is_file() or path.suffix.lower() not in {".ttf", ".ttc", ".otf"}:
        raise ValueError("an explicit local TrueType/OpenType font file is required")
    try:
        ImageFont.truetype(str(path), 40)
    except (OSError, ValueError) as exc:
        raise ValueError("font is not a readable TrueType/OpenType font") from exc
    return path


def validate_image_review(review: Any, page_id: str, base_sha256: str, caption_plan: dict[str, Any],
                          size: tuple[int, int]) -> dict[str, Any]:
    """Validate caller-supplied observations; this does not detect image contents."""
    if not isinstance(review, dict) or review.get("page_id") != page_id or review.get("image_sha256") != base_sha256:
        raise ValueError("image placement review must bind this page's current base image hash")
    if review.get("geometry_observed_from_image") is not True or review.get("caption_placements_verified") is not True:
        raise ValueError("image placement review must confirm actual observed geometry and caption placements")
    observed = review.get("panels")
    if not isinstance(observed, list) or not observed:
        raise ValueError("image placement review needs actual observed panels")
    panels = {}
    for item in observed:
        if not isinstance(item, dict):
            raise ValueError("image placement review panels must be objects")
        pid = _identifier(item.get("panel_id"), "review panel_id")
        if pid in panels:
            raise ValueError("duplicate review panel_id")
        panels[pid] = _pixel_bounds(item.get("bounds"), size, f"review panel {pid}")
    needed = {c.get("panel_id") for c in caption_plan["captions"] if c.get("panel_id") is not None}
    if not needed.issubset(panels):
        raise ValueError("image placement review is missing caption-bound panels")
    protected = []
    raw_regions = review.get("protected_regions")
    if not isinstance(raw_regions, list):
        raise ValueError("image placement review must explicitly list protected_regions (empty if observed none)")
    for item in raw_regions:
        protected.append(_pixel_bounds(item.get("bounds") if isinstance(item, dict) else item, size, "protected region"))
    speakers = {}
    for item in review.get("speaker_regions", []):
        if not isinstance(item, dict):
            raise ValueError("speaker_regions entries must be objects")
        speaker_id = _identifier(item.get("speaker_id"), "speaker_id")
        pid = item.get("panel_id")
        rect = _pixel_bounds(item.get("bounds"), size, f"speaker {speaker_id}")
        if pid not in panels or not _inside(panels[pid], rect):
            raise ValueError("speaker region must be inside its confirmed observed panel")
        if (speaker_id, pid) in speakers:
            raise ValueError("duplicate speaker region")
        speakers[(speaker_id, pid)] = rect
    carriers = {}
    for item in review.get("carrier_regions", []):
        cid = _identifier(item.get("carrier_id"), "carrier_id")
        pid = item.get("panel_id")
        rect = _pixel_bounds(item.get("bounds"), size, f"carrier {cid}")
        if pid not in panels or not _inside(panels[pid], rect):
            raise ValueError("carrier must be inside its observed panel")
        carriers[(cid, pid)] = rect
    return {"panels": panels, "protected_regions": protected, "speaker_regions": speakers, "carrier_regions": carriers}


def _block(caption: dict[str, Any], size: tuple[int, int], review: dict[str, Any] | None) -> tuple[dict[str, Any], tuple[int, int, int, int]]:
    kind = caption.get("type", "narration")
    if kind not in SEMANTIC_TYPES:
        raise ValueError(f"unsupported source text type {kind!r}")
    rect = _pixel_bounds(caption.get("bounds"), size, f"caption {caption.get('caption_id')}")
    for field in ("font_size",):
        value = caption.get(field, 40)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} must be a positive integer")
    if caption.get("align", "left") not in {"left", "center", "right"}:
        raise ValueError("align must be left, center or right")
    style = _style(caption, kind)
    if caption.get("align", _native_align(style)) != _native_align(style):
        raise ValueError(f"original {style} renderer uses {_native_align(style)} alignment; move bounds for local placement")
    block = copy.deepcopy(caption)
    block.update(bubble_style=style, text_type=kind, coordinate_source="fast_authored_or_selected_SB_guidance",
                 font_size_policy="fixed", emotional_intensity="high" if kind == "shout" else "normal", tail_enabled=False)
    block["speaker"] = caption.get("speaker_id", caption.get("owner_id"))
    if caption.get("tail_requested"):
        if kind not in {"dialogue", "thought"}:
            raise ValueError("tails are only supported for confirmed dialogue or thought ownership")
        if review is not None:
            target = review["speaker_regions"].get((block["speaker"], caption.get("panel_id")))
            if target is None:
                raise ValueError("requested tail needs a confirmed speaker/owner region in the same actual panel")
            block.update(tail_enabled=True, speaker_region=list(target), speaker_region_format="xyxy")
    if block["bubble_style"] == "note_embedded":
        carrier = None if review is None else review["carrier_regions"].get((caption.get("carrier_id"), caption.get("panel_id")))
        if review is not None and (carrier is None or not _inside(carrier, rect)):
            raise ValueError("physical note needs a confirmed same-panel carrier containing its writable area")
        # Preflight tests only the planned writable area; it makes no claim of an observed carrier.
        if not caption.get("carrier_id"):
            raise ValueError("physical note requires an explicit carrier_id")
        block.update(anchor={"kind": "carrier", "carrier_id": caption["carrier_id"]},
                     carrier={"asset_id": caption["carrier_id"]})
    return block, rect


def _adapt_original_thought_contour(canvas: Image.Image, before: Image.Image, block: dict[str, Any],
                                    config: dict[str, Any], text_bounds: tuple[int, int, int, int],
                                    report: dict[str, Any]) -> None:
    """Unite the original cloud ellipses so their internal strokes cannot cut glyphs.

    This is a FAST-only repair of the existing thought renderer's silhouette.
    The protected compositor and its text fitting/font/positions stay unchanged.
    Original confirmed thought dots outside the body also remain unchanged.
    """
    x0, y0, x1, y1 = block["_render_body_rect"]
    width, height = x1 - x0, y1 - y0
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    ellipses = [(4, 12, max(70, width // 3), height - 10),
                (width // 4, 0, (width * 2) // 3, height - 8),
                ((width * 3) // 5, 10, width - 4, height - 12)]
    for ellipse in ellipses:
        mask_draw.ellipse(ellipse, fill=255)
    # A zero margin makes erosion honest where the central cloud touches its top edge.
    interior = ImageOps.expand(mask, border=3, fill=0).filter(ImageFilter.MinFilter(7)).crop(
        (3, 3, width + 3, height + 3))
    outline = ImageChops.subtract(mask, interior)
    glyphs = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    text_config = dict(config, font_size=block["font_size"], _explicit_font_size=True, font_size_policy="fixed")
    local_bounds = compositor._draw_text(ImageDraw.Draw(glyphs), block["text"],
        (12, 14, width - 12, height - 16), text_config, size=block["font_size"], align="center")
    redrawn_bounds = (local_bounds[0] + x0, local_bounds[1] + y0, local_bounds[2] + x0, local_bounds[3] + y0)
    if redrawn_bounds != tuple(text_bounds):
        raise ValueError("thought contour adaptation changed the original fixed-font text placement")
    if ImageChops.subtract(glyphs.getchannel("A"), interior).getbbox():
        raise ValueError("thought text leaves the safe cloud interior; expand or reposition its bounds locally")
    canvas.paste(before.crop((x0, y0, x1, y1)), (x0, y0))
    canvas.paste((255, 255, 255, 255), (x0, y0, x1, y1), mask)
    canvas.paste(compositor.V0_BORDER, (x0, y0, x1, y1), outline)
    canvas.alpha_composite(glyphs, (x0, y0))
    report["contour_adaptation"] = {
        "scope": "FAST_only", "method": "outer_contour_of_original_three_ellipse_union",
        "original_ellipse_geometry_retained": True, "internal_strokes_removed": True,
        "same_fixed_font_and_text_bounds": True, "glyphs_inside_cloud_interior": True,
        "border_width_px": 3}


def render_caption_plan(caption_plan: dict[str, Any], image: Image.Image, font_path: Path | str,
                        review: dict[str, Any] | None = None) -> tuple[Image.Image, list[dict[str, Any]]]:
    """Use the same original raster primitives for both preflight and final render."""
    font_path = validate_font(font_path)
    settings = caption_plan.get("text_settings") or {}
    config = dict(settings, font_file=str(font_path), font_bold_file=str(font_path), font_size_policy="fixed")
    config.setdefault("minimum_readable_font_size", 24)
    canvas = image.convert("RGBA").copy()
    draw = ImageDraw.Draw(canvas)
    layouts = []
    placed = []
    for index, caption in enumerate(caption_plan["captions"], 1):
        if not isinstance(caption, dict) or not isinstance(caption.get("text"), str) or not caption["text"].strip():
            raise ValueError(f"caption {index}: text must be nonempty")
        block, rect = _block(caption, image.size, review)
        before_thought = canvas.copy() if block["bubble_style"] == "thought_bubble" else None
        text_bounds, report = compositor._draw_block(draw, block, rect, config)
        if not report.get("rendered"):
            raise ValueError(f"caption {index}: text overflows or cannot render ({report.get('failure_reason')})")
        if before_thought is not None:
            _adapt_original_thought_contour(canvas, before_thought, block, config, text_bounds, report)
        geometry = compositor._render_geometry(block, rect, text_bounds, report["used_style"])
        safety = compositor._text_geometry_safety(block, geometry, report["used_style"])
        if not safety["safe"]:
            raise ValueError(f"caption {index}: text is outside its bubble or a connector covers text")
        canvas_rect = (0, 0, image.width, image.height)
        panel_rect = review["panels"].get(caption.get("panel_id")) if review else None
        if review is None:
            panel = next((p for p in caption_plan.get("panel_guidance", []) if p.get("panel_id") == caption.get("panel_id")), {})
            if panel.get("bounds") is not None:
                panel_rect = _pixel_bounds(panel["bounds"], image.size, "planned panel guidance")
        for part in geometry:
            bounds = tuple(part["rect"])
            if not _inside(canvas_rect, bounds):
                raise ValueError(f"caption {index}: rendered geometry leaves the page")
            if panel_rect and not _inside(panel_rect, bounds):
                raise ValueError(f"caption {index}: rendered geometry crosses its {'actual' if review else 'planned'} panel")
            if review:
                for protected in review["protected_regions"]:
                    if compositor._part_intersects_rect(part, protected):
                        raise ValueError(f"caption {index}: rendered geometry covers an observed protected region")
            for previous in placed:
                if compositor._part_intersects_rect(part, tuple(previous["rect"])):
                    raise ValueError(f"caption {index}: rendered geometry overlaps another caption")
        placed.extend(geometry)
        layouts.append({"caption_id": caption.get("caption_id", f"C{index:02d}"), "panel_id": caption.get("panel_id"),
                        "type": caption.get("type", "narration"), "speaker_id": caption.get("speaker_id"),
                        "owner_id": caption.get("owner_id"), "planned_bounds": caption["bounds"],
                        "used_style": report["used_style"], "geometry": geometry, "safety": safety,
                        "font_raster_evidence": report.get("font_raster_evidence"),
                        "fit": report.get("fit"), "tail_enabled": block.get("tail_enabled", False),
                        "geometry_evidence": "actual_image_review" if review else "planning_only",
                        "contour_adaptation": report.get("contour_adaptation"),
                        "warnings": report.get("warnings", []), "renderer": "original_text_compositor._draw_block"})
    return canvas.convert("RGB"), layouts


def preflight_caption_plan(caption_plan: dict[str, Any], font_path: Path | str,
                           canvas_size: tuple[int, int] | list[int]) -> dict[str, Any]:
    if not isinstance(canvas_size, (list, tuple)) or len(canvas_size) != 2 or any(
        isinstance(n, bool) or not isinstance(n, int) or n <= 0 for n in canvas_size
    ):
        raise ValueError("canvas_size must be two positive integers")
    font_path = validate_font(font_path)
    _, layouts = render_caption_plan(caption_plan, Image.new("RGB", tuple(canvas_size), "white"), font_path)
    return {"status": "passed", "scope": "planned_geometry_real_font_only", "canvas_size": list(canvas_size),
            "font_sha256": hashlib.sha256(font_path.read_bytes()).hexdigest(), "rendered_layouts": layouts,
            "requires_actual_image_placement_review": True}
