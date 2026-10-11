"""Reusable post-layout text compositor for douyin-simple-comic-workflow.

This module is intentionally image-based: it accepts a rendered base PNG and a
generic text_blocks plan, then emits a final PNG plus machine-readable reports.
It does not generate or modify the base artwork. The command-line interface is
the formal Skill entry point; callers can also import compose_page().
"""

from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageDraw, ImageFont


STYLE_NAMES = {
    "narration_box",
    "rounded_speech",
    "thought_bubble",
    "phone_dialogue",
    "shout_burst",
    "note_embedded",
    "emphasis_box",
}
TYPE_STYLES = {
    "narration": "narration_box",
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


def load_layout_profile(layout_id: str | None, layout_constraints: str | Path | None = None) -> dict[str, Any]:
    """Load the bundled layout-to-bubble preference for one selected SB.

    The profile is a preference/constraint layer, not a claim that the source
    SB artwork contains a unique bubble shape. Missing profiles remain
    backward-compatible: explicit block styles still work and are reported as
    having no layout-specific evidence.
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
        return {"layout_id": layout_id, "status": "loaded", "source": str(path), "profile": profile}
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
    try:
        data = load_yaml(map_path) or {}
        profiles = data.get("profiles") or []
        profile_ids = [item.get("layout_id") for item in profiles]
        if len(profiles) != 68:
            errors.append(f"bubble map profile count is {len(profiles)}, expected 68")
        if sorted(profile_ids) != expected:
            errors.append("bubble map IDs do not equal SB-001..SB-068")
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
            if item.get("source_rule_level") == "none":
                warnings.append(f"{layout_id}: no SB-specific bubble evidence; generic rules only")
    except Exception as exc:
        errors.append(f"bubble map validation error: {exc}")
    return {
        "status": "valid" if not errors else "invalid",
        "map_path": str(map_path),
        "index_path": str(layout_dir / "layouts.json"),
        "profile_count": len(profile_ids) if 'profile_ids' in locals() else 0,
        "index_count": index_count,
        "index_ids": index_ids,
        "errors": errors,
        "warnings": warnings,
        "source_boundary": "Only explicit wording in SB descriptions is source evidence; adaptation_rule is workflow-added.",
    }


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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
    for label in labels:
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
    if used_style == "note_embedded":
        carrier_rect = _carrier_polygon_rect(block) or _carrier_rect(block) or rect
        geometry.append({"part": "carrier", "rect": list(carrier_rect)})
    else:
        geometry.append({"part": "shape", "rect": list(shape_rect)})
    if used_style == "rounded_speech":
        tail = _tail_geometry(block, shape_rect)
        visible_tails = _outside_body_rects(tail, shape_rect) if tail else []
        for visible_tail in visible_tails:
            geometry.append({"part": "tail", "rect": list(visible_tail), "draw_order": "behind_body"})
    if used_style == "thought_bubble":
        dots = _thought_geometry(block, shape_rect)
        if dots:
            geometry.append({"part": "thought_connector", "rect": list(dots)})
    return geometry


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
    connector_parts = [item for item in geometry if item.get("part") in {"tail", "thought_connector"}]
    connector_text_overlaps = []
    for connector in connector_parts:
        connector_rect = _rect(connector.get("rect"), "xyxy")
        if connector_rect and any(_intersects(connector_rect, text_rect) for text_rect in text_parts):
            connector_text_overlaps.append(connector.get("part"))
    return {
        "text_inside_body": text_inside_body,
        "connector_parts_present": bool(connector_parts),
        "connector_drawn_before_text": True,
        "border_drawn_before_text": True,
        "glyph_occlusion_by_own_shape": bool(connector_text_overlaps),
        "connector_text_overlaps": connector_text_overlaps,
        "tail_hidden_attachment_clipped": used_style == "rounded_speech",
        "safe": text_inside_body and not connector_text_overlaps,
        "style": used_style,
    }


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max(1, width):
            current = candidate
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines or [""]


def _draw_text(draw: ImageDraw.ImageDraw, text: str, rect: tuple[int, int, int, int], config: dict[str, Any], *, size: int | None = None, bold: bool = False, align: str = "left") -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = rect
    padding = int(config.get("text_box_style", {}).get("padding", 22))
    requested_size = int(size or config.get("font_size", 42))
    font_size = requested_size
    min_size = max(18, requested_size // 2)
    while True:
        font = _font(config, size=font_size, bold=bold)
        lines = _wrap(draw, text, font, x1 - x0 - padding * 2)
        heights = [draw.textbbox((0, 0), line, font=font)[3] for line in lines]
        total = sum(heights) + max(0, len(lines) - 1) * 8
        if total <= max(1, (y1 - y0) - padding * 2) or font_size <= min_size:
            break
        font_size -= 2
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


def _fit_text_in_rect(draw: ImageDraw.ImageDraw, text: str, rect: tuple[int, int, int, int], config: dict[str, Any], *, size: int, bold: bool = False) -> dict[str, Any]:
    """Measure the same wrapping loop used by ``_draw_text``.

    The raster routine uses a top padding floor and then centers when there is
    room.  Carrier text therefore needs a one-sided vertical fit check against
    the actual writable rectangle, rather than the generic bubble body's
    symmetric padding rule.
    """
    padding = int(config.get("text_box_style", {}).get("padding", 22))
    requested = int(size)
    min_size = max(18, requested // 2)
    font_size = requested
    while True:
        font = _font(config, size=font_size, bold=bold)
        lines = _wrap(draw, text, font, rect[2] - rect[0] - padding * 2)
        heights = [draw.textbbox((0, 0), line, font=font)[3] for line in lines]
        total = sum(heights) + max(0, len(lines) - 1) * 8
        max_width = max((draw.textbbox((0, 0), line, font=font)[2] for line in lines), default=0)
        if total + padding <= rect[3] - rect[1] or font_size <= min_size:
            break
        font_size -= 2
    return {
        "font_size": font_size,
        "line_count": len(lines),
        "content_width": max_width,
        "content_height": total,
        "fit_ok": total + padding <= rect[3] - rect[1] and max_width + padding <= rect[2] - rect[0],
    }


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
    requested = int(size or config.get("font_size", 42))
    min_size = max(20, requested // 2)
    usable_w = max(1, x1 - x0 - padding * 2)
    usable_h = max(1, y1 - y0 - padding * 2)
    font_size = requested
    while True:
        font = _font(config, size=font_size, bold=bold)
        lines = _wrap(draw, text, font, usable_w)
        heights = [draw.textbbox((0, 0), line, font=font)[3] for line in lines]
        total_h = sum(heights) + max(0, len(lines) - 1) * 8
        if total_h <= usable_h or font_size <= min_size:
            break
        font_size -= 2
    max_line_w = max((draw.textbbox((0, 0), line, font=font)[2] for line in lines), default=0)
    desired_w = min(x1 - x0, max(min_width, max_line_w + padding * 2))
    desired_h = min(y1 - y0, max(min_height, total_h + padding * 2))
    # If the requested anchor is too short to contain the text at the minimum
    # readable size, keep the anchor and let the placement report block it.
    fit_ok = total_h + padding * 2 <= (y1 - y0) and max_line_w + padding * 2 <= (x1 - x0)
    return (x0, y0, x0 + int(desired_w), y0 + int(desired_h)), {
        "font_size": font_size,
        "line_count": len(lines),
        "fit_ok": fit_ok,
        "content_width": max_line_w,
        "content_height": total_h,
    }


def _draw_block(draw: ImageDraw.ImageDraw, block: dict[str, Any], rect: tuple[int, int, int, int], config: dict[str, Any]) -> tuple[tuple[int, int, int, int], dict[str, Any]]:
    style = block.get("bubble_style") or DEFAULT_STYLE
    result: dict[str, Any] = {"requested_style": style, "used_style": style, "fallback_used": False, "warnings": []}
    if style not in STYLE_NAMES:
        style = DEFAULT_STYLE
        result.update({"used_style": style, "fallback_used": True, "fallback_reason": "unknown_bubble_style"})
    text = str(block.get("text", ""))
    draw_config = dict(config)
    if block.get("font_size") is not None:
        draw_config["font_size"] = int(block["font_size"])

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
        carrier_fit = _fit_text_in_rect(draw, text, text_rect, draw_config, size=max(24, int(draw_config.get("font_size", 42)) - 8))
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
    compact, fit = _compact_rect(
        draw,
        text,
        rect,
        draw_config,
        size=max(26, int(draw_config.get("font_size", 42)) - 8) if style in {"phone_dialogue", "thought_bubble"} else None,
        min_width=200 if style == "phone_dialogue" else 150,
        min_height=112 if style == "phone_dialogue" else 72,
        bold=style in {"emphasis_box", "shout_burst"},
    )
    block["_render_body_rect"] = compact
    result["body_rect"] = list(compact)
    result["fit"] = fit
    if not fit["fit_ok"]:
        result.update({"selection_status": "needs-placement", "rendered": False, "failure_reason": "text_does_not_fit_anchor_at_readable_size"})
        return compact, result

    text_size = fit["font_size"]

    if style == "thought_bubble":
        speaker_rect = _rect(block.get("speaker_region"), block.get("speaker_region_format", "xywh")) if block.get("tail_enabled") else None
        text_bounds = _draw_thought(draw, compact, text, draw_config, speaker_rect, text_size=text_size)
        if speaker_rect:
            result["tail_target"] = block.get("speaker")
            result["connector"] = "thought_dots"
        else:
            result["warnings"].append("speaker_region_missing_no_thought_connector")
    elif style == "phone_dialogue":
        x0, y0, x1, y1 = compact
        draw.rounded_rectangle(compact, radius=min(20, (y1 - y0) // 2), fill=V0_FILL, outline=V0_BORDER, width=3)
        draw.ellipse((x0 + 12, y0 + 20, x0 + 40, y0 + 48), outline=V0_BORDER, width=2)
        text_bounds = _draw_text(draw, text, (x0 + 48, y0 + 6, x1 - 10, y1 - 6), draw_config, size=text_size)
    elif style == "shout_burst":
        if str(block.get("emotional_intensity", "")).lower() != "high":
            style = "rounded_speech" if block.get("speaker") else DEFAULT_STYLE
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
    result.update({"selection_status": "selected", "rendered": True, "text_bounds": list(text_bounds), "body_rect": list(compact)})
    return text_bounds, result


def _resolve_block(block: dict[str, Any], layout_context: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any], tuple[int, int, int, int] | None]:
    resolved = copy.deepcopy(block)
    layout_context = layout_context or {"layout_id": None, "status": "unavailable", "source": None, "profile": {}}
    layout_profile = layout_context.get("profile") or {}
    block_id = block.get("id")
    text = block.get("text")
    result: dict[str, Any] = {
        "id": block_id,
        "panel_id": block.get("panel_id"),
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
        "fallback_used": False,
    }
    trace: list[dict[str, Any]] = []
    if text is None or str(text) == "":
        result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "empty_or_null_text", "selection_trace": trace})
        return resolved, result, None

    semantic_type, type_reason = _text_type(block)
    trace.append({"stage": "type", "input": block.get("type"), "result": semantic_type, "reason": type_reason})
    requested_type = block.get("type")
    result["requested_type"] = requested_type
    result["type"] = semantic_type or requested_type
    if semantic_type is None:
        if requested_type not in (None, ""):
            semantic_type = "narration"
            result.update({"type": semantic_type, "selection_status": "fallback", "fallback_used": True, "fallback_reason": "unsupported_text_type"})
        else:
            result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "unsupported_text_type", "selection_trace": trace})
            return resolved, result, None
    requested_style = block.get("bubble_style")
    auto_style = requested_style in (None, "", "auto")
    type_style = TYPE_STYLES[semantic_type]
    preferred_candidates = layout_profile.get("preferred_bubble_candidates") or []
    if auto_style:
        # Layout profiles express preference, not a unique gallery shape. The
        # semantic type remains authoritative; the profile only explains why
        # the compact type-specific style was chosen for this SB.
        effective_style = type_style
        requested_style = "auto"
        style_selection_reason = "type_default_supported_by_layout_preference" if type_style in preferred_candidates else "generic_type_mapping_no_layout_specific_shape"
    else:
        effective_style = requested_style if requested_style in STYLE_NAMES else type_style
        style_selection_reason = "explicit_block_style"
    result["requested_bubble_style"] = requested_style
    fallback_reason = None
    if not auto_style and requested_style not in STYLE_NAMES:
        fallback_reason = "unknown_bubble_style"
    elif not auto_style and requested_style != TYPE_STYLES[semantic_type]:
        if not (semantic_type == "shout" and requested_style == "shout_burst"):
            effective_style = TYPE_STYLES[semantic_type]
            fallback_reason = "style_type_mismatch"
    resolved["type"] = semantic_type
    resolved["bubble_style"] = effective_style
    result["used_style"] = effective_style
    result["style_selection_reason"] = style_selection_reason
    result["layout_preference_applied"] = bool(auto_style and type_style in preferred_candidates)
    if fallback_reason:
        prior_fallback = result.get("fallback_reason")
        combined = f"{prior_fallback};{fallback_reason}" if prior_fallback and prior_fallback != fallback_reason else fallback_reason
        result.update({"fallback_used": True, "fallback_reason": combined, "selection_status": "fallback"})

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
    if speaker and speaker != "narrator" and effective_style in {"rounded_speech", "thought_bubble"} and not speaker_valid:
        if not (semantic_type == "shout" and str(block.get("emotional_intensity", "")).lower() != "high" and effective_style == "rounded_speech" and speaker_identified):
            result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "speaker_region_missing_or_invalid", "selection_trace": trace})
            return resolved, result, None
    if effective_style == "shout_burst" and str(block.get("emotional_intensity", "")).lower() != "high":
        effective_style = "rounded_speech" if speaker_identified else DEFAULT_STYLE
        resolved["bubble_style"] = effective_style
        prior_fallback = result.get("fallback_reason")
        combined = f"{prior_fallback};shout_requires_high_intensity" if prior_fallback and prior_fallback != "shout_requires_high_intensity" else "shout_requires_high_intensity"
        result.update({"used_style": effective_style, "fallback_used": True, "fallback_reason": combined, "selection_status": "fallback"})
    result["tail_target"] = speaker if effective_style == "rounded_speech" and speaker_valid else None
    resolved["speaker_status"] = "confirmed" if speaker_valid else speaker_status
    resolved["tail_enabled"] = bool(speaker_valid and effective_style in {"rounded_speech", "thought_bubble"})
    if effective_style == "thought_bubble":
        result["connector"] = "thought_dots" if speaker_valid else None
    result["tail_enabled"] = bool(speaker_valid and effective_style in {"rounded_speech", "thought_bubble"})
    trace.append({"stage": "emotional_intensity", "input": block.get("emotional_intensity"), "result": block.get("emotional_intensity") or "neutral", "reason": "high intensity required for shout_burst" if semantic_type == "shout" else "preserved type-specific style"})

    if semantic_type == "phone_dialogue":
        channel = str(block.get("channel") or "").lower()
        anchor_kind = str((block.get("anchor") or {}).get("kind") or "").lower()
        if channel not in {"telephone", "phone", "phone_channel"} and anchor_kind != "phone_channel":
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
    if semantic_type == "note" or effective_style == "note_embedded":
        if not carrier_valid:
            result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "note_carrier_missing_or_not_writable", "selection_trace": trace})
            return resolved, result, None
        resolved["bubble_style"] = "note_embedded"
        result["used_style"] = "note_embedded"
        result["carrier_id"] = carrier_id

    avoid_names = list(block.get("avoid_regions") or [])
    avoid_rects, missing_avoid, malformed_avoid, avoid_adapter = _resolved_avoid_rects(block)
    if not isinstance(block.get("avoid_region_rects") or {}, dict):
        result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "avoid_region_rects_not_mapping", "selection_trace": trace})
        return resolved, result, None
    trace.append({"stage": "whitespace_avoidance", "input": avoid_names, "result": "coordinates-resolved" if not (missing_avoid or malformed_avoid) else "needs-placement", "reason": "explicit panel coordinates supplied", "coordinate_adapter": avoid_adapter})
    if missing_avoid or malformed_avoid:
        result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "avoid_region_coordinates_missing_or_malformed", "missing_avoid_regions": missing_avoid, "malformed_avoid_regions": malformed_avoid, "selection_trace": trace})
        return resolved, result, None
    if anchor_rect is None:
        result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "anchor_rect_missing_or_ambiguous", "selection_trace": trace})
        return resolved, result, None
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
    carrier_match = block.get("bubble_style") == "note_embedded" and carrier_rect is not None and all(_contains(carrier_rect, _rect(g.get("rect"), "xyxy")) for g in geometry if g.get("part") == "text")
    overlaps = []
    overlap_parts = []
    for name, protected_rect in protected:
        for part in geometry:
            part_rect = _rect(part.get("rect"), "xyxy")
            if part_rect and _intersects(part_rect, protected_rect):
                # The carrier is an existing object in the base art; only the
                # newly drawn note text must be tested against protected areas.
                if part.get("part") == "carrier":
                    continue
                if carrier_match and part.get("part") == "text" and _contains(carrier_rect, part_rect):
                    continue
                overlaps.append(name)
                overlap_parts.append(f"{part.get('part')}:{name}")
    same_panel = []
    for previous in placed:
        if previous.get("panel_id") != block.get("panel_id"):
            continue
        for part in geometry:
            part_rect = _rect(part.get("rect"), "xyxy")
            if not part_rect:
                continue
            for old_part in previous.get("geometry", []):
                old_rect = _rect(old_part.get("rect"), "xyxy")
                if old_rect and _intersects(part_rect, old_rect):
                    same_panel.append(f"{part.get('part')}:{old_part.get('part')}:{previous.get('id')}")
    all_rects = [_rect(p.get("rect"), "xyxy") for p in geometry]
    all_rects = [r for r in all_rects if r]
    return {
        "protected_region_names": list(rects),
        "unresolved_region_names": unresolved,
        "protected_overlaps": sorted(set(overlaps)),
        "overlap_parts": sorted(set(overlap_parts)),
        "same_panel_geometry_overlaps": sorted(set(same_panel)),
        "same_panel_text_overlap": bool(same_panel),
        "inside_canvas": all(r[0] >= 0 and r[1] >= 0 and r[2] <= canvas_width and r[3] <= canvas_height for r in all_rects),
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
    raw_blocks = load_yaml(Path(text_blocks)) if isinstance(text_blocks, (str, Path)) else text_blocks
    layout_id = raw_blocks.get("layout_id") if isinstance(raw_blocks, dict) else None
    synthetic_plan = bool(raw_blocks.get("synthetic")) if isinstance(raw_blocks, dict) else False
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
    image = Image.open(base_path).convert("RGBA")
    draw = ImageDraw.Draw(image)
    records: list[dict[str, Any]] = []
    placed: list[dict[str, Any]] = []
    duplicate_groups: dict[tuple[Any, Any, Any], list[int]] = {}
    id_groups: dict[Any, list[int]] = {}
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            records.append({"id": None, "rendered": False, "selection_status": "needs-placement", "failure_reason": "block_not_mapping"})
            continue
        if block.get("id") is not None:
            id_groups.setdefault(block.get("id"), []).append(index)
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
            records.append({"id": block.get("id"), "panel_id": block.get("panel_id"), "source_field": block.get("source_field"), "source_index": block.get("source_index"), "type": block.get("type"), "text": block.get("text", ""), "rendered": False, "selection_status": "duplicate-skipped", "dedupe_status": "deduped", "duplicate_of_index": duplicate_indices[index]})
            continue
        if index in conflict_indices:
            records.append({"id": block.get("id"), "panel_id": block.get("panel_id"), "source_field": block.get("source_field"), "source_index": block.get("source_index"), "type": block.get("type"), "text": block.get("text", ""), "rendered": False, "selection_status": "needs-placement", "dedupe_status": "blocked", "failure_reason": "duplicate_id_or_source_link_conflict"})
            continue
        legacy_text = _legacy_source_text(legacy_fields, block.get("source_field"), block.get("source_index"))
        if legacy_text is not None and legacy_text != str(block.get("text", "")):
            records.append({"id": block.get("id"), "panel_id": block.get("panel_id"), "source_field": block.get("source_field"), "source_index": block.get("source_index"), "type": block.get("type"), "text": block.get("text", ""), "rendered": False, "selection_status": "needs-placement", "dedupe_status": "blocked", "failure_reason": "legacy_structured_text_conflict", "legacy_text": legacy_text})
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
        rendered_result.update(plan)
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
            )
            if unsafe:
                image = before
                draw = ImageDraw.Draw(image)
                rendered_result.update({"rendered": False, "selection_status": "needs-placement", "failure_reason": "unsafe_placement", "unsafe_content_excluded": True})
            else:
                placed.append({"id": resolved.get("id"), "panel_id": resolved.get("panel_id"), "geometry": geometry})
        else:
            # A failed fit or missing carrier must not leave a partial outline
            # or glyph on the output image.
            image = before
            draw = ImageDraw.Draw(image)
        records.append(rendered_result)
    out = Path(output_image)
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, format="PNG")
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
        "compositor_version": "0.2-draft",
        "page_id": page_id,
        "layout_id": layout_id,
        "layout_constraint_status": layout_context.get("status"),
        "layout_constraint_source": layout_context.get("source"),
        "layout_profile": layout_context.get("profile", {}),
        "layout_map_validation": layout_map_validation,
        "input_base_image": str(base_path),
        "output_image": str(out),
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
        "fallback_policy": "unknown styles and weak shout use the v0.1 narration_box fallback; an explicit weak shout speaker uses rounded_speech; missing note carriers and unsafe placement remain needs-placement",
    }
    placement_data = {
        "compositor": "douyin-simple-comic-workflow/scripts/text_compositor.py",
        "page_id": page_id,
        "layout_id": layout_id,
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
