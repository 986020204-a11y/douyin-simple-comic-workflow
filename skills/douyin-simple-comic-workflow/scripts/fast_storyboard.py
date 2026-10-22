#!/usr/bin/env python3
"""Lightweight, narrative-led selection from the original 68 bundled SBs.

This module reads the two small library indexes, then ONLY selected SB sources.
It does not compile STRICT contracts, prove geometry, or generate artwork.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import re

import yaml


LIBRARY = Path(__file__).resolve().parents[1] / "references/comic-layouts"
NEAR_SCORE_GAP = 2
COMPLEX_MARKERS = ("polygon", "curved", "spiral", "inset", "nested", "breakout",
                   "cross_panel", "continuous_character", "shared_canvas", "physical_carrier",
                   "perspective", "typographic_overlay", "organic_unframed", "layered_page")


def _text(value, minimum=1):
    return isinstance(value, str) and len(re.sub(r"\s+", "", value)) >= minimum


def _reason(value):
    if not _text(value, 8):
        return False
    compact = re.sub(r"\s+", "", value).lower()
    return compact not in {"todotodo", "待补充待补充", "同上同上同上", "继续沿用既有模板"}


def normalized_bounds(value):
    return (isinstance(value, list) and len(value) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value)
            and min(value[:2]) >= 0 and min(value[2:]) > 0
            and value[0] + value[2] <= 1 and value[1] + value[3] <= 1)


def load_pool(library_root=None):
    """Read metadata only; no all-template imports, filesystem walks or proof scans."""
    root = Path(library_root) if library_root is not None else LIBRARY
    pool = json.loads((root / "layouts.json").read_text(encoding="utf-8-sig"))
    if (not isinstance(pool, list) or len(pool) != 68
            or {p.get("id") for p in pool} != {f"SB-{i:03d}" for i in range(1, 69)}
            or any(p.get("category") != "comic-storyboard" for p in pool)):
        raise ValueError("Bundled SB index must contain the original 68 unique comic-storyboard layouts")
    return pool


def _template_index(root):
    value = yaml.safe_load((root / "template-index.yaml").read_text(encoding="utf-8-sig"))
    entries = value.get("templates", []) if isinstance(value, dict) else []
    index = {item.get("layout_id"): item for item in entries if isinstance(item, dict)}
    if len(index) != 68 or set(index) != {f"SB-{i:03d}" for i in range(1, 69)}:
        raise ValueError("Bundled template metadata must index all 68 original SBs")
    return index


def _tokens(value):
    """Use the original prompt_style semantic matching, without its compiler."""
    value = (value or "").lower()
    result = set(re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", value))
    for n in (2, 3, 4):
        result.update(value[i:i+n] for i in range(max(0, len(value)-n+1)) if value[i:i+n].strip())
    return result


def layout_score(item, narrative_function, content=""):
    hay = " ".join([item.get("name", ""), item.get("name_en", ""),
                     " ".join(item.get("keywords", [])), item.get("layout_structure", "")])
    score = len(_tokens(f"{narrative_function} {content}") & _tokens(hay))
    for phrase in (narrative_function, content):
        if phrase and phrase in hay:
            score += 12
    return score


def shortlist(query="", limit=5, library_root=None):
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 8:
        raise ValueError("Shortlist limit must be 1..8")
    root = Path(library_root) if library_root is not None else LIBRARY
    index = _template_index(root)
    ranked = sorted(load_pool(root), key=lambda p: (-layout_score(p, query), p["id"]))[:limit]
    return [{**{key: item[key] for key in ("id", "name", "panel_count", "layout_structure")},
             "native_panel_count": index[item["id"]]["panel_count"],
             "fast_compatibility": compatibility(index[item["id"]])} for item in ranked]


def _mechanisms(value):
    if isinstance(value, dict):
        return _mechanisms(value.get("required_mechanisms", []))
    if not isinstance(value, list):
        return []
    return [item if isinstance(item, str) else str(item.get("feature", item.get("mechanism", "")))
            for item in value if isinstance(item, (str, dict))]


def compatibility(entry):
    mechanisms = _mechanisms(entry.get("required_mechanisms", []))
    complex_features = [feature for feature in mechanisms
                        if any(marker in feature for marker in COMPLEX_MARKERS)]
    return {"level": "approximate_complex_requires_review" if complex_features else "approximate_simple",
            "native_panel_count": entry["panel_count"], "complex_features": complex_features,
            "text_treatment_limitations": copy.deepcopy(entry.get("text_renderer_preflight_blockers", [])),
            "pixel_exact": False, "actual_image_review_required": True,
            "policy": "Use the original narrative relationships as a whole-page visual guide; exact geometry requires STRICT."}


def _validate_page(page):
    pid = page.get("page_id")
    if not _text(page.get("narrative_function"), 4):
        raise ValueError(f"{pid}: narrative_function must state this page's story/emotion purpose")
    if not _reason(page.get("panel_count_reason")):
        raise ValueError(f"{pid}: panel_count_reason must explain the number of real story units")
    panels = page.get("panels")
    if not isinstance(panels, list) or not panels:
        raise ValueError(f"{pid}: ordered panels/story units are required")
    seen = set()
    for number, panel in enumerate(panels, 1):
        if not isinstance(panel, dict) or any(not _text(panel.get(key)) for key in ("focus", "main_action_or_emotion")):
            raise ValueError(f"{pid}: each panel needs focus and one main_action_or_emotion")
        panel.setdefault("panel_id", f"U{number:02d}")
        if not _text(panel["panel_id"]) or panel["panel_id"] in seen:
            raise ValueError(f"{pid}: panel_id must be unique and nonempty within a page")
        seen.add(panel["panel_id"])
        if "bounds" in panel and not normalized_bounds(panel["bounds"]):
            raise ValueError(f"{pid}/{panel['panel_id']}: bounds must be normalized in-canvas xywh")
    if "panel_count" in page and page["panel_count"] != len(panels):
        raise ValueError(f"{pid}: panel_count disagrees with actual planned story units")
    page["panel_count"] = len(panels)


def _selected_layout(item, entry, page, root, cache):
    lid = item["id"]
    if lid not in cache:
        prompt_path = root / item.get("prompt_file", f"{lid}.md")
        template_path = root / entry["template_path"]
        if (prompt_path.parent.resolve() != root.resolve()
                or root.resolve() not in template_path.resolve().parents):
            raise ValueError("Selected SB source must remain inside the bundled library")
        note = prompt_path.read_text(encoding="utf-8-sig").split("<!-- en -->", 1)[-1].strip()
        template = yaml.safe_load(template_path.read_text(encoding="utf-8-sig"))
        if not isinstance(template, dict) or template.get("layout_id") != lid:
            raise ValueError(f"Selected executable template identity mismatch: {lid}")
        cache[lid] = (note, template, prompt_path, template_path)
    note, template, prompt_path, template_path = cache[lid]
    native = template.get("panels") or (template.get("structure") or {}).get("units") or []
    native = sorted(native, key=lambda p: p.get("order", 0))
    if len(native) != entry["panel_count"]:
        raise ValueError(f"{lid}: selected template count differs from the lightweight index")
    adapted = len(native) != len(page["panels"])
    mapped = []
    mapping = {}
    for number, panel in enumerate(page["panels"]):
        original = native[number] if not adapted else {}
        mapping[original.get("panel_id")] = panel["panel_id"]
        region = {"panel_id": panel["panel_id"], "order": number + 1,
                  "source_panel_id": original.get("panel_id"), "approximate": True}
        if "bounds" in panel:
            region.update({"bounds": copy.deepcopy(panel["bounds"]), "bounds_source": "authored_page_plan"})
        elif normalized_bounds(original.get("bounds")):
            region.update({"bounds": copy.deepcopy(original["bounds"]), "bounds_source": "selected_template_visual_guide"})
        region["geometry_type"] = panel.get("geometry_type", original.get("geometry_type", "rect"))
        mapped.append(region)
    zones = []
    if not adapted:
        for source in [*(template.get("bubbles") or []), *(template.get("text_zones") or [])]:
            if not normalized_bounds(source.get("bounds")):
                continue
            source_panel = source.get("panel_id", source.get("canvas_binding_id"))
            target_panel = mapping.get(source_panel)
            if target_panel is None and source_panel in {"CANVAS", "canvas"}:
                target_panel = "CANVAS"
            if target_panel is None:
                continue
            # Source-example speakers are not the current story. Never copy their tails.
            zone = {key: copy.deepcopy(source[key]) for key in
                    ("bounds", "shape", "position", "allowed_text_types", "avoid", "visual_style") if key in source}
            zone.update({"zone_id": source.get("bubble_id", source.get("zone_id")), "panel_id": target_panel,
                         "source_panel_id": source_panel, "approximate": True,
                         "source_tail_removed": True, "tail_required": bool((source.get("tail") or {}).get("required"))})
            zones.append(zone)
    result = {"layout_id": lid, "layout_name": item["name"],
              "layout_source": "bundled-internal-comic-layouts", "match_policy": "fast_visual_guide",
              "source_path": str(prompt_path), "source_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
              "template_path": str(template_path), "template_sha256": hashlib.sha256(template_path.read_bytes()).hexdigest(),
              "prompt": note, "fast_compatibility": compatibility(entry),
              "guidance": {"panels": mapped, "text_zones": zones, "approximate": True,
                           "source": "selected_original_executable_template",
                           "source_canvas": copy.deepcopy(template.get("canvas", {})),
                           "target_policy": "Normalized planning guide for 3:4; actual image positions require local review."}}
    if isinstance(page.get("layout_adaptation"), dict):
        result["adaptation"] = copy.deepcopy(page["layout_adaptation"])
    if adapted:
        result["guidance"]["source"] = "authored_adaptation_of_selected_original_template"
    return result


def _audit_repetition(document, pages):
    ids = [page["layout_id"] for page in pages]
    runs = []
    start = 0
    for end in range(1, len(ids) + 1):
        if end == len(ids) or ids[end] != ids[start]:
            if end - start >= 3 or (start == 0 and end == len(ids) and len(ids) >= 2):
                runs.append((start, end, ids[start]))
            start = end
    policy = document.get("layout_policy", "narrative_variety")
    if policy not in {"narrative_variety", "uniform_by_user_request"}:
        raise ValueError("layout_policy must be narrative_variety or uniform_by_user_request")
    request = document.get("uniform_layout_request")
    if policy == "uniform_by_user_request":
        if not isinstance(request, dict) or request.get("source") != "user" or not _text(request.get("instruction_excerpt")):
            raise ValueError("Uniform layout requires the actual user instruction in uniform_layout_request")
    justifications = document.get("repetition_justifications", [])
    if not isinstance(justifications, list):
        raise ValueError("repetition_justifications must be a list")
    reviewed = []
    for first, end, lid in runs:
        affected = [p["page_id"] for p in pages[first:end]]
        if policy == "uniform_by_user_request":
            reviewed.append({"page_ids": affected, "layout_id": lid, "reason": request["instruction_excerpt"], "source": "user"})
            continue
        declared = next((j for j in justifications if isinstance(j, dict)
                         and j.get("page_ids") == affected and j.get("layout_id") == lid), None)
        if (not declared or not _reason(declared.get("reason"))
                or not _reason(declared.get("narrative_purpose"))):
            raise ValueError(f"{', '.join(affected)} use {lid} repeatedly: supply a concrete narrative repetition_justifications entry; do not rotate layouts mechanically")
        alternatives = declared.get("alternatives_considered")
        available = set.intersection(*[{c["layout_id"] for c in p["selection_evidence"]["candidates"] if c["compatible"]}
                                      for p in pages[first:end]])
        if not isinstance(alternatives, list) or not alternatives or any(a == lid or a not in available for a in alternatives):
            raise ValueError("Repetition justification needs real compatible alternatives_considered")
        reviewed.append(copy.deepcopy(declared))
    return {"status": "passed", "scope": "lightweight_narrative_metadata_not_visual_acceptance",
            "page_count": len(pages), "layout_histogram": dict(Counter(ids)),
            "repetition_decisions": reviewed, "distinct_layout_quota": None, "visual_quality_checked": False}


def select_pages(document, pool=None, library_root=None):
    root = Path(library_root) if library_root is not None else LIBRARY
    pool = load_pool(root) if pool is None else pool
    index = _template_index(root)
    pages = copy.deepcopy(document.get("pages"))
    if not isinstance(pages, list) or not pages:
        raise ValueError("pages must contain authored story units")
    seen = set()
    previous = None
    repeat_length = 0
    cache = {}
    for page in pages:
        if not isinstance(page, dict) or not _text(page.get("page_id")) or page["page_id"] in seen:
            raise ValueError("Each page needs a unique nonempty page_id")
        seen.add(page["page_id"])
        _validate_page(page)
        count = len(page["panels"])
        narrative = page["narrative_function"]
        theme = page.get("theme", "")
        if not isinstance(theme, str):
            raise ValueError(f"{page['page_id']}: theme must be text")
        content = " ".join([theme] + [p[key] for p in page["panels"] for key in ("focus", "main_action_or_emotion")])
        explicit = page.get("layout_id")
        adaptation = page.get("layout_adaptation")
        candidates = []
        for item in pool:
            entry = index[item["id"]]
            matches = entry["panel_count"] == count
            adapted = (explicit == item["id"] and item["panel_count"] == "variable"
                       and isinstance(adaptation, dict) and _reason(adaptation.get("reason"))
                       and all(normalized_bounds(p.get("bounds")) for p in page["panels"]))
            score = layout_score(item, narrative, content)
            penalty = min(repeat_length, 2) if item["id"] == previous else 0
            candidates.append({"layout_id": item["id"], "score": score, "compatible": bool(matches or adapted),
                               "native_panel_count": entry["panel_count"], "adapted_story_units": bool(adapted and not matches),
                               "reason": "story-unit count matches original template metadata" if matches else
                               "explicit authored adaptation with page regions" if adapted else "native count differs; no authored adaptation",
                               "repetition_penalty": penalty, "adjusted_score": score - penalty})
        compatible = sorted((c for c in candidates if c["compatible"]), key=lambda c: (-c["score"], c["layout_id"]))
        if explicit:
            chosen = next((c for c in compatible if c["layout_id"] == explicit), None)
            if chosen is None:
                raise ValueError(f"{page['page_id']}: {explicit} is unknown or incompatible with {count} authored story units; a variable-count adaptation needs a narrative reason and authored panel bounds")
            selection = f"本页“{narrative}”明确选择原库 {explicit}；{page['panel_count_reason']}。"
        else:
            if not compatible:
                raise ValueError(f"{page['page_id']}: no native SB matches {count} story units; author an explicit adaptation without dropping story content")
            top = compatible[0]["score"]
            near = [c for c in compatible if c["score"] >= max(1, top - NEAR_SCORE_GAP)] if top > 0 else compatible[:1]
            chosen = min(near, key=lambda c: (-c["adjusted_score"], -c["score"], c["layout_id"]))
            selection = (f"本页“{narrative}”匹配原库 {chosen['layout_id']} (score={chosen['score']})；"
                         f"{page['panel_count_reason']}。仅在叙事分差不超过 2 分的兼容候选内考虑连续重复。")
        if _text(page.get("selection_reason")):
            selection += " " + page["selection_reason"].strip()
        lid = chosen["layout_id"]
        item = next(p for p in pool if p["id"] == lid)
        page.update({"layout_id": lid, "selection_reason": selection,
                     "selection_evidence": {"page_id": page["page_id"], "selected_layout_id": lid,
                                            "narrative_function": narrative, "selection_scope": "per_page",
                                            "selection_reason": selection,
                                            "candidates": sorted(candidates, key=lambda c: (not c["compatible"], -c["score"], c["layout_id"]))}})
        page["layout"] = _selected_layout(item, index[lid], page, root, cache)
        repeat_length = repeat_length + 1 if previous == lid else 1
        previous = lid
    audit = _audit_repetition(document, pages)
    return {"pages": pages, "rhythm_audit": audit, "library_size": len(pool),
            "selection_policy": "original_semantic_match_then_near_score_repetition_review"}
