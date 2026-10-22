#!/usr/bin/env python3
"""Compose FAST comic text locally and resume the selected caption revision.

New semantic plans reuse the original comic renderer, require placement evidence
from the actual image and preserve generation inputs/attempts. Frozen v1 runs keep
their legacy rendering behavior. Nothing in this module generates artwork.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sys
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from fast_text import (prepare_caption_plan, preflight_caption_plan, render_caption_plan,
                       validate_font, validate_image_review)


RENDERER_VERSION = "fast-caption-v2.1-original-comic-text"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _wrap(text: str, draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    """Wrap by measured glyph widths, including Chinese without word spaces."""
    def measured(value: str) -> float:
        if not value:
            return 0.0
        box = draw.textbbox((0, 0), value, font=font, anchor="lt")
        return max(float(draw.textlength(value, font=font)), float(box[2] - box[0]))

    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        current = ""
        for character in paragraph:
            if measured(current + character) <= width:
                current += character
                continue
            if not current or measured(character) > width:
                raise ValueError("a glyph is wider than the caption area")
            lines.append(current)
            current = character
        lines.append(current)
    return lines


def _caption_layout(
    caption: Any, index: int, size: tuple[int, int], draw: ImageDraw.ImageDraw, font_path: Path
) -> tuple[tuple[int, int, int, int], list[str], ImageFont.FreeTypeFont, int, str]:
    prefix = f"caption {index}"
    if not isinstance(caption, dict):
        raise ValueError(f"{prefix}: expected an object")
    text = caption.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{prefix}: text must be nonempty")
    bounds = caption.get("bounds")
    if not isinstance(bounds, list) or len(bounds) != 4 or any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
        for value in bounds
    ):
        raise ValueError(f"{prefix}: bounds must be four finite normalized numbers")
    x, y, width, height = bounds
    if min(x, y) < 0 or min(width, height) <= 0 or x + width > 1 or y + height > 1:
        raise ValueError(f"{prefix}: bounds must stay within the page")
    pixel_width, pixel_height = size
    rect = (round(x * pixel_width), round(y * pixel_height),
            round((x + width) * pixel_width), round((y + height) * pixel_height))
    padding = 12
    available_width = rect[2] - rect[0] - 2 * padding
    available_height = rect[3] - rect[1] - 2 * padding
    if min(available_width, available_height) <= 0:
        raise ValueError(f"{prefix}: caption area is too small")
    font_size = caption.get("font_size", 40)
    if isinstance(font_size, bool) or not isinstance(font_size, int) or font_size <= 0:
        raise ValueError(f"{prefix}: font_size must be a positive integer")
    align = caption.get("align", "left")
    if align not in ("left", "center", "right"):
        raise ValueError(f"{prefix}: align must be left, center or right")
    try:
        font = ImageFont.truetype(str(font_path), size=font_size)
    except (OSError, ValueError) as exc:
        raise ValueError("font is not a readable TrueType/OpenType font") from exc
    try:
        lines = _wrap(text, draw, font, available_width)
    except ValueError as exc:
        raise ValueError(f"{prefix}: {exc}") from exc
    ascent, descent = font.getmetrics()
    gap = max(4, round(font_size * 0.2))
    line_height = ascent + descent + gap
    needed_height = len(lines) * line_height - gap
    if needed_height > available_height:
        raise ValueError(f"{prefix}: text overflows {available_width}x{available_height} at font_size {font_size}")
    return rect, lines, font, line_height, align


def _compose_legacy(
    run_root: Path | str, page_id: str, font_path: Path | str, output_path: Path | str | None = None,
    caption_plan_path: Path | str | None = None,
) -> dict[str, Any]:
    """Compose one succeeded page from frozen input; never mutate generation state."""
    # Shared validation checks the frozen plan and every bound input before use.
    from fast_queue import validate_frozen

    root = Path(run_root).resolve()
    plan = validate_frozen(root)
    if not re.fullmatch(r"P\d{2,}", page_id):
        raise ValueError("page_id must look like P01")
    pages = plan.get("pages", [])
    if isinstance(pages, dict):
        page = pages.get(page_id)
    else:
        matches = [item for item in pages if isinstance(item, dict) and item.get("page_id") == page_id]
        page = matches[0] if len(matches) == 1 else None
    if not isinstance(page, dict):
        raise ValueError(f"{page_id}: page is absent or duplicated in the frozen plan")
    state = _load(root / "fast" / "state.json")
    record = state.get("pages", {}).get(page_id, {})
    if record.get("status") != "succeeded":
        raise ValueError(f"{page_id}: a succeeded base image is required")
    base_path = Path(record.get("output_path", "")).resolve()
    if not base_path.is_file() or _sha256(base_path) != record.get("image_sha256"):
        raise ValueError(f"{page_id}: base image is missing or its hash changed")
    try:
        with Image.open(base_path) as source:
            source.load()
            image = source.convert("RGB")
    except (OSError, ValueError) as exc:
        raise ValueError(f"{page_id}: base image is unreadable") from exc
    raw_caption_path = page.get("caption_plan_path")
    if not isinstance(raw_caption_path, str) or not Path(raw_caption_path).is_absolute():
        raise ValueError(f"{page_id}: an absolute frozen caption_plan_path is required")
    chosen_caption_path = Path(raw_caption_path)
    caption_plan = _load(chosen_caption_path)
    if caption_plan.get("page_id") != page_id or not isinstance(caption_plan.get("captions"), list):
        raise ValueError(f"{page_id}: invalid caption plan")
    if caption_plan_path is not None:
        revision = Path(caption_plan_path)
        revision = (revision if revision.is_absolute() else root / revision).resolve()
        revision_root = (root / "fast" / "caption-revisions").resolve()
        if not _within(revision, revision_root) or not revision.is_file():
            raise ValueError("caption revision must be a file inside this run's fast/caption-revisions directory")
        replacement = _load(revision)
        original_captions, revised_captions = caption_plan["captions"], replacement.get("captions")
        if replacement.get("page_id") != page_id or not isinstance(revised_captions, list) or len(revised_captions) != len(original_captions):
            raise ValueError("caption revision must preserve page_id and caption count")
        for original, revised in zip(original_captions, revised_captions):
            if not isinstance(original, dict) or not isinstance(revised, dict) or (
                {key: value for key, value in original.items() if key != "text"}
                != {key: value for key, value in revised.items() if key != "text"}
            ):
                raise ValueError("caption revision may change text only; keep bounds, font_size and align")
        chosen_caption_path, caption_plan = revision, replacement
    font_path = Path(font_path).resolve()
    if not font_path.is_file() or font_path.suffix.lower() not in (".ttf", ".ttc", ".otf"):
        raise ValueError("an explicit local TrueType/OpenType font file is required")
    try:
        ImageFont.truetype(str(font_path), size=40)
    except (OSError, ValueError) as exc:
        raise ValueError("font is not a readable TrueType/OpenType font") from exc
    draw = ImageDraw.Draw(image)
    layouts = [_caption_layout(item, index, image.size, draw, font_path)
               for index, item in enumerate(caption_plan["captions"], 1)]
    # Nothing is saved until every caption has passed size/bounds checks.
    for rect, lines, font, line_height, align in layouts:
        draw.rectangle((rect[0], rect[1], rect[2] - 1, rect[3] - 1), fill=(255, 255, 252))
        available_width = rect[2] - rect[0] - 24
        for index, line in enumerate(lines):
            if not line:
                continue
            box = draw.textbbox((0, 0), line, font=font, anchor="lt")
            width = max(float(draw.textlength(line, font=font)), float(box[2] - box[0]))
            offset = 0 if align == "left" else (available_width - width) / (2 if align == "center" else 1)
            draw.text((rect[0] + 12 + offset - box[0], rect[1] + 12 + index * line_height),
                      line, font=font, fill=(22, 22, 22), anchor="lt")
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")
    data = encoded.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    render_signature = hashlib.sha256(json.dumps({
        "renderer": RENDERER_VERSION, "base_sha256": record["image_sha256"],
        "font_sha256": _sha256(font_path), "caption_plan_sha256": _sha256(chosen_caption_path),
    }, sort_keys=True).encode("utf-8")).hexdigest()
    final_root = (root / "fast" / "final").resolve()
    if output_path is None:
        output = final_root / f"{page_id}-{render_signature[:16]}.png"
    else:
        output = Path(output_path)
        output = (output if output.is_absolute() else root / output).resolve()
    if not _within(output, final_root) or output == final_root or output == base_path or output.suffix.lower() != ".png":
        raise ValueError("output must be a PNG inside this run's fast/final directory")
    status = "saved"
    if output.exists():
        if not output.is_file() or output.read_bytes() != data:
            raise ValueError("final output already exists with different content; choose a new path")
        status = "skipped"
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation protects historical files even under concurrent calls.
        try:
            with output.open("xb") as destination:
                destination.write(data)
        except FileExistsError:
            if not output.is_file() or output.read_bytes() != data:
                raise ValueError("final output appeared with different content") from None
            status = "skipped"
    return {"page_id": page_id, "status": status, "output_path": str(output),
            "image_sha256": digest, "caption_count": len(layouts),
            "base_image_modified": False, "needs_human_review": True,
            "caption_plan_path": str(chosen_caption_path), "render_signature": render_signature,
            "renderer": RENDERER_VERSION}


@contextmanager
def _selection_lock(root: Path):
    """Serialise local selection changes without acquiring a generation claim."""
    path = root / "fast" / ".caption-selection.lock"
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("caption selection is busy; retry after the other local caption operation finishes") from None
    try:
        handle.write("local caption selection\n")
        handle.close()
        yield
    finally:
        handle.close()
        path.unlink(missing_ok=True)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _save_exclusive(path: Path, data: bytes) -> str:
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise ValueError("final output already exists with different content; choose a new path")
        return "skipped"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        if not path.is_file() or path.read_bytes() != data:
            raise ValueError("final output appeared with different content") from None
        return "skipped"
    return "saved"


def _validate_semantic_revision(original: dict[str, Any], replacement: dict[str, Any]) -> None:
    """Position/bubble edits cannot silently rewrite source ownership or meaning."""
    allowed_top = {"captions", "image_review", "revision_reason", "text_revision_reason"}
    if {k: v for k, v in original.items() if k not in allowed_top} != {
        k: v for k, v in replacement.items() if k not in allowed_top
    }:
        raise ValueError("caption revision must preserve the frozen page, font settings and selected SB guidance")
    source, revised = original.get("captions"), replacement.get("captions")
    if not isinstance(revised, list) or len(source) != len(revised):
        raise ValueError("caption revision must preserve caption count and reading order")
    editable = {"text", "text_revision_reason", "bounds", "bounds_source", "font_size", "align",
                "placement_intention", "bubble_style", "tail_requested"}
    for index, (before, after) in enumerate(zip(source, revised), 1):
        if not isinstance(after, dict) or {k: v for k, v in before.items() if k not in editable} != {
            k: v for k, v in after.items() if k not in editable
        }:
            raise ValueError(f"caption {index}: revision must preserve source text, semantic type, panel and speaker/owner")
        if after.get("text") != before.get("text") and not (
            after.get("text_revision_reason") or replacement.get("text_revision_reason")
        ):
            raise ValueError(f"caption {index}: changed text requires an explicit text_revision_reason")


def _selected_revision(root: Path, page_id: str, plan_hash: str, base_hash: str,
                       original_path: Path, validate_files: bool = True) -> tuple[dict[str, Any], dict[str, Any] | None]:
    path = root / "fast" / "caption-selection.json"
    manifest = _load(path) if path.is_file() else {"schema_version": 1, "pages": {}}
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("pages"), dict):
        raise ValueError("invalid caption-selection manifest")
    record = manifest["pages"].get(page_id)
    if record is None:
        return manifest, None
    if not isinstance(record, dict) or record.get("generation_plan_sha256") != plan_hash:
        raise ValueError("selected caption version is bound to a different frozen plan or base image")
    if record.get("base_image_sha256") != base_hash:
        if not validate_files:
            # An explicitly supplied revision is the only way to select text for a reviewed replacement image.
            return manifest, None
        raise ValueError("selected caption version is bound to a different frozen plan or base image")
    selected = Path(record.get("caption_plan_path", "")).resolve()
    revision_root = (root / "fast" / "caption-revisions").resolve()
    if selected != original_path and not _within(selected, revision_root):
        raise ValueError("selected caption revision must stay inside this run's caption-revisions directory")
    if not validate_files:
        return manifest, record
    if not selected.is_file() or _sha256(selected) != record.get("caption_plan_sha256"):
        raise ValueError("selected caption revision is missing or its hash changed; save a new revision explicitly")
    output = Path(record.get("output_path", "")).resolve()
    final_root = (root / "fast" / "final").resolve()
    if not _within(output, final_root) or not output.is_file() or _sha256(output) != record.get("output_sha256"):
        raise ValueError("selected final output is missing or its hash changed")
    report = record.get("layout_report_path")
    if report:
        report_path = Path(report).resolve()
        if not _within(report_path, final_root) or not report_path.is_file() or _sha256(report_path) != record.get("layout_report_sha256"):
            raise ValueError("selected caption layout report is missing or its hash changed")
    return manifest, record


def _commit_selection(root: Path, manifest: dict[str, Any], result: dict[str, Any],
                       plan_hash: str, base_hash: str, font_path: Path | None) -> None:
    record = {"generation_plan_sha256": plan_hash, "base_image_sha256": base_hash,
              "caption_plan_path": result["caption_plan_path"],
              "caption_plan_sha256": _sha256(Path(result["caption_plan_path"])),
              "output_path": result["output_path"], "output_sha256": result["image_sha256"],
              "font_path": str(font_path) if font_path is not None else None,
              "font_sha256": _sha256(font_path) if font_path is not None else None,
              "render_signature": result["render_signature"], "renderer": result["renderer"]}
    if result.get("layout_report_path"):
        record.update(layout_report_path=result["layout_report_path"],
                      layout_report_sha256=_sha256(Path(result["layout_report_path"])))
    manifest["pages"][result["page_id"]] = record
    path = root / "fast" / "caption-selection.json"
    pending = path.with_suffix(".json.pending")
    pending.write_bytes(_json_bytes(manifest))
    pending.replace(path)
    result["selection_manifest_path"] = str(path)
    result["selected_final"] = True


def _passed_visual_review(root: Path, page_id: str, record: dict[str, Any]) -> bool:
    """Read and verify the queue's current observation snapshot without changing it."""
    from fast_queue import _review_document

    if record.get("visual_review_status") != "passed" or record.get("visual_review_image_sha256") != record.get("image_sha256"):
        return False
    path_value = record.get("visual_review_path")
    if not isinstance(path_value, str):
        return False
    path = Path(path_value).resolve()
    try:
        if not _within(path, (root / "fast" / "reviews").resolve()) or not path.is_file() or _sha256(path) != record.get("visual_review_sha256"):
            return False
        _, passed, _ = _review_document(path, page_id, record["image_sha256"])
        return passed
    except (ValueError, OSError, TypeError, KeyError):
        return False


