#!/usr/bin/env python3
"""Preserve returned scene edits and register only explicitly reviewed repairs.

This offline helper never makes an image or performs a visual review. Saving an
edit always leaves it pending. Registration checks a separately supplied review;
assembly rechecks the original, edit, repair record and review hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from PIL import Image
import yaml


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Mapping required: {path}")
    return value


def inside(root: Path, value: str | Path) -> Path:
    root = root.resolve()
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f"Path must stay inside this isolated run: {path}")
    return path


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def image_ok(path: Path) -> None:
    with Image.open(path) as image:
        image.verify()


def save_repair(root: Path, record_path: Path) -> dict:
    """Copy a returned edit into the run; never inherit a review flag."""
    record_path = inside(root, record_path)
    record = read(record_path)
    original = inside(root, record["original_path"])
    saved = inside(root, record["saved_path"])
    source = Path(record["generated_source_path"])
    source = (source if source.is_absolute() else root / source).resolve()
    if saved == original or source == original:
        raise ValueError("Repair must be a separate image; preserve the original")
    if not str(record.get("reason", "")).strip():
        raise ValueError("Repair requires a concrete reason")
    image_ok(original)
    image_ok(source)
    if saved.exists() and digest(saved) != digest(source):
        raise ValueError("Refuse to overwrite a different saved repair")
    saved.parent.mkdir(parents=True, exist_ok=True)
    if not saved.exists():
        shutil.copy2(source, saved)
    record.update(original_path=str(original), saved_path=str(saved),
                  original_sha256=digest(original), edited_sha256=digest(saved),
                  actual_edit_reviewed=False, review_status="pending")
    record.pop("review_binding", None)
    record.pop("visual_review_notes", None)
    write(record_path, record)
    return {"saved": str(saved), "review_status": "pending", "original_modified": False}


def register_repair(root: Path, record_path: Path, review_path: Path,
                    overrides_path: Path | None = None) -> dict:
    record_path, review_path = inside(root, record_path), inside(root, review_path)
    record, review = read(record_path), read(review_path)
    original = inside(root, record["original_path"])
    edited = inside(root, record.get("saved_path") or record.get("edited_path"))
    image_ok(original)
    image_ok(edited)
    if original == edited:
        raise ValueError("A repair cannot overwrite its original")
    if record.get("original_sha256") != digest(original) or record.get("edited_sha256") != digest(edited):
        raise ValueError("Repair record is stale")
    if (review.get("review_status") != "passed" or review.get("actual_image_checked") is not True
            or review.get("synthetic") is not False or not str(review.get("reviewer", "")).strip()
            or not review.get("notes") or review.get("repair_record_sha256") != digest(record_path)
            or review.get("original_sha256") != digest(original)
            or review.get("edited_sha256") != digest(edited)):
        raise ValueError("A separate actual-image review must bind this repair record and both images")
    reason = record.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("Repair requires a concrete reason")
    page, unit = record.get("page_id"), record.get("unit_id")
    if not page or not unit or review.get("page_id") != page or review.get("unit_id") != unit:
        raise ValueError("Repair and review must name the same page/unit")
    item = {"original_path": str(original), "original_sha256": digest(original),
            "edited_path": str(edited), "edited_sha256": digest(edited),
            "actual_edit_reviewed": True, "reason": reason,
            "repair_record": str(record_path), "repair_record_sha256": digest(record_path),
            "review_binding": {"path": str(review_path), "sha256": digest(review_path)}}
    overrides_path = inside(root, overrides_path or root / "pages/asset-overrides.json")
    overrides = read(overrides_path) if overrides_path.exists() else {}
    key = f"{page}/{unit}"
    if key in overrides and overrides[key] != item:
        raise ValueError("A different repair is already registered; use a new isolated attempt")
    overrides[key] = item
    write(overrides_path, overrides)
    return {"job_id": key, "override_path": str(overrides_path), "review_status": "passed"}


def resolve_repair(root: Path, key: str, original: Path, item: dict) -> Path:
    """Recheck a registered edit, including legacy records with concrete review notes."""
    original = inside(root, original)
    edited = inside(root, item["edited_path"])
    if (inside(root, item.get("original_path", original)) != original
            or original == edited or item.get("actual_edit_reviewed") is not True
            or not str(item.get("reason", "")).strip()
            or item.get("original_sha256") != digest(original)
            or item.get("edited_sha256") != digest(edited)):
        raise ValueError(f"Unreviewed or stale repair: {key}")
    image_ok(edited)
    record_path = inside(root, item["repair_record"])
    record = read(record_path)
    if (record.get("original_sha256") != digest(original)
            or record.get("edited_sha256") != digest(edited)
            or f'{record.get("page_id")}/{record.get("unit_id")}' != key):
        raise ValueError(f"Repair record does not bind the current job: {key}")
    binding = item.get("review_binding")
    if binding:
        review_path = inside(root, binding["path"])
        if digest(review_path) != binding.get("sha256") or digest(record_path) != item.get("repair_record_sha256"):
            raise ValueError(f"Repair review/record changed: {key}")
        review = read(review_path)
        if (review.get("review_status") != "passed" or review.get("actual_image_checked") is not True
                or review.get("synthetic") is not False or not review.get("reviewer") or not review.get("notes")
                or review.get("repair_record_sha256") != digest(record_path)
                or review.get("original_sha256") != digest(original)
                or review.get("edited_sha256") != digest(edited)
                or f'{review.get("page_id")}/{review.get("unit_id")}' != key):
            raise ValueError(f"Repair lacks current actual-image acceptance: {key}")
    elif not (record.get("actual_edit_reviewed") is True and record.get("visual_review_notes")):
        # Existing v0.8 runs recorded manual observations inside the hash-bound
        # original/edit record. A lone legacy acceptance boolean is insufficient.
        raise ValueError(f"Legacy repair has no concrete manual review observations: {key}")
    return edited


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["save", "register"])
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--overrides", type=Path)
    args = parser.parse_args()
    if args.action == "register" and not args.review:
        parser.error("register requires --review; saving never creates acceptance")
    result = (save_repair(args.run_root, args.record) if args.action == "save" else
              register_repair(args.run_root, args.record, args.review, args.overrides))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
