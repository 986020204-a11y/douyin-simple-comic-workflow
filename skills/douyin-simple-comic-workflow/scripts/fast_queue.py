#!/usr/bin/env python3
"""Offline handoff for Codex's built-in image_gen; never calls an image API.

The frozen FAST plan and each input are hash-bound. A claim reserves one of at
most two attempts, but is not proof that a tool call occurred. Record the real
tool call ID on complete/fail; unknown calls remain explicitly unknown after a
crash. An inflight claim never expires automatically. Simulation artifacts are
accepted only in an explicitly simulated plan and never constitute GPT output.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from typing import Any
import uuid

from PIL import Image


class QueueError(ValueError):
    """A queue operation cannot safely proceed."""


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise QueueError(f"Cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise QueueError(f"Expected JSON object: {path}")
    return value


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


@contextlib.contextmanager
def _lock(path: Path, timeout: float = 15):
    lock_path = Path(str(path) + ".lock")
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
                    raise QueueError("Timed out waiting for FAST state lock")
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


def _paths(run_root: str | Path) -> tuple[Path, Path, Path]:
    root = Path(run_root).resolve()
    return root, root / "fast" / "plan.json", root / "fast" / "state.json"


@contextlib.contextmanager
def _final_operation_lock(root: Path, plan_path: Path, state_path: Path):
    """Keep selection stable until a claim/review commits; lock state first."""
    with _lock(state_path):
        try:
            required = _read(plan_path).get("first_final_review_required", False)
        except QueueError:
            required = False  # _checked persists the ordinary frozen-input stop.
        if required:
            from fast_caption import _selection_lock
            with _selection_lock(root):
                yield
        else:
            yield


def _event(state: dict, kind: str, **values: Any) -> None:
    now = time.time()
    state["updated_at"] = now
    # Actual call/result records also stay on each page's attempt_history.
    state.setdefault("events", []).append({"time": now, "kind": kind, **values})


def _image_info(path: Path) -> tuple[int, int, str]:
    try:
        with Image.open(path) as image:
            size, format_name = image.size, image.format or "PNG"
            image.verify()
        with Image.open(path) as image:
            image.load()
        if min(size) < 1:
            raise ValueError("Empty dimensions")
        return size[0], size[1], format_name
    except Exception as exc:
        raise QueueError(f"Image missing or unreadable: {path}") from exc


def _binding(binding: dict, *, image: bool = False) -> Path:
    if not isinstance(binding, dict) or not binding.get("path") or not binding.get("sha256"):
        raise QueueError("Frozen file binding requires path and sha256")
    path = Path(binding["path"])
    if not path.is_absolute():
        raise QueueError(f"Frozen file path must be absolute: {path}")
    if not path.is_file() or sha256(path) != binding["sha256"]:
        raise QueueError(f"Frozen input missing or changed: {path}")
    if image:
        _image_info(path)
    return path.resolve()


def _validate_plan(root: Path, plan: dict) -> None:
    if plan.get("schema_version") != 1 or plan.get("mode") != "fast":
        raise QueueError("Expected FAST plan schema version 1")
    if type(plan.get("simulation")) is not bool or plan.get("max_attempts") != 2:
        raise QueueError("FAST plan requires explicit simulation boolean and max_attempts=2")
    if "visual_review_required" in plan and type(plan["visual_review_required"]) is not bool:
        raise QueueError("visual_review_required must be an explicit boolean")
    if "first_final_review_required" in plan and type(plan["first_final_review_required"]) is not bool:
        raise QueueError("first_final_review_required must be an explicit boolean")
    pages = plan.get("pages")
    if not isinstance(pages, list) or not pages:
        raise QueueError("FAST plan requires pages")
    if not isinstance(plan.get("input_bindings"), list):
        raise QueueError("FAST plan requires input_bindings")
    for item in plan["input_bindings"]:
        _binding(item)
    ids = set()
    images_root = (root / "fast" / "images").resolve()
    for page in pages:
        page_id = page.get("page_id")
        if not isinstance(page_id, str) or not re.fullmatch(r"P[0-9]{2,}", page_id) or page_id in ids:
            raise QueueError("Page IDs must be unique P01-style identifiers")
        ids.add(page_id)
        _binding({"path": page.get("prompt_path"), "sha256": page.get("prompt_sha256")})
        if not Path(page["prompt_path"]).read_text(encoding="utf-8-sig").strip():
            raise QueueError(f"Empty page prompt: {page_id}")
        refs = page.get("reference_bindings", [])
        if not isinstance(refs, list):
            raise QueueError(f"Invalid reference bindings: {page_id}")
        for item in refs:
            _binding(item, image=True)
        output_dir = Path(page.get("output_dir", ""))
        if not output_dir.is_absolute() or output_dir.resolve() != images_root:
            raise QueueError("FAST output_dir must be this run's fast/images directory")
        if page.get("caption_plan_path"):
            _binding({"path": page["caption_plan_path"], "sha256": page.get("caption_plan_sha256")})
    if plan.get("first_page_id") not in ids:
        raise QueueError("FAST plan first_page_id must identify a page")
    if plan.get("first_final_review_required"):
        first = next(p for p in pages if p["page_id"] == plan["first_page_id"])
        if not plan.get("visual_review_required") or not first.get("caption_plan_path"):
            raise QueueError("First-final review requires base visual review and a caption plan")
        if not _read(Path(first["caption_plan_path"])).get("captions"):
            raise QueueError("Textless first pages do not need a lettering review gate")


def _checked(root: Path, plan_path: Path, state_path: Path) -> tuple[dict, dict]:
    state = _read(state_path)
    try:
        if not plan_path.is_file() or sha256(plan_path) != state.get("plan_sha256"):
            raise QueueError("Frozen FAST plan changed; use a new run for a new plan")
        plan = _read(plan_path)
        _validate_plan(root, plan)
        state["visual_review_required"] = plan.get("visual_review_required", False)
        state["first_final_review_required"] = plan.get("first_final_review_required", False)
    except (QueueError, OSError) as exc:
        state["status"] = "stopped"
        state["stop_reason"] = str(exc)
        state["stop_kind"] = "frozen_input_changed"
        _event(state, "stopped", reason=str(exc))
        _write(state_path, state)
        raise QueueError(str(exc)) from exc
    _refresh_first_final(root, plan, state)
    return plan, state


def _selected_first_final(root: Path, plan: dict, state: dict) -> tuple[dict, str]:
    # Reuse the compositor's file/path/hash validation; no story or image analysis.
    from fast_caption import _selected_revision

    first = state["pages"][plan["first_page_id"]]
    if first["status"] != "succeeded" or first.get("visual_review_status") != "passed":
        raise QueueError("Save and review the first base image before reviewing its lettered final")
    spec = next(p for p in plan["pages"] if p["page_id"] == first["page_id"])
    try:
        _, selection = _selected_revision(root, first["page_id"], state["plan_sha256"],
                                          first["image_sha256"], Path(spec["caption_plan_path"]).resolve())
    except (ValueError, OSError) as exc:
        raise QueueError(str(exc)) from exc
    if selection is None:
        raise QueueError("Locally letter and select the formal first page before continuing")
    fingerprint = hashlib.sha256(json.dumps(selection, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8")).hexdigest()
    return selection, fingerprint


def _refresh_first_final(root: Path, plan: dict, state: dict) -> None:
    if not state.get("first_final_review_required"):
        return  # Preserve frozen legacy runs without reading new review artifacts.
    state["first_final_review_status"] = "pending"
    state["first_final_output_path"] = None
    try:
        selection, fingerprint = _selected_first_final(root, plan, state)
        state["first_final_output_path"] = selection["output_path"]
        record = state.get("first_final_review")
        if not record or record.get("selection_sha256") != fingerprint:
            raise QueueError("View the current lettered first page and record its integrated comic review")
        _binding({"path": record.get("review_path"), "sha256": record.get("review_sha256")})
        state["first_final_review_status"] = record["status"]
        state["first_final_review_error"] = record.get("failure_reason")
    except (QueueError, OSError) as exc:
        # A missing/stale review needs local review or relettering, never regeneration.
        state["first_final_review_error"] = str(exc)


def validate_frozen(run_root: str | Path) -> dict:
    """Validate current frozen plan/input hashes; persist a stop on mismatch."""
    root, plan_path, state_path = _paths(run_root)
    with _lock(state_path):
        plan, _ = _checked(root, plan_path, state_path)
        return plan


def _refresh_outputs(state: dict) -> None:
    for page in state["pages"].values():
        if page["status"] != "succeeded":
            continue
        try:
            path = Path(page["output_path"])
            _image_info(path)
            if sha256(path) != page.get("image_sha256"):
                raise QueueError(f"Recorded image changed: {path}")
        except (QueueError, OSError, TypeError) as exc:
            page["status"] = "failed"
            page["error_reason"] = str(exc)
            page["needs_human_review"] = True
            page["errors"].append(str(exc))
            _event(state, "saved_image_invalid", page_id=page["page_id"], reason=str(exc))
            continue
        if state.get("visual_review_required") and page.get("visual_review_status") in {"passed", "failed"}:
            try:
                _binding({"path": page.get("visual_review_path"),
                          "sha256": page.get("visual_review_sha256")})
                if page.get("visual_review_image_sha256") != page["image_sha256"]:
                    raise QueueError("Visual review is bound to a different image")
            except (QueueError, OSError) as exc:
                # Review evidence failure never makes a good image eligible for
                # regeneration. Re-review the same saved image instead.
                page.update(visual_review_status="pending", needs_human_review=True,
                            visual_review_error=str(exc))
                _event(state, "visual_review_invalid", page_id=page["page_id"], reason=str(exc))
    if state["status"] != "stopped":
        state["status"] = ("complete" if all(p["status"] == "succeeded" and
                           (not state.get("visual_review_required") or
                            p.get("visual_review_status") == "passed")
                           for p in state["pages"].values()) and
                           (not state.get("first_final_review_required") or
                            state.get("first_final_review_status") == "passed")
                           else "active")


def _summary(state: dict) -> dict:
    pages = list(state["pages"].values())
    records = [attempt for page in pages for attempt in page["attempt_history"]]
    return {
        "status": state["status"], "mode": "fast", "simulation": state["simulation"],
        "visual_review_required": state.get("visual_review_required", False),
        "first_final_review_required": state.get("first_final_review_required", False),
        "first_final_review_status": state.get("first_final_review_status", "not_required"),
        "first_final_review_error": state.get("first_final_review_error"),
        "stop_reason": state.get("stop_reason"), "plan_sha256": state["plan_sha256"],
        "counts": {"pages": len(pages), "succeeded": sum(p["status"] == "succeeded" for p in pages),
                   "dispatched_attempts": sum(p["attempts"] for p in pages),
                   "recorded_tool_calls": sum(bool(a.get("tool_call_id")) for a in records),
                   "recorded_builtin_image_gen_calls": sum(bool(a.get("tool_call_id")) and
                                                           a.get("provider") == "codex.image_gen" for a in records),
                   "recorded_simulation_results": sum(bool(a.get("tool_call_id")) and
                                                      a.get("provider") == "simulation" for a in records),
                   "visual_reviews_passed": sum(p.get("visual_review_status") == "passed" for p in pages),
                   "visual_reviews_pending": sum(p["status"] == "succeeded" and
                                                  p.get("visual_review_status") == "pending" for p in pages),
                   "visual_reviews_failed": sum(p.get("visual_review_status") == "failed" for p in pages),
                   "unknown_tool_results": sum(a.get("tool_status") == "unknown" for a in records)},
        "usage_note": "Actual token, quota and cost data unavailable; no estimate recorded.",
        "usage": {"tokens": None, "quota": None, "cost": None},
        "pages": [{key: page.get(key) for key in (
            "page_id", "status", "prompt_sha256", "reference_paths", "output_path", "image_sha256",
            "attempts", "error_reason", "needs_human_review", "claim_token",
            "visual_review_status", "visual_review_path", "visual_review_sha256",
            "visual_review_image_sha256", "visual_retry_authorized")}
                  for page in pages],
    }


def init_queue(run_root: str | Path) -> dict:
    root, plan_path, state_path = _paths(run_root)
    with _lock(state_path):
        if state_path.exists():
            _, state = _checked(root, plan_path, state_path)
            _refresh_outputs(state)
            _write(state_path, state)
            return _summary(state)
        plan = _read(plan_path)
        _validate_plan(root, plan)
        state = {"schema_version": 1, "mode": "fast", "simulation": plan["simulation"],
                 "visual_review_required": plan.get("visual_review_required", False),
                 "first_final_review_required": plan.get("first_final_review_required", False),
                 "plan_sha256": sha256(plan_path), "status": "active", "stop_reason": None,
                 "created_at": time.time(), "pages": {}, "events": []}
        for page in plan["pages"]:
            refs = page.get("reference_bindings", [])
            state["pages"][page["page_id"]] = {
                "page_id": page["page_id"], "prompt_sha256": page["prompt_sha256"],
                "reference_bindings": refs, "reference_paths": [r["path"] for r in refs],
                "output_path": None, "image_sha256": None, "attempts": 0,
                "status": "pending", "error_reason": None, "errors": [],
                "needs_human_review": True, "claim_token": None, "attempt_history": [],
                "visual_review_status": ("pending" if plan.get("visual_review_required")
                                         else "legacy_not_required"),
                "visual_review_path": None, "visual_review_sha256": None,
                "visual_review_image_sha256": None, "visual_review_history": [],
                "visual_retry_authorized": False,
            }
        _refresh_first_final(root, plan, state)
        _event(state, "initialized")
        _write(state_path, state)
        return _summary(state)


def status(run_root: str | Path) -> dict:
    root, plan_path, state_path = _paths(run_root)
    with _lock(state_path):
        _, state = _checked(root, plan_path, state_path)
        _refresh_outputs(state)
        _write(state_path, state)
        return _summary(state)


def _downstream_completed(state: dict, first_page_id: str) -> bool:
    return any(p["page_id"] != first_page_id and any(a.get("output_path") for a in p["attempt_history"])
               for p in state["pages"].values())


def claim_page(run_root: str | Path) -> dict:
    root, plan_path, state_path = _paths(run_root)
    with _final_operation_lock(root, plan_path, state_path):
        plan, state = _checked(root, plan_path, state_path)
        _refresh_outputs(state)
        if state["status"] == "stopped":
            _write(state_path, state)
            return {"status": "stopped", "reason": state.get("stop_reason")}
        inflight = next((p for p in state["pages"].values()
                         if p["status"] in {"inflight", "save_failed"}), None)
        if inflight:
            _write(state_path, state)
            return {"status": "waiting", "page_id": inflight["page_id"],
                    "page_status": inflight["status"], "claim_token": inflight["claim_token"],
                    "attempt": inflight["attempts"],
                    "tool_call_id": inflight["attempt_history"][-1].get("tool_call_id"),
                    "source_path": inflight["attempt_history"][-1].get("source_path"),
                    "reason": ("Image import failed; retry complete with the same claim/tool result."
                               if inflight["status"] == "save_failed" else
                               "Existing call may still be running; complete it or explicitly recover.")}
        if state.get("visual_review_required"):
            unreviewed = next((p for p in state["pages"].values() if p["status"] == "succeeded"
                               and p.get("visual_review_status") != "passed"), None)
            if unreviewed:
                _write(state_path, state)
                failed = unreviewed.get("visual_review_status") == "failed"
                return {"status": "visual_review_failed" if failed else "awaiting_visual_review",
                        "page_id": unreviewed["page_id"], "output_path": unreviewed["output_path"],
                        "image_sha256": unreviewed["image_sha256"],
                        "visual_review_status": unreviewed.get("visual_review_status"),
                        "reason": ("Image content review failed. Caption issues use local reflow; "
                                   "an image retry requires the explicit retry-visual command."
                                   if failed else "View the actual saved image and record its visual review before continuing.")}
        first = state["pages"][plan["first_page_id"]]
        if (first["status"] == "succeeded" and state.get("first_final_review_required")
                and state.get("first_final_review_status") != "passed"):
            _write(state_path, state)
            failed = state.get("first_final_review_status") == "failed"
            return {"status": "final_review_failed" if failed else "awaiting_final_review",
                    "page_id": first["page_id"], "output_path": state.get("first_final_output_path"),
                    "reason": state.get("first_final_review_error") or
                              "Correct the first page locally and review its selected lettered final; no new image attempt is needed."}
        eligible = ([first] if first["status"] != "succeeded" else list(state["pages"].values()))
        page = next((p for p in eligible if p["status"] in {"pending", "failed"} and p["attempts"] < 2), None)
        if page is None:
            _write(state_path, state)
            return {"status": "complete" if state["status"] == "complete" else "exhausted",
                    "summary": _summary(state)}
        if (state.get("visual_review_required") and page["page_id"] == first["page_id"]
                and page["attempts"] and _downstream_completed(state, first["page_id"])):
            _write(state_path, state)
            return {"status": "blocked", "page_id": page["page_id"],
                    "reason": "The first page already anchors downstream images; preserve this run and use a new run to replace it."}
        spec = next(p for p in plan["pages"] if p["page_id"] == page["page_id"])
        refs = [dict(binding) for binding in spec.get("reference_bindings", [])]
        if plan.get("reuse_first_page_reference", False) and page["page_id"] != first["page_id"]:
            first_binding = {"path": first["output_path"], "sha256": first["image_sha256"]}
            _binding(first_binding, image=True)
            if first_binding["path"] not in [r["path"] for r in refs]:
                refs.append(first_binding)
        token = uuid.uuid4().hex
        page.update(status="inflight", attempts=page["attempts"] + 1,
                    claim_token=token, error_reason=None, reference_bindings=refs,
                    reference_paths=[r["path"] for r in refs])
        page["attempt_history"].append({"attempt": page["attempts"], "claim_token": token,
                                        "claimed_at": time.time(), "tool_status": "unknown",
                                        "tool_call_id": None, "provider": None,
                                        "reference_bindings": refs})
        prompt = Path(spec["prompt_path"]).read_text(encoding="utf-8-sig")
        if refs and state.get("visual_review_required"):
            prompt += ("\nReference-role constraint: inherit character identity, clothing and visual style only. "
                       "The current page's frozen storyboard controls camera, panel arrangement and character positions. "
                       "Do not copy the first page's layout or lettering positions.")
        request = {"prompt": prompt,
                   "transparent_background": False}
        if refs:
            request["referenced_image_paths"] = [r["path"] for r in refs]
        _event(state, "dispatch_claimed", page_id=page["page_id"], attempt=page["attempts"])
        _write(state_path, state)
        return {"status": "claimed", "page_id": page["page_id"], "attempt": page["attempts"],
                "claim_token": token, "request": request, "simulation": state["simulation"],
                "reference_roles": [{"path": ref["path"],
                                     "role": "first_page_identity_style" if ref["path"] == first.get("output_path")
                                     else "character_identity_or_style", "copy_layout": False} for ref in refs]}


def _claimed(state: dict, page_id: str, claim_token: str) -> dict:
    page = state["pages"].get(page_id)
    if page is None or not claim_token or page.get("claim_token") != claim_token:
        raise QueueError("Unknown page or stale claim token")
    return page


def _finish_failure(state: dict, page: dict, reason: str, *, tool_call_id: str | None = None,
                    provider: str | None = None, recovered: bool = False) -> None:
    page.update(status="failed", error_reason=reason, needs_human_review=True)
    page["errors"].append(reason)
    record = page["attempt_history"][-1]
    record.update(finished_at=time.time(), error_reason=reason)
    if tool_call_id:
        record.update(tool_call_id=tool_call_id, provider=provider, tool_status="failed")
    if recovered:
        record["recovered"] = True
        page["claim_token"] = None
    _event(state, "recovered" if recovered else "failed", page_id=page["page_id"], reason=reason)


def _copy_result(source: Path, directory: Path, attempt: int) -> tuple[Path, str, int, int]:
    """Reuse a verified previous copy, preserving partial/conflicting files."""
    width, height, format_name = _image_info(source)
    source_hash = sha256(source)
    extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif",
                 "TIFF": ".tiff", "BMP": ".bmp"}.get(format_name.upper(), ".img")
    directory.mkdir(parents=True, exist_ok=True)
    save_number = 1
    while True:
        suffix = "" if save_number == 1 else f"-save-{save_number:02d}"
        destination = directory / f"attempt-{attempt:02d}{suffix}{extension}"
        if not destination.exists():
            break
        try:
            _image_info(destination)
            if sha256(destination) == source_hash:
                return destination, source_hash, width, height
        except (OSError, QueueError):
            pass
        save_number += 1
    with source.open("rb") as input_stream, destination.open("xb") as output_stream:
        shutil.copyfileobj(input_stream, output_stream)
        output_stream.flush()
        os.fsync(output_stream.fileno())
    _image_info(destination)
    if sha256(destination) != source_hash or sha256(source) != source_hash:
        raise QueueError("Source image changed while copying")
    return destination, source_hash, width, height


def complete_page(run_root: str | Path, page_id: str, claim_token: str,
                  image_path: str | Path, tool_call_id: str,
                  provider: str = "codex.image_gen") -> dict:
    """Copy actual returned bytes, fully decode them, then record success.

    Local files/tool IDs are audit records, not cryptographic proof of origin.
    The calling agent must supply the actual built-in tool output file.
    """
    root, plan_path, state_path = _paths(run_root)
    with _lock(state_path):
        plan, state = _checked(root, plan_path, state_path)
        page = _claimed(state, page_id, claim_token)
        if not isinstance(tool_call_id, str) or not tool_call_id.strip():
            raise QueueError("Actual tool_call_id is required")
        if state["simulation"]:
            if provider != "simulation":
                raise QueueError("Simulation plans accept only provider=simulation")
        elif provider != "codex.image_gen":
            raise QueueError("Real FAST runs accept only the built-in codex.image_gen provider")
        if page["status"] == "succeeded":
            if page["attempt_history"][-1].get("tool_call_id") != tool_call_id:
                raise QueueError("Repeated completion requires the original tool_call_id")
            _refresh_outputs(state)
            _write(state_path, state)
            if page["status"] == "succeeded":
                return {"status": "succeeded", "page_id": page_id, "output_path": page["output_path"],
                        "image_sha256": page["image_sha256"],
                        "visual_review_status": page.get("visual_review_status"),
                        "already_completed": True}
            raise QueueError("Saved output is no longer valid; claim the remaining retry")
        if page["status"] not in {"inflight", "save_failed"}:
            raise QueueError("Completion requires an active inflight or save_failed claim")
        record = page["attempt_history"][-1]
        if record.get("tool_call_id") and record["tool_call_id"] != tool_call_id:
            raise QueueError("Saving the same claim requires the original tool_call_id")
        # Duplicated call IDs would misstate the actual-call log.
        if any(a is not record and a.get("tool_call_id") == tool_call_id
               for p in state["pages"].values() for a in p["attempt_history"]):
            raise QueueError("Tool call ID already recorded for another result")
        spec = next(p for p in plan["pages"] if p["page_id"] == page_id)
        record["save_attempts"] = record.get("save_attempts", 0) + 1
        record.setdefault("tool_result_received_at", time.time())
        try:
            source = Path(image_path).resolve()
            directory = Path(spec["output_dir"]) / page_id
            destination, image_hash, width, height = _copy_result(source, directory, page["attempts"])
        except (OSError, QueueError) as exc:
            reason = str(exc)
            # The tool result already exists. Retry local import, never generate
            # another candidate solely because disk access or decoding failed.
            page.update(status="save_failed", error_reason=reason,
                        save_error_reason=reason, needs_human_review=True)
            page["errors"].append(reason)
            record.update(tool_status="succeeded_save_failed", tool_call_id=tool_call_id,
                          provider=provider, source_path=str(image_path), save_error_reason=reason)
            _event(state, "save_failed", page_id=page_id, reason=reason, tool_call_id=tool_call_id)
            _write(state_path, state)
            raise QueueError(reason) from exc
        page.update(status="succeeded", output_path=str(destination.resolve()), image_sha256=image_hash,
                    error_reason=None, save_error_reason=None, needs_human_review=True,
                    artifact_origin="simulation" if state["simulation"] else "codex.image_gen")
        if state.get("visual_review_required"):
            page.update(visual_review_status="pending", visual_review_path=None,
                        visual_review_sha256=None, visual_review_image_sha256=None,
                        visual_review_error=None, visual_retry_authorized=False)
        page["attempt_history"][-1].update(
            finished_at=time.time(), tool_status="succeeded", tool_call_id=tool_call_id,
            provider=provider, source_path=str(source), output_path=page["output_path"],
            image_sha256=image_hash, width=width, height=height,
            provenance_note="Caller records actual tool output; local provenance is not cryptographically verified.")
        _event(state, "succeeded", page_id=page_id, attempt=page["attempts"], tool_call_id=tool_call_id)
        _refresh_outputs(state)
        _write(state_path, state)
        return {"status": "succeeded", "page_id": page_id, "output_path": page["output_path"],
                "image_sha256": image_hash, "needs_human_review": True,
                "visual_review_status": page.get("visual_review_status"),
                "artifact_origin": page["artifact_origin"]}


def _review_document(path: str | Path, page_id: str, image_hash: str) -> tuple[dict, bool, str]:
    """Validate the caller's image-viewing attestation, not computer vision proof."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise QueueError("Cannot read visual review JSON") from exc
    if not isinstance(document, dict) or document.get("page_id") != page_id:
        raise QueueError("Visual review must identify this page_id")
    if document.get("image_sha256") != image_hash:
        raise QueueError("Visual review image_sha256 is stale or does not match this image")
    if document.get("geometry_observed_from_image") is not True:
        raise QueueError("View the actual image before setting geometry_observed_from_image=true")
    kinds = {"character_consistency": "character", "story_coverage": "story",
             "storyboard_execution": "storyboard"}
    checks = document.get("checks")
    if not isinstance(checks, dict) or set(checks) != set(kinds):
        raise QueueError("Visual review requires character_consistency, story_coverage and storyboard_execution checks")
    failed = set()
    for name, check in checks.items():
        if (not isinstance(check, dict) or type(check.get("passed")) is not bool or
                not isinstance(check.get("reason"), str) or not check["reason"].strip()):
            raise QueueError("Each visual check requires explicit passed boolean and nonblank reason")
        if not check["passed"]:
            failed.add(kinds[name])
    if "caption_issues" in document and not isinstance(document["caption_issues"], list):
        raise QueueError("caption_issues must be a list; resolve those issues locally")
    if failed:
        if document.get("failure_kind") != "image":
            raise QueueError("Failed visual reviews require failure_kind=image; caption placement and font overflow use local reflow")
        if not isinstance(document.get("image_defect_reason"), str) or not document["image_defect_reason"].strip():
            raise QueueError("Failed visual reviews require an image_defect_reason")
        defects = document.get("image_defects")
        if not isinstance(defects, list) or not defects:
            raise QueueError("Failed visual reviews require image_defects")
        categories = set()
        for defect in defects:
            if (not isinstance(defect, dict) or defect.get("category") not in set(kinds.values())
                    or not isinstance(defect.get("reason"), str) or not defect["reason"].strip()):
                raise QueueError("Image defects must identify character, story or storyboard with a nonblank reason; captions are local-only")
            categories.add(defect["category"])
        if not failed.issubset(categories):
            raise QueueError("Each failed visual check needs a corresponding image defect category")
    elif document.get("image_defects"):
        raise QueueError("Passing checks cannot include image defects")
    digest = hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()
    return document, not failed, digest


