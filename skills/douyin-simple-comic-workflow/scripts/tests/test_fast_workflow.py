"""Offline FAST workflow contracts; all generated image fixtures are SIMULATED.

These tests never call an image tool or an external API. Pillow is used only to
make explicitly labelled, disposable simulator outputs under TemporaryDirectory.
"""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image, PngImagePlugin

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import fast_prepare
import fast_queue


class FastWorkflowOffline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fast-simulation-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.source = self.inputs / "article.md"
        self.source.write_text("小海回家，看见妈妈留着灯。妈妈递来一杯热水，两人笑了。", encoding="utf-8")
        self.reference = self.simulated_image("inputs/reference.png", color="coral")
        self.run = self.root / "project"
        self.spec = {
            "mode": "fast",
            "source_path": str(self.source),
            "analysis": {"source_facts": ["小海回家", "妈妈留灯"], "open_questions": []},
            "characters": [{"character_id": "N01", "description": "小海，短发，蓝上衣",
                            "reference_paths": [str(self.reference)]}],
            "style": {"prompt": "Simple Chinese hand-drawn diary comic, white paper, black felt-tip lines.",
                      "reference_paths": [str(self.reference)]},
            "layout_policy": "uniform_by_user_request",
            "uniform_layout_request": {"source": "user", "instruction_excerpt":
                "SIMULATION fixture: use SB-002 for these three queue-regression pages."},
            "pages": [self.page(i) for i in range(1, 4)],
        }

    @staticmethod
    def page(number):
        pid = f"P{number:02d}"
        return {"page_id": pid, "layout_id": "SB-002",
                "narrative_function": f"第{number}次归家回应，表现小海逐渐放松的情绪",
                "panel_count_reason": "四个连续节点分别承接进门、看灯、递水与微笑，保持动作顺序。",
                "panels": [{"description": f"Page {number}, action {i}",
                            "focus": f"小海归家回应的第{i}个节点",
                            "main_action_or_emotion": f"通过第{i}个连续动作逐渐放松"} for i in range(1, 5)],
                "prompt": f"One complete four-panel comic page {number}, N01 enters a warm home. No text, no letters, no captions.",
                "reference_paths": [], "captions": []}

    def simulated_image(self, name, color="white"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("test_fixture", "SIMULATED OUTPUT: not GPT artwork, offline test only")
        Image.new("RGB", (120, 160), color).save(path, pnginfo=metadata)
        return path

    def write_spec(self, spec=None):
        path = self.inputs / "fast-input.json"
        path.write_text(json.dumps(self.spec if spec is None else spec, ensure_ascii=False), encoding="utf-8")
        return path

    def prepare(self, simulation=True, spec=None):
        fast_prepare.prepare(self.write_spec(spec), self.run, simulation=simulation)
        fast_queue.init_queue(self.run)
        return self.read_state()

    def read_state(self):
        return json.loads((self.run / "fast/state.json").read_text(encoding="utf-8"))

    def read_plan(self):
        return json.loads((self.run / "fast/plan.json").read_text(encoding="utf-8"))

    def claim(self, expected="P01"):
        claim = fast_queue.claim_page(self.run)
        self.assertEqual(claim.get("status"), "claimed", claim)
        self.assertEqual(claim["page_id"], expected, claim)
        return claim

    def complete(self, claim, color="skyblue"):
        output = self.simulated_image(
            f"SIMULATED_TOOL_OUTPUTS/{claim['page_id']}-{claim['attempt']}.png", color=color)
        result = fast_queue.complete_page(self.run, claim["page_id"], claim["claim_token"],
            output, f"SIMULATED-CALL-{claim['page_id']}-{claim['attempt']}", provider="simulation")
        if self.read_plan().get("visual_review_required"):
            self.review(claim["page_id"], result["image_sha256"])
        return output, result

    def review(self, page_id, image_hash):
        # Mechanical queue fixture only, never real-image story acceptance.
        evidence = {"page_id": page_id, "image_sha256": image_hash,
                    "simulation": True, "geometry_observed_from_image": True,
                    "checks": {name: {"passed": True, "reason": "SIMULATION: declared queue-test fixture"}
                               for name in ("character_consistency", "story_coverage", "storyboard_execution")}}
        review_path = self.root / f"SIMULATED-{page_id}-review.json"
        review_path.write_text(json.dumps(evidence), encoding="utf-8")
        return fast_queue.review_page(self.run, page_id, review_path)

    def failed_operation(self, operation):
        """Allow CLI-oriented results or validation exceptions, but never a pass."""
        try:
            result = operation()
        except (ValueError, RuntimeError, FileNotFoundError):
            return
        self.assertIsInstance(result, dict, result)
        self.assertNotIn(result.get("status"), {"claimed", "succeeded", "complete", "ready", "passed"}, result)

    def test_prepare_freezes_separate_artifacts_and_no_text_prompts(self):
        self.prepare()
        for filename in ("analysis.json", "characters.json", "style.json", "storyboard.json"):
            path = self.run / "fast/planning" / filename
            self.assertTrue(path.is_file(), filename)
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))
        self.assertEqual((self.run / "source/article.md").read_text(encoding="utf-8"),
                         self.source.read_text(encoding="utf-8"))
        self.assertTrue((self.run / "fast/config.json").is_file())
        for page_id in ("P01", "P02", "P03"):
            prompt = self.run / "fast/prompts" / f"{page_id}.txt"
            self.assertTrue(prompt.is_file())
            self.assertIn("No text", prompt.read_text(encoding="utf-8"))
        self.assertTrue(self.read_plan().get("simulation"))

    def test_prepare_reads_only_selected_sb_rules(self):
        read_paths = []
        original = Path.read_text

        def track_reads(path, *args, **kwargs):
            read_paths.append(path)
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", new=track_reads):
            self.prepare()
        sb_rules = {p.name for p in read_paths if p.suffix == ".md" and p.name.startswith("SB-")}
        self.assertEqual(sb_rules, {"SB-002.md"})

    def test_shared_references_are_snapshotted_and_reused_in_requests(self):
        self.prepare()
        original_reference = self.reference.resolve()
        first = self.claim()
        first_refs = first["request"].get("referenced_image_paths", [])
        self.assertTrue(first_refs)
        self.assertNotIn(str(original_reference), first_refs)
        for ref in first_refs:
            self.assertTrue(Path(ref).is_relative_to(self.run))
        self.reference.unlink()
        self.complete(first)
        next_page = self.claim("P02")
        second_refs = next_page["request"].get("referenced_image_paths", [])
        self.assertTrue(set(first_refs).issubset(second_refs))
        self.assertTrue(all(Path(ref).is_file() for ref in second_refs))

    def test_first_page_gate_and_success_copy_survive_external_output_deletion(self):
        self.prepare()
        claim = self.claim()
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "waiting")
        output, _ = self.complete(claim)
        page = self.read_state()["pages"]["P01"]
        self.assertEqual(page["status"], "succeeded")
        saved = Path(page["output_path"])
        if not saved.is_absolute():
            saved = self.run / saved
        self.assertNotEqual(output.resolve(), saved.resolve())
        self.assertTrue(saved.is_relative_to(self.run))
        self.assertEqual(saved.read_bytes(), output.read_bytes())
        output.unlink()
        with Image.open(saved) as im:
            im.load()
            self.assertEqual(im.size, (120, 160))
        self.claim("P02")

    def test_completed_page_is_skipped_and_all_successes_end_queue(self):
        self.prepare()
        saved_hashes = {}
        for pid in ("P01", "P02", "P03"):
            claim = self.claim(pid)
            self.complete(claim)
            page = self.read_state()["pages"][pid]
            saved_hashes[pid] = page["image_sha256"]
        fast_queue.init_queue(self.run)
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "complete")
        for pid, page in self.read_state()["pages"].items():
            self.assertEqual(page["attempts"], 1)
            self.assertEqual(page["image_sha256"], saved_hashes[pid])

    def test_saved_output_corruption_retries_only_invalid_page(self):
        self.prepare()
        self.complete(self.claim("P01"))
        self.complete(self.claim("P02"))
        state = self.read_state()
        first_hash = state["pages"]["P01"]["image_sha256"]
        damaged = Path(state["pages"]["P02"]["output_path"])
        damaged.write_bytes(b"SIMULATED corruption after registration")
        fast_queue.status(self.run)
        self.assertEqual(self.read_state()["pages"]["P02"]["status"], "failed")
        retry = self.claim("P02")
        self.assertEqual(retry["attempt"], 2)
        self.complete(retry)
        self.assertEqual(self.read_state()["pages"]["P01"]["image_sha256"], first_hash)
        self.assertEqual(self.read_state()["pages"]["P01"]["attempts"], 1)

    def test_reservation_log_distinguishes_unknown_from_recorded_tool_call(self):
        self.prepare()
        claim = self.claim()
        summary = fast_queue.status(self.run)
        self.assertEqual(summary["counts"]["dispatched_attempts"], 1)
        self.assertEqual(summary["counts"]["recorded_tool_calls"], 0)
        self.assertEqual(summary["counts"]["unknown_tool_results"], 1)
        self.complete(claim)
        summary = fast_queue.status(self.run)
        self.assertEqual(summary["counts"]["recorded_tool_calls"], 1)
        self.assertEqual(summary["counts"]["unknown_tool_results"], 0)
        self.assertNotIn("cost", summary)
        self.assertNotIn("tokens", summary)
        self.assertTrue(self.read_state()["pages"]["P01"]["needs_human_review"])

    def test_failed_page_only_retries_and_two_attempt_limit_is_persistent(self):
        self.prepare()
        self.complete(self.claim("P01"))
        first = self.claim("P02")
        fast_queue.fail_page(self.run, "P02", first["claim_token"], "SIMULATED image tool failure")
        retry = self.claim("P02")
        self.assertEqual(retry["attempt"], 2)
        fast_queue.fail_page(self.run, "P02", retry["claim_token"], "SIMULATED second failure")
        fast_queue.init_queue(self.run)
        fast_queue.claim_page(self.run)
        state = self.read_state()
        self.assertEqual(state["pages"]["P01"]["status"], "succeeded")
        self.assertEqual(state["pages"]["P01"]["attempts"], 1)
        self.assertEqual(state["pages"]["P02"]["attempts"], 2)
        self.assertNotEqual(state["pages"]["P02"]["status"], "inflight")

    def test_successful_retry_then_next_page(self):
        self.prepare()
        first = self.claim()
        fast_queue.fail_page(self.run, "P01", first["claim_token"], "SIMULATED transient failure")
        retry = self.claim()
        self.assertEqual(retry["attempt"], 2)
        self.complete(retry)
        self.claim("P02")
        self.assertEqual(self.read_state()["pages"]["P01"]["attempts"], 2)

    def test_restart_keeps_inflight_claim_until_explicit_recovery(self):
        self.prepare()
        first = self.claim()
        fast_queue.init_queue(self.run)
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "waiting")
        self.assertEqual(self.read_state()["pages"]["P01"]["attempts"], 1)
        fast_queue.recover_page(self.run, "P01", "SIMULATED process interrupted; checked no output")
        second = self.claim()
        self.assertEqual(second["attempt"], 2)
        self.assertNotEqual(second["claim_token"], first["claim_token"])

    def test_stale_claim_cannot_complete_recovered_attempt(self):
        self.prepare()
        old = self.claim()
        fast_queue.recover_page(self.run, "P01", "SIMULATED interruption")
        new = self.claim()
        output = self.simulated_image("SIMULATED_TOOL_OUTPUTS/stale.png")
        self.failed_operation(lambda: fast_queue.complete_page(self.run, "P01", old["claim_token"],
            output, "SIMULATED-STALE", provider="simulation"))
        page = self.read_state()["pages"]["P01"]
        self.assertNotEqual(page["status"], "succeeded")
        self.assertEqual(page["claim_token"], new["claim_token"])

    def test_missing_and_corrupt_output_cannot_be_registered_successful(self):
        for output_kind in ("missing", "corrupt"):
            with self.subTest(output_kind=output_kind):
                self.run = self.root / output_kind
                self.prepare()
                claim = self.claim()
                output = self.root / f"SIMULATED_TOOL_OUTPUTS/{output_kind}.png"
                output.parent.mkdir(exist_ok=True)
                if output_kind == "corrupt":
                    output.write_bytes(b"SIMULATED invalid png bytes")
                self.failed_operation(lambda: fast_queue.complete_page(self.run, "P01", claim["claim_token"],
                    output, "SIMULATED-INVALID", provider="simulation"))
                self.assertNotEqual(self.read_state()["pages"]["P01"]["status"], "succeeded")

    def test_failed_image_import_can_resume_without_another_generation_attempt(self):
        self.prepare()
        claim = self.claim()
        output = self.root / "SIMULATED_TOOL_OUTPUTS/delayed-output.png"
        tool_id = "SIMULATED-IMPORT-RETRY"
        self.failed_operation(lambda: fast_queue.complete_page(self.run, "P01", claim["claim_token"],
            output, tool_id, provider="simulation"))
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "waiting")
        self.assertEqual(self.read_state()["pages"]["P01"]["attempts"], 1)
        self.simulated_image("SIMULATED_TOOL_OUTPUTS/delayed-output.png")
        fast_queue.complete_page(self.run, "P01", claim["claim_token"], output, tool_id, provider="simulation")
        page = self.read_state()["pages"]["P01"]
        self.assertEqual(page["status"], "succeeded")
        self.assertEqual(page["attempts"], 1)

    def test_partial_copy_is_preserved_and_local_save_retry_keeps_one_generation(self):
        self.prepare()
        claim = self.claim()
        source = self.simulated_image("SIMULATED_TOOL_OUTPUTS/copy-interrupted.png")
        original_bytes = source.read_bytes()

        def interrupted_copy(input_stream, output_stream):
            output_stream.write(input_stream.read(17))
            raise OSError("SIMULATED disk interruption")

        with mock.patch.object(fast_queue.shutil, "copyfileobj", side_effect=interrupted_copy):
            self.failed_operation(lambda: fast_queue.complete_page(self.run, "P01", claim["claim_token"],
                source, "SIMULATED-PARTIAL-COPY", provider="simulation"))
        partials = list((self.run / "fast/images/P01").glob("*.png"))
        self.assertEqual(len(partials), 1)
        partial = partials[0]
        partial_bytes = partial.read_bytes()
        self.assertNotEqual(partial_bytes, original_bytes)
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "waiting")
        result = fast_queue.complete_page(self.run, "P01", claim["claim_token"], source,
                                         "SIMULATED-PARTIAL-COPY", provider="simulation")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(partial.read_bytes(), partial_bytes)
        self.assertEqual(Path(result["output_path"]).read_bytes(), original_bytes)
        self.assertEqual(self.read_state()["pages"]["P01"]["attempts"], 1)
        self.assertEqual(fast_queue.status(self.run)["counts"]["recorded_tool_calls"], 1)

    def test_repeated_result_registration_is_idempotent(self):
        self.prepare()
        claim = self.claim()
        output, first_result = self.complete(claim)
        saved = Path(first_result["output_path"])
        before = saved.stat().st_mtime_ns
        repeated = fast_queue.complete_page(self.run, "P01", claim["claim_token"], output,
            "SIMULATED-CALL-P01-1", provider="simulation")
        self.assertEqual(repeated["output_path"], str(saved))
        self.assertEqual(saved.stat().st_mtime_ns, before)
        self.assertEqual(fast_queue.status(self.run)["counts"]["recorded_tool_calls"], 1)
        self.assertEqual(self.read_state()["pages"]["P01"]["attempts"], 1)

    def test_same_tool_call_cannot_be_counted_twice_across_pages(self):
        self.prepare()
        first = self.claim()
        self.complete(first)
        second = self.claim("P02")
        output = self.simulated_image("SIMULATED_TOOL_OUTPUTS/duplicate-call.png")
        self.failed_operation(lambda: fast_queue.complete_page(self.run, "P02", second["claim_token"],
            output, "SIMULATED-CALL-P01-1", provider="simulation"))
        self.assertNotEqual(self.read_state()["pages"]["P02"]["status"], "succeeded")
        self.assertEqual(fast_queue.status(self.run)["counts"]["recorded_tool_calls"], 1)

    def test_changed_frozen_prompt_blocks_dispatch_without_new_attempt(self):
        self.prepare()
        prompt = self.run / "fast/prompts/P01.txt"
        prompt.write_text(prompt.read_text(encoding="utf-8") + "\nUnauthorized change", encoding="utf-8")
        self.failed_operation(lambda: fast_queue.claim_page(self.run))
        self.assertEqual(self.read_state()["pages"]["P01"]["attempts"], 0)

    def test_changed_frozen_reference_blocks_dispatch(self):
        self.prepare()
        plan = self.read_plan()
        page = plan["pages"][0] if isinstance(plan["pages"], list) else plan["pages"]["P01"]
        references = [b["path"] for b in page.get("reference_bindings", [])]
        self.assertTrue(references, page)
        frozen_reference = Path(references[0])
        if not frozen_reference.is_absolute():
            frozen_reference = self.run / frozen_reference
        frozen_reference.write_bytes(b"SIMULATED reference changed")
        self.failed_operation(lambda: fast_queue.claim_page(self.run))
        self.assertEqual(self.read_state()["pages"]["P01"]["attempts"], 0)

    def test_resume_uses_saved_plan_without_reading_original_story(self):
        self.prepare()
        self.complete(self.claim())
        self.source.unlink()
        (self.inputs / "fast-input.json").unlink()
        fast_prepare.prepare(self.inputs / "missing-original-draft.json", self.run, simulation=True)
        fast_queue.init_queue(self.run)
        self.claim("P02")

    def test_simulation_result_rejected_by_real_project(self):
        self.prepare(simulation=False)
        claim = self.claim()
        output = self.simulated_image("SIMULATED_TOOL_OUTPUTS/forbidden.png")
        self.failed_operation(lambda: fast_queue.complete_page(self.run, "P01", claim["claim_token"],
            output, "SIMULATED-FORBIDDEN", provider="simulation"))
        self.assertNotEqual(self.read_state()["pages"]["P01"]["status"], "succeeded")

    def test_unavailable_builtin_tool_stops_run_until_explicit_resume(self):
        self.prepare()
        fast_queue.stop_run(self.run, "Codex built-in image_gen unavailable")
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "stopped")
        self.assertTrue(all(p["attempts"] == 0 for p in self.read_state()["pages"].values()))
        fast_queue.resume_run(self.run)
        self.claim()

    def test_existing_frozen_project_is_not_overwritten_by_new_story(self):
        self.prepare()
        old_plan = (self.run / "fast/plan.json").read_bytes()
        self.source.write_text("另一篇不相关的故事。", encoding="utf-8")
        modified = copy.deepcopy(self.spec)
        modified["pages"][0]["prompt"] = "Changed story prompt"
        fast_prepare.prepare(self.write_spec(modified), self.run, simulation=True)
        self.assertEqual((self.run / "fast/plan.json").read_bytes(), old_plan)

    def test_duplicate_and_path_traversing_page_ids_rejected_before_creation(self):
        for page_id in ("P01", "../P99"):
            with self.subTest(page_id=page_id):
                draft = copy.deepcopy(self.spec)
                draft["pages"][1]["page_id"] = page_id
                self.run = self.root / ("duplicate" if page_id == "P01" else "traversal")
                self.failed_operation(lambda: fast_prepare.prepare(self.write_spec(draft), self.run, simulation=True))
                self.assertFalse((self.run / "fast/plan.json").exists())

    def test_exact_layout_request_routes_away_from_fast(self):
        draft = copy.deepcopy(self.spec)
        draft["requires_exact_bubbles"] = True
        self.failed_operation(lambda: fast_prepare.prepare(self.write_spec(draft), self.run, simulation=True))
        self.assertFalse((self.run / "fast/plan.json").exists())

    def test_retry_and_resume_do_not_invoke_whole_story_prepare(self):
        self.prepare()
        with mock.patch.object(fast_prepare, "prepare", side_effect=AssertionError("whole-story planning repeated")):
            claim = self.claim()
            fast_queue.fail_page(self.run, "P01", claim["claim_token"], "SIMULATED transient failure")
            fast_queue.init_queue(self.run)
            self.complete(self.claim())
            self.claim("P02")

    def test_cli_lifecycle_serializes_concurrent_claims_and_copies_simulator_output(self):
        self.run = self.root / "CLI project 空格"
        spec_path = self.write_spec()
        # Exercise each CLI's explicit UTF-8 stdout under the Windows default
        # encoding, rather than hiding the boundary with interpreter UTF-8 mode.
        environment = dict(os.environ, PYTHONUTF8="0")

        def cli(script, *arguments):
            process = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, arguments)],
                capture_output=True, text=True, encoding="utf-8", env=environment, timeout=15)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertEqual(len(process.stdout.strip().splitlines()), 1, process.stdout)
            return json.loads(process.stdout)

        prepared = cli("fast_prepare.py", "prepare", "--plan", spec_path,
                       "--run-root", self.run, "--simulation")
        self.assertEqual(prepared["counts"]["dispatched_attempts"], 0)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: cli("fast_queue.py", "claim", "--run-root", self.run), range(2)))
        self.assertCountEqual([r["status"] for r in results], ["claimed", "waiting"])
        claim = next(r for r in results if r["status"] == "claimed")
        self.assertIn("小海，短发，蓝上衣", claim["request"]["prompt"])
        self.assertIn("空格", claim["request"]["referenced_image_paths"][0])
        output = self.simulated_image("SIMULATED_TOOL_OUTPUTS/cli-output.png")
        result = cli("fast_queue.py", "complete", "--run-root", self.run, "--page-id", "P01",
                     "--claim-token", claim["claim_token"], "--image", output,
                     "--tool-call-id", "SIMULATED-CLI-CALL", "--provider", "simulation")
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(Path(result["output_path"]).is_file())
        if self.read_plan().get("visual_review_required"):
            self.review("P01", result["image_sha256"])
        resumed = cli("fast_queue.py", "status", "--run-root", self.run)
        self.assertEqual(resumed["counts"]["recorded_tool_calls"], 1)
        next_page = cli("fast_queue.py", "claim", "--run-root", self.run)
        self.assertEqual(next_page["page_id"], "P02")

        layouts = cli("fast_prepare.py", "layouts", "--query", "four", "--limit", "1")
        name = layouts["layouts"][0]["name"]
        self.assertTrue(any("\u4e00" <= char <= "\u9fff" for char in name), name)


if __name__ == "__main__":
    unittest.main()
