#!/usr/bin/env python3
"""Freeze an agent-authored FAST plan offline; never generate story artwork."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from PIL import Image
import yaml

import fast_storyboard
import fast_style

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "references/comic-layouts"
DEFAULT_CONFIG = ROOT / "config/fast.json"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping: {path}")
    return value


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _source_path(value, base):
    path = Path(value)
    path = (path if path.is_absolute() else base / path).resolve()
    if not path.is_file():
        raise ValueError(f"Missing input file: {path}")
    return path


def _pool():
    return fast_storyboard.load_pool(LIBRARY)


def shortlist(query="", limit=5):
    """Small machine-ranked view; never dump all SB rules into model context."""
    return fast_storyboard.shortlist(query, limit, LIBRARY)


def page_character_cards(page, characters):
    """Use explicit page membership, never guess which visual actors to omit."""
    if "character_ids" not in page:
        return characters  # Old drafts retain their original prompt/reference behavior.
    selected = page["character_ids"]
    known = {c["character_id"] for c in characters}
    if (not isinstance(selected, list) or any(not isinstance(cid, str) for cid in selected)
            or len(set(selected)) != len(selected) or set(selected) - known):
        raise ValueError(f"{page['page_id']}: character_ids must contain unique existing character IDs")
    owners = {caption.get(key) for caption in page.get("captions", []) if isinstance(caption, dict)
              for key in ("speaker_id", "owner_id") if isinstance(caption.get(key), str)} & known
    if owners - set(selected):
        raise ValueError(f"{page['page_id']}: character_ids omits a dialogue/thought owner: {sorted(owners - set(selected))}")
    return [c for c in characters if c["character_id"] in selected]


def _prompt_parts(values):
    """Deduplicate exact authored text only; never infer synonyms or truncate."""
    result = []
    for value in values:
        if isinstance(value, str) and value.strip() and value.strip() not in result:
            result.append(value.strip())
    return result


def _prompt_bounds(bounds):
    return "xywh=" + json.dumps(bounds, ensure_ascii=False, separators=(",", ":"))


def build_generation_prompt(page, style, characters):
    """Project frozen planning into image instructions, not serialized records.

    The authored shared and page prompts remain intact. Only known image-facing
    fields enter this projection; complete cards, storyboards and caption plans
    are still frozen separately. Reference instructions are added by claim_page
    when actual references exist, including a dynamically reused first page.
    """
    sections = [style["prompt"].strip()]
    cards = []
    for character in characters:
        # Do not expose reference paths, provenance or arbitrary private notes.
        details = _prompt_parts(character.get(key) for key in
                                ("description", "appearance", "wardrobe", "visual_notes"))
        cards.append(character["character_id"] + ": " + "; ".join(details))
    if cards:
        sections.append("Characters:\n" + "\n".join(cards))
    layout = page.get("layout")
    if layout:
        mechanism = layout["prompt"].strip()
        # Remove only the exact stock scaffold from bundled SB notes.
        mechanism = mechanism.removeprefix("Comic storyboard. Layout: ")
        mechanism = mechanism.removesuffix(
            " Let this storyboard mechanism determine the page structure, reading flow, panel hierarchy, "
            "and pacing; output a complete single-page comic where panels tell a continuous story with "
            "consistent characters.")
        sections.append("Layout (approximate): " + mechanism)
    if "preset_id" in style:
        application = page["style_application"]
        decisions = _prompt_parts(application[key] for key in ("performance", "camera", "layout"))
        sections.append("Page direction: " + "; ".join(decisions))
    regions = {region["panel_id"]: region for region in
               layout["guidance"]["panels"]} if layout else {}
    panel_lines = []
    for panel in page["panels"]:
        region = regions.get(panel["panel_id"], panel)
        position = " " + _prompt_bounds(region["bounds"]) if region.get("bounds") else ""
        details = _prompt_parts(panel.get(key) for key in
                                ("visual", "description", "main_action_or_emotion", "focus", "camera"))
        shape = region.get("geometry_type")
        if shape and shape != "rect":
            position += " " + str(shape)
        panel_lines.append(panel["panel_id"] + position + ": " + "; ".join(details))
    sections.append("Panels in reading order (normalized xywh):\n" + "\n".join(panel_lines))
    sections.append(page["prompt"].strip())
    if page["captions"]:
        reservations = []
        for caption in page["captions"]:
            owners = _prompt_parts(caption.get(key) for key in ("speaker_id", "owner_id", "speaker"))
            row = caption["panel_id"] + " " + _prompt_bounds(caption["bounds"])
            if owners:
                row += " owner=" + "/".join(owners)
            intention = caption.get("placement_intention")
            if isinstance(intention, str) and intention.strip():
                row += ": " + intention.strip()
            reservations.append(row)
        sections.append("Reserve quiet space for local lettering; keep faces, hands and key objects clear:\n"
                        + "\n".join(reservations))
    sections.append("Generate one complete portrait 3:4 comic page with consistent characters and style. "
                    "No text, letters, numbers, labels, logos, watermarks, speech bubbles or caption boxes; "
                    "lettering is added locally.")
    return "\n\n".join(sections) + "\n"


def check_caption_band_policy(page, shared_prompt=""):
    """Catch explicit blanket footer instructions locally, not visual quality."""
    prompt = shared_prompt + "\n" + page["prompt"]
    def affirmative(match):
        prefix = prompt[max(0, match.start()-20):match.start()]
        return not re.search(r"(?:do\s+not|don't|never|avoid|不要|禁止|避免|勿)\s*$", prefix, re.I)
    blanket = re.search(
        r"\breserve\b[^.!?\n]{0,70}\b(?:empty|blank)\s+lower\s+caption\s+zone\b"
        r"[^.!?\n]{0,45}\b(?:each|every)\s+panel\b", prompt, re.I)
    if blanket and not affirmative(blanket):
        blanket = None
    repeated = [match for match in re.finditer(
        r"\bkeep\s+(?:its|the)\s+lower\s+\d+(?:\.\d+)?\s*(?:percent|%)\s+"
        r"(?:completely\s+)?(?:empty|blank)\b", prompt, re.I) if affirmative(match)]
    chinese = re.search(
        r"(?:每一格|每格|每个画格|所有画格)的?(?:底部|下方|下半部)(?:都|统一)?"
        r"(?:预留|留出|保留)[^。！？\n]{0,20}(?:空白|字幕区|文字区)", prompt)
    if chinese and re.search(r"(?:不要|禁止|避免|勿)[^。！？\n]{0,8}$", prompt[max(0, chinese.start()-15):chinese.start()]):
        chinese = None
    uniform = len(page["panels"]) > 1 and len(repeated) >= len(page["panels"])
    reason = page.get("caption_band_reason")
    if (blanket or chinese or uniform) and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError(f"{page['page_id']}: uniform lower caption bands need a page-specific caption_band_reason "
                         "from narrative intent or the user's requested format; otherwise plan text with the scene")


def _text_settings(draft, base, pages, fast):
    settings = copy.deepcopy(draft.get("text_settings", {}))
    if not isinstance(settings, dict):
        raise ValueError("text_settings must be an object")
    settings.setdefault("font_size", 40)
    if isinstance(settings["font_size"], bool) or not isinstance(settings["font_size"], int) or settings["font_size"] <= 0:
        raise ValueError("text_settings.font_size must be a positive integer")
    settings.setdefault("canvas_size", [1080, 1440])
    size = settings["canvas_size"]
    if (not isinstance(size, list) or len(size) != 2
            or any(type(value) is not int or value <= 0 for value in size)
            or size[0] * 4 != size[1] * 3):
        raise ValueError("text_settings.canvas_size must be positive 3:4 integer dimensions")
    needs_font = any(page.get("captions") for page in pages)
    font = settings.get("font_path")
    if font:
        source = _source_path(font, base)
    elif needs_font:
        source = next((Path(value) for value in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                      "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc") if Path(value).is_file()), None)
        if source is None:
            raise ValueError("Nonempty captions need an explicit local Chinese TrueType/OpenType font in text_settings.font_path")
    else:
        return settings, None
    if source.suffix.lower() not in {".ttf", ".ttc", ".otf"}:
        raise ValueError("text_settings.font_path must be a local TrueType/OpenType font")
    sha = digest(source)
    destination = fast / "fonts" / f"{sha}{source.suffix.lower()}"
    settings.update({"font_path": str(destination), "font_sha256": sha,
                     "font_binding": {"path": str(destination), "sha256": sha}})
    return settings, source


def prepare(plan_path, run_root, simulation=False):
    """Persist one authored plan; existing frozen runs resume without rereading the story."""
    from fast_queue import init_queue, status
    from fast_caption import prepare_caption_plan, preflight_caption_plan

    run_root = Path(run_root).resolve()
    fast = run_root / "fast"
    frozen = fast / "plan.json"
    if frozen.exists():
        # status revalidates frozen local inputs and images, never the original draft/source.
        return status(run_root) if (fast / "state.json").exists() else init_queue(run_root)
    if run_root.exists() and any(run_root.iterdir()):
        raise ValueError("FAST preparation requires a new empty run directory; existing projects are preserved")
    plan_path = Path(plan_path).resolve()
    draft = load(plan_path)
    if draft.get("mode", "fast").lower() != "fast":
        raise ValueError("Use the unchanged STRICT workflow for strict requests")
    if draft.get("requires_exact_layout") or draft.get("requires_exact_bubbles"):
        raise ValueError("Exact panels/bubble positions require STRICT; FAST cannot certify exact geometry")
    source = _source_path(draft["source_path"], plan_path.parent)
    analysis, characters = draft.get("analysis"), draft.get("characters")
    style = fast_style.resolve_style(draft.get("style"))
    pages = copy.deepcopy(draft.get("pages"))
    if not isinstance(analysis, dict) or not analysis:
        raise ValueError("Save the one-time story analysis in analysis")
    if not isinstance(characters, list) or any(not isinstance(c, dict) for c in characters):
        raise ValueError("characters must be a list of cards (empty allowed for no characters)")
    ids = [c.get("character_id") for c in characters]
    if any(not isinstance(c, str) or not c.strip() for c in ids) or len(set(ids)) != len(ids):
        raise ValueError("Character cards need unique nonempty character_id values")
    if not isinstance(style, dict) or not isinstance(style.get("prompt"), str) or not style["prompt"].strip():
        raise ValueError("style.prompt must contain the reusable visual specification")
    if not isinstance(pages, list) or not pages or any(not isinstance(page, dict) for page in pages):
        raise ValueError("pages must be a nonempty list")
    page_ids = [p.get("page_id") for p in pages]
    if any(not isinstance(pid, str) or not re.fullmatch(r"P\d{2,}", pid) for pid in page_ids) or len(set(page_ids)) != len(page_ids):
        raise ValueError("Pages need unique P## IDs in story order")
    # Validate all drafts and reference files before creating a run.
    references = {}
    for owner in [*characters, style, *pages]:
        refs = owner.get("reference_paths", [])
        if not isinstance(refs, list):
            raise ValueError("reference_paths must be a list")
        for ref in refs:
            path = _source_path(ref, plan_path.parent)
            with Image.open(path) as img:
                img.verify()
            with Image.open(path) as img:
                img.load()
            references[str(path)] = (digest(path), path.suffix.lower())
    for page in pages:
        application = fast_style.page_application(page, style)
        if application is not None:
            page["style_application"] = application
        if not isinstance(page.get("panels"), list) or not page["panels"]:
            raise ValueError(f"{page['page_id']}: ordered panels/story units are required")
        if not isinstance(page.get("prompt"), str) or not page["prompt"].strip():
            raise ValueError(f"{page['page_id']}: final page prompt is required")
        page_character_cards(page, characters)
        check_caption_band_policy(page, style["prompt"])
    decision = fast_storyboard.select_pages({**draft, "pages": pages}, _pool(), LIBRARY)
    pages = decision["pages"]
    text_settings, font_source = _text_settings(draft, plan_path.parent, pages, fast)
    # Check actual-font capacity before creating a run or allowing a generation
    # claim. Existing frozen runs return above without touching their inputs.
    for page in pages:
        captions = page.get("captions", [])
        if not isinstance(captions, list):
            raise ValueError(f"{page['page_id']}: captions must be a list")
        if any(not isinstance(c, dict) or not isinstance(c.get("type"), str) or not c["type"].strip() for c in captions):
            raise ValueError(f"{page['page_id']}: new caption plans need explicit text type; geometry must not invent dialogue")
        page["caption_plan"] = prepare_caption_plan(page, text_settings)
        if "preset_id" in style:
            page["caption_plan"]["style_application"] = {
                "preset_id": style["preset_id"], "lettering": page["style_application"]["lettering"]}
        if captions:
            page["caption_plan"]["capacity_preflight"] = preflight_caption_plan(
                page["caption_plan"], font_source, tuple(text_settings["canvas_size"]))
        page["captions"] = page["caption_plan"]["captions"]

    config = load(DEFAULT_CONFIG)
    if config.get("mode") != "fast" or config.get("generator") != "codex.image_gen" or config.get("max_attempts") != 2:
        raise ValueError("FAST config must use builtin codex.image_gen and at most two attempts")
    config["simulation"] = bool(simulation)
    fast.mkdir(parents=True)
    if font_source is not None:
        font_dest = Path(text_settings["font_path"])
        font_dest.parent.mkdir()
        shutil.copyfile(font_source, font_dest)
    source_dest = run_root / "source/article.md"
    source_dest.parent.mkdir()
    shutil.copyfile(source, source_dest)
    ref_bindings = {}
    for original, (sha, extension) in references.items():
        dest = fast / "references" / f"{sha}{extension}"
        dest.parent.mkdir(exist_ok=True)
        if not dest.exists():
            shutil.copyfile(original, dest)
        ref_bindings[original] = {"path": str(dest), "sha256": sha}

    def resolve_refs(owner):
        return [ref_bindings[str(_source_path(ref, plan_path.parent))] for ref in owner.get("reference_paths", [])]

    for owner in [*characters, style]:
        owner["reference_paths"] = [b["path"] for b in resolve_refs(owner)]
    rows = []
    storyboard = []
    for page in pages:
        pid = page["page_id"]
        current_characters = page_character_cards(page, characters)
        shared = [*style["reference_paths"],
                  *[ref for character in current_characters for ref in character["reference_paths"]]]
        refs = list(dict.fromkeys([*shared, *[b["path"] for b in resolve_refs(page)]]))
        bindings = [{"path": path, "sha256": digest(path)} for path in refs]
        layout = page["layout"]
        storyboard.append({"page_id": pid, "panels": page["panels"], "panel_count": len(page["panels"]),
                           "layout_id": page["layout_id"], "layout": layout,
                           "selection_reason": page["selection_reason"],
                           "selection_evidence": page["selection_evidence"],
                           "narrative_function": page["narrative_function"],
                           "panel_count_reason": page["panel_count_reason"],
                           "text_design": page["captions"]})
        if "character_ids" in page:
            storyboard[-1]["character_ids"] = list(page["character_ids"])
        if page.get("caption_band_reason"):
            storyboard[-1]["caption_band_reason"] = page["caption_band_reason"]
        if "preset_id" in style:
            storyboard[-1]["style_application"] = page["style_application"]
        prompt = build_generation_prompt(page, style, current_characters)
        prompt_path = fast / "prompts" / f"{pid}.txt"
        prompt_path.parent.mkdir(exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        caption_path = fast / "captions" / f"{pid}.json"
        write(caption_path, page["caption_plan"])
        rows.append({"page_id": pid, "prompt_path": str(prompt_path), "prompt_sha256": digest(prompt_path),
                     "reference_bindings": bindings, "caption_plan_path": str(caption_path),
                     "caption_plan_sha256": digest(caption_path),
                     "output_dir": str(fast / "images")})
    for name, value in (("analysis", analysis), ("characters", characters), ("style", style),
                        ("text-settings", text_settings),
                        ("storyboard", {"pages": storyboard, "rhythm_audit": decision["rhythm_audit"],
                                        "selection_policy": decision["selection_policy"]})):
        write(fast / "planning" / f"{name}.json", value)
    write(fast / "config.json", config)
    local_inputs = [source_dest, fast / "config.json", *sorted((fast / "planning").glob("*.json")),
                    *sorted((fast / "prompts").glob("*.txt")), *sorted((fast / "captions").glob("*.json")),
                    *sorted((fast / "references").glob("*")), *sorted((fast / "fonts").glob("*"))]
    frozen_plan = {"schema_version": 1, "mode": "fast", "simulation": bool(simulation),
                   "max_attempts": 2, "first_page_id": page_ids[0], "reuse_first_page_reference": True,
                   "semantic_planning_version": 1, "visual_review_required": True,
                   "first_final_review_required": bool(config.get("first_final_review_required", True)
                                                       and pages[0]["caption_plan"]["captions"]),
                   "text_settings": text_settings,
                   "input_bindings": [{"path": str(p), "sha256": digest(p)} for p in local_inputs],
                   "pages": rows}
    write(frozen, frozen_plan)  # Commit marker; never rewrite this plan when resuming.
    return init_queue(run_root)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--plan", type=Path, required=True)
    prep.add_argument("--run-root", type=Path, required=True)
    prep.add_argument("--simulation", action="store_true", help="Offline test fixture only; never a production image")
    layouts = commands.add_parser("layouts")
    layouts.add_argument("--query", default="")
    layouts.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    try:
        result = ({"layouts": shortlist(args.query, args.limit)} if args.command == "layouts"
                  else prepare(args.plan, args.run_root, args.simulation))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