def review_page(run_root: str | Path, page_id: str, review_path: str | Path) -> dict:
    """Record a hash-bound visual review after the caller views the saved page."""
    root, plan_path, state_path = _paths(run_root)
    with _lock(state_path):
        plan, state = _checked(root, plan_path, state_path)
        _refresh_outputs(state)
        page = state["pages"].get(page_id)
        if not state.get("visual_review_required"):
            raise QueueError("This legacy run has no visual-review gate; preserve its frozen workflow")
        if page is None or page["status"] != "succeeded":
            _write(state_path, state)
            raise QueueError("Visual review requires a valid saved image")
        document, passed, digest = _review_document(review_path, page_id, page["image_sha256"])
        previous = next((r for r in page.get("visual_review_history", [])
                         if r.get("document_sha256") == digest and
                         r.get("image_sha256") == page["image_sha256"]), None)
        if previous and (page.get("visual_review_sha256") == previous["review_sha256"] and
                         page.get("visual_review_status") == ("passed" if passed else "failed")):
            _write(state_path, state)
            return {"status": page["visual_review_status"], "page_id": page_id,
                    "visual_review_path": page["visual_review_path"], "already_reviewed": True,
                    "attempts": page["attempts"]}
        snapshot = root / "fast" / "reviews" / page_id / f"attempt-{page['attempts']:02d}-{digest}.json"
        if snapshot.exists() and _read(snapshot) != document:
            raise QueueError("Existing visual review snapshot changed; preserve it and supply a new review")
        if not snapshot.exists():
            _write(snapshot, document)
        snapshot_hash = sha256(snapshot)
        review_status = "passed" if passed else "failed"
        record = {"attempt": page["attempts"], "image_sha256": page["image_sha256"],
                  "document_sha256": digest, "review_path": str(snapshot), "review_sha256": snapshot_hash,
                  "status": review_status, "reviewed_at": time.time(),
                  "evidence_note": "Caller attests they viewed the actual image; no automatic vision verification is performed."}
        page.setdefault("visual_review_history", []).append(record)
        page.update(visual_review_status=review_status, visual_review_path=str(snapshot),
                    visual_review_sha256=snapshot_hash, visual_review_image_sha256=page["image_sha256"],
                    visual_review_error=None, visual_retry_authorized=False,
                    # Agent image review is separate from the eventual human
                    # acceptance of the finished, captioned comic.
                    needs_human_review=True)
        _event(state, "visual_review_recorded", page_id=page_id, result=review_status,
               image_sha256=page["image_sha256"], review_sha256=snapshot_hash)
        _refresh_outputs(state)
        _write(state_path, state)
        retry_available = (not passed and page["attempts"] < 2 and
                           not (page_id == plan["first_page_id"] and _downstream_completed(state, page_id)))
        return {"status": review_status, "page_id": page_id, "attempts": page["attempts"],
                "image_sha256": page["image_sha256"], "visual_review_path": str(snapshot),
                "visual_review_sha256": snapshot_hash, "retry_available": retry_available,
                "caption_issues": document.get("caption_issues", [])}


