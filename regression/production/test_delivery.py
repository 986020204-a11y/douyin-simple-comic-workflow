"""Fresh diagnostic-only fixtures; historical tests and comics are never edited."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "douyin-simple-comic-workflow" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from PIL import Image, ImageDraw
import yaml
import production_delivery as delivery
import production_finalize as finalizer


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2) if path.suffix == ".json" else yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
    path.write_text(content, encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="comic-delivery-regression-")
        self.root = Path(self.temp.name)
        self.ids = ["P03", "P01"]
        source = self.root / "source.md"
        source.write_text("验证完成", encoding="utf-8")
        config_path = self.root / "config/text-layout.yaml"
        save(config_path, {"minimum_readable_font_size": 32})
        decision = self.root / "storyboard-decision.yaml"
        save(decision, {"pages": [{"page_id": pid, "layout_id": "SB-001", "panel_count": 1,
                                     "panels": [{"panel_id": "P01"}]} for pid in self.ids],
                        "planned_panel_count": 2})
        production = {"diagnostic_test_only": True, "source_path": "source.md",
                      "storyboard_decision_path": "storyboard-decision.yaml", "text_policy": "excerpts", "pages": []}
        requests = {"expected_page_ids": self.ids, "pages": []}
        manifest = {"diagnostic_test_only": True, "source_path": "source.md", "content_coverage_path": "preparation/content-coverage.json",
                    "expected_page_ids": self.ids, "production_manifest_path": "production.yaml",
                    "generation_requests_path": "preparation/generation-requests.json",
                    "story_review": "reports/story.json", "pages": []}
        final_hashes = {}
        for i, pid in enumerate(self.ids):
            base = self.root / f"pages/renders/{pid}-base.png"
            final = self.root / f"pages/final/{pid}-final.png"
            base.parent.mkdir(parents=True, exist_ok=True)
            final.parent.mkdir(parents=True, exist_ok=True)
            picture = Image.new("RGB", (1080, 1440), (230 + i, 240, 250))
            picture.save(base)
            ImageDraw.Draw(picture).rectangle((20, 20, 50 + i, 50), fill="black")
            picture.save(final)
            bh, fh = digest(base), digest(final)
            final_hashes[pid] = fh
            block = {"id": f"{pid}-B01", "bubble_id": "B01", "panel_id": "P01", "type": "narration", "source_type": "narration",
                     "speaker": "narrator", "text": "验证" if i == 0 else "完成", "source_article_range": [i*2, i*2+2],
                     "source_excerpt_verbatim": True, "font_size": 36, "font_size_policy": "fixed"}
            plan = {"page_id": pid, "layout_id": "SB-001", "text_blocks": [block]}
            plan_path = self.root / f"plans/{pid}.yaml"
            target_path = self.root / f"targets/{pid}.yaml"
            save(plan_path, plan)
            save(target_path, {"layout_id": "SB-001", "canvas": {"coordinate_system": "normalized_xywh_0_to_1"},
                               "panels": [{"panel_id": "P01", "order": 1, "bounds": [0, 0, 1, 1]}]})
            actual = {**plan, "actual_image_checked": True, "synthetic": False, "synthetic_input": False, "base_image_sha256": bh}
            save(self.root / f"plans/actual/{pid}.yaml", actual)
            geometry = [{"panel_id": "P01", "order": 1, "x": 0, "y": 0, "width": 1080, "height": 1440}]
            audit = {"selected_layout": "SB-001", "target_panel_count": 1, "actual_panel_count": 1,
                     "target_panel_geometry": geometry, "actual_panel_geometry": geometry,
                     "image_geometry_measurement_verified": True,
                     "measurement_evidence": {"geometry_observed_from_image": True, "image_sha256": bh},
                     "reading_order_match": "passed", "execution_geometry_match": "passed", "base_image_modified": False,
                     "match_policy": "adapted", "user_approved_adaptation": True, "adapted_target_match": "passed",
                     "source_reference_geometry_match": "failed", "storyboard_layout_match": "failed",
                     "layout_deviation": [{"kind": "uniform_cover_crop", "evidence": "diagnostic_fixture"}]}
            save(self.root / f"reports/{pid}-base.json", audit)
            final_audit = {**audit, "full_template_execution": "passed", "execution_style_match": "passed",
                           "text_container_execution_match": "passed", "base_image_sha256": bh, "final_image_sha256": fh}
            save(self.root / f"reports/{pid}-layout.json", final_audit)
            render = {"base_image_sha256_before": bh, "base_image_sha256_after": bh, "output_image_sha256": fh,
                      "base_image_modified": False, "page_acceptance_status": "accepted", "actual_image_checked": True,
                      "synthetic_input": False, "unresolved_count": 0, "rendered_count": 1, "canonical_block_count": 1,
                      "rendered_blocks": [{**block, "rendered": True, "actual_font_sizes": [36], "font_size_adjusted": False,
                         "font_raster_evidence": {"retained_in_output": True, "base_image_sha256": bh, "output_image_sha256": fh}}]}
            render_path = self.root / f"reports/{pid}-render.yaml"
            save(render_path, render)
            bubble_path = self.root / f"reports/{pid}-bubble.json"
            save(bubble_path, {"execution_bubble_match": "passed", "actual_render_verified": True,
                               "image_evidence": {"verified": True, "output_image_sha256": fh, "base_hash_match": True}})
            visual = {"page_id": pid, "actual_image_checked": True, "synthetic": False, "status": "passed",
                      "image_sha256": fh, "base_image_sha256": bh,
                      "checks": {key: "passed" for key in delivery.REVIEW_CHECKS},
                      "evidence_files": {"render_report": {"path": str(render_path), "sha256": digest(render_path)},
                                         "bubble_audit": {"path": str(bubble_path), "sha256": digest(bubble_path)}}}
            save(self.root / f"reports/{pid}-review.json", visual)
            proof_path = self.root / f"preparation/{pid}/generation-readiness.json"
            save(proof_path, {"page_id": pid, "generation_ready": True,
                              "input_bindings": [{"path": str(p), "sha256": digest(p)}
                                                 for p in (source, decision, plan_path, target_path, config_path)]})
            requests["pages"].append({"page_id": pid, "template_path": str(target_path),
                                       "proof": {"report_path": str(proof_path), "sha256": digest(proof_path)}})
            production["pages"].append({"page_id": pid, "text_plan_path": str(plan_path), "template_path": str(target_path),
                                         "text_layout_path": str(config_path)})
            manifest["pages"].append({"page_id": pid, "base_image": str(base), "final_image": str(final),
                                      "base_audit": f"reports/{pid}-base.json", "final_layout_audit": f"reports/{pid}-layout.json",
                                      "render_report": f"reports/{pid}-render.yaml", "bubble_audit": f"reports/{pid}-bubble.json",
                                      "visual_review": f"reports/{pid}-review.json"})
        coverage_path = self.root / "preparation/content-coverage.json"
        save(coverage_path, {"status": "passed", "errors": [], "source_sha256": digest(source), "expected_page_ids": self.ids,
                             "storyboard_binding": {"path": str(decision), "sha256": digest(decision)},
                             "beats": [{"beat_id": f"B{i}", "source_range": [i*2, i*2+2],
                                        "bindings": [{"page_id": pid, "panel_id": "P01"}]} for i,pid in enumerate(self.ids)]})
        save(self.root / "production.yaml", production)
        save(self.root / "preparation/generation-requests.json", requests)
        save(self.root / "reports/story.json", {"status": "passed", "source_sha256": digest(source),
             "coverage_sha256": digest(coverage_path), "reviewed_page_hashes": final_hashes,
             "no_missing_required_beats": True, "actual_image_checked": True, "synthetic": False,
             "reviewer": "diagnostic_fixture", "semantic_observations": ["DIAGNOSTIC ONLY: fabricated evidence tests validators, never real comic acceptance."]})
        self.manifest = self.root / "delivery-input.pending.yaml"
        save(self.manifest, manifest)
        for pid in self.ids:
            self.refresh_visual_provenance(pid)

    def tearDown(self):
        self.temp.cleanup()

    def run_check(self):
        return delivery.validate_manifest(self.manifest, diagnostic=True)

    def mutate(self, name, callback):
        path = self.root / name
        value = delivery.load_mapping(path)
        callback(value)
        save(path, value)

    def snapshot(self):
        return {str(p.relative_to(self.root)): (digest(p), p.stat().st_mtime_ns)
                for p in self.root.rglob("*") if p.is_file()}

    def refresh_visual_provenance(self, pid):
        """Explicit fabricated diagnostic observations; never production truth."""
        def binding(path):
            return {"path": str(path), "sha256": digest(path)}
        base = self.root / f"pages/renders/{pid}-base.png"
        final = self.root / f"pages/final/{pid}-final.png"
        bh, fh = digest(base), digest(final)
        generation_plan = self.root / f"plans/{pid}.yaml"
        generation_target = self.root / f"targets/{pid}.yaml"
        actual_target = self.root / f"executed-targets/{pid}.yaml"
        actual_target.parent.mkdir(parents=True, exist_ok=True)
        actual_target.write_bytes(generation_target.read_bytes())
        annotations = self.root / f"reports/{pid}-annotations.json"
        save(annotations, {"diagnostic_test_only": True, "page_id": pid, "base_sha256": bh,
                           "actual_image_checked": True, "geometry_visually_checked": True, "synthetic": False,
                           "reviewer": "DIAGNOSTIC_ONLY_FABRICATED", "notes": ["Diagnostic fixture, no actual artwork was reviewed."]})
        plan_path = self.root / f"plans/actual/{pid}.yaml"
        plan = delivery.load_mapping(plan_path)
        plan.update(execution_template_path=str(actual_target), actual_annotations_binding=binding(annotations),
                    generation_plan_path=str(generation_plan), generation_plan_sha256=digest(generation_plan),
                    generation_template_path=str(generation_target), generation_template_sha256=digest(generation_target))
        save(plan_path, plan)
        render_path = self.root / f"reports/{pid}-render.yaml"
        render = delivery.load_mapping(render_path)
        for row in render["rendered_blocks"]:
            record = row["font_raster_evidence"]
            record.update(method="pillow_draw_text_font_object", draw_calls=[{
                "text": row["text"], "font_size": row["actual_font_sizes"][0],
                "font_file": "DIAGNOSTIC_ONLY_NOT_A_REAL_FONT", "glyph_bounds_xyxy": [20,20,50,50]}])
        save(render_path, render)
        font_path = self.root / f"reports/{pid}-fonts.json"
        save(font_path, {"diagnostic_test_only": True, "actual_image_checked": True,
                        "base_image_sha256": bh, "output_image_sha256": fh,
                        "blocks": [{"block_id": row["id"], "actual_font_sizes": row["actual_font_sizes"],
                                    "font_raster_evidence": row["font_raster_evidence"]}
                                   for row in render["rendered_blocks"]]})
        evidence = {"render_report": render_path, "bubble_audit": self.root / f"reports/{pid}-bubble.json",
                    "font_raster": font_path, "base_audit": self.root / f"reports/{pid}-base.json",
                    "final_layout_audit": self.root / f"reports/{pid}-layout.json"}
        review_path = self.root / f"reports/{pid}-review.json"
        visual = delivery.load_mapping(review_path)
        visual.update(diagnostic_test_only=True, review_status="passed", reviewer="DIAGNOSTIC_ONLY_FABRICATED",
                      notes=["Explicit fabricated diagnostic record tests the gate; not actual image acceptance."],
                      evidence_files={key: binding(path) for key,path in evidence.items()},
                      input_bindings=[binding(plan_path), binding(actual_target), binding(annotations)])
        original = self.root / f"reports/{pid}-supplied-review.json"
        supplied = copy.deepcopy(visual)
        supplied.pop("review_binding", None)
        save(original, supplied)
        visual["review_binding"] = binding(original)
        save(review_path, visual)

    def configure_font(self, minimum, size):
        """Prepare a fresh internally bound diagnostic snapshot at this size."""
        save(self.root / "config/text-layout.yaml", {"minimum_readable_font_size": minimum})
        requests_path = self.root / "preparation/generation-requests.json"
        requests = delivery.load_mapping(requests_path)
        for page in requests["pages"]:
            pid = page["page_id"]
            for name in (f"plans/{pid}.yaml", f"plans/actual/{pid}.yaml"):
                self.mutate(name, lambda d: d["text_blocks"][0].update(font_size=size))
            self.mutate(f"reports/{pid}-render.yaml",
                        lambda d: d["rendered_blocks"][0].update(actual_font_sizes=[size]))
            self.mutate(f"reports/{pid}-review.json", lambda d: d["evidence_files"]["render_report"].update(
                sha256=digest(self.root / f"reports/{pid}-render.yaml")))
            proof_path = Path(page["proof"]["report_path"])
            proof = delivery.load_mapping(proof_path)
            for binding in proof["input_bindings"]:
                binding["sha256"] = digest(Path(binding["path"]))
            save(proof_path, proof)
            page["proof"]["sha256"] = digest(proof_path)
        save(requests_path, requests)
        for pid in self.ids:
            self.refresh_visual_provenance(pid)

    def rebind_preparation(self):
        requests_path = self.root / "preparation/generation-requests.json"
        requests = delivery.load_mapping(requests_path)
        for page in requests["pages"]:
            proof_path = Path(page["proof"]["report_path"])
            proof = delivery.load_mapping(proof_path)
            for binding in proof["input_bindings"]:
                binding["sha256"] = digest(Path(binding["path"]))
            save(proof_path, proof)
            page["proof"]["sha256"] = digest(proof_path)
        save(requests_path, requests)

    def configure_canvas_zone(self, genuine=True):
        """Project the genuine SB-015 source zone without altering its YAML."""
        pid = "P03"
        source_template = SCRIPTS.parent / "references/comic-layouts/executable-templates/SB-015.yaml"
        target_path = self.root / f"targets/{pid}.yaml"
        if genuine:
            target_path.write_bytes(source_template.read_bytes())
            self.assertEqual(digest(target_path), digest(source_template))
        template = delivery.load_mapping(target_path)
        if genuine:
            container = next(b for b in delivery.executable_text_containers(template)
                             if b.get("bubble_id") == "TZ-C01")
            self.assertEqual(container["canvas_binding_id"], "CANVAS")
        else:
            container = {"bubble_id": "TZ-C01", "panel_id": "CANVAS", "canvas_binding_id": "CANVAS",
                         "source_container_kind": "canvas_text_zone", "source_text_zone_id": "C01"}
        layout_id = template["layout_id"]
        for name in (f"plans/{pid}.yaml", f"plans/actual/{pid}.yaml"):
            plan = delivery.load_mapping(self.root / name)
            plan["layout_id"] = layout_id
            plan["text_blocks"][0].update(panel_id="CANVAS", bubble_id="TZ-C01", type="caption",
                                          source_type="caption", bubble_contract=copy.deepcopy(container))
            save(self.root / name, plan)
        self.mutate(f"reports/{pid}-render.yaml", lambda d: d["rendered_blocks"][0].update(
            panel_id="CANVAS", bubble_id="TZ-C01", type="caption", source_type="caption"))
        self.mutate(f"reports/{pid}-review.json", lambda d: d["evidence_files"]["render_report"].update(
            sha256=digest(self.root / f"reports/{pid}-render.yaml")))
        target_width = template.get("canvas", {}).get("width", 1080)
        target_height = template.get("canvas", {}).get("height", 1440)
        geometry = [{"panel_id": p["panel_id"], "order": p["order"],
                     "x": p["bounds"][0]*target_width, "y": p["bounds"][1]*target_height,
                     "width": p["bounds"][2]*target_width, "height": p["bounds"][3]*target_height}
                    for p in template["panels"]]
        for name in (f"reports/{pid}-base.json", f"reports/{pid}-layout.json"):
            self.mutate(name, lambda d: d.update(selected_layout=layout_id,
                target_panel_count=len(geometry), actual_panel_count=len(geometry),
                target_panel_geometry=copy.deepcopy(geometry), actual_panel_geometry=copy.deepcopy(geometry)))
        decision_path = self.root / "storyboard-decision.yaml"
        decision = delivery.load_mapping(decision_path)
        decision["pages"][0].update(layout_id=layout_id, panel_count=len(geometry), panels=template["panels"])
        decision["planned_panel_count"] = sum(p["panel_count"] for p in decision["pages"])
        save(decision_path, decision)
        self.mutate("preparation/content-coverage.json", lambda d: d["storyboard_binding"].update(sha256=digest(decision_path)))
        self.mutate("reports/story.json", lambda d: d.update(coverage_sha256=digest(self.root / "preparation/content-coverage.json")))
        self.rebind_preparation()
        self.refresh_visual_provenance(pid)

    def test_complete_nonconsecutive_prepared_order_passes_and_read_only_writes_nothing(self):
        before = self.snapshot()
        result = finalizer.finalize(self.root, check_only=True, diagnostic=True)
        self.assertEqual(result["status"], "passed", result.get("errors"))
        self.assertEqual(result["frozen_bindings_checked"], 4)
        self.assertEqual([p["page_id"] for p in result["pages"]], self.ids)
        self.assertEqual(before, self.snapshot())

    def test_metadata_only_finalization_and_separate_diagnostic_package(self):
        before = {p: digest(p) for p in self.root.rglob("*.png")}
        result = finalizer.finalize(self.root, diagnostic=True)
        self.assertEqual(result["status"], "passed", result.get("errors"))
        self.assertEqual(before, {p: digest(p) for p in self.root.rglob("*.png")})
        out = self.root / "delivery-release"
        package = delivery.deliver(self.root / "delivery-input.yaml", out, diagnostic=True)
        self.assertEqual(package["status"], "passed")
        with zipfile.ZipFile(package["archive"]["path"]) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual({n for n in archive.namelist() if n.endswith(".png")},
                             {f"images/{p}-final.png" for p in self.ids})

    def test_modified_frozen_plan_blocks(self):
        self.mutate("plans/P03.yaml", lambda d: d["text_blocks"][0].update(text="改文"))
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_modified_proof_blocks(self):
        self.mutate("preparation/P03/generation-readiness.json", lambda d: d.update(generation_ready=False))
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_actual_text_change_cannot_silently_pass(self):
        self.mutate("plans/actual/P03.yaml", lambda d: d["text_blocks"][0].update(text="【验证】"))
        result = self.run_check()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("differs from frozen" in e["reason"] for e in result["errors"]))

    def test_strict_source_failure_cannot_be_relabelled_passed(self):
        self.mutate("reports/P03-base.json", lambda d: d.update(storyboard_layout_match="passed"))
        result = self.run_check()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("source mismatch" in e["reason"] for e in result["errors"]))

    def test_selected_layout_value_does_not_mask_geometry_failure(self):
        self.mutate("reports/P03-base.json", lambda d: d["actual_panel_geometry"][0].update(width=1000))
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_missing_layout_field_blocks(self):
        self.mutate("reports/P03-layout.json", lambda d: d.pop("layout_deviation"))
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_extra_canonical_directory_variant_blocks(self):
        picture = Image.new("RGB", (1080,1440), "white")
        picture.save(self.root / "pages/final/P03-final-v2.png")
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_stale_story_final_hash_blocks(self):
        self.mutate("reports/story.json", lambda d: d["reviewed_page_hashes"].update(P03="0"*64))
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_partial_delivery_does_not_pass(self):
        self.mutate("delivery-input.pending.yaml", lambda d: d["pages"].pop())
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_diagnostic_fixture_cannot_be_packaged_as_production(self):
        self.assertEqual(delivery.validate_manifest(self.manifest)["status"], "blocked")

    def test_output_manifest_cannot_replace_production_input(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "delivery-input metadata"):
            finalizer.finalize(self.root, output_manifest=Path("production.yaml"), diagnostic=True)
        self.assertEqual(before, self.snapshot())

    def test_output_manifest_cannot_escape_run_root(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "run-local"):
            finalizer.finalize(self.root, output_manifest=Path("../delivery-input.yaml"), diagnostic=True)
        self.assertEqual(before, self.snapshot())

    def test_exact_source_excerpt_mismatch_blocks_even_when_freeze_is_consistent(self):
        self.mutate("plans/actual/P03.yaml", lambda d: d["text_blocks"][0].update(source_excerpt_verbatim=False))
        result = self.run_check()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("exact approved-source" in e["reason"] for e in result["errors"]))

    def test_rendered_channel_cannot_silently_change(self):
        self.mutate("reports/P03-render.yaml", lambda d: d["rendered_blocks"][0].update(type="dialogue"))
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_frozen_target_geometry_cannot_be_replaced_by_self_consistent_false_audit(self):
        def change(d):
            d["target_panel_geometry"][0].update(width=1000)
            d["actual_panel_geometry"][0].update(width=1000)
        self.mutate("reports/P03-base.json", change)
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_stale_declared_story_review_hash_blocks(self):
        self.mutate("delivery-input.pending.yaml", lambda d: d.update(story_review_sha256="0"*64))
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_28px_font_passes_frozen_24px_readable_minimum(self):
        self.configure_font(minimum=24, size=28)
        result = self.run_check()
        self.assertEqual(result["status"], "passed", result.get("errors"))
        self.assertEqual(result["text_integrity"]["P03"]["minimum_readable_font_size"], 24)
        self.assertEqual(len(result["frozen_bindings"]), 4)

    def test_28px_font_fails_frozen_32px_readable_minimum(self):
        self.configure_font(minimum=32, size=28)
        result = self.run_check()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("readable actual glyph evidence" in e["reason"] for e in result["errors"]))

    def test_changed_text_configuration_after_preparation_blocks(self):
        self.mutate("config/text-layout.yaml", lambda d: d.update(minimum_readable_font_size=24))
        result = self.run_check()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("frozen text_layout_path changed" in e["reason"] for e in result["errors"]))

    def test_nonpositive_readable_minimum_blocks(self):
        self.configure_font(minimum=0, size=28)
        result = self.run_check()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("positive finite number" in e["reason"] for e in result["errors"]))

    def test_genuine_unmodified_sb015_canvas_zone_is_not_a_story_panel(self):
        self.configure_canvas_zone()
        result = self.run_check()
        self.assertEqual(result["status"], "passed", result.get("errors"))
        row = next(p for p in result["pages"] if p["page_id"] == "P03")
        self.assertNotIn("CANVAS", [p["panel_id"] for p in row["actual_panel_geometry"]])
        self.assertEqual(result["text_integrity"]["P03"]["blocks"][0]["panel_id"], "CANVAS")

    def test_forged_canvas_without_source_zone_is_rejected(self):
        self.configure_canvas_zone(genuine=False)
        result = self.run_check()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("CANVAS" in e["reason"] for e in result["errors"]))

    def test_canvas_scope_without_original_explicit_binding_is_rejected(self):
        self.configure_canvas_zone()
        self.mutate("targets/P03.yaml", lambda d: d["text_zones"][0].pop("canvas_binding_id"))
        self.rebind_preparation()
        self.refresh_visual_provenance("P03")
        result = self.run_check()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("original explicit executable canvas" in e["reason"] for e in result["errors"]))

    def test_canvas_contract_cannot_forge_another_source_zone(self):
        self.configure_canvas_zone()
        self.mutate("plans/actual/P03.yaml", lambda d: d["text_blocks"][0]["bubble_contract"].update(source_text_zone_id="C99"))
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_same_panel_bubble_switch_after_freeze_is_rejected(self):
        self.mutate("plans/actual/P03.yaml", lambda d: d["text_blocks"][0].update(bubble_id="B99"))
        result = self.run_check()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("differs from frozen preparation" in e["reason"] for e in result["errors"]))

    def test_actual_visual_review_requires_named_reviewer(self):
        self.mutate("reports/P03-review.json", lambda d: d.pop("reviewer"))
        result = self.run_check()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("reviewer" in e["reason"] for e in result["errors"]))

    def test_actual_visual_review_requires_concrete_notes(self):
        self.mutate("reports/P03-review.json", lambda d: d.update(notes=[]))
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_actual_visual_review_requires_separate_supplied_observations(self):
        self.mutate("reports/P03-review.json", lambda d: d.pop("review_binding"))
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_production_review_cannot_change_supplied_observations(self):
        self.mutate("reports/P03-supplied-review.json", lambda d: d.update(notes=["Different observations."]))
        self.mutate("reports/P03-review.json", lambda d: d["review_binding"].update(
            sha256=digest(self.root / "reports/P03-supplied-review.json")))
        result = self.run_check()
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("separately supplied visual observations" in e["reason"] for e in result["errors"]))

    def test_delivery_accepts_review_without_mobile_preview_binding(self):
        for name in ("reports/P03-review.json", "reports/P03-supplied-review.json"):
            self.mutate(name, lambda d: [d.pop(key, None) for key in
                ("mobile_image", "mobile_image_sha256", "mobile_image_checked")])
        self.mutate("reports/P03-review.json", lambda d: d["review_binding"].update(
            sha256=digest(self.root / "reports/P03-supplied-review.json")))
        result = self.run_check()
        self.assertEqual(result["status"], "passed")

    def test_actual_annotations_must_be_bound_by_both_reviews(self):
        for name in ("reports/P03-review.json", "reports/P03-supplied-review.json"):
            self.mutate(name, lambda d: d.update(input_bindings=d["input_bindings"][:2]))
        self.mutate("reports/P03-review.json", lambda d: d["review_binding"].update(
            sha256=digest(self.root / "reports/P03-supplied-review.json")))
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_actual_visual_review_requires_all_five_current_reports(self):
        self.mutate("reports/P03-review.json", lambda d: d["evidence_files"].pop("font_raster"))
        self.assertEqual(self.run_check()["status"], "blocked")

    def test_normal_delivery_rejects_diagnostic_evidence_linked_below_review(self):
        self.mutate("delivery-input.pending.yaml", lambda d: d.pop("diagnostic_test_only"))
        for pid in self.ids:
            for name in (f"reports/{pid}-review.json", f"reports/{pid}-supplied-review.json"):
                self.mutate(name, lambda d: d.pop("diagnostic_test_only"))
            self.mutate(f"reports/{pid}-review.json", lambda d: d["review_binding"].update(
                sha256=digest(self.root / f"reports/{pid}-supplied-review.json")))
        result = delivery.validate_manifest(self.manifest)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("diagnostic" in e["reason"].lower() for e in result["errors"]))


if __name__ == "__main__":
    unittest.main()
