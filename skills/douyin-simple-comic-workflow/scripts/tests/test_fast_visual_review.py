"""Offline image-review gates. All artwork fixtures are explicitly SIMULATED.

These tests verify state transitions and evidence binding. They do not claim to
perform computer vision or validate an actual generated comic's artistic merit.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image, PngImagePlugin

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import fast_queue


class FastVisualReviewOffline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="SIMULATED-fast-review-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "project"
        self.fast = self.run / "fast"
        self.fast.mkdir(parents=True)
        self.reference = self.image("reference.png", "coral")
        self.plan = {"schema_version": 1, "mode": "fast", "simulation": True,
                     "max_attempts": 2, "visual_review_required": True,
                     "first_page_id": "P01", "reuse_first_page_reference": True,
                     "input_bindings": [], "pages": []}
        for number in range(1, 4):
            pid = f"P{number:02d}"
            prompt = self.fast / f"{pid}.txt"
            prompt.write_text(f"SIMULATED planned page {pid}. Current layout controls composition.", encoding="utf-8")
            self.plan["pages"].append({"page_id": pid, "prompt_path": str(prompt),
                "prompt_sha256": fast_queue.sha256(prompt), "output_dir": str(self.fast / "images"),
                "reference_bindings": [{"path": str(self.reference),
                                        "sha256": fast_queue.sha256(self.reference)}]})
        self.save_plan()
        fast_queue.init_queue(self.run)

    def save_plan(self):
        (self.fast / "plan.json").write_text(json.dumps(self.plan), encoding="utf-8")

    def reset_queue(self):
        (self.fast / "state.json").unlink()
        self.save_plan()
        fast_queue.init_queue(self.run)

    def state(self):
        return json.loads((self.fast / "state.json").read_text(encoding="utf-8"))

    def image(self, name, color="skyblue"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("test_fixture", "SIMULATED OUTPUT: offline state tests only, not GPT artwork")
        Image.new("RGB", (120, 160), color).save(path, pnginfo=metadata)
        return path

    def claim(self, pid="P01"):
        result = fast_queue.claim_page(self.run)
        self.assertEqual(result["status"], "claimed", result)
        self.assertEqual(result["page_id"], pid, result)
        return result

    def complete(self, claim, color="skyblue"):
        source = self.image(f"SIMULATED/{claim['page_id']}-{claim['attempt']}.png", color)
        return fast_queue.complete_page(self.run, claim["page_id"], claim["claim_token"], source,
            f"SIMULATED-CALL-{claim['page_id']}-{claim['attempt']}", provider="simulation")

    def review_file(self, pid="P01", passed=True, **changes):
        page = self.state()["pages"][pid]
        document = {"page_id": pid, "image_sha256": page["image_sha256"],
            "geometry_observed_from_image": True,
            "checks": {name: {"passed": True, "reason": "SIMULATED image-viewing attestation for state test"}
                       for name in ("character_consistency", "story_coverage", "storyboard_execution")}}
        if not passed:
            document["checks"]["storyboard_execution"] = {"passed": False,
                "reason": "SIMULATED missing reaction panel"}
            document.update(failure_kind="image", image_defect_reason="SIMULATED missing reaction panel",
                image_defects=[{"category": "storyboard", "reason": "SIMULATED missing reaction panel"}])
        document.update(changes)
        path = self.root / f"review-{pid}.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def pass_review(self, pid="P01"):
        return fast_queue.review_page(self.run, pid, self.review_file(pid))

    def test_first_image_saved_but_next_dispatch_requires_review(self):
        result = self.complete(self.claim())
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["visual_review_status"], "pending")
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "awaiting_visual_review")
        self.assertEqual(self.state()["pages"]["P02"]["attempts"], 0)
        self.assertEqual(fast_queue.status(self.run)["counts"]["visual_reviews_pending"], 1)

    def test_every_page_gate_and_review_completion_have_no_new_tool_calls(self):
        for pid in ("P01", "P02", "P03"):
            self.complete(self.claim(pid))
            self.assertEqual(fast_queue.claim_page(self.run)["status"], "awaiting_visual_review")
            before = fast_queue.status(self.run)["counts"]["dispatched_attempts"]
            self.pass_review(pid)
            self.assertEqual(fast_queue.status(self.run)["counts"]["dispatched_attempts"], before)
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "complete")
        self.assertEqual(fast_queue.status(self.run)["counts"]["recorded_tool_calls"], 3)

    def test_resume_preserves_pending_review_and_saved_image(self):
        self.complete(self.claim())
        before = self.state()["pages"]["P01"]
        fast_queue.init_queue(self.run)
        fast_queue.resume_run(self.run)
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "awaiting_visual_review")
        after = self.state()["pages"]["P01"]
        self.assertEqual(after["image_sha256"], before["image_sha256"])
        self.assertEqual(after["attempts"], 1)

    def test_failed_review_does_not_automatically_regenerate(self):
        self.complete(self.claim())
        original = self.state()["pages"]["P01"]
        failed = fast_queue.review_page(self.run, "P01", self.review_file(passed=False))
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "visual_review_failed")
        page = self.state()["pages"]["P01"]
        self.assertEqual(page["status"], "succeeded")
        self.assertEqual(page["attempts"], 1)
        self.assertEqual(fast_queue.sha256(page["output_path"]), original["image_sha256"])

    def test_explicit_image_retry_preserves_original_and_maximum_two_attempts(self):
        self.complete(self.claim())
        original = copy.deepcopy(self.state()["pages"]["P01"])
        fast_queue.review_page(self.run, "P01", self.review_file(passed=False))
        authorization = fast_queue.retry_visual_page(self.run, "P01", "Replace the SIMULATED missing action panel")
        self.assertEqual(authorization["attempts"], 1)
        claim = self.claim()
        self.assertEqual(claim["attempt"], 2)
        self.complete(claim, color="green")
        page = self.state()["pages"]["P01"]
        self.assertEqual(fast_queue.sha256(original["output_path"]), original["image_sha256"])
        self.assertNotEqual(page["output_path"], original["output_path"])
        self.assertEqual(len(page["attempt_history"]), 2)
        self.assertEqual(len(page["visual_review_history"]), 1)
        self.assertEqual(page["visual_review_status"], "pending")
        fast_queue.review_page(self.run, "P01", self.review_file(passed=False))
        with self.assertRaisesRegex(fast_queue.QueueError, "at most two"):
            fast_queue.retry_visual_page(self.run, "P01", "SIMULATED second defect")
        self.assertEqual(self.state()["pages"]["P01"]["attempts"], 2)

    def test_retry_requires_failed_image_review_and_nonblank_reason(self):
        self.complete(self.claim())
        with self.assertRaises(fast_queue.QueueError):
            fast_queue.retry_visual_page(self.run, "P01", "SIMULATED arbitrary retry")
        fast_queue.review_page(self.run, "P01", self.review_file(passed=False))
        with self.assertRaises(fast_queue.QueueError):
            fast_queue.retry_visual_page(self.run, "P01", " ")
        self.assertEqual(self.state()["pages"]["P01"]["attempts"], 1)

    def test_first_page_reference_after_retry_uses_reviewed_replacement(self):
        self.complete(self.claim())
        fast_queue.review_page(self.run, "P01", self.review_file(passed=False))
        old = self.state()["pages"]["P01"]["output_path"]
        fast_queue.retry_visual_page(self.run, "P01", "SIMULATED corrected reaction")
        new = self.complete(self.claim(), color="green")["output_path"]
        self.pass_review()
        second = self.claim("P02")
        self.assertIn(new, second["request"]["referenced_image_paths"])
        self.assertNotIn(old, second["request"]["referenced_image_paths"])
        self.assertIn(str(self.reference), second["request"]["referenced_image_paths"])

    def test_cannot_replace_first_reference_after_downstream_image_exists(self):
        self.complete(self.claim())
        self.pass_review()
        self.complete(self.claim("P02"))
        self.pass_review("P02")
        reviewed = fast_queue.review_page(self.run, "P01", self.review_file(passed=False))
        self.assertFalse(reviewed["retry_available"])
        with self.assertRaisesRegex(fast_queue.QueueError, "downstream"):
            fast_queue.retry_visual_page(self.run, "P01", "SIMULATED late first-page correction")
        self.assertEqual(self.state()["pages"]["P01"]["attempts"], 1)

    def test_stale_review_and_unobserved_geometry_rejected(self):
        self.complete(self.claim())
        for changes in ({"image_sha256": "0" * 64}, {"geometry_observed_from_image": False},
                        {"geometry_observed_from_image": 1}, {"page_id": "P99"}):
            with self.subTest(changes=changes), self.assertRaises(fast_queue.QueueError):
                fast_queue.review_page(self.run, "P01", self.review_file(**changes))
        self.assertEqual(self.state()["pages"]["P01"]["visual_review_status"], "pending")

    def test_checks_require_boolean_reason_and_all_three_domains(self):
        self.complete(self.claim())
        base = json.loads(self.review_file().read_text(encoding="utf-8"))
        for check in ({"passed": "true", "reason": "SIMULATED"}, {"passed": True, "reason": ""}):
            checks = copy.deepcopy(base["checks"])
            checks["story_coverage"] = check
            with self.subTest(check=check), self.assertRaises(fast_queue.QueueError):
                fast_queue.review_page(self.run, "P01", self.review_file(checks=checks))
        checks = copy.deepcopy(base["checks"])
        checks.pop("storyboard_execution")
        with self.assertRaises(fast_queue.QueueError):
            fast_queue.review_page(self.run, "P01", self.review_file(checks=checks))

    def test_caption_issues_do_not_authorize_image_regeneration(self):
        self.complete(self.claim())
        passed = fast_queue.review_page(self.run, "P01",
            self.review_file(caption_issues=["SIMULATED caption overlaps a hand; reflow locally"]))
        self.assertEqual(passed["status"], "passed")
        with self.assertRaises(fast_queue.QueueError):
            fast_queue.retry_visual_page(self.run, "P01", "SIMULATED caption reposition")
        with self.assertRaisesRegex(fast_queue.QueueError, "local reflow"):
            fast_queue.review_page(self.run, "P01", self.review_file(passed=False, failure_kind="caption"))
        with self.assertRaisesRegex(fast_queue.QueueError, "captions are local-only"):
            fast_queue.review_page(self.run, "P01", self.review_file(passed=False,
                image_defects=[{"category": "caption", "reason": "SIMULATED font overflow"}]))
        self.assertEqual(self.state()["pages"]["P01"]["attempts"], 1)

    def test_review_snapshot_is_independent_and_tampering_requires_rereview_not_generation(self):
        self.complete(self.claim())
        review_path = self.review_file()
        result = fast_queue.review_page(self.run, "P01", review_path)
        snapshot = Path(result["visual_review_path"])
        self.assertNotEqual(review_path, snapshot)
        review_path.write_text("unrelated external edit", encoding="utf-8")
        self.assertEqual(fast_queue.status(self.run)["pages"][0]["visual_review_status"], "passed")
        snapshot.write_text("SIMULATED review evidence tampering", encoding="utf-8")
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "awaiting_visual_review")
        self.assertEqual(self.state()["pages"]["P01"]["status"], "succeeded")
        self.assertEqual(self.state()["pages"]["P01"]["attempts"], 1)

    def test_repeated_review_is_lock_safe_and_does_not_duplicate_history(self):
        self.complete(self.claim())
        review_path = self.review_file()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: fast_queue.review_page(self.run, "P01", review_path), range(2)))
        self.assertEqual([r["status"] for r in results], ["passed", "passed"])
        self.assertEqual(sum(bool(r.get("already_reviewed")) for r in results), 1)
        self.assertEqual(len(self.state()["pages"]["P01"]["visual_review_history"]), 1)
        self.assertEqual(self.state()["pages"]["P01"]["attempts"], 1)

    def test_reference_role_metadata_never_enters_image_tool_schema(self):
        claim = self.claim()
        self.assertEqual(set(claim["request"]), {"prompt", "transparent_background", "referenced_image_paths"})
        self.assertFalse(claim["reference_roles"][0]["copy_layout"])
        self.assertIn("current page's frozen storyboard", claim["request"]["prompt"])
        self.complete(claim)
        self.pass_review()
        second = self.claim("P02")
        self.assertTrue(any(r["role"] == "first_page_identity_style" for r in second["reference_roles"]))

    def test_import_retry_uses_same_call_and_attempt_before_visual_gate(self):
        claim = self.claim()
        source = self.image("SIMULATED/import-retry.png")
        with mock.patch.object(fast_queue, "_copy_result", side_effect=OSError("SIMULATED disk failure")):
            with self.assertRaises(fast_queue.QueueError):
                fast_queue.complete_page(self.run, "P01", claim["claim_token"], source,
                                         "SIMULATED-SAVE-RETRY", provider="simulation")
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "waiting")
        with self.assertRaisesRegex(fast_queue.QueueError, "original claim/tool_call_id"):
            fast_queue.recover_page(self.run, "P01", "SIMULATED save failure recovery cannot regenerate")
        fast_queue.complete_page(self.run, "P01", claim["claim_token"], source,
                                 "SIMULATED-SAVE-RETRY", provider="simulation")
        self.assertEqual(fast_queue.claim_page(self.run)["status"], "awaiting_visual_review")
        self.assertEqual(self.state()["pages"]["P01"]["attempts"], 1)
        self.assertEqual(fast_queue.status(self.run)["counts"]["recorded_tool_calls"], 1)

    def test_same_call_completion_is_idempotent_without_resetting_passed_review(self):
        claim = self.claim()
        result = self.complete(claim)
        self.pass_review()
        repeated = fast_queue.complete_page(self.run, "P01", claim["claim_token"], result["output_path"],
                                           "SIMULATED-CALL-P01-1", provider="simulation")
        self.assertTrue(repeated["already_completed"])
        self.assertEqual(self.state()["pages"]["P01"]["visual_review_status"], "passed")
        with self.assertRaises(fast_queue.QueueError):
            fast_queue.complete_page(self.run, "P01", claim["claim_token"], result["output_path"],
                                     "SIMULATED-WRONG-CALL", provider="simulation")

    def test_absent_flag_preserves_legacy_resume_and_automatic_next_page(self):
        self.plan.pop("visual_review_required")
        self.reset_queue()
        self.complete(self.claim())
        fast_queue.init_queue(self.run)
        fast_queue.resume_run(self.run)
        self.claim("P02")
        self.assertEqual(self.state()["pages"]["P01"]["visual_review_status"], "legacy_not_required")

    def test_visual_review_flag_must_be_boolean(self):
        for flag in ("true", 1, None):
            self.plan["visual_review_required"] = flag
            self.save_plan()
            with self.subTest(flag=flag), self.assertRaisesRegex(fast_queue.QueueError, "explicit boolean"):
                fast_queue._validate_plan(self.run, self.plan)


if __name__ == "__main__":
    unittest.main()