def review_final_page(run_root: str | Path, page_id: str, review_path: str | Path) -> dict:
    """Record actual viewing of the selected lettered first page, without an image call."""
    root, plan_path, state_path = _paths(run_root)
    with _final_operation_lock(root, plan_path, state_path):
        plan, state = _checked(root, plan_path, state_path)
        _refresh_outputs(state)
        if not state.get("first_final_review_required") or page_id != plan["first_page_id"]:
            raise QueueError("This frozen run/page has no first-final review gate")
        selection, fingerprint = _selected_first_final(root, plan, state)
        document = _read(Path(review_path))
        if (document.get("page_id") != page_id or
                document.get("image_sha256") != selection["output_sha256"] or
                document.get("caption_plan_sha256") != selection["caption_plan_sha256"]):
            raise QueueError("Final review must bind this page's current final image and caption plan hashes")
        if document.get("actual_final_viewed") is not True:
            raise QueueError("View the actual selected lettered final before setting actual_final_viewed=true")
        checks = document.get("checks")
        required = {"storyboard_expression", "text_scene_integration", "reading_order"}
        if not isinstance(checks, dict) or set(checks) != required:
            raise QueueError("Final review requires storyboard_expression, text_scene_integration and reading_order")
        for check in checks.values():
            if (not isinstance(check, dict) or type(check.get("passed")) is not bool or
                    not isinstance(check.get("reason"), str) or not check["reason"].strip()):
                raise QueueError("Each final check requires an explicit passed boolean and concrete viewing reason")
        result = "passed" if all(check["passed"] for check in checks.values()) else "failed"
        digest = hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")).encode("utf-8")).hexdigest()
        previous = state.get("first_final_review", {})
        if (previous.get("document_sha256") == digest and previous.get("selection_sha256") == fingerprint
                and state.get("first_final_review_status") == result):
            return {"status": result, "page_id": page_id, "already_reviewed": True,
                    "review_path": previous["review_path"], "generation_requested": False}
        snapshot = root / "fast" / "final-reviews" / page_id / f"{fingerprint}-{digest}.json"
        if snapshot.exists() and _read(snapshot) != document:
            raise QueueError("Existing final review snapshot changed; preserve it and supply a new review")
        if not snapshot.exists():
            _write(snapshot, document)
        record = {"selection_sha256": fingerprint, "document_sha256": digest,
                  "image_sha256": selection["output_sha256"],
                  "caption_plan_sha256": selection["caption_plan_sha256"],
                  "review_path": str(snapshot), "review_sha256": sha256(snapshot),
                  "status": result, "reviewed_at": time.time(),
                  "failure_reason": "; ".join(f"{name}: {check['reason']}" for name, check in checks.items()
                                              if not check["passed"]) or None,
                  "evidence_note": "Caller attests actual final-image viewing; no automatic aesthetic judgement is performed."}
        state.setdefault("first_final_review_history", []).append(record)
        state["first_final_review"] = record
        _refresh_first_final(root, plan, state)
        _refresh_outputs(state)
        _event(state, "first_final_review_recorded", page_id=page_id, result=result,
               image_sha256=selection["output_sha256"])
        _write(state_path, state)
        return {"status": result, "page_id": page_id, "review_path": str(snapshot),
                "generation_requested": False, "attempts": state["pages"][page_id]["attempts"]}


