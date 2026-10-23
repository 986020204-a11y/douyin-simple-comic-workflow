#!/usr/bin/env python3
"""Read optional comic style presets offline; never generate art or choose SBs."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config/style-presets.json"
APPLICATION_FIELDS = ("performance", "camera", "layout", "lettering")


def load_catalog(path=None):
    catalog = json.loads(Path(path or CATALOG).read_text(encoding="utf-8-sig"))
    presets = catalog.get("presets")
    if catalog.get("schema_version") != 1 or not isinstance(presets, list) or not presets:
        raise ValueError("Invalid style preset catalog")
    aliases = {}
    identifiers = set()
    for preset in presets:
        for key in ("preset_id", "name", "prompt"):
            if not isinstance(preset.get(key), str) or not preset[key].strip():
                raise ValueError(f"Style preset needs {key}")
        if preset["preset_id"] in identifiers:
            raise ValueError(f"Duplicate style preset ID: {preset['preset_id']}")
        identifiers.add(preset["preset_id"])
        names = preset.get("aliases", [])
        if not isinstance(names, list) or any(not isinstance(n, str) or not n.strip() for n in names):
            raise ValueError("Style aliases must be nonempty strings")
        guidance = preset.get("planning_guidance", {})
        if not isinstance(guidance, dict) or any(
                not isinstance(guidance.get(k), str) or not guidance[k].strip()
                for k in ("character_design", *APPLICATION_FIELDS)):
            raise ValueError("Style preset needs character, acting, camera, layout and lettering guidance")
        preview = preset.get("preview", {})
        if not isinstance(preview, dict) or preview.get("role") != "selection_only":
            raise ValueError("Preset preview must be marked selection_only")
        relative = Path(preview.get("path", ""))
        target = (ROOT / relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(ROOT.resolve()) or not target.is_file():
            raise ValueError(f"Missing or unsafe preset preview: {relative}")
        for alias in [preset["preset_id"], preset["name"], *names]:
            token = alias.strip().casefold()
            if token in aliases and aliases[token] != preset["preset_id"]:
                raise ValueError(f"Ambiguous style alias: {alias}")
            aliases[token] = preset["preset_id"]
    return catalog


def get_preset(value, catalog=None):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("style.preset_id must be a nonempty style ID or alias")
    token = value.strip().casefold()
    for preset in (catalog or load_catalog())["presets"]:
        if token in {name.strip().casefold() for name in
                     [preset["preset_id"], preset["name"], *preset.get("aliases", [])]}:
            return copy.deepcopy(preset)
    raise ValueError(f"Unknown style preset: {value}")


def list_presets():
    catalog = load_catalog()
    return {"catalog_version": catalog["catalog_version"], "presets": [
        {"preset_id": p["preset_id"], "name": p["name"],
         "preview_path": str((ROOT / p["preview"]["path"]).resolve()),
         "preview_focus": p["preview"]["focus"]}
        for p in catalog["presets"]]}


def resolve_style(style):
    """Snapshot a selected preset; leave legacy/custom style objects intact."""
    if not isinstance(style, dict):
        raise ValueError("style must be an object")
    resolved = copy.deepcopy(style)
    if "preset_id" not in style:
        return resolved
    reserved = {"preset_snapshot", "preset_version", "preset_name", "planning_guidance"}
    if reserved.intersection(style):
        raise ValueError("New style drafts must not supply derived preset snapshot fields")
    extra = style.get("prompt", "")
    if not isinstance(extra, str):
        raise ValueError("style.prompt must be text when supplied")
    catalog = load_catalog()
    preset = get_preset(style["preset_id"], catalog)
    prompt = preset["prompt"]
    if extra.strip():
        prompt += "\n\nProject-specific style additions (explicit story requirements take priority):\n" + extra.strip()
    resolved.update({"preset_id": preset["preset_id"], "preset_name": preset["name"],
                     "preset_version": catalog["catalog_version"],
                     "preset_snapshot": preset, "planning_guidance": preset["planning_guidance"],
                     "prompt": prompt})
    resolved.setdefault("reference_paths", [])
    return resolved


def page_application(page, style):
    """Require authored page decisions, without picking geometry or rewriting text."""
    if "preset_id" not in style:
        return None
    application = page.get("style_application")
    if not isinstance(application, dict) or any(
            not isinstance(application.get(key), str) or not application[key].strip()
            for key in APPLICATION_FIELDS):
        raise ValueError(f"{page.get('page_id', '?')}: selected style requires style_application "
                         "with performance, camera, layout and lettering decisions")
    return {key: application[key].strip() for key in APPLICATION_FIELDS}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    show = commands.add_parser("show")
    show.add_argument("--preset", required=True)
    args = parser.parse_args()
    try:
        result = list_presets() if args.command == "list" else get_preset(args.preset)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