def _verify_before_selection(root: Path, page_id: str, plan_hash: str, original_record: dict[str, Any],
                             caption_path: Path, caption_hash: str, font_path: Path | None,
                             font_hash: str | None, visual_review_required: bool) -> None:
    """A concurrent image retry/review change must not select stale rendered text."""
    if _sha256(root / "fast" / "plan.json") != plan_hash:
        raise ValueError("frozen generation plan changed during local caption rendering")
    current = _load(root / "fast" / "state.json").get("pages", {}).get(page_id, {})
    if (current.get("status") != "succeeded" or current.get("image_sha256") != original_record.get("image_sha256")
            or current.get("output_path") != original_record.get("output_path")):
        raise ValueError("base image or generation state changed during local caption rendering; review the current image")
    base = Path(current.get("output_path", ""))
    if not base.is_file() or _sha256(base) != current.get("image_sha256"):
        raise ValueError("base image changed during local caption rendering")
    if visual_review_required and (
        current.get("visual_review_sha256") != original_record.get("visual_review_sha256")
        or not _passed_visual_review(root, page_id, current)
    ):
        raise ValueError("visual review changed or is no longer valid; recheck the actual image before selecting final text")
    if not caption_path.is_file() or _sha256(caption_path) != caption_hash:
        raise ValueError("caption revision changed during local rendering; save a new immutable revision")
    if font_path is not None and (not font_path.is_file() or _sha256(font_path) != font_hash):
        raise ValueError("frozen font changed during local caption rendering")