def retry_visual_page(run_root: str | Path, page_id: str, reason: str) -> dict:
    """Explicitly authorize the sole remaining image retry for a failed review."""
    root, plan_path, state_path = _paths(run_root)
    with _lock(state_path):
        plan, state = _checked(root, plan_path, state_path)
        _refresh_outputs(state)
        page = state["pages"].get(page_id)
        if not isinstance(reason, str) or not reason.strip():
            raise QueueError("Explicit image retry reason is required")
        if (not state.get("visual_review_required") or page is None or page["status"] != "succeeded"
                or page.get("visual_review_status") != "failed"):
            raise QueueError("Image retry requires a saved image with a current failed image-content review")
        if page["attempts"] >= 2:
            raise QueueError("FAST permits at most two image attempts per page")
        if page_id == plan["first_page_id"] and _downstream_completed(state, page_id):
            raise QueueError("Cannot replace the first page after downstream images exist; preserve this run and start a new one")
        # The original file and attempt/review records remain intact. This
        # authorization reserves no attempt and performs no generation.
        page.update(status="failed", visual_retry_authorized=True, error_reason=reason)
        _event(state, "visual_retry_authorized", page_id=page_id, reason=reason,
               previous_image_sha256=page["image_sha256"])
        _refresh_outputs(state)
        _write(state_path, state)
        return {"status": "retry_authorized", "page_id": page_id, "attempts": page["attempts"],
                "previous_output_path": page["output_path"], "previous_image_sha256": page["image_sha256"]}


