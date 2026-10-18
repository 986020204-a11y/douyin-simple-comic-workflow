#!/usr/bin/env python3
"""Offline, bounded scene-job handoff with durable progress and a real-pilot gate.

This module does not generate images or call a network API. ``claim`` emits the
actual request and reference paths for an agent to pass to its image tool.
``complete`` records an existing image as generated_unreviewed, never accepted.
All state transitions use an OS file lock and atomic replacement. Lease expiry
is advisory: a slow image call can still be alive. Only explicit ``recover``
releases expired leases; ``recover --worker`` abandons a known stopped worker.
Abandoned calls count towards the bounded attempt budget.

Manifest (paths may be relative to the manifest):
  schema_version: 1
  pipeline_version: workflow-and-generator-version
  pilot_page_id: P01
  pages:
    - page_id: P01
      template_path: targets/P01.yaml
      proof: {report_path: reports/P01-ready.json, sha256: <actual hash>}
      jobs:
        - unit_id: P01
          request: {prompt: <complete scene prompt>, ...actual tool parameters}
          reference_paths: [characters/reference.png, previews/SB-001.webp]

A readiness report must bind every input with ``input_bindings`` and contain
``complete_proof`` links and hashes for its rendered image, compositor report,
and bubble audit. It proves layout capability, not real image acceptance.

Pilot final-review schema: page_id, image_sha256, base_image_sha256,
mobile_image_sha256, mobile_image:{path,sha256}, reviewer, notes,
review_binding:{path,sha256} linking the separately supplied visual review,
actual_image_checked:true, mobile_image_checked:true, synthetic:false, review_status:passed (or
passed_with_declared_adaptations), checks:{mobile_readability,character_continuity,
speaker_binding,text_integrity,critical_occlusion,full_template_execution,
execution_style_match}, all ``passed``. ``evidence_files`` binds render_report
and bubble_audit with {path,sha256}; optional font_raster is hash-checked too.
Mandatory evidence_files: render_report, bubble_audit, font_raster, base_audit,
final_layout_audit. Actual plan, execution target and annotations must be current
hash-bound inputs, linked to the frozen preparation. Glyph evidence records
retained actual draw calls and image hashes. Diagnostic evidence cannot enter a
normal queue, including markers nested in linked JSON/YAML inputs.
The base audit uses audit_storyboard_layout.py's actual geometry/hash evidence.
Every dispatch rechecks the current pilot image, evidence and asset hashes.

Use ``sync`` after changing a request or rebuilding a proof. Asset reuse requires
an identical generation fingerprint (request, references, template, pipeline
version) AND an unchanged readable image. A new valid text-only readiness proof
does not invalidate unchanged artwork; proof hashes are still checked separately
on every dispatch. Reuse never carries over acceptance evidence.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any
import uuid

from PIL import Image, ImageChops
import yaml


QUEUE_VERSION = "1.0"
FINAL_CHECKS = (
    "mobile_readability", "character_continuity", "speaker_binding",
    "text_integrity", "critical_occlusion", "full_template_execution",
    "execution_style_match",
)


class QueueError(ValueError):
    """A blocked or invalid queue operation; no successful state is fabricated."""


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: str | Path) -> dict:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml
        value = yaml.safe_load(text)
    else:
        value = json.loads(text)
    if not isinstance(value, dict):
        raise QueueError(f"Expected mapping: {path}")
    return value


def _path(value: str | Path, base: Path) -> Path:
    path = Path(value)
    return (path if path.is_absolute() else base / path).resolve()


def _file_binding(path: str | Path) -> dict:
    path = Path(path).resolve()
    if not path.is_file():
        raise QueueError(f"Required file missing: {path}")
    return {"path": str(path), "sha256": sha256(path)}


def _check_binding(binding: dict, base: Path, *, image: bool = False) -> Path:
    if not isinstance(binding, dict) or not binding.get("path") or not binding.get("sha256"):
        raise QueueError("File evidence requires path and sha256")
    path = _path(binding["path"], base)
    if not path.is_file() or sha256(path) != binding["sha256"]:
        raise QueueError(f"Missing or changed evidence file: {path}")
    if image:
        _verify_image(path)
    return path


def _verify_image(path: Path) -> tuple[int, int]:
    try:
        with Image.open(path) as image:
            dimensions = image.size
            image.verify()
    except Exception as exc:
        raise QueueError(f"Image is missing or unreadable: {path}") from exc
    if min(dimensions) < 1:
        raise QueueError(f"Invalid image dimensions: {path}")
    return dimensions


@contextlib.contextmanager
def _lock(state_path: str | Path, timeout: float = 15):
    """Use kernel locks, so process death cannot leave a permanently stale lock."""
    lock_path = Path(str(state_path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    if handle.seek(0, os.SEEK_END) == 0:
        handle.write(b"\0")
        handle.flush()
    deadline = time.monotonic() + timeout
    acquired = False
    try:
        while not acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise QueueError(f"Timed out waiting for queue lock: {lock_path}")
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _write(path: str | Path, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and Path(temporary).exists():
            Path(temporary).unlink()


def _event(state: dict, kind: str, **values: Any) -> None:
    state.setdefault("events", []).append({"time": time.time(), "kind": kind, **values})
    state["events"] = state["events"][-1000:]
    state["updated_at"] = time.time()


def _linked(proof: dict, stem: str, base: Path, *, image: bool = False) -> Path:
    return _check_binding({"path": proof.get(f"{stem}_path"),
                           "sha256": proof.get(f"{stem}_sha256")}, base, image=image)


def _bubble_pass(report: dict) -> bool:
    if report.get("execution_bubble_match") == "passed":
        return True
    return (report.get("match_policy") == "adapted"
            and report.get("user_approved_adaptation") is True
            and report.get("adapted_target_match") == "passed")


def _passed(value: Any) -> bool:
    return value is True or value == "passed"


def _render_base_hash_matches(report: dict, expected: str) -> bool:
    if "base_image_sha256" in report:
        return report["base_image_sha256"] == expected
    return (report.get("base_image_sha256_before") == expected
            and report.get("base_image_sha256_after") == expected)


def _reject_diagnostic(value: Any, base: Path, seen: set[Path] | None = None) -> None:
    """Follow explicit file bindings; metadata labels cannot launder test proof."""
    seen = set() if seen is None else seen
    if isinstance(value, dict):
        if value.get("diagnostic_test_only") is True:
            raise QueueError("Diagnostic evidence cannot enter a normal queue")
        if value.get("path") and value.get("sha256"):
            path = _check_binding(value, base)
            if path not in seen and path.suffix.lower() in {".json", ".yaml", ".yml"}:
                seen.add(path)
                # Dependency indexes may be JSON/YAML sequences; schema files
                # themselves still use the stricter mapping-only _load().
                try:
                    linked = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
                except yaml.YAMLError as exc:
                    raise QueueError(f"Invalid linked diagnostic evidence: {path}") from exc
                _reject_diagnostic(linked, path.parent, seen)
        for item in value.values():
            _reject_diagnostic(item, base, seen)
    elif isinstance(value, list):
        for item in value:
            _reject_diagnostic(item, base, seen)


def _validate_proof(proof_binding: dict, template_binding: dict, *, diagnostic: bool = False) -> dict:
    path = _check_binding(proof_binding, Path.cwd())
    proof = _load(path)
    if not diagnostic:
        _reject_diagnostic(proof, path.parent)
    if proof.get("generation_ready") is not True:
        raise QueueError(f"Page is not generation_ready: {path}")
    bindings = proof.get("input_bindings")
    if not isinstance(bindings, list) or not bindings:
        raise QueueError(f"Readiness proof has no hash-bound inputs: {path}")
    bound_paths = set()
    for binding in bindings:
        bound_paths.add(str(_check_binding(binding, path.parent)))
    if template_binding["path"] not in bound_paths:
        raise QueueError(f"Readiness proof is not bound to the current template: {path}")
    _check_binding(template_binding, Path.cwd())
    complete = proof.get("complete_proof") or {}
    if complete.get("accepted") is not True:
        raise QueueError(f"Complete layout/text proof has not passed: {path}")
    image_path = _linked(complete, "image", path.parent, image=True)
    render_path = _linked(complete, "render_report", path.parent)
    bubble_path = _linked(complete, "bubble_audit", path.parent)
    render = _load(render_path)
    if (render.get("page_acceptance_status") != "accepted"
            or render.get("synthetic_input") is not True
            or render.get("actual_image_checked") is not False):
        raise QueueError(f"Complete proof must be an accepted synthetic render: {render_path}")
    count = render.get("canonical_block_count")
    if type(count) is not int or count < 0 or render.get("rendered_count") != count:
        raise QueueError(f"Complete proof did not render every canonical text block: {render_path}")
    if render.get("unresolved_count") != 0:
        raise QueueError(f"Complete proof has unresolved text blocks: {render_path}")
    if render.get("output_image_sha256") != sha256(image_path):
        raise QueueError(f"Complete proof render/image hash mismatch: {render_path}")
    if count and render.get("pixel_difference_nonempty") is not True:
        raise QueueError(f"Complete proof has no raster text evidence: {render_path}")
    if not _bubble_pass(_load(bubble_path)):
        raise QueueError(f"Complete proof bubble audit failed: {bubble_path}")
    if not diagnostic:
        for evidence_path in (render_path, bubble_path):
            _reject_diagnostic(_load(evidence_path), evidence_path.parent)
    return proof


def _fingerprint(job: dict, version: str) -> str:
    material = {"queue_version": QUEUE_VERSION, "pipeline_version": version,
                "request": job["request"], "reference_bindings": job["reference_bindings"],
                "template_binding": job["template_binding"]}
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _normalize_manifest(manifest_path: str | Path, *, diagnostic: bool = False) -> dict:
    path = Path(manifest_path).resolve()
    raw = _load(path)
    if raw.get('diagnostic_test_only') is True and not diagnostic:
        raise QueueError('Diagnostic requests require explicit --diagnostic mode')
    if raw.get("schema_version") not in {1, "1"}:
        raise QueueError("Manifest schema_version must be 1")
    version = raw.get("pipeline_version")
    if not isinstance(version, str) or not version.strip():
        raise QueueError("Manifest pipeline_version is required for cache invalidation")
    pages: dict[str, dict] = {}
    jobs: dict[str, dict] = {}
    if not isinstance(raw.get("pages"), list) or not raw["pages"]:
        raise QueueError("Manifest requires explicit nonempty pages/jobs")
    for page in raw["pages"]:
        page_id = page.get("page_id")
        if not isinstance(page_id, str) or not page_id.strip() or page_id in pages:
            raise QueueError(f"Invalid or duplicate page_id: {page_id}")
        template = _file_binding(_path(page.get("template_path", ""), path.parent))
        supplied = page.get("proof") or {}
        proof = {"path": str(_path(supplied.get("report_path", ""), path.parent)),
                 "sha256": supplied.get("sha256")}
        _validate_proof(proof, template, diagnostic=diagnostic)
        rows = page.get("jobs")
        if not isinstance(rows, list) or not rows:
            raise QueueError(f"Page requires explicit scene jobs: {page_id}")
        pages[page_id] = {"page_id": page_id, "template_binding": template,
                          "proof_binding": proof, "generation_ready": True,
                          "generation_block_reason": None, "text_issues": []}
        for row in rows:
            unit_id = row.get("unit_id")
            request = row.get("request")
            if not isinstance(unit_id, str) or not unit_id.strip():
                raise QueueError(f"Missing unit_id on {page_id}")
            job_id = f"{page_id}/{unit_id}"
            if job_id in jobs:
                raise QueueError(f"Duplicate job: {job_id}")
            if not isinstance(request, dict) or not isinstance(request.get("prompt"), str) or not request["prompt"].strip():
                raise QueueError(f"Job requires the complete actual request.prompt: {job_id}")
            references = row.get("reference_paths")
            if not isinstance(references, list):
                raise QueueError(f"Job reference_paths must be an explicit list: {job_id}")
            refs = []
            for reference in references:
                reference_path = _path(reference, path.parent)
                _verify_image(reference_path)
                refs.append(_file_binding(reference_path))
            request_refs = request.get("referenced_image_paths")
            if refs and not isinstance(request_refs, list):
                raise QueueError(f"Actual request must include explicit referenced_image_paths: {job_id}")
            if request_refs is not None and (not isinstance(request_refs, list) or
                    [str(_path(item, path.parent)) for item in request_refs] != [item["path"] for item in refs]):
                raise QueueError(f"Actual request image inputs differ from hashed reference_paths: {job_id}")
            if request.get("num_last_images_to_include"):
                raise QueueError(f"Queue requests require explicit hash-bound reference paths: {job_id}")
            job = {"job_id": job_id, "page_id": page_id, "unit_id": unit_id,
                   "request": copy.deepcopy(request), "reference_bindings": refs,
                   "template_binding": template, "proof_binding": proof,
                   "status": "pending", "attempts": 0, "history": [], "asset": None,
                   "lease": None, "blocked_reason": None}
            # Emit paths that the actual image tool can read regardless of the
            # worker's current directory, not just a separate metadata list.
            if request_refs is not None:
                job["request"]["referenced_image_paths"] = [item["path"] for item in refs]
            job["fingerprint"] = _fingerprint(job, version)
            jobs[job_id] = job
    if raw.get("pilot_page_id") not in pages:
        raise QueueError("pilot_page_id must name a manifest page")
    if raw.get('expected_page_ids') is not None and list(pages) != raw['expected_page_ids']:
        raise QueueError('Queue pages differ from the complete prepared page list')
    return {"manifest_binding": _file_binding(path), "pipeline_version": version,
            "diagnostic_test_only": raw.get('diagnostic_test_only') is True,
            "pilot_page_id": raw["pilot_page_id"], "pages": pages, "jobs": jobs}


def init_queue(manifest_path: str | Path, state_path: str | Path, *,
               max_concurrency: int = 4, max_attempts: int = 3, diagnostic: bool = False) -> dict:
    """Create state without making, reviewing, or dispatching any image."""
    if max_concurrency < 1 or max_attempts < 1:
        raise QueueError("Concurrency and attempt limits must be positive")
    with _lock(state_path):
        if Path(state_path).exists():
            raise QueueError("Queue already exists; use sync to reconcile changed requests")
        normalized = _normalize_manifest(manifest_path, diagnostic=diagnostic)
        state = {"schema_version": 1, "queue_version": QUEUE_VERSION, **normalized,
                 "max_concurrency": max_concurrency, "max_attempts": max_attempts,
                 "pilot_acceptance": None, "created_at": time.time(), "events": [],
                 "stats": {"claimed_calls": 0, "completed_calls": 0,
                           "generation_failures": 0, "lease_expirations": 0,
                           "invalidated_assets": 0, "reused_assets": 0,
                           "generation_seconds": 0.0, "text_issues": 0}}
        _event(state, "initialized")
        _write(state_path, state)
        return _summary(state)


def sync_queue(manifest_path: str | Path, state_path: str | Path) -> dict:
    """Reuse only identical, intact assets; changed fingerprints lose acceptance."""
    with _lock(state_path):
        state = _load(state_path)
        if any(job["status"] == "inflight" for job in state["jobs"].values()):
            raise QueueError("Wait for active leases or explicitly recover stopped workers before sync")
        fresh = _normalize_manifest(manifest_path, diagnostic=state.get('diagnostic_test_only') is True)
        for job_id, job in fresh["jobs"].items():
            old = state["jobs"].get(job_id)
            if old and old["fingerprint"] == job["fingerprint"]:
                if old["status"] == "generated_unreviewed" and _asset_intact(old):
                    retained = copy.deepcopy(old)
                    retained["proof_binding"] = job["proof_binding"]
                    fresh["jobs"][job_id] = retained
                    state["stats"]["reused_assets"] += 1
                elif old["status"] != "generated_unreviewed":
                    retained = copy.deepcopy(old)
                    retained["proof_binding"] = job["proof_binding"]
                    fresh["jobs"][job_id] = retained
            elif old:
                job["history"] = old["history"] + [{"kind": "superseded_input",
                    "fingerprint": old["fingerprint"], "asset": old.get("asset"),
                    "attempts": old["attempts"], "time": time.time()}]
                if old.get("asset"):
                    state["stats"]["invalidated_assets"] += 1
        state.update(fresh)
        # Images can be cached; final image acceptance is always checked anew.
        state["pilot_acceptance"] = None
        _event(state, "synced", manifest=str(Path(manifest_path).resolve()))
        _write(state_path, state)
        return _summary(state)


def _asset_intact(job: dict) -> bool:
    asset = job.get("asset")
    if not asset or asset.get("fingerprint") != job["fingerprint"]:
        return False
    try:
        _check_binding(asset, Path.cwd(), image=True)
        return True
    except (QueueError, OSError):
        return False


def _invalidate_asset(state: dict, job: dict, reason: str) -> None:
    if job.get("asset"):
        job["history"].append({"kind": "invalidated_asset", "asset": job["asset"],
                               "reason": reason, "time": time.time()})
        state["stats"]["invalidated_assets"] += 1
    job["asset"] = None
    job["lease"] = None
    job["status"] = "pending" if job["attempts"] < state["max_attempts"] else "blocked"
    job["blocked_reason"] = reason if job["status"] == "blocked" else None
    state["pilot_acceptance"] = None
    _event(state, "asset_invalidated", job_id=job["job_id"], reason=reason)


def _recover(state: dict, worker: str | None = None) -> list[str]:
    recovered = []
    now = time.time()
    for job in state["jobs"].values():
        lease = job.get("lease")
        if job["status"] != "inflight" or not lease:
            continue
        abandoned = lease["worker"] == worker if worker is not None else lease["expires_at"] <= now
        if abandoned:
            job["history"].append({"kind": "abandoned_lease", "lease": lease,
                                   "attempt": job["attempts"], "time": now})
            job["lease"] = None
            job["status"] = "pending" if job["attempts"] < state["max_attempts"] else "blocked"
            job["blocked_reason"] = "attempt_limit_reached_after_abandoned_lease" if job["status"] == "blocked" else None
            state["stats"]["lease_expirations"] += 1
            recovered.append(job["job_id"])
            _event(state, "lease_recovered", job_id=job["job_id"], worker=lease["worker"])
    return recovered


def _refresh(state: dict) -> None:
    try:
        _check_binding(state["manifest_binding"], Path.cwd())
        state["manifest_current"] = True
    except (QueueError, OSError):
        state["manifest_current"] = False
    for page in state["pages"].values():
        try:
            _validate_proof(page["proof_binding"], page["template_binding"],
                            diagnostic=state.get("diagnostic_test_only") is True)
            page["generation_ready"] = True
            page["generation_block_reason"] = None
        except (QueueError, OSError, ValueError) as exc:
            page["generation_ready"] = False
            page["generation_block_reason"] = str(exc)
        if not state["manifest_current"]:
            page["generation_ready"] = False
            page["generation_block_reason"] = "manifest_changed_requires_explicit_sync"
    for job in state["jobs"].values():
        try:
            current_refs = []
            for reference in job["reference_bindings"]:
                _verify_image(Path(reference["path"]))
                current_refs.append(_file_binding(reference["path"]))
        except (QueueError, OSError) as exc:
            job["input_block_reason"] = str(exc)
            continue
        job["input_block_reason"] = None
        if current_refs != job["reference_bindings"]:
            if job["status"] == "inflight":
                # A changed input does not stop an already running provider
                # call. Keep its concurrency slot and claim until the worker
                # is explicitly recovered; a stale completion is rejected.
                job["input_block_reason"] = "reference_content_changed_during_active_claim"
                continue
            # Same pathname with different content is a different generation job.
            _invalidate_asset(state, job, "reference_content_changed")
            job["reference_bindings"] = current_refs
            job["fingerprint"] = _fingerprint(job, state["pipeline_version"])
            job["attempts"] = 0
            job["status"] = "pending"
        if job["status"] == "generated_unreviewed" and not _asset_intact(job):
            _invalidate_asset(state, job, "asset_file_missing_or_changed")


def _base_audit_valid(path: Path, base_image: Path) -> dict:
    report = _load(path)
    evidence = report.get("measurement_evidence") or {}
    if (report.get("synthetic") is True or report.get("synthetic_input") is True
            or report.get("actual_image_checked") is False
            or report.get("image_geometry_measurement_verified") is not True
            or evidence.get("geometry_observed_from_image") is not True
            or evidence.get("image_sha256") != sha256(base_image)):
        raise QueueError("Pilot base audit lacks actual hash-bound image geometry evidence")
    count = report.get("target_panel_count")
    actual = report.get("actual_panel_geometry")
    target = report.get("target_panel_geometry")
    if (type(count) is not int or count <= 0 or report.get("actual_panel_count") != count
            or not isinstance(actual, list) or len(actual) != count
            or not isinstance(target, list) or len(target) != count):
        raise QueueError("Pilot base audit panel counts/geometries are missing or inconsistent")
    ids = [row.get("panel_id") or row.get("unit_id") for row in actual]
    if None in ids or len(set(ids)) != count:
        raise QueueError("Pilot base audit actual panel IDs are invalid")
    target_ids = [row.get("panel_id") or row.get("unit_id") for row in target]
    if target_ids != ids:
        raise QueueError("Pilot base audit reported reading order contradicts its panel geometry")
    # Recheck numeric evidence rather than accepting contradictory `passed`
    # labels. The geometry auditor uses a two-pixel edge tolerance as well.
    for want, got in zip(target, actual):
        if want.get("order") != got.get("order"):
            raise QueueError("Pilot base audit panel order deviates from target")
        for key in ("x", "y", "width", "height"):
            w, g = want.get(key), got.get(key)
            if (type(w) not in {int, float} or type(g) not in {int, float}
                    or not math.isfinite(w) or not math.isfinite(g)
                    or (key in {"width", "height"} and min(w, g) <= 0)
                    or abs(w - g) > 2):
                raise QueueError(f"Pilot base audit panel {key} deviates from target")
        kind = want.get("geometry_type", "rect")
        if kind not in {"rect", "rectangle", "xywh"} and got.get("geometry_type", "rect") != kind:
            raise QueueError("Pilot base audit geometry type deviates from target")
        if want.get("polygon") or want.get("points"):
            from audit_storyboard_layout import _polygon, _polygon_distance
            wp, gp = _polygon(want), _polygon(got)
            if not wp or len(wp) != len(gp) or _polygon_distance(wp, gp) > 4:
                raise QueueError("Pilot base audit polygon deviates from target")
    if (not _passed(report.get("reading_order_match"))
            or report.get("execution_geometry_match") != "passed"
            or report.get("base_image_modified") is not False):
        raise QueueError("Pilot actual base layout did not pass")
    if report.get("match_policy") == "adapted":
        if report.get("user_approved_adaptation") is not True or report.get("adapted_target_match") != "passed":
            raise QueueError("Pilot adapted target is not explicitly approved and passed")
    elif report.get("storyboard_layout_match") != "passed":
        raise QueueError("Pilot source storyboard layout did not pass")
    return report


def validate_visual_provenance(qa_path: Path, base_path: Path, final_path: Path, *,
                               expected_evidence: dict[str, Path] | None = None,
                               expected_actual_plan_path: Path | None = None,
                               diagnostic: bool = False) -> dict:
    """Validate separately supplied observations, current mobile proof and inputs.

    Shared by queue/delivery; it never invents observations or accepts artwork
    from geometry alone. The caller also validates report contents and frozen
    generation lineage appropriate to its stage.
    """
    qa_path, base_path, final_path = Path(qa_path).resolve(), Path(base_path).resolve(), Path(final_path).resolve()
    qa = _load(qa_path)
    if not diagnostic:
        _reject_diagnostic(qa, qa_path.parent)
    base_hash, final_hash = sha256(base_path), sha256(final_path)
    notes = qa.get("notes")
    valid_notes = ((isinstance(notes, str) and bool(notes.strip())) or
                   (isinstance(notes, list) and bool(notes)
                    and all(isinstance(n, str) and n.strip() for n in notes)))
    if (not isinstance(qa.get("reviewer"), str) or not qa["reviewer"].strip() or not valid_notes
            or qa.get("actual_image_checked") is not True or qa.get("mobile_image_checked") is not True
            or qa.get("synthetic") is not False or qa.get("image_sha256") != final_hash
            or qa.get("base_image_sha256") != base_hash
            or qa.get("review_status") not in {"passed", "passed_with_declared_adaptations"}
            or any(qa.get("checks", {}).get(k) != "passed" for k in FINAL_CHECKS)):
        raise QueueError("Actual visual review requires current images, reviewer, concrete notes and all seven checks")
    mobile = _check_binding(qa.get("mobile_image"), qa_path.parent, image=True)
    if qa.get("mobile_image_sha256") != sha256(mobile) or _verify_image(mobile) != (360, 480):
        raise QueueError("Visual review requires a current hash-bound 360x480 mobile image")
    with Image.open(final_path) as final, Image.open(mobile) as small:
        expected = final.convert("RGB").resize((360, 480), Image.Resampling.LANCZOS)
        if ImageChops.difference(expected, small.convert("RGB")).getbbox() is not None:
            raise QueueError("Reviewed mobile image is not the current final image's uniform reduction")
    source_path = _check_binding(qa.get("review_binding"), qa_path.parent)
    if source_path == qa_path:
        raise QueueError("Production review must bind a separate supplied visual review")
    source = _load(source_path)
    fields = ("page_id", "image_sha256", "base_image_sha256", "mobile_image_sha256",
              "actual_image_checked", "mobile_image_checked", "synthetic", "review_status",
              "reviewer", "notes", "checks")
    if any(source.get(k) != qa.get(k) for k in fields):
        raise QueueError("Production review differs from the separately supplied visual observations")
    evidence = qa.get("evidence_files") or {}
    required = ("render_report", "bubble_audit", "font_raster", "base_audit", "final_layout_audit")
    if any(k not in evidence for k in required):
        raise QueueError("Visual review requires render, bubbles, glyphs, base and final layout evidence")
    paths = {k: _check_binding(v, qa_path.parent) for k, v in evidence.items()}
    for k in required:
        original_binding = source.get("evidence_files", {}).get(k)
        if not original_binding or _check_binding(original_binding, source_path.parent) != paths[k]:
            raise QueueError(f"Supplied visual review lacks current {k} evidence")
    for name, expected in (expected_evidence or {}).items():
        if paths.get(name) != Path(expected).resolve():
            raise QueueError(f"Visual review binds a different {name} file")
    inputs = qa.get("input_bindings")
    if not isinstance(inputs, list) or not inputs:
        raise QueueError("Visual review must bind actual plan, executed target and annotations")
    input_paths = {_check_binding(b, qa_path.parent) for b in inputs}
    source_inputs = {_check_binding(b, source_path.parent) for b in source.get("input_bindings", [])}
    candidates = []
    for path in input_paths:
        if path.suffix.lower() in {".json", ".yaml", ".yml"}:
            item = _load(path)
            if item.get("page_id") == qa.get("page_id") and item.get("actual_annotations_binding"):
                candidates.append((path, item))
    if len(candidates) != 1:
        raise QueueError("Visual review requires one unambiguous current actual text plan")
    plan_path, plan = candidates[0]
    if expected_actual_plan_path is not None and plan_path != Path(expected_actual_plan_path).resolve():
        raise QueueError("Visual review binds a different actual text plan")
    target_path = _path(plan.get("execution_template_path", ""), plan_path.parent)
    annotations_path = _check_binding(plan["actual_annotations_binding"], plan_path.parent)
    if not {plan_path, target_path, annotations_path} <= input_paths & source_inputs:
        raise QueueError("Both visual reviews must bind current actual plan, target and annotations")
    annotations = _load(annotations_path)
    if (plan.get("base_image_sha256") != base_hash or plan.get("actual_image_checked") is not True
            or plan.get("synthetic") is not False or plan.get("synthetic_input") is not False
            or annotations.get("page_id") != qa.get("page_id") or annotations.get("base_sha256") != base_hash
            or annotations.get("actual_image_checked") is not True
            or annotations.get("geometry_visually_checked") is not True or annotations.get("synthetic") is True):
        raise QueueError("Current actual plan and annotations must bind the reviewed base image")
    return {"review": qa, "source_review": source, "evidence_paths": paths,
            "actual_plan_path": plan_path, "actual_plan": plan,
            "executed_target_path": target_path, "executed_target": _load(target_path),
            "bound_files": list(input_paths | set(paths.values()) | {mobile, source_path, qa_path})}


def _glyph_evidence_valid(fonts: dict, render: dict, plan: dict, base_hash: str, final_hash: str) -> None:
    if (fonts.get("actual_image_checked") is not True or fonts.get("base_image_sha256") != base_hash
            or fonts.get("output_image_sha256") != final_hash):
        raise QueueError("Actual glyph evidence must bind current base and final images")
    blocks, rows, glyphs = plan.get("text_blocks"), render.get("rendered_blocks"), fonts.get("blocks")
    if not isinstance(blocks, list) or not isinstance(rows, list) or not isinstance(glyphs, list):
        raise QueueError("Actual glyph evidence requires plan, render and font block lists")
    ids = [b.get("id") for b in blocks]
    if (None in ids or len(set(ids)) != len(ids) or len(rows) != len(ids) or len(glyphs) != len(ids)
            or {b.get("id") for b in rows} != set(ids) or {b.get("block_id") for b in glyphs} != set(ids)):
        raise QueueError("Actual glyph evidence does not cover every canonical block")
    rendered, font_rows = {b["id"]: b for b in rows}, {b["block_id"]: b for b in glyphs}
    for block in blocks:
        row, proof = rendered[block["id"]], font_rows[block["id"]]
        if row.get("rendered") is not True or any(row.get(k) != block.get(k) for k in ("text", "type", "speaker", "panel_id")):
            raise QueueError("Actual rendered text, channel, speaker or panel differs from its plan")
        record = proof.get("font_raster_evidence") or {}
        sizes, calls = proof.get("actual_font_sizes"), record.get("draw_calls")
        if (row.get("font_raster_evidence") != record or row.get("actual_font_sizes") != sizes
                or record.get("method") != "pillow_draw_text_font_object" or record.get("retained_in_output") is not True
                or record.get("base_image_sha256") != base_hash or record.get("output_image_sha256") != final_hash
                or not isinstance(sizes, list) or not sizes or not isinstance(calls, list) or not calls
                or any(type(size) not in {int, float} or not math.isfinite(size) or size <= 0 for size in sizes)
                or set(sizes) != {c.get("font_size") for c in calls}):
            raise QueueError("Current retained glyph draw calls are missing or inconsistent")
        for call in calls:
            bounds = call.get("glyph_bounds_xyxy")
            if (not isinstance(call.get("text"), str) or not call["text"]
                    or not call.get("font_file") or not isinstance(bounds, list) or len(bounds) != 4
                    or any(type(v) not in {int, float} or not math.isfinite(v) for v in bounds)
                    or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]):
                raise QueueError("Actual font evidence lacks concrete glyph bounds")


def _target_audit_binding_valid(report: dict, target: dict) -> None:
    from layout_executor import compile_template_contract
    expected = compile_template_contract(target)["panel_geometry"]
    measured = report.get("target_panel_geometry") or []
    if report.get("selected_layout") != target.get("layout_id"):
        raise QueueError("Pilot audit selected_layout differs from the frozen/executed SB target")
    if len(expected) != len(measured) or any(
            (want.get("panel_id") != got.get("panel_id") or want.get("order") != got.get("order")
             or want.get("geometry_type", "rect") != got.get("geometry_type", "rect")
             or any(abs(want[k] - got[k]) > 1.01 for k in ("x", "y", "width", "height")))
            for want, got in zip(expected, measured)):
        raise QueueError("Pilot layout audit is not bound to the current frozen/executed target geometry")
    from audit_storyboard_layout import _polygon, _polygon_distance
    for want, got in zip(expected, measured):
        wp, gp = _polygon(want), _polygon(got)
        if wp and (len(wp) != len(gp) or _polygon_distance(wp, gp) > 4):
            raise QueueError("Pilot layout audit polygon differs from frozen/executed target")


def _validate_pilot(state: dict, acceptance: dict) -> None:
    page_id = state["pilot_page_id"]
    for job in state["jobs"].values():
        if job["page_id"] == page_id:
            if job["status"] != "generated_unreviewed" or not _asset_intact(job):
                raise QueueError("Pilot requires all its actual generated assets, unchanged")
            if acceptance.get("job_fingerprints", {}).get(job["job_id"]) != job["fingerprint"]:
                raise QueueError("Pilot acceptance belongs to a different asset request")
    page = state["pages"][page_id]
    if not page["generation_ready"]:
        raise QueueError("Pilot readiness inputs changed; rebuild proof before acceptance")
    base_image = _check_binding(acceptance["base_image"], Path.cwd(), image=True)
    final_image = _check_binding(acceptance["final_image"], Path.cwd(), image=True)
    if _verify_image(base_image) != (1080, 1440) or _verify_image(final_image) != (1080, 1440):
        raise QueueError('Pilot base and final must both be 1080x1440 before batch generation')
    base_audit = _check_binding(acceptance["base_audit"], Path.cwd())
    final_audit_path = _check_binding(acceptance["final_audit"], Path.cwd())
    base_report = _base_audit_valid(base_audit, base_image)
    final = _load(final_audit_path)
    if (final.get("page_id") != page_id or final.get("synthetic") is not False
            or final.get("actual_image_checked") is not True
            or final.get("image_sha256") != sha256(final_image)
            or final.get("base_image_sha256") != sha256(base_image)
            or final.get("review_status") not in {"passed", "passed_with_declared_adaptations"}):
        raise QueueError("Pilot final audit lacks actual hash-bound acceptance evidence")
    if any(final.get("checks", {}).get(key) != "passed" for key in FINAL_CHECKS):
        raise QueueError("Pilot final checks are incomplete or failed")
    provenance = validate_visual_provenance(final_audit_path, base_image, final_image,
        expected_evidence={"base_audit": base_audit},
        diagnostic=state.get("diagnostic_test_only") is True)
    actual_plan, actual_target = provenance["actual_plan"], provenance["executed_target"]
    generation_template = _check_binding({"path": actual_plan.get("generation_template_path"),
        "sha256": actual_plan.get("generation_template_sha256")}, provenance["actual_plan_path"].parent)
    if (str(generation_template) != page["template_binding"]["path"]
            or actual_plan["generation_template_sha256"] != page["template_binding"]["sha256"]):
        raise QueueError("Pilot actual target belongs to different frozen generation inputs")
    generation_plan_binding = {"path": actual_plan.get("generation_plan_path"),
                               "sha256": actual_plan.get("generation_plan_sha256")}
    generation_plan_path = _check_binding(generation_plan_binding, provenance["actual_plan_path"].parent)
    readiness = _load(Path(page["proof_binding"]["path"]))
    if not any(_check_binding(b, Path(page["proof_binding"]["path"]).parent) == generation_plan_path
               for b in readiness["input_bindings"]):
        raise QueueError("Pilot generation plan is not bound to the complete readiness proof")
    frozen_target, frozen_plan = _load(generation_template), _load(generation_plan_path)
    _target_audit_binding_valid(base_report, frozen_target)
    text_fit_fields = {"bubbles", "text_zones", "source_target_deviation", "match_policy",
                       "user_approved_adaptation", "diagnostic_test_only"}
    if {k:v for k,v in actual_target.items() if k not in text_fit_fields} != {
            k:v for k,v in frozen_target.items() if k not in text_fit_fields}:
        raise QueueError("Pilot execution target changed frozen panels or mechanisms")
    old_blocks, new_blocks = frozen_plan.get("text_blocks"), actual_plan.get("text_blocks")
    immutable = ("id", "text", "type", "source_type", "speaker", "panel_id", "source_article_range")
    if (not isinstance(old_blocks, list) or not isinstance(new_blocks, list) or len(old_blocks) != len(new_blocks)
            or any(any(old.get(k) != new.get(k) for k in immutable) for old,new in zip(old_blocks,new_blocks))):
        raise QueueError("Pilot text, channel, speaker, source or panel differs from frozen preparation")
    evidence_files = final.get("evidence_files") or {}
    for name in ("render_report", "bubble_audit"):
        if name not in evidence_files:
            raise QueueError(f"Pilot final audit has no actual {name} binding")
    for binding in evidence_files.values():
        _check_binding(binding, final_audit_path.parent)
    render = _load(_check_binding(evidence_files["render_report"], final_audit_path.parent))
    canonical_count = render.get("canonical_block_count")
    if (render.get("page_acceptance_status") != "accepted"
            or render.get("synthetic_input") is not False
            or render.get("actual_image_checked") is not True
            or render.get("output_image_sha256") != sha256(final_image)
            or not _render_base_hash_matches(render, sha256(base_image))
            or render.get("unresolved_count") != 0
            or type(canonical_count) is not int or canonical_count < 0
            or render.get("rendered_count") != canonical_count
            or (canonical_count and render.get("pixel_difference_nonempty") is not True)):
        raise QueueError("Pilot final compositor report is not a complete actual render")
    bubbles = _load(_check_binding(evidence_files["bubble_audit"], final_audit_path.parent))
    image_evidence = bubbles.get("image_evidence") or {}
    if (not _bubble_pass(bubbles) or bubbles.get("actual_render_verified") is not True
            or image_evidence.get("verified") is not True
            or image_evidence.get("output_image_sha256") != sha256(final_image)
            or image_evidence.get("base_hash_match") is not True):
        raise QueueError("Pilot final bubbles lack actual hash-bound raster evidence")
    font_path = provenance["evidence_paths"]["font_raster"]
    _glyph_evidence_valid(_load(font_path), render, actual_plan, sha256(base_image), sha256(final_image))
    layout_path = provenance["evidence_paths"]["final_layout_audit"]
    layout = _base_audit_valid(layout_path, base_image)
    if (layout.get("full_template_execution") != "passed" or layout.get("execution_style_match") != "passed"
            or layout.get("final_image_sha256") != sha256(final_image)
            or layout.get("base_image_sha256") != sha256(base_image)
            or layout.get("actual_image_checked") is not True):
        raise QueueError("Pilot final template execution lacks current full image evidence")
    _target_audit_binding_valid(layout, actual_target)
    for binding in final.get("input_bindings", []):
        _check_binding(binding, final_audit_path.parent)


def _pilot_unlocked(state: dict) -> bool:
    acceptance = state.get("pilot_acceptance")
    if not acceptance:
        state["pilot_block_reason"] = "complete_actual_pilot_required"
        return False
    try:
        _validate_pilot(state, acceptance)
        state["pilot_block_reason"] = None
        return True
    except (QueueError, OSError, ValueError) as exc:
        state["pilot_block_reason"] = str(exc)
        state["pilot_acceptance"] = None
        _event(state, "pilot_acceptance_invalidated", reason=str(exc))
        return False


def claim_jobs(state_path: str | Path, worker: str, *, limit: int | None = None,
               lease_seconds: float = 1800) -> dict:
    """Atomically emit independent requests up to the global concurrency limit."""
    if not worker.strip() or (limit is not None and limit < 1) or not math.isfinite(lease_seconds) or lease_seconds <= 0:
        raise QueueError("Worker, positive limit and finite positive lease_seconds are required")
    with _lock(state_path):
        state = _load(state_path)
        _refresh(state)
        unlocked = _pilot_unlocked(state)
        active = sum(job["status"] == "inflight" for job in state["jobs"].values())
        capacity = max(0, state["max_concurrency"] - active)
        capacity = min(capacity, limit) if limit is not None else capacity
        dispatch = []
        for job in state["jobs"].values():
            if len(dispatch) >= capacity:
                break
            page = state["pages"][job["page_id"]]
            if (job["status"] != "pending" or not page["generation_ready"]
                    or job.get("input_block_reason")
                    or (job["page_id"] != state["pilot_page_id"] and not unlocked)):
                continue
            if job["attempts"] >= state["max_attempts"]:
                job["status"] = "blocked"
                job["blocked_reason"] = "attempt_limit_reached"
                continue
            now = time.time()
            token = uuid.uuid4().hex
            job["lease"] = {"worker": worker, "claim_token": token, "started_at": now,
                            "expires_at": now + lease_seconds}
            job["attempts"] += 1
            job["status"] = "inflight"
            state["stats"]["claimed_calls"] += 1
            _event(state, "claimed", job_id=job["job_id"], attempt=job["attempts"], worker=worker)
            dispatch.append({"job_id": job["job_id"], "page_id": job["page_id"],
                "unit_id": job["unit_id"], "claim_token": token,
                "fingerprint": job["fingerprint"], "attempt": job["attempts"],
                "request": copy.deepcopy(job["request"]),
                "reference_paths": [item["path"] for item in job["reference_bindings"]],
                "reference_bindings": copy.deepcopy(job["reference_bindings"]),
                "lease_expires_at": job["lease"]["expires_at"],
                "render_status": "not-generated", "acceptance_status": "not-reviewed"})
        _write(state_path, state)
        return {"jobs": dispatch, "pilot_unlocked": unlocked,
                "pilot_block_reason": state.get("pilot_block_reason"), "summary": _summary(state)}


def _owned_job(state: dict, job_id: str, token: str) -> dict:
    job = state["jobs"].get(job_id)
    if not job or job["status"] != "inflight" or not job.get("lease") or job["lease"]["claim_token"] != token:
        raise QueueError("Job has no matching active claim; late/stale completions are rejected")
    if job.get("input_block_reason") or not state["pages"][job["page_id"]]["generation_ready"]:
        raise QueueError("Job inputs changed while generating; rebuild proof/sync before retry")
    return job


def complete_job(state_path: str | Path, job_id: str, claim_token: str,
                 asset_path: str | Path) -> dict:
    """Record only real existing image bytes, without accepting their contents."""
    with _lock(state_path):
        state = _load(state_path)
        _refresh(state)
        job = _owned_job(state, job_id, claim_token)
        path = Path(asset_path).resolve()
        _verify_image(path)
        asset = _file_binding(path)
        seconds = max(0.0, time.time() - job["lease"]["started_at"])
        asset.update(fingerprint=job["fingerprint"], acceptance_status="not-reviewed")
        job["asset"] = asset
        job["history"].append({"kind": "generated", "attempt": job["attempts"],
                               "seconds": seconds, "asset": asset, "time": time.time()})
        job["lease"] = None
        job["status"] = "generated_unreviewed"
        state["stats"]["completed_calls"] += 1
        state["stats"]["generation_seconds"] += seconds
        _event(state, "generated_unreviewed", job_id=job_id, seconds=seconds)
        _write(state_path, state)
        return {"job_id": job_id, "status": job["status"], "asset": asset}


def fail_job(state_path: str | Path, job_id: str, claim_token: str, reason: str) -> dict:
    """Only the failed scene job becomes eligible for a bounded retry."""
    if not reason.strip():
        raise QueueError("A failure reason is required")
    with _lock(state_path):
        state = _load(state_path)
        _refresh(state)
        job = _owned_job(state, job_id, claim_token)
        seconds = max(0.0, time.time() - job["lease"]["started_at"])
        job["history"].append({"kind": "generation_failed", "reason": reason,
                               "attempt": job["attempts"], "seconds": seconds, "time": time.time()})
        job["lease"] = None
        job["status"] = "pending" if job["attempts"] < state["max_attempts"] else "blocked"
        job["blocked_reason"] = "attempt_limit_reached" if job["status"] == "blocked" else None
        state["stats"]["generation_failures"] += 1
        state["stats"]["generation_seconds"] += seconds
        _event(state, "generation_failed", job_id=job_id, reason=reason)
        _write(state_path, state)
        return {"job_id": job_id, "status": job["status"], "attempts": job["attempts"],
                "blocked_reason": job["blocked_reason"]}


def record_text_issue(state_path: str | Path, page_id: str, reason: str) -> dict:
    """Track a compositor repair without invalidating successful scene assets."""
    if not reason.strip():
        raise QueueError("A text repair reason is required")
    with _lock(state_path):
        state = _load(state_path)
        if page_id not in state["pages"]:
            raise QueueError(f"Unknown page: {page_id}")
        state["pages"][page_id]["text_issues"].append({"reason": reason, "time": time.time()})
        state["stats"]["text_issues"] += 1
        if page_id == state["pilot_page_id"]:
            state["pilot_acceptance"] = None
        _event(state, "text_repair_required", page_id=page_id, reason=reason)
        _write(state_path, state)
        return {"page_id": page_id, "status": "needs_text_repair",
                "scene_assets_invalidated": False}


def accept_pilot(state_path: str | Path, base_image: str | Path, base_audit: str | Path,
                 final_image: str | Path, final_audit: str | Path) -> dict:
    """Unlock later pages only after actual base and final image evidence pass."""
    with _lock(state_path):
        state = _load(state_path)
        _refresh(state)
        acceptance = {"base_image": _file_binding(base_image), "base_audit": _file_binding(base_audit),
                      "final_image": _file_binding(final_image), "final_audit": _file_binding(final_audit),
                      "accepted_at": time.time(), "job_fingerprints": {
                          job["job_id"]: job["fingerprint"] for job in state["jobs"].values()
                          if job["page_id"] == state["pilot_page_id"]}}
        _validate_pilot(state, acceptance)
        state["pilot_acceptance"] = acceptance
        state["pilot_block_reason"] = None
        state["pages"][state["pilot_page_id"]]["text_issues"] = []
        _event(state, "actual_pilot_accepted")
        _write(state_path, state)
        return {"pilot_unlocked": True, "pilot_page_id": state["pilot_page_id"],
                "evidence": acceptance}


def recover_leases(state_path: str | Path, worker: str | None = None) -> dict:
    with _lock(state_path):
        state = _load(state_path)
        recovered = _recover(state, worker)
        _write(state_path, state)
        return {"recovered_jobs": recovered, "summary": _summary(state)}


def _summary(state: dict) -> dict:
    counts: dict[str, int] = {}
    for job in state["jobs"].values():
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    blocked_pages = {page_id: page["generation_block_reason"]
                     for page_id, page in state["pages"].items() if not page["generation_ready"]}
    expired = [job["job_id"] for job in state["jobs"].values()
               if job["status"] == "inflight" and job.get("lease")
               and job["lease"]["expires_at"] <= time.time()]
    return {"queue_version": state["queue_version"], "pipeline_version": state["pipeline_version"],
            "diagnostic_test_only": state.get('diagnostic_test_only') is True,
            "page_count": len(state["pages"]), "job_count": len(state["jobs"]),
            "job_status_counts": counts, "max_concurrency": state["max_concurrency"],
            "max_attempts": state["max_attempts"], "pilot_page_id": state["pilot_page_id"],
            "pilot_unlocked": state.get("pilot_acceptance") is not None,
            "blocked_pages": blocked_pages, "stats": copy.deepcopy(state["stats"]),
            "expired_leases_awaiting_explicit_recovery": expired,
            "wall_seconds": max(0.0, time.time() - state["created_at"]),
            "acceptance_cache": "disabled; generated asset reuse only"}


def queue_status(state_path: str | Path) -> dict:
    with _lock(state_path):
        state = _load(state_path)
        _refresh(state)
        _pilot_unlocked(state)
        _write(state_path, state)
        result = _summary(state)
        result["pilot_block_reason"] = state.get("pilot_block_reason")
        result["jobs"] = [{"job_id": job["job_id"], "status": job["status"],
            "attempts": job["attempts"], "asset": job.get("asset"),
            "blocked_reason": job.get("blocked_reason") or job.get("input_block_reason")}
            for job in state["jobs"].values()]
        return result


def main() -> int:
    # Queue handoffs contain Chinese absolute paths and must remain parseable
    # when subprocess pipes inherit Windows' legacy console code page.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "sync", "claim", "complete", "fail", "recover", "status", "accept-pilot", "record-text-issue"):
        command = sub.add_parser(name)
        command.add_argument("--state", type=Path, required=True)
        if name in {"init", "sync"}:
            command.add_argument("--manifest", type=Path, required=True)
        if name == "init":
            command.add_argument("--max-concurrency", type=int, default=4)
            command.add_argument("--max-attempts", type=int, default=3)
            command.add_argument('--diagnostic', action='store_true', help='Allow explicitly marked diagnostic-only requests')
        if name == "claim":
            command.add_argument("--worker", required=True)
            command.add_argument("--limit", type=int)
            command.add_argument("--lease-seconds", type=float, default=1800,
                                 help="Advisory deadline; expiry never redispatches a possibly live image call automatically")
        if name == "recover":
            command.add_argument("--worker", help="Explicitly abandon all leases of this known stopped worker; otherwise expired leases only")
        if name in {"complete", "fail"}:
            command.add_argument("--job-id", required=True)
            command.add_argument("--claim-token", required=True)
        if name == "complete":
            command.add_argument("--asset", type=Path, required=True)
        if name in {"fail", "record-text-issue"}:
            command.add_argument("--reason", required=True)
        if name == "record-text-issue":
            command.add_argument("--page-id", required=True)
        if name == "accept-pilot":
            for key in ("base-image", "base-audit", "final-image", "final-audit"):
                command.add_argument(f"--{key}", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = init_queue(args.manifest, args.state, max_concurrency=args.max_concurrency, max_attempts=args.max_attempts, diagnostic=args.diagnostic)
        elif args.command == "sync":
            result = sync_queue(args.manifest, args.state)
        elif args.command == "claim":
            result = claim_jobs(args.state, args.worker, limit=args.limit, lease_seconds=args.lease_seconds)
        elif args.command == "complete":
            result = complete_job(args.state, args.job_id, args.claim_token, args.asset)
        elif args.command == "fail":
            result = fail_job(args.state, args.job_id, args.claim_token, args.reason)
        elif args.command == "recover":
            result = recover_leases(args.state, args.worker)
        elif args.command == "status":
            result = queue_status(args.state)
        elif args.command == "record-text-issue":
            result = record_text_issue(args.state, args.page_id, args.reason)
        else:
            result = accept_pilot(args.state, args.base_image, args.base_audit, args.final_image, args.final_audit)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (QueueError, OSError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