def compose(
    run_root: Path | str, page_id: str, font_path: Path | str | None = None,
    output_path: Path | str | None = None, caption_plan_path: Path | str | None = None,
) -> dict[str, Any]:
    """Render/select locally; default resumes the last verified caption version."""
    from fast_queue import validate_frozen

    root = Path(run_root).resolve()
    plan = validate_frozen(root)
    if not re.fullmatch(r"P\d{2,}", page_id):
        raise ValueError("page_id must look like P01")
    pages = plan.get("pages", [])
    matches = [item for item in pages if isinstance(item, dict) and item.get("page_id") == page_id] if isinstance(pages, list) else []
    page = (matches[0] if len(matches) == 1 else None) if isinstance(pages, list) else pages.get(page_id)
    if not isinstance(page, dict):
        raise ValueError(f"{page_id}: page is absent or duplicated in the frozen plan")
    state = _load(root / "fast" / "state.json")
    record = state.get("pages", {}).get(page_id, {})
    if record.get("status") != "succeeded":
        raise ValueError(f"{page_id}: a succeeded base image is required")
    base_path = Path(record.get("output_path", "")).resolve()
    if not base_path.is_file() or _sha256(base_path) != record.get("image_sha256"):
        raise ValueError(f"{page_id}: base image is missing or its hash changed")
    raw_caption_path = page.get("caption_plan_path")
    if not isinstance(raw_caption_path, str) or not Path(raw_caption_path).is_absolute():
        raise ValueError(f"{page_id}: an absolute frozen caption_plan_path is required")
    original_path = Path(raw_caption_path).resolve()
    original = _load(original_path)
    if original.get("page_id") != page_id or not isinstance(original.get("captions"), list):
        raise ValueError(f"{page_id}: invalid caption plan")
    semantic = original.get("schema_version", 1) >= 2
    review_required = bool(semantic and plan.get("visual_review_required"))
    if review_required and not _passed_visual_review(root, page_id, record):
        return {"page_id": page_id, "status": "pending-image-review", "selected_final": False,
                "message": "Review the actual image for character, story and storyboard execution before selecting final text.",
                "base_image_modified": False, "generation_requested": False}
    with _selection_lock(root):
        plan_hash = _sha256(root / "fast" / "plan.json")
        manifest, selected = _selected_revision(root, page_id, plan_hash, record["image_sha256"], original_path,
                                               validate_files=caption_plan_path is None)
        chosen = original_path
        if caption_plan_path is not None:
            chosen = Path(caption_plan_path)
            chosen = (chosen if chosen.is_absolute() else root / chosen).resolve()
            if not _within(chosen, (root / "fast" / "caption-revisions").resolve()) or not chosen.is_file():
                raise ValueError("caption revision must be a file inside this run's fast/caption-revisions directory")
        elif selected:
            chosen = Path(selected["caption_plan_path"])
        captions = _load(chosen)
        chosen_hash = _sha256(chosen)
        if chosen != original_path and semantic:
            _validate_semantic_revision(original, captions)
        font_binding = (original.get("text_settings") or {}).get("font_binding") or {}
        if font_path is None:
            font_path = font_binding.get("path") or (selected or {}).get("font_path")
            if font_path is None and (not semantic or captions["captions"]):
                raise ValueError("an explicit local TrueType/OpenType font file is required for a legacy run")
        font = validate_font(font_path) if font_path is not None else None
        font_hash = _sha256(font) if font is not None else None
        if semantic and captions["captions"] and (not font_binding.get("sha256") or font_hash != font_binding["sha256"]):
            raise ValueError("font hash differs from the frozen real-font preflight; use the frozen font snapshot")
        if selected and caption_plan_path is None and selected.get("font_sha256") != font_hash:
            raise ValueError("font hash differs from the selected final version")
        if not semantic:
            # Old frozen inputs remain untouched and retain their original text-only revision contract.
            result = _compose_legacy(root, page_id, font, output_path,
                                     chosen if chosen != original_path else None)
            _verify_before_selection(root, page_id, plan_hash, record, chosen, chosen_hash, font, font_hash, False)
            _commit_selection(root, manifest, result, plan_hash, record["image_sha256"], font)
            return result
        review = captions.get("image_review")
        if captions["captions"] and review is None:
            return {"page_id": page_id, "status": "pending-placement", "selected_final": False,
                    "message": "View the current base image and save actual panel, protected-region and speaker observations in a caption revision.",
                    "base_image_modified": False, "generation_requested": False}
        try:
            with Image.open(base_path) as source:
                source.load()
                image = source.convert("RGB")
        except (OSError, ValueError) as exc:
            raise ValueError(f"{page_id}: base image is unreadable") from exc
        observed = validate_image_review(review, page_id, record["image_sha256"], captions, image.size) if review is not None else None
        rendered, layouts = render_caption_plan(captions, image, font, observed) if captions["captions"] else (image.copy(), [])
        encoded = io.BytesIO()
        rendered.save(encoded, format="PNG")
        data = encoded.getvalue()
        signature = hashlib.sha256(json.dumps({"renderer": RENDERER_VERSION, "base_sha256": record["image_sha256"],
                      "font_sha256": font_hash, "caption_plan_sha256": chosen_hash}, sort_keys=True).encode()).hexdigest()
        final_root = (root / "fast" / "final").resolve()
        output = final_root / f"{page_id}-{signature[:16]}.png" if output_path is None else Path(output_path)
        output = (output if output.is_absolute() else root / output).resolve()
        if not _within(output, final_root) or output == final_root or output == base_path or output.suffix.lower() != ".png":
            raise ValueError("output must be a PNG inside this run's fast/final directory")
        report_path = output.with_suffix(".layout.json")
        report = {"page_id": page_id, "renderer": RENDERER_VERSION, "generation_plan_sha256": plan_hash,
                  "base_image_sha256": record["image_sha256"], "caption_plan_path": str(chosen),
                  "caption_plan_sha256": chosen_hash, "font_sha256": font_hash,
                  "image_size": list(image.size), "rendered_layouts": layouts,
                  "image_review_method": "caller_observation_of_current_base_image", "automatic_detection": False}
        result = {"page_id": page_id, "status": _save_exclusive(output, data), "output_path": str(output),
                  "image_sha256": hashlib.sha256(data).hexdigest(), "caption_count": len(layouts),
                  "base_image_modified": False, "needs_human_review": True, "generation_requested": False,
                  "caption_plan_path": str(chosen), "render_signature": signature, "renderer": RENDERER_VERSION,
                  "layout_report_path": str(report_path), "rendered_layouts": layouts}
        _save_exclusive(report_path, _json_bytes(report))
        _verify_before_selection(root, page_id, plan_hash, record, chosen, chosen_hash, font, font_hash, review_required)
        _commit_selection(root, manifest, result, plan_hash, record["image_sha256"], font)
        return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--font", type=Path, help="frozen snapshot for new plans; explicit font required for legacy runs")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--caption-plan", type=Path, help="local semantic/position revision inside fast/caption-revisions")
    args = parser.parse_args()
    try:
        result = compose(args.run_root, args.page_id, args.font, args.output, args.caption_plan)
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