def fail_page(run_root: str | Path, page_id: str, claim_token: str, reason: str,
              tool_call_id: str | None = None, provider: str | None = None) -> dict:
    root, plan_path, state_path = _paths(run_root)
    with _lock(state_path):
        _, state = _checked(root, plan_path, state_path)
        page = _claimed(state, page_id, claim_token)
        if not reason.strip():
            raise QueueError("Failure reason is required")
        if page["status"] == "failed":
            return {"status": "failed", "page_id": page_id, "attempts": page["attempts"]}
        if page["status"] != "inflight":
            raise QueueError("Failure requires an active inflight claim")
        expected_provider = "simulation" if state["simulation"] else "codex.image_gen"
        if provider is not None and provider != expected_provider:
            raise QueueError(f"This plan accepts only provider={expected_provider}")
        if tool_call_id is not None and (not isinstance(tool_call_id, str) or not tool_call_id.strip()):
            raise QueueError("Recorded tool_call_id must be nonblank")
        if tool_call_id and any(a.get("tool_call_id") == tool_call_id for p in state["pages"].values()
                                for a in p["attempt_history"]):
            raise QueueError("Tool call ID already recorded")
        _finish_failure(state, page, reason, tool_call_id=tool_call_id,
                        provider=expected_provider if tool_call_id else None)
        _write(state_path, state)
        return {"status": "failed", "page_id": page_id, "attempts": page["attempts"],
                "retry_available": page["attempts"] < 2}


