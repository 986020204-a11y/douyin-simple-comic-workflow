"""Queue behavior regression using tiny synthetic fixtures, never story artwork.

These fixtures exercise evidence validation, not artistic quality acceptance.
No historical run or real comic file is written by this test.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/douyin-simple-comic-workflow/scripts"
sys.path.insert(0, str(SCRIPTS))
import production_queue as queue


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class QueueRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="comic-queue-diagnostic-")
        self.root = Path(self.temp.name)
        self.state = self.root / "state.json"
        self.diagnostic = True
        self.manifest = self.root / "requests.json"
        self.template = self.root / "template.json"
        dump(self.template, {"layout_id": "SB-001", "diagnostic_test_only": True,
             "canvas":{"width":1080,"height":1440},
             "panels":[{"panel_id":"U01","order":1,"bounds":[0,0,1,1]}]})
        self.reference = self.root / "reference.png"
        Image.new("RGB", (16, 16), "navy").save(self.reference)
        self.source = self.root / "source.txt"
        self.source.write_text("fixture-only source", encoding="utf-8")
        self.pages = [self.make_page("P01", 3), self.make_page("P02", 2)]
        self.raw = {"schema_version": 1, "pipeline_version": "test-v1",
                    "diagnostic_test_only": True, "pilot_page_id": "P01", "pages": self.pages}
        dump(self.manifest, self.raw)
        queue.init_queue(self.manifest, self.state, max_concurrency=2, max_attempts=3, diagnostic=True)

    def tearDown(self):
        self.temp.cleanup()

    def binding(self, path):
        return {"path": str(path), "sha256": queue.sha256(path)}

    def make_page(self, page_id, count):
        generation = self.root/f'{page_id}-generation-plan.json'
        text = self.source.read_text(encoding='utf-8')
        dump(generation, {'page_id':page_id, 'diagnostic_test_only':self.diagnostic,
             'text_blocks':[{'id':'T1','text':text,'panel_id':'U01','type':'narration',
                            'source_type':'narration','speaker':'narrator','source_article_range':[0,len(text)]}]})
        image = self.root / f"{page_id}-proof.png"
        Image.new("RGB", (16, 16), "white").save(image)
        render = self.root / f"{page_id}-proof-render.json"
        dump(render, {"diagnostic_test_only":self.diagnostic, "page_acceptance_status": "accepted", "synthetic_input": True,
                      "actual_image_checked": False, "canonical_block_count": 1,
                      "rendered_count": 1, "unresolved_count": 0,
                      "pixel_difference_nonempty": True,
                      "output_image_sha256": queue.sha256(image)})
        bubble = self.root / f"{page_id}-proof-bubble.json"
        dump(bubble, {"diagnostic_test_only":self.diagnostic,"execution_bubble_match": "passed"})
        ready = self.root / f"{page_id}-ready.json"
        dump(ready, {"diagnostic_test_only":self.diagnostic,"generation_ready": True, "synthetic_input": True,
            "actual_image_checked": False,
            "input_bindings": [self.binding(self.template), self.binding(self.source), self.binding(generation)],
            "complete_proof": {"accepted": True,
                "render_report_path": str(render), "render_report_sha256": queue.sha256(render),
                "image_path": str(image), "image_sha256": queue.sha256(image),
                "bubble_audit_path": str(bubble), "bubble_audit_sha256": queue.sha256(bubble)}})
        return {"page_id": page_id, "template_path": str(self.template),
                "proof": {"report_path": str(ready), "sha256": queue.sha256(ready)},
                "jobs": [{"unit_id": f"U{i+1:02d}",
                          "request": {"prompt": f"{page_id} fixture {i+1}", "style": "test",
                                      "referenced_image_paths": [str(self.reference)]},
                          "reference_paths": [str(self.reference)]} for i in range(count)]}

    def asset(self, name, color="green", size=(16, 16)):
        path = self.root / f"{name}.png"
        Image.new("RGB", size, color).save(path)
        return path

    def complete_claims(self, jobs):
        for job in jobs:
            queue.complete_job(self.state, job["job_id"], job["claim_token"],
                self.asset(job["job_id"].replace("/", "-")))

    def complete_pilot(self):
        while True:
            jobs = queue.claim_jobs(self.state, "pilot-worker")["jobs"]
            if not jobs:
                break
            self.complete_claims(jobs)

    def evidence(self):
        """Explicit fabricated diagnostic records, never artistic acceptance."""
        base = self.asset("pilot-base", "white", size=(1080, 1440))
        final = self.asset("pilot-final", "gray", size=(1080, 1440))
        geometry = [{"panel_id": "U01", "order": 1, "x": 0, "y": 0,
                     "width": 1080, "height": 1440}]
        base_audit = self.root / "base-audit.json"
        dump(base_audit, {"diagnostic_test_only":self.diagnostic,"selected_layout": "SB-001", "target_panel_count": 1,
            "actual_panel_count": 1, "target_panel_geometry": geometry,
            "actual_panel_geometry": geometry, "image_geometry_measurement_verified": True,
            "measurement_evidence": {"image_sha256": queue.sha256(base),
                                     "geometry_observed_from_image": True},
            "reading_order_match": "passed", "execution_geometry_match": "passed",
            "storyboard_layout_match": "passed", "base_image_modified": False})
        render = self.root / "actual-render.json"
        glyph = {'method':'pillow_draw_text_font_object','retained_in_output':True,
                 'base_image_sha256':queue.sha256(base),'output_image_sha256':queue.sha256(final),
                 'actual_font_sizes':[32], 'draw_calls':[{'text':'diagnostic', 'font_size':32,
                  'font_file':'explicit-diagnostic-font','glyph_bounds_xyxy':[10,10,120,42]}]}
        generation = self.root/'P01-generation-plan.json'
        block = json.loads(generation.read_text(encoding='utf-8'))['text_blocks'][0]
        rendered = dict(block, rendered=True, actual_font_sizes=[32], font_raster_evidence=glyph)
        dump(render, {"diagnostic_test_only":self.diagnostic,"page_acceptance_status": "accepted", "synthetic_input": False,
            "actual_image_checked": True, "output_image_sha256": queue.sha256(final),
            "base_image_sha256": queue.sha256(base), "unresolved_count": 0,
            "rendered_count": 1, "canonical_block_count": 1,
            "pixel_difference_nonempty": True, 'rendered_blocks':[rendered]})
        bubbles = self.root / "actual-bubbles.json"
        dump(bubbles, {"diagnostic_test_only":self.diagnostic,"execution_bubble_match": "passed", "actual_render_verified": True,
            "image_evidence": {"verified": True, "output_image_sha256": queue.sha256(final),
                               "base_hash_match": True}})
        font_path = self.root/'actual-fonts.json'
        dump(font_path, {'diagnostic_test_only':self.diagnostic,'actual_image_checked':True,
             'base_image_sha256':queue.sha256(base),'output_image_sha256':queue.sha256(final),
             'blocks':[{'block_id':'T1','actual_font_sizes':[32],'font_raster_evidence':glyph}]})
        layout_path = self.root/'final-layout.json'
        layout = json.loads(base_audit.read_text(encoding='utf-8'))
        layout.update(full_template_execution='passed',execution_style_match='passed',
                      actual_image_checked=True,base_image_sha256=queue.sha256(base),final_image_sha256=queue.sha256(final))
        dump(layout_path,layout)
        actual_target = self.root/'actual-target.json'
        dump(actual_target,json.loads(self.template.read_text(encoding='utf-8')))
        annotation = self.root/'actual-annotations.json'
        dump(annotation,{'diagnostic_test_only':self.diagnostic,'page_id':'P01','actual_image_checked':True,
                         'geometry_visually_checked':True,'synthetic':False,'base_sha256':queue.sha256(base)})
        actual_plan = self.root/'actual-plan.json'
        plan = json.loads(generation.read_text(encoding='utf-8'))
        plan.update(synthetic=False,synthetic_input=False,actual_image_checked=True,
                    base_image_sha256=queue.sha256(base),actual_annotations_binding=self.binding(annotation),
                    generation_plan_path=str(generation),generation_plan_sha256=queue.sha256(generation),
                    generation_template_path=str(self.template),generation_template_sha256=queue.sha256(self.template),
                    execution_template_path=str(actual_target))
        dump(actual_plan,plan)
        review = {"diagnostic_test_only":self.diagnostic,"page_id": "P01", "synthetic": False,
            "actual_image_checked": True, "review_status": "passed",
            "image_sha256": queue.sha256(final), "base_image_sha256": queue.sha256(base),
            'reviewer':'diagnostic fixture author','notes':['Fabricated diagnostic records; not artwork acceptance.'],
            "checks": {key: "passed" for key in queue.FINAL_CHECKS},
            "evidence_files": {"render_report": self.binding(render), "bubble_audit": self.binding(bubbles),
                               'font_raster':self.binding(font_path),'base_audit':self.binding(base_audit),
                               'final_layout_audit':self.binding(layout_path)},
            "input_bindings": [self.binding(actual_plan),self.binding(actual_target),self.binding(annotation)]}
        source_review = self.root/'supplied-visual-review.json'; dump(source_review,review)
        final_audit = self.root / "final-audit.json"
        review.update(review_binding=self.binding(source_review))
        dump(final_audit,review)
        return base, base_audit, final, final_audit

    def unlock(self):
        self.complete_pilot()
        evidence = self.evidence()
        result = queue.accept_pilot(self.state, *evidence)
        self.assertTrue(result["pilot_unlocked"])
        return evidence

    def ordinary_attack_mode(self):
        """Remove test labels only to exercise ordinary-mode rejection paths.

        The isolated root still records this adversarial fixture's provenance;
        none of these records is an actual image review or delivered artwork.
        """
        dump(self.root/'FIXTURE-METADATA.json',{'diagnostic_test_only':True,
             'purpose':'Adversarial ordinary-mode gate tests, never artwork acceptance.'})
        self.diagnostic = False
        target = json.loads(self.template.read_text(encoding='utf-8'))
        target['diagnostic_test_only'] = False; dump(self.template,target)
        self.raw['diagnostic_test_only'] = False
        self.raw['pages'] = [self.make_page('P01',3),self.make_page('P02',2)]
        dump(self.manifest,self.raw)
        self.state = self.root/'ordinary-attack-state.json'
        queue.init_queue(self.manifest,self.state,max_concurrency=2)

    def refresh_review_bindings(self, evidence):
        final = json.loads(evidence[3].read_text(encoding='utf-8'))
        for name,item in final['evidence_files'].items():
            final['evidence_files'][name] = self.binding(Path(item['path']))
        final['input_bindings'] = [self.binding(Path(item['path'])) for item in final['input_bindings']]
        supplied = self.root/'supplied-visual-review.json'
        dump(supplied,{k:v for k,v in final.items() if k not in {'review_binding','mobile_image'}})
        final['review_binding'] = self.binding(supplied)
        dump(evidence[3],final)

    def test_no_generator_dispatch_is_not_generated(self):
        result = queue.claim_jobs(self.state, "worker")
        self.assertEqual(len(result["jobs"]), 2)
        self.assertTrue(all(job["render_status"] == "not-generated" for job in result["jobs"]))
        status = queue.queue_status(self.state)
        self.assertEqual(status["job_status_counts"], {"inflight": 2, "pending": 3})
        self.assertEqual(status["stats"]["completed_calls"], 0)

    def test_only_pilot_before_actual_acceptance(self):
        self.complete_pilot()
        self.assertEqual(queue.claim_jobs(self.state, "worker")["jobs"], [])
        self.assertFalse(queue.queue_status(self.state)["pilot_unlocked"])

    def test_boolean_selected_layout_and_synthetic_cannot_unlock(self):
        self.complete_pilot()
        evidence = self.evidence()
        dump(evidence[3], {"accepted": True, "selected_layout": "SB-001", "synthetic": True})
        with self.assertRaises(queue.QueueError):
            queue.accept_pilot(self.state, *evidence)
        self.assertEqual(queue.claim_jobs(self.state, "worker")["jobs"], [])

    def test_base_image_hash_mismatch_rejected(self):
        self.complete_pilot()
        evidence = self.evidence()
        Image.new("RGB", (16, 16), "red").save(evidence[0])
        with self.assertRaises(queue.QueueError):
            queue.accept_pilot(self.state, *evidence)

    def test_real_evidence_unlocks_other_pages(self):
        self.unlock()
        claims = queue.claim_jobs(self.state, "worker")["jobs"]
        self.assertEqual(len(claims), 2)
        self.assertTrue(all(job["page_id"] == "P02" for job in claims))

    def test_final_image_change_relocks_pilot(self):
        evidence = self.unlock()
        Image.new("RGB", (16, 16), "red").save(evidence[2])
        self.assertEqual(queue.claim_jobs(self.state, "worker")["jobs"], [])
        self.assertFalse(queue.queue_status(self.state)["pilot_unlocked"])

    def test_final_evidence_file_change_relocks_pilot(self):
        self.unlock()
        render = self.root / "actual-render.json"
        value = json.loads(render.read_text(encoding="utf-8"))
        value["new_content"] = "changed"
        dump(render, value)
        self.assertEqual(queue.claim_jobs(self.state, "worker")["jobs"], [])

    def test_concurrency_global_across_processes(self):
        command = [sys.executable, str(SCRIPTS / "production_queue.py"), "claim",
                   "--state", str(self.state), "--worker"]
        def claim(number):
            result = subprocess.run(command + [f"worker-{number}"], capture_output=True,
                                    text=True, encoding="utf-8", check=True)
            return json.loads(result.stdout)
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(claim, range(3)))
        jobs = [job for result in results for job in result["jobs"]]
        self.assertEqual(len(jobs), 2)
        self.assertEqual(len({job["job_id"] for job in jobs}), 2)

    def test_only_failed_job_is_retried(self):
        jobs = queue.claim_jobs(self.state, "worker")["jobs"]
        good, bad = jobs
        self.complete_claims([good])
        queue.fail_job(self.state, bad["job_id"], bad["claim_token"], "generator failure")
        next_jobs = queue.claim_jobs(self.state, "worker")["jobs"]
        self.assertIn(bad["job_id"], [job["job_id"] for job in next_jobs])
        self.assertNotIn(good["job_id"], [job["job_id"] for job in next_jobs])
        current = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(current["jobs"][good["job_id"]]["attempts"], 1)

    def test_attempt_limit_blocks_further_retry(self):
        job_id = None
        for attempt in range(3):
            claims = queue.claim_jobs(self.state, "worker", limit=1)["jobs"]
            job = claims[0]
            job_id = job["job_id"]
            self.assertEqual(job["attempt"], attempt + 1)
            result = queue.fail_job(self.state, job_id, job["claim_token"], "failure")
        self.assertEqual(result["status"], "blocked")
        next_claim = queue.claim_jobs(self.state, "worker", limit=1)["jobs"][0]
        self.assertNotEqual(next_claim["job_id"], job_id)

    def test_text_repair_keeps_completed_assets(self):
        self.complete_pilot()
        before = json.loads(self.state.read_text(encoding="utf-8"))
        result = queue.record_text_issue(self.state, "P01", "caption too close to face")
        self.assertFalse(result["scene_assets_invalidated"])
        after = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(before["jobs"], after["jobs"])
        self.assertEqual(queue.claim_jobs(self.state, "worker")["jobs"], [])

    def test_sync_reuses_assets_but_not_acceptance(self):
        self.unlock()
        summary = queue.sync_queue(self.manifest, self.state)
        self.assertEqual(summary["stats"]["reused_assets"], 3)
        self.assertFalse(summary["pilot_unlocked"])
        self.assertEqual(summary["job_status_counts"], {"generated_unreviewed": 3, "pending": 2})

    def rebuild_text_proofs(self):
        """Change only source text and its legal proof, never generation inputs."""
        self.source.write_text("changed caption; same image composition", encoding="utf-8")
        self.raw["pages"] = [self.make_page("P01", 3), self.make_page("P02", 2)]
        dump(self.manifest, self.raw)

    def test_rebuilt_text_only_proof_reuses_artwork_and_resets_pilot(self):
        self.unlock()
        before = json.loads(self.state.read_text(encoding="utf-8"))
        self.rebuild_text_proofs()
        summary = queue.sync_queue(self.manifest, self.state)
        after = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(summary["job_status_counts"], {"generated_unreviewed": 3, "pending": 2})
        self.assertEqual(summary["stats"]["invalidated_assets"], 0)
        self.assertEqual(summary["stats"]["reused_assets"], 3)
        self.assertFalse(summary["pilot_unlocked"])
        for job_id in ("P01/U01", "P01/U02", "P01/U03"):
            self.assertEqual(before["jobs"][job_id]["fingerprint"], after["jobs"][job_id]["fingerprint"])
            self.assertEqual(before["jobs"][job_id]["asset"], after["jobs"][job_id]["asset"])
            self.assertNotEqual(before["jobs"][job_id]["proof_binding"], after["jobs"][job_id]["proof_binding"])
        self.assertEqual(queue.claim_jobs(self.state, "worker")["jobs"], [])

    def test_reserved_scene_regions_change_invalidates_affected_artwork(self):
        self.complete_pilot()
        self.raw["pages"][0]["jobs"][1]["request"]["reserved_text_zones"] = [
            {"bounds": [0.0, 0.0, 0.5, 0.25], "background_requirement": "quiet"}]
        dump(self.manifest, self.raw)
        summary = queue.sync_queue(self.manifest, self.state)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(summary["stats"]["invalidated_assets"], 1)
        self.assertEqual(state["jobs"]["P01/U02"]["status"], "pending")
        self.assertEqual(state["jobs"]["P01/U01"]["status"], "generated_unreviewed")

    def test_template_change_with_new_legal_proof_invalidates_artwork(self):
        self.complete_pilot()
        dump(self.template, {"layout_id": "SB-001", "fixture": True,
                             "reserved_bounds": [0, 0, 0.5, 0.25]})
        self.raw["pages"] = [self.make_page("P01", 3), self.make_page("P02", 2)]
        dump(self.manifest, self.raw)
        summary = queue.sync_queue(self.manifest, self.state)
        self.assertEqual(summary["job_status_counts"], {"pending": 5})
        self.assertEqual(summary["stats"]["invalidated_assets"], 3)

    def test_invalid_rebuilt_proof_still_blocks_dispatch(self):
        self.complete_pilot()
        self.rebuild_text_proofs()
        path = Path(self.raw["pages"][0]["proof"]["report_path"])
        proof = json.loads(path.read_text(encoding="utf-8"))
        proof["complete_proof"]["accepted"] = False
        dump(path, proof)
        self.raw["pages"][0]["proof"]["sha256"] = queue.sha256(path)
        dump(self.manifest, self.raw)
        with self.assertRaises(queue.QueueError):
            queue.sync_queue(self.manifest, self.state)
        self.assertEqual(queue.claim_jobs(self.state, "worker")["jobs"], [])

    def test_inflight_proof_change_requires_recovery_and_rejects_old_token(self):
        job = queue.claim_jobs(self.state, "still-running", limit=1)["jobs"][0]
        self.rebuild_text_proofs()
        with self.assertRaises(queue.QueueError):
            queue.complete_job(self.state, job["job_id"], job["claim_token"], self.asset("stale"))
        with self.assertRaises(queue.QueueError):
            queue.sync_queue(self.manifest, self.state)
        status = queue.queue_status(self.state)
        self.assertEqual(status["job_status_counts"]["inflight"], 1)
        self.assertEqual(queue.claim_jobs(self.state, "other-worker")["jobs"], [])
        queue.recover_leases(self.state, "still-running")
        queue.sync_queue(self.manifest, self.state)
        with self.assertRaises(queue.QueueError):
            queue.complete_job(self.state, job["job_id"], job["claim_token"], self.asset("late"))
        replacement = queue.claim_jobs(self.state, "replacement", limit=1)["jobs"][0]
        self.assertEqual(replacement["job_id"], job["job_id"])
        self.assertNotEqual(replacement["claim_token"], job["claim_token"])

    def test_reference_content_change_invalidates_cached_assets(self):
        self.complete_pilot()
        old = json.loads(self.state.read_text(encoding="utf-8"))
        Image.new("RGB", (16, 16), "red").save(self.reference)
        status = queue.queue_status(self.state)
        new = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(status["job_status_counts"], {"pending": 5})
        self.assertEqual(status["stats"]["invalidated_assets"], 3)
        self.assertNotEqual(old["jobs"]["P01/U01"]["fingerprint"], new["jobs"]["P01/U01"]["fingerprint"])

    def test_prompt_change_invalidates_only_changed_job(self):
        self.complete_pilot()
        self.raw["pages"][0]["jobs"][1]["request"]["prompt"] += " new action"
        dump(self.manifest, self.raw)
        result = queue.sync_queue(self.manifest, self.state)
        self.assertEqual(result["job_status_counts"], {"generated_unreviewed": 2, "pending": 3})
        self.assertEqual(result["stats"]["invalidated_assets"], 1)

    def test_pipeline_version_change_invalidates_all_assets(self):
        self.complete_pilot()
        self.raw["pipeline_version"] = "test-v2"
        dump(self.manifest, self.raw)
        result = queue.sync_queue(self.manifest, self.state)
        self.assertEqual(result["job_status_counts"], {"pending": 5})

    def test_asset_bytes_changed_not_accepted_or_reused(self):
        self.complete_pilot()
        old = json.loads(self.state.read_text(encoding="utf-8"))
        path = Path(old["jobs"]["P01/U01"]["asset"]["path"])
        Image.new("RGB", (16, 16), "yellow").save(path)
        status = queue.queue_status(self.state)
        jobs = {job["job_id"]: job for job in status["jobs"]}
        self.assertEqual(jobs["P01/U01"]["status"], "pending")
        self.assertEqual(jobs["P01/U02"]["status"], "generated_unreviewed")

    def test_proof_input_changed_blocks_all_dispatch(self):
        self.source.write_text("changed source text", encoding="utf-8")
        result = queue.claim_jobs(self.state, "worker")
        self.assertEqual(result["jobs"], [])
        self.assertEqual(len(result["summary"]["blocked_pages"]), 2)

    def test_proof_image_bytes_changed_blocks_dispatch(self):
        Image.new("RGB", (16, 16), "red").save(self.root / "P01-proof.png")
        result = queue.claim_jobs(self.state, "worker")
        self.assertEqual(result["jobs"], [])
        self.assertIn("P01", result["summary"]["blocked_pages"])

    def test_missing_asset_cannot_be_registered(self):
        job = queue.claim_jobs(self.state, "worker", limit=1)["jobs"][0]
        with self.assertRaises(queue.QueueError):
            queue.complete_job(self.state, job["job_id"], job["claim_token"], self.root / "missing.png")

    def test_recovery_rejects_late_completion(self):
        job = queue.claim_jobs(self.state, "crashed-worker", limit=1)["jobs"][0]
        result = queue.recover_leases(self.state, "crashed-worker")
        self.assertEqual(result["recovered_jobs"], [job["job_id"]])
        with self.assertRaises(queue.QueueError):
            queue.complete_job(self.state, job["job_id"], job["claim_token"], self.asset("late"))
        next_job = queue.claim_jobs(self.state, "replacement", limit=1)["jobs"][0]
        self.assertEqual(next_job["attempt"], 2)
        self.assertNotEqual(next_job["claim_token"], job["claim_token"])

    def test_expired_lease_requires_explicit_recovery_after_restart(self):
        job = queue.claim_jobs(self.state, "worker", limit=1, lease_seconds=0.01)["jobs"][0]
        time.sleep(0.02)
        result = queue.queue_status(self.state)
        self.assertEqual(result["stats"]["lease_expirations"], 0)
        self.assertEqual(result["jobs"][0]["status"], "inflight")
        self.assertEqual(result["expired_leases_awaiting_explicit_recovery"], [job["job_id"]])
        other_jobs = queue.claim_jobs(self.state, "other-worker")["jobs"]
        self.assertNotIn(job["job_id"], [other["job_id"] for other in other_jobs])
        self.assertEqual(queue.recover_leases(self.state)["recovered_jobs"], [job["job_id"]])
        next_job = queue.claim_jobs(self.state, "replacement", limit=1)["jobs"][0]
        self.assertEqual(next_job["job_id"], job["job_id"])
        self.assertEqual(next_job["attempt"], 2)

    def test_unexpired_active_lease_not_recovered_automatically(self):
        jobs = queue.claim_jobs(self.state, "still-running", limit=2, lease_seconds=600)["jobs"]
        self.assertEqual(queue.recover_leases(self.state)["recovered_jobs"], [])
        self.assertEqual(queue.claim_jobs(self.state, "other-worker")["jobs"], [])
        status = queue.queue_status(self.state)
        self.assertEqual(status["job_status_counts"]["inflight"], 2)
        self.assertEqual(status["stats"]["lease_expirations"], 0)

    def test_changed_manifest_requires_explicit_sync(self):
        self.raw["pages"][0]["jobs"][0]["request"]["prompt"] += " modified"
        dump(self.manifest, self.raw)
        result = queue.claim_jobs(self.state, "worker")
        self.assertEqual(result["jobs"], [])
        self.assertEqual(result["summary"]["blocked_pages"]["P01"], "manifest_changed_requires_explicit_sync")

    def test_request_references_must_match_hashed_inputs(self):
        self.raw["pages"][0]["jobs"][0]["request"]["referenced_image_paths"] = []
        dump(self.manifest, self.raw)
        with self.assertRaises(queue.QueueError):
            queue.init_queue(self.manifest, self.root / "different-state.json", diagnostic=True)

    def test_base_audit_boolean_order_and_dual_hash_render_compatibility(self):
        self.complete_pilot()
        evidence = self.evidence()
        base_audit = json.loads(evidence[1].read_text(encoding="utf-8"))
        base_audit["reading_order_match"] = True
        dump(evidence[1], base_audit)
        render_path = self.root / "actual-render.json"
        render = json.loads(render_path.read_text(encoding="utf-8"))
        digest = render.pop("base_image_sha256")
        render["base_image_sha256_before"] = digest
        render["base_image_sha256_after"] = digest
        dump(render_path, render)
        final = json.loads(evidence[3].read_text(encoding="utf-8"))
        final["evidence_files"]["render_report"] = self.binding(render_path)
        final["evidence_files"]["base_audit"] = self.binding(evidence[1])
        supplied = self.root/'supplied-visual-review.json'
        dump(supplied, {k:v for k,v in final.items() if k not in {'review_binding','mobile_image'}})
        final['review_binding'] = self.binding(supplied)
        dump(evidence[3], final)
        self.assertTrue(queue.accept_pilot(self.state, *evidence)["pilot_unlocked"])

    def test_duplicate_unit_rejected(self):
        self.raw["pages"][0]["jobs"][1]["unit_id"] = "U01"
        dump(self.manifest, self.raw)
        with self.assertRaises(queue.QueueError):
            queue.init_queue(self.manifest, self.root / "new-state.json", diagnostic=True)

    def test_diagnostic_requests_cannot_enter_normal_queue(self):
        self.raw['diagnostic_test_only'] = True
        dump(self.manifest, self.raw)
        with self.assertRaisesRegex(queue.QueueError, 'explicit --diagnostic'):
            queue.init_queue(self.manifest, self.root/'normal-state.json')
        report = queue.init_queue(self.manifest, self.root/'diagnostic-state.json', diagnostic=True)
        self.assertTrue(report['diagnostic_test_only'])

    def test_queue_cannot_omit_a_prepared_page(self):
        self.raw['expected_page_ids'] = ['P01', 'P02', 'P03']
        dump(self.manifest, self.raw)
        with self.assertRaisesRegex(queue.QueueError, 'complete prepared page list'):
            queue.init_queue(self.manifest, self.root/'incomplete-state.json', diagnostic=True)

    def test_wrong_pilot_dimensions_block_batch_unlock(self):
        self.complete_pilot()
        evidence = self.evidence()
        Image.new('RGB', (1080, 1080), 'gray').save(evidence[2])
        audit = json.loads(evidence[3].read_text(encoding='utf-8'))
        audit['image_sha256'] = queue.sha256(evidence[2])
        dump(evidence[3], audit)
        with self.assertRaisesRegex(queue.QueueError, '1080x1440'):
            queue.accept_pilot(self.state, *evidence)

    def test_reference_metadata_alone_cannot_dispatch(self):
        del self.raw['pages'][0]['jobs'][0]['request']['referenced_image_paths']
        dump(self.manifest, self.raw)
        with self.assertRaisesRegex(queue.QueueError, 'explicit referenced_image_paths'):
            queue.init_queue(self.manifest, self.root/'missing-request-refs.json', diagnostic=True)

    def test_relative_references_emit_absolute_actual_tool_inputs(self):
        for page in self.raw['pages']:
            for job in page['jobs']:
                job['reference_paths'] = [self.reference.name]
                job['request']['referenced_image_paths'] = [self.reference.name]
        dump(self.manifest, self.raw)
        other = self.root/'relative-state.json'
        queue.init_queue(self.manifest, other, diagnostic=True)
        job = queue.claim_jobs(other, 'worker', limit=1)['jobs'][0]
        self.assertEqual(job['request']['referenced_image_paths'], [str(self.reference)])
        self.assertEqual(job['reference_paths'], job['request']['referenced_image_paths'])

    def test_changed_inflight_reference_keeps_capacity_until_explicit_recovery(self):
        jobs = queue.claim_jobs(self.state, 'still-running', limit=2)['jobs']
        Image.new('RGB', (16, 16), 'red').save(self.reference)
        status = queue.queue_status(self.state)
        self.assertEqual(status['job_status_counts']['inflight'], 2)
        self.assertEqual(queue.claim_jobs(self.state, 'replacement')['jobs'], [])
        with self.assertRaises(queue.QueueError):
            queue.complete_job(self.state, jobs[0]['job_id'], jobs[0]['claim_token'], self.asset('stale-reference'))
        queue.recover_leases(self.state, 'still-running')
        replacements = queue.claim_jobs(self.state, 'replacement')['jobs']
        self.assertEqual(len(replacements), 2)
        self.assertTrue(all(new['claim_token'] not in {old['claim_token'] for old in jobs} for new in replacements))

    def test_wrong_claim_owner_cannot_complete_or_fail(self):
        job = queue.claim_jobs(self.state, 'owner', limit=1)['jobs'][0]
        for action in ('complete', 'fail'):
            with self.subTest(action=action), self.assertRaises(queue.QueueError):
                if action == 'complete':
                    queue.complete_job(self.state, job['job_id'], 'wrong-token', self.asset('unowned'))
                else:
                    queue.fail_job(self.state, job['job_id'], 'wrong-token', 'unowned failure')
        self.assertEqual(queue.queue_status(self.state)['job_status_counts']['inflight'], 1)

    def test_repeated_abandoned_calls_obey_attempt_limit(self):
        for expected in range(1, 4):
            job = queue.claim_jobs(self.state, 'stopped', limit=1)['jobs'][0]
            self.assertEqual(job['job_id'], 'P01/U01')
            self.assertEqual(job['attempt'], expected)
            queue.recover_leases(self.state, 'stopped')
        state = json.loads(self.state.read_text(encoding='utf-8'))
        self.assertEqual(state['jobs']['P01/U01']['status'], 'blocked')
        self.assertNotEqual(queue.claim_jobs(self.state, 'worker', limit=1)['jobs'][0]['job_id'], 'P01/U01')

    def test_worker_targeted_recovery_does_not_abandon_other_expired_call(self):
        stopped = queue.claim_jobs(self.state, 'known-stopped', limit=1)['jobs'][0]
        alive = queue.claim_jobs(self.state, 'still-alive', limit=1, lease_seconds=.01)['jobs'][0]
        time.sleep(.02)
        result = queue.recover_leases(self.state, 'known-stopped')
        self.assertEqual(result['recovered_jobs'],[stopped['job_id']])
        jobs = {job['job_id']:job for job in queue.queue_status(self.state)['jobs']}
        self.assertEqual(jobs[alive['job_id']]['status'],'inflight')

    def test_contradictory_pilot_geometry_cannot_unlock(self):
        self.complete_pilot()
        evidence = self.evidence()
        for key, value in [('x', 30), ('width', 900), ('order', 2), ('height', float('nan'))]:
            with self.subTest(key=key):
                original = json.loads(evidence[1].read_text(encoding='utf-8'))
                changed = copy.deepcopy(original)
                changed['actual_panel_geometry'][0][key] = value
                dump(evidence[1], changed)
                with self.assertRaisesRegex(queue.QueueError, 'deviates'):
                    queue.accept_pilot(self.state, *evidence)
                dump(evidence[1], original)

    def test_boolean_canonical_count_cannot_fake_complete_proof(self):
        render = self.root/'P01-proof-render.json'
        value = json.loads(render.read_text(encoding='utf-8'))
        value.update(canonical_block_count=True, rendered_count=True)
        dump(render, value)
        proof = Path(self.raw['pages'][0]['proof']['report_path'])
        value = json.loads(proof.read_text(encoding='utf-8'))
        value['complete_proof']['render_report_sha256'] = queue.sha256(render)
        dump(proof, value)
        self.raw['pages'][0]['proof']['sha256'] = queue.sha256(proof)
        dump(self.manifest, self.raw)
        with self.assertRaisesRegex(queue.QueueError, 'canonical text block'):
            queue.init_queue(self.manifest, self.root/'bool-count.json', diagnostic=True)

    def test_ordinary_mode_seven_flags_cannot_replace_supplied_review(self):
        self.ordinary_attack_mode(); self.complete_pilot()
        for missing in ('reviewer','notes','review_binding'):
            with self.subTest(missing=missing):
                evidence = self.evidence()
                value = json.loads(evidence[3].read_text(encoding='utf-8'))
                value.pop(missing); dump(evidence[3],value)
                with self.assertRaises(queue.QueueError):
                    queue.accept_pilot(self.state,*evidence)
                self.assertEqual(queue.claim_jobs(self.state,'other')['jobs'],[])

    def test_required_glyph_and_final_layout_files_cannot_be_omitted(self):
        self.complete_pilot()
        for missing in ('font_raster','final_layout_audit','base_audit'):
            with self.subTest(missing=missing):
                evidence = self.evidence()
                value = json.loads(evidence[3].read_text(encoding='utf-8'))
                value['evidence_files'].pop(missing); dump(evidence[3],value)
                with self.assertRaisesRegex(queue.QueueError,'requires render, bubbles, glyphs'):
                    queue.accept_pilot(self.state,*evidence)

    def test_supplied_visual_observations_cannot_be_rewritten(self):
        self.complete_pilot(); evidence = self.evidence()
        value = json.loads(evidence[3].read_text(encoding='utf-8'))
        value['notes'] = ['New invented observations not present in original review.']
        dump(evidence[3],value)
        with self.assertRaisesRegex(queue.QueueError,'differs from the separately supplied'):
            queue.accept_pilot(self.state,*evidence)

    def test_current_full_size_review_does_not_require_mobile_preview(self):
        self.complete_pilot(); evidence = self.evidence()
        value = json.loads(evidence[3].read_text(encoding='utf-8'))
        self.assertNotIn('mobile_image', value)
        self.assertNotIn('mobile_image_sha256', value)
        self.assertTrue(queue.accept_pilot(self.state,*evidence)['pilot_unlocked'])

    def test_missing_actual_glyph_draw_calls_block_pilot(self):
        self.complete_pilot(); evidence = self.evidence()
        for filename,container in [('actual-fonts.json','blocks'),('actual-render.json','rendered_blocks')]:
            path = self.root/filename; value = json.loads(path.read_text(encoding='utf-8'))
            value[container][0]['font_raster_evidence']['draw_calls'] = []
            dump(path,value)
        self.refresh_review_bindings(evidence)
        with self.assertRaisesRegex(queue.QueueError,'retained glyph draw calls'):
            queue.accept_pilot(self.state,*evidence)

    def test_final_layout_full_execution_cannot_be_replaced_by_visual_flag(self):
        self.complete_pilot(); evidence = self.evidence()
        path = self.root/'final-layout.json'; value = json.loads(path.read_text(encoding='utf-8'))
        value['full_template_execution'] = 'failed'; dump(path,value)
        self.refresh_review_bindings(evidence)
        with self.assertRaisesRegex(queue.QueueError,'final template execution'):
            queue.accept_pilot(self.state,*evidence)

    def test_actual_plan_target_annotations_must_all_be_reviewed(self):
        self.complete_pilot()
        for filename in ('actual-plan.json','actual-target.json','actual-annotations.json'):
            with self.subTest(filename=filename):
                evidence = self.evidence()
                value = json.loads(evidence[3].read_text(encoding='utf-8'))
                value['input_bindings'] = [b for b in value['input_bindings'] if Path(b['path']).name != filename]
                dump(evidence[3],value); self.refresh_review_bindings(evidence)
                with self.assertRaises(queue.QueueError):
                    queue.accept_pilot(self.state,*evidence)

    def test_report_selected_sb_must_match_frozen_target(self):
        self.complete_pilot(); evidence = self.evidence()
        value = json.loads(evidence[1].read_text(encoding='utf-8'))
        value['selected_layout'] = 'SB-068'; dump(evidence[1],value)
        self.refresh_review_bindings(evidence)
        with self.assertRaisesRegex(queue.QueueError,'selected_layout differs'):
            queue.accept_pilot(self.state,*evidence)

    def test_self_consistent_report_geometry_cannot_replace_executed_target(self):
        self.complete_pilot(); evidence = self.evidence()
        path = self.root/'final-layout.json'; value = json.loads(path.read_text(encoding='utf-8'))
        value['target_panel_geometry'][0]['width'] = 1000
        value['actual_panel_geometry'][0]['width'] = 1000
        dump(path,value); self.refresh_review_bindings(evidence)
        with self.assertRaisesRegex(queue.QueueError,'target geometry'):
            queue.accept_pilot(self.state,*evidence)

    def test_ordinary_mode_rejects_diagnostic_marker_nested_in_linked_glyphs(self):
        self.ordinary_attack_mode(); self.complete_pilot(); evidence = self.evidence()
        path = self.root/'actual-fonts.json'; value = json.loads(path.read_text(encoding='utf-8'))
        value['blocks'][0]['nested_provenance'] = {'diagnostic_test_only':True}
        dump(path,value); self.refresh_review_bindings(evidence)
        with self.assertRaisesRegex(queue.QueueError,'Diagnostic evidence'):
            queue.accept_pilot(self.state,*evidence)
        self.assertEqual(queue.claim_jobs(self.state,'other')['jobs'],[])

    def test_ordinary_mode_rejects_nested_diagnostic_readiness_proof(self):
        self.ordinary_attack_mode()
        proof_path = Path(self.raw['pages'][0]['proof']['report_path'])
        proof = json.loads(proof_path.read_text(encoding='utf-8'))
        proof['nested_origin'] = {'diagnostic_test_only':True}; dump(proof_path,proof)
        self.raw['pages'][0]['proof']['sha256'] = queue.sha256(proof_path); dump(self.manifest,self.raw)
        with self.assertRaisesRegex(queue.QueueError,'Diagnostic evidence'):
            queue.init_queue(self.manifest,self.root/'laundered-readiness.json')

    def test_ordinary_proof_accepts_list_form_library_dependency(self):
        self.ordinary_attack_mode()
        index = self.root/'library-list.json'
        dump(index,[{'layout_id':'SB-001'},{'layout_id':'SB-002'}])
        proof_path = Path(self.raw['pages'][0]['proof']['report_path'])
        proof = json.loads(proof_path.read_text(encoding='utf-8'))
        proof['input_bindings'].append(self.binding(index))
        dump(proof_path,proof)
        self.raw['pages'][0]['proof']['sha256'] = queue.sha256(proof_path)
        dump(self.manifest,self.raw)
        queue.init_queue(self.manifest,self.root/'normal-list-index-state.json')

    def test_ordinary_proof_rejects_diagnostic_marker_inside_list_dependency(self):
        self.ordinary_attack_mode()
        index = self.root/'diagnostic-library-list.json'
        dump(index,[{'layout_id':'SB-001','diagnostic_test_only':True}])
        proof_path = Path(self.raw['pages'][0]['proof']['report_path'])
        proof = json.loads(proof_path.read_text(encoding='utf-8'))
        proof['input_bindings'].append(self.binding(index))
        dump(proof_path,proof)
        self.raw['pages'][0]['proof']['sha256'] = queue.sha256(proof_path)
        dump(self.manifest,self.raw)
        with self.assertRaisesRegex(queue.QueueError,'Diagnostic evidence'):
            queue.init_queue(self.manifest,self.root/'normal-diagnostic-index-state.json')


if __name__ == "__main__":
    unittest.main(verbosity=2)
