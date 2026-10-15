#!/usr/bin/env python3
"""Promote one checked candidate to the canonical final page name.

This helper handles a retry as a candidate operation. It never promotes a
versioned ``*-final-vNNN.png`` path and it does not create formal variants.
Use ``--replace`` only when repairing an existing canonical final; the old
canonical file is copied into the page candidate directory before replacement.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest must contain a mapping")
    return value


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def finalize(run_dir: Path, manifest_path: Path, page_id: str, candidate: str, replace: bool = False) -> dict[str, Any]:
    page_id = page_id.upper()
    manifest = _load(manifest_path)
    pages = manifest.get("pages")
    if not isinstance(pages, list):
        raise ValueError("manifest.pages must be a list")
    matches = [page for page in pages if isinstance(page, dict) and str(page.get("page_id", "")).upper() == page_id]
    if len(matches) != 1:
        raise ValueError(f"manifest must contain exactly one page entry for {page_id}")

    candidate_path = (run_dir / candidate).resolve()
    candidate_root = (run_dir / "pages" / "candidates" / page_id).resolve()
    if candidate_path.parent != candidate_root and candidate_root not in candidate_path.parents:
        raise ValueError("candidate must be under pages/candidates/<PAGE_ID>")
    if not candidate_path.is_file():
        raise FileNotFoundError(candidate_path)
    if candidate_path.suffix.casefold() != ".png":
        raise ValueError("candidate must be a PNG")

    final_path = run_dir / "pages" / "final" / f"{page_id}-final.png"
    final_path.parent.mkdir(parents=True, exist_ok=True)
    page = matches[0]
    candidate_records = page.get("candidate_images") or []
    if not isinstance(candidate_records, list):
        candidate_records = []
    candidate_rel = _relative(candidate_path, run_dir)
    if candidate_rel not in candidate_records:
        candidate_records.append(candidate_rel)

    superseded: list[str] = []
    if final_path.exists():
        if not replace:
            raise FileExistsError(f"canonical final already exists; use --replace for a repair: {final_path}")
        archive = candidate_root / f"superseded-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{final_path.name}"
        shutil.copy2(final_path, archive)
        superseded.append(_relative(archive, run_dir))

    shutil.copy2(candidate_path, final_path)
    discarded = page.get("discarded_candidates") or []
    if not isinstance(discarded, list):
        discarded = []
    for item in superseded:
        if item not in discarded:
            discarded.append(item)
    page["final_image"] = _relative(final_path, run_dir)
    page["retained_final_image"] = final_path.name
    page["final_image_count"] = 1
    page["candidate_images"] = candidate_records
    page["discarded_candidates"] = discarded
    page["candidate_image_count"] = max(
        int(page.get("candidate_image_count") or 0), len(candidate_records) + len(discarded)
    )
    page.setdefault("generated_variants", 0)
    manifest_path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"page_id": page_id, "final_image": page["final_image"], "candidate": candidate_rel, "superseded": superseded}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    result = finalize(args.run_dir.resolve(), args.manifest.resolve(), args.page_id, args.candidate, args.replace)
    print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