def recover_page(run_root: str | Path, page_id: str, reason: str) -> dict:
    root, plan_path, state_path = _paths(run_root)
    with _lock(state_path):
        _, state = _checked(root, plan_path, state_path)
        page = state["pages"].get(page_id)
        if page is None or page["status"] not in {"inflight", "save_failed"}:
            raise QueueError("Recovery requires an inflight or save_failed page")
        if state.get("visual_review_required") and page["status"] == "save_failed":
            raise QueueError("An image tool result already exists. Restore or copy that output with complete and the original claim/tool_call_id; do not reserve a new image attempt for a save failure")
        if not reason.strip():
            raise QueueError("Explicit recovery reason is required")
        _finish_failure(state, page, reason, recovered=True)
        _write(state_path, state)
        return {"status": "recovered", "page_id": page_id, "attempts": page["attempts"],
                "tool_status": page["attempt_history"][-1]["tool_status"],
                "retry_available": page["attempts"] < 2}


def stop_run(run_root: str | Path, reason: str) -> dict:
    root, plan_path, state_path = _paths(run_root)
    with _lock(state_path):
        _, state = _checked(root, plan_path, state_path)
        if not reason.strip():
            raise QueueError("Stop reason is required")
        state.update(status="stopped", stop_reason=reason, stop_kind="explicit")
        _event(state, "stopped", reason=reason)
        _write(state_path, state)
        return {"status": "stopped", "reason": reason}


