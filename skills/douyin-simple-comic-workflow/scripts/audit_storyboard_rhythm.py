#!/usr/bin/env python3
"""Block unsupported multi-page storyboard choices before artwork generation.

This is a metadata/narrative-rhythm gate, not an image-quality review. Real SB
geometry, text capacity and actual images still require their own checks. The
gate deliberately has no quota for distinct layouts or distinct panel counts.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import re

import yaml


DEFAULT_LIBRARY = Path(__file__).resolve().parents[1] / "references/comic-layouts"
SCOPE = "metadata_narrative_rhythm_gate_not_visual_quality"
_LIBRARY_CACHE: dict[tuple[str, str], dict[str, dict]] = {}


def _text(value: object, minimum: int = 1) -> bool:
    return isinstance(value, str) and len(re.sub(r"\s+", "", value)) >= minimum


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _reason(value: object) -> bool:
    """Reject empty/placeholding/reuse-only reasons, without judging prose style."""
    if not _text(value, 8):
        return False
    compact = re.sub(r"\s+", "", str(value)).lower()
    if compact in {"todotodo", "待补充待补充", "同上同上同上", "继续沿用既有模板"}:
        return False
    if re.fullmatch(r"matchedstory-function/themetermsagainstbundledmetadata\(score=[^)]*\)", compact):
        return False
    return True


def _library(root: Path) -> dict[str, dict]:
    """Reuse parsed library metadata only while every text input stays identical."""
    root = root.resolve()
    signature = hashlib.sha256()
    for path in sorted(p for p in root.rglob('*')
                       if p.is_file() and p.suffix.lower() in {'.json', '.yaml', '.yml', '.md'}):
        signature.update(path.relative_to(root).as_posix().encode('utf-8'))
        signature.update(b'\0')
        signature.update(hashlib.sha256(path.read_bytes()).digest())
    key = (str(root), signature.hexdigest())
    if key not in _LIBRARY_CACHE:
        parsed = _parse_library(root)
        if len(_LIBRARY_CACHE) >= 4:
            _LIBRARY_CACHE.pop(next(iter(_LIBRARY_CACHE)))
        _LIBRARY_CACHE[key] = parsed
    return copy.deepcopy(_LIBRARY_CACHE[key])


def _parse_library(root: Path) -> dict[str, dict]:
    pool = json.loads((root / "layouts.json").read_text(encoding="utf-8-sig"))
    if not isinstance(pool, list) or len(pool) != 68:
        raise ValueError("Bundled library must contain exactly 68 layouts")
    index = yaml.safe_load((root / "template-index.yaml").read_text(encoding="utf-8-sig"))
    entries = index.get("templates", []) if isinstance(index, dict) else []
    indexed = {entry.get("layout_id"): entry for entry in entries if isinstance(entry, dict)}
    if len(indexed) != len(entries):
        raise ValueError("Template index has duplicate or invalid layout entries")
    result = {}
    for item in pool:
        if not isinstance(item, dict):
            raise ValueError("Layout pool contains a non-mapping entry")
        layout_id = item.get("id")
        if (not isinstance(layout_id, str) or not re.fullmatch(r"SB-\d{3}", layout_id)
                or layout_id in result or item.get("category") != "comic-storyboard"):
            raise ValueError(f"Invalid/duplicate bundled layout: {layout_id}")
        entry = indexed.get(layout_id)
        if not isinstance(entry, dict):
            raise ValueError(f"Missing template index entry: {layout_id}")
        prompt = item.get("prompt_file")
        template_path = entry.get("template_path")
        if not _text(prompt) or not (root / prompt).is_file():
            raise ValueError(f"Missing source prompt: {layout_id}")
        if not _text(template_path) or not (root / template_path).is_file():
            raise ValueError(f"Missing executable template: {layout_id}")
        template = yaml.safe_load((root / template_path).read_text(encoding="utf-8-sig"))
        if not isinstance(template, dict) or template.get("layout_id") != layout_id:
            raise ValueError(f"Executable template identity mismatch: {layout_id}")
        structure = template.get("structure") or {}
        units = template.get("panels") or structure.get("units") or []
        if not isinstance(units, list) or not units:
            raise ValueError(f"Executable template has no native story units: {layout_id}")
        if entry.get("panel_count") != len(units):
            raise ValueError(f"Native template/index count mismatch: {layout_id}")
        result[layout_id] = {"panel_count": len(units), "name": item.get("name")}
    return result


def _same_runs(ids: list[object]) -> list[tuple[int, int, object]]:
    runs = []
    start = 0
    for index in range(1, len(ids) + 1):
        if index == len(ids) or ids[index] != ids[start]:
            runs.append((start, index, ids[start]))
            start = index
    return runs


def audit_decision(decision: dict, library_root: Path | None = None) -> dict:
    """Return a fail-closed, side-effect-free report for a storyboard handoff."""
    errors: list[str] = []
    warnings: list[str] = []
    adaptations: list[dict] = []
    metrics = {"page_count": 0, "unique_layout_count": 0, "layout_histogram": {},
               "max_consecutive_same_layout": 0, "panel_count_histogram": {}}

    def report() -> dict:
        return {"status": "blocked" if errors else "passed", "generation_ready": not errors,
                "errors": errors, "warnings": warnings, "metrics": metrics,
                "scope": SCOPE, "images_generated": False,
                "declared_adaptations": adaptations, "visual_quality_checked": False}

    if not isinstance(decision, dict):
        errors.append("Storyboard decision must be a mapping")
        return report()
    try:
        library = _library(Path(library_root) if library_root is not None else DEFAULT_LIBRARY)
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        errors.append(f"Bundled storyboard library unavailable or inconsistent: {exc}")
        return report()

    pages = decision.get("pages")
    # Preserve the old single-layout CLI's actual output, never expand it to N pages.
    legacy_single = not isinstance(pages, list) and decision.get("page_count", 1) == 1
    if legacy_single and (decision.get("layout_id") or decision.get("selected_layout")):
        page = dict(decision)
        selected = page.get("selected_layout")
        if isinstance(selected, dict):
            page.setdefault("layout_id", selected.get("id", selected.get("layout_id")))
        elif isinstance(selected, str):
            page.setdefault("layout_id", selected)
        page.setdefault("page_id", "P01")
        if "panels" not in page:
            contract = page.get("execution_contract") or {}
            page["panels"] = contract.get("panel_geometry")
        pages = [page]
    if not isinstance(pages, list) or not pages:
        errors.append("A non-empty pages list is required; a single selected layout cannot stand for multiple pages")
        return report()
    metrics["page_count"] = len(pages)
    if not _positive_int(decision.get("page_count")) and not legacy_single:
        errors.append("page_count must be a positive integer")
    elif decision.get("page_count", 1) != len(pages):
        errors.append("page_count does not equal len(pages)")

    policy = decision.get("layout_policy", "narrative_variety")
    uniform = policy == "uniform_by_user_request"
    if policy not in {"narrative_variety", "uniform_by_user_request"}:
        errors.append("layout_policy must be narrative_variety or uniform_by_user_request")
    if uniform:
        request = decision.get("uniform_layout_request")
        if (not isinstance(request, dict) or request.get("source") != "user"
                or not _text(request.get("instruction_excerpt"))):
            errors.append("uniform_by_user_request requires source:user and a non-empty instruction_excerpt")
        else:
            adaptations.append({"type": "uniform_layout_by_user_request", "source": "user",
                                "instruction_excerpt": request["instruction_excerpt"],
                                "status": "declared_adaptation_not_visual_acceptance"})

    seen: set[str] = set()
    ids: list[object] = []
    page_ids: list[str] = []
    counts: list[int] = []
    for position, page in enumerate(pages):
        if not isinstance(page, dict):
            errors.append(f"Page {position + 1} must be a mapping")
            ids.append(None)
            page_ids.append(f"<invalid-{position + 1}>")
            continue
        page_id = page.get("page_id")
        if not _text(page_id) or page_id in seen:
            errors.append(f"Page {position + 1} requires a unique non-empty page_id")
        if isinstance(page_id, str):
            seen.add(page_id)
        label = page_id if isinstance(page_id, str) else f"page-{position + 1}"
        page_ids.append(label)
        layout_id = page.get("layout_id")
        ids.append(layout_id)
        if not isinstance(layout_id, str) or layout_id not in library:
            errors.append(f"{label}: layout_id is not a real bundled SB ID: {layout_id}")
        count = page.get("panel_count")
        panels = page.get("panels")
        if not _positive_int(count):
            errors.append(f"{label}: panel_count must be a positive integer")
        else:
            counts.append(count)
            if isinstance(layout_id, str) and layout_id in library and library[layout_id]["panel_count"] != count:
                errors.append(f"{label}: panel_count={count} differs from {layout_id} native count={library[layout_id]['panel_count']}")
        if not isinstance(panels, list) or len(panels) != count:
            errors.append(f"{label}: panel_count must equal len(panels)")
        if legacy_single:
            continue
        if not _text(page.get("narrative_function"), 4):
            errors.append(f"{label}: narrative_function needs a concrete page function")
        if not _reason(page.get("panel_count_reason")):
            errors.append(f"{label}: panel_count_reason must explain this page's narrative needs, not merely reuse")
        evidence = page.get("selection_evidence")
        if not isinstance(evidence, dict):
            errors.append(f"{label}: missing per-page selection_evidence; legacy handoffs cannot start new production")
            continue
        for key, expected in (("page_id", page_id), ("selected_layout_id", layout_id),
                              ("narrative_function", page.get("narrative_function"))):
            if evidence.get(key) != expected or expected is None:
                errors.append(f"{label}: selection_evidence.{key} does not bind to this page")
        if not _reason(evidence.get("selection_reason", page.get("selection_reason"))):
            errors.append(f"{label}: selection_evidence needs a concrete selection_reason")
        candidates = evidence.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            errors.append(f"{label}: selection_evidence requires real evaluated candidates")
            continue
        candidate_ids: set[str] = set()
        compatible_ids: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                errors.append(f"{label}: candidate must be a mapping")
                continue
            cid = candidate.get("layout_id")
            if not isinstance(cid, str) or cid not in library:
                errors.append(f"{label}: candidate is not a real bundled SB ID: {cid}")
                continue
            if cid in candidate_ids:
                errors.append(f"{label}: duplicate candidate {cid}")
            candidate_ids.add(cid)
            compatible = candidate.get("compatible")
            if not isinstance(compatible, bool) or not _reason(candidate.get("reason")):
                errors.append(f"{label}: candidate {cid} needs boolean compatible and a concrete reason")
            if compatible is True:
                compatible_ids.add(cid)
                if _positive_int(count) and library[cid]["panel_count"] != count:
                    errors.append(f"{label}: compatible candidate {cid} has a different native panel count")
            for key in ("score", "repetition_penalty", "adjusted_score"):
                score = candidate.get(key)
                if key in candidate and (not isinstance(score, (int, float)) or isinstance(score, bool)
                                         or not math.isfinite(score)):
                    errors.append(f"{label}: candidate {cid} has invalid {key}")
        if not isinstance(layout_id, str) or layout_id not in compatible_ids:
            errors.append(f"{label}: selected layout is not an evaluated compatible candidate")
        declared_count = evidence.get("compatible_candidate_count")
        if declared_count is not None and declared_count != len(compatible_ids):
            errors.append(f"{label}: compatible_candidate_count does not match candidates")
        if len(compatible_ids) == 1:
            warnings.append(f"{label}: only one compatible candidate recorded; this is not independent visual acceptance")

    valid_ids = [lid for lid in ids if isinstance(lid, str)]
    metrics.update(unique_layout_count=len(set(valid_ids)),
                   layout_histogram=dict(Counter(valid_ids)),
                   panel_count_histogram={str(key): value for key, value in sorted(Counter(counts).items())})
    runs = _same_runs(ids) if ids else []
    metrics["max_consecutive_same_layout"] = max((end - start for start, end, _ in runs), default=0)

    covered: set[int] = set()
    justifications = decision.get("repetition_justifications", [])
    if not isinstance(justifications, list):
        errors.append("repetition_justifications must be a list")
        justifications = []
    for index, item in enumerate(justifications):
        prefix = f"repetition_justifications[{index}]"
        before = len(errors)
        if not isinstance(item, dict):
            errors.append(f"{prefix}: must be a mapping")
            continue
        members = item.get("page_ids")
        layout_id = item.get("layout_id")
        if not isinstance(layout_id, str) or layout_id not in library:
            errors.append(f"{prefix}: requires a real bundled layout_id")
        if (not isinstance(members, list) or len(members) < 2
                or any(not isinstance(member, str) or member not in page_ids for member in members)
                or len(set(members)) != len(members)):
            errors.append(f"{prefix}: page_ids must identify at least two existing distinct pages")
            positions = []
        else:
            positions = [page_ids.index(member) for member in members]
            if positions != list(range(positions[0], positions[0] + len(positions))):
                errors.append(f"{prefix}: page_ids must be a contiguous range in reading order")
            if any(ids[position] != layout_id for position in positions):
                errors.append(f"{prefix}: every covered page must use its declared layout_id")
        if not _reason(item.get("reason")) or not _reason(item.get("narrative_purpose")):
            errors.append(f"{prefix}: concrete reason and narrative_purpose are required")
        alternatives = item.get("alternatives_considered")
        if (not isinstance(alternatives, list) or not alternatives
                or any(not isinstance(alt, str) or alt not in library or alt == layout_id for alt in alternatives)):
            errors.append(f"{prefix}: alternatives_considered requires real other SB IDs")
        if len(errors) == before:
            covered.update(positions)
            adaptations.append({"type": "narrative_repetition", "page_ids": members,
                                "layout_id": layout_id, "reason": item["reason"],
                                "narrative_purpose": item["narrative_purpose"],
                                "alternatives_considered": alternatives,
                                "status": "declared_adaptation_not_visual_acceptance"})

    if not uniform:
        for start, end, layout_id in runs:
            full_uniform = len(ids) >= 2 and start == 0 and end == len(ids)
            if (full_uniform or end - start >= 3) and any(position not in covered for position in range(start, end)):
                errors.append(f"Repeated layout {layout_id} on {', '.join(page_ids[start:end])} requires concrete contiguous repetition_justifications or an explicit uniform_by_user_request")
    if adaptations:
        warnings.append("Repetition exceptions are declared adaptations only; they do not certify visual rhythm or image quality")
    return report()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--library-root", type=Path, default=None)
    args = parser.parse_args()
    try:
        decision = yaml.safe_load(args.decision.read_text(encoding="utf-8-sig"))
        result = audit_decision(decision, args.library_root)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        result = {"status": "blocked", "generation_ready": False, "errors": [str(exc)],
                  "warnings": [], "metrics": {}, "scope": SCOPE, "images_generated": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output)}, ensure_ascii=False))
    return 0 if result["generation_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