def resume_run(run_root: str | Path) -> dict:
    root, plan_path, state_path = _paths(run_root)
    with _lock(state_path):
        _, state = _checked(root, plan_path, state_path)
        state.update(status="active", stop_reason=None, stop_kind=None)
        _refresh_outputs(state)
        _event(state, "resumed")
        _write(state_path, state)
        return _summary(state)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("init", "status", "claim", "complete", "fail", "recover", "stop", "resume",
                    "review", "review-final", "retry-visual"):
        item = sub.add_parser(command)
        item.add_argument("--run-root", required=True)
        if command in {"complete", "fail", "recover", "review", "review-final", "retry-visual"}:
            item.add_argument("--page-id", required=True)
        if command in {"complete", "fail"}:
            item.add_argument("--claim-token", required=True)
            item.add_argument("--tool-call-id", required=command == "complete")
            item.add_argument("--provider", default="codex.image_gen" if command == "complete" else None)
        if command == "complete":
            item.add_argument("--image", required=True)
        if command in {"review", "review-final"}:
            item.add_argument("--review", required=True)
        if command in {"fail", "recover", "stop", "retry-visual"}:
            item.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "complete":
            result = complete_page(args.run_root, args.page_id, args.claim_token, args.image,
                                   args.tool_call_id, args.provider)
        elif args.command == "fail":
            result = fail_page(args.run_root, args.page_id, args.claim_token, args.reason,
                               args.tool_call_id, args.provider)
        elif args.command == "recover":
            result = recover_page(args.run_root, args.page_id, args.reason)
        elif args.command == "stop":
            result = stop_run(args.run_root, args.reason)
        elif args.command == "review":
            result = review_page(args.run_root, args.page_id, args.review)
        elif args.command == "review-final":
            result = review_final_page(args.run_root, args.page_id, args.review)
        elif args.command == "retry-visual":
            result = retry_visual_page(args.run_root, args.page_id, args.reason)
        else:
            result = {"init": init_queue, "status": status, "claim": claim_page,
                      "resume": resume_run}[args.command](args.run_root)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (QueueError, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
