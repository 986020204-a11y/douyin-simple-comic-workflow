"""Isolated labeled diagnostics for actual-image runtime, never comic artwork."""
from pathlib import Path
import copy
import json
import sys
import tempfile
import unittest

from PIL import Image
import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills/douyin-simple-comic-workflow"
sys.path.insert(0, str(SKILL / "scripts"))
import production_runtime as runtime
import scene_repairs as repairs


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="comic-runtime-diagnostic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = repairs.read(SKILL / "references/comic-layouts/executable-templates/SB-055.yaml")
        self.target.update(canvas={"width": 1080, "height": 1440}, match_policy="adapted",
                           user_approved_adaptation=True, diagnostic_test_only=True)
        self.target["panels"][0]["bounds"] = [0, 0, 1, 1]
        for unit in self.target.get("structure", {}).get("units", []):
            unit["bounds"] = [0, 0, 1, 1]
        self.target["bubbles"][0]["bounds"] = [.1, .1, .2, .2]
        self.target["bubbles"][0]["polygon"] = [[.1, .1], [.3, .1], [.3, .3], [.1, .3]]
        self.target["bubbles"][0]["typography_regions"] = [
            {"bounds": [.11, .11, .18, .06], "coordinate_space": "template_normalized"},
            {"bounds": [.11, .2, .18, .06], "coordinate_space": "template_normalized"}]
        self.write("targets/custom.yaml", self.target)
        self.write("plans/custom.yaml", {"page_id": "CUSTOM-7", "text_blocks": [], "diagnostic_test_only": True})
        font = str(SKILL / "assets/fonts/mashanzheng/MaShanZheng-Regular.ttf")
        self.write("config/text.yaml", {"font_file": font, "font_bold_file": font, "font_size": 36})
        self.write("production.yaml", {"diagnostic_test_only": True, "pages": [{
            "page_id": "CUSTOM-7", "template_path": "targets/custom.yaml",
            "text_plan_path": "plans/custom.yaml", "text_layout_path": "config/text.yaml"}]})
        self.image("pages/assets/CUSTOM-7-P01-scene.png", (800, 600), "steelblue")
        self.rt = runtime.Runtime(self.root, self.root / "production.yaml", "CUSTOM-7")

    def write(self, path, obj):
        path = self.root / path
        runtime.write(path, obj)
        return path

    def image(self, path, size=(80, 60), color="blue"):
        path = self.root / path
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", size, color).save(path)
        return path

    def test_assemble_uses_uniform_cover_and_preserves_existing_base(self):
        before = repairs.digest(self.rt.generation_target)
        result = self.rt.assemble()
        self.assertEqual(result["execution_geometry_match"], "passed")
        self.assertFalse(result["base_image_modified"])
        self.assertEqual(repairs.digest(self.rt.generation_target), before)
        actual = repairs.read(self.rt.report("base-actual.json"))
        fit = actual["asset_cover_adaptations"][0]
        self.assertEqual(fit["uniform_scale"], 2.4)
        self.assertEqual(fit["crop_after_scale_xy"], [420.0, 0])
        self.assertFalse(fit["stretched"])
        with self.assertRaisesRegex(ValueError, "Preserve existing base"):
            self.rt.assemble()

    def test_diagnostic_queue_cannot_feed_normal_runtime(self):
        self.rt.state_path = self.write("diagnostic-state.json", {"diagnostic_test_only": True})
        self.rt.manifest.pop("diagnostic_test_only")
        with self.assertRaisesRegex(ValueError, "Diagnostic queue assets"):
            self.rt.assets()

    def test_polygon_cover_uses_polygon_envelope(self):
        unit = {"unit_id": "OVERHANG", "x": 200, "y": 200, "width": 200, "height": 200,
                "polygon": [[100, 100], [600, 100], [600, 500], [100, 500]]}
        fit = runtime.cover_fit(unit, (500, 400), (1080, 1440))
        self.assertEqual(fit["target_size"], [500, 400])
        self.assertEqual(fit["uniform_scale"], 1)

    def test_fit_persists_polygon_transform_without_mutating_frozen_inputs(self):
        self.rt.assemble()
        originals = [repairs.digest(p) for p in (self.rt.generation_plan, self.rt.generation_target)]
        record = self.write("fit.yaml", {"page_id": "CUSTOM-7", "approved_for_run": True,
            "origin": "workflow_adaptation", "reason": "Diagnostic bounds/polygon regression only",
            "base_image_sha256": repairs.digest(self.rt.base), "bubble_bounds_px": {"B01": [216, 288, 432, 432]}})
        self.rt.fit(record)
        _, _, target_path, target = self.rt.actual_files()
        bubble = target["bubbles"][0]
        self.assertEqual(bubble["bounds"], [.2, .2, .4, .3])
        for got, expected in zip(bubble["polygon"], [[.2, .2], [.6, .2], [.6, .5], [.2, .5]]):
            for a, b in zip(got, expected):
                self.assertAlmostEqual(a, b)
        self.assertTrue(target_path.is_file())
        self.assertEqual([repairs.digest(p) for p in (self.rt.generation_plan, self.rt.generation_target)], originals)
        self.assertEqual(bubble["tail"]["mode"], "none")
        self.assertEqual(len(bubble["typography_regions"]), 2)
        for region in bubble["typography_regions"]:
            self.assertTrue(runtime.contained(region["bounds"], bubble["bounds"], tolerance=.00001))

    def test_typography_fit_cannot_add_regions_or_place_them_outside_body(self):
        self.rt.assemble()
        record = {"page_id": "CUSTOM-7", "approved_for_run": True, "origin": "workflow_adaptation",
            "reason": "Diagnostic typography regression", "base_image_sha256": repairs.digest(self.rt.base),
            "bubble_bounds_px": {"B01": [216, 288, 432, 432]},
            "bubble_typography_regions_px": {"B01": [[220, 300, 100, 100]]}}
        with self.assertRaisesRegex(ValueError, "preserves the existing region count"):
            self.rt.fit(self.write("fit.yaml", record))
        record["bubble_typography_regions_px"]["B01"] = [[0, 0, 100, 100], [220, 300, 100, 100]]
        with self.assertRaisesRegex(ValueError, "leaves fitted body"):
            self.rt.fit(self.write("fit.yaml", record))

    def test_fit_requires_approval_and_stays_inside_panel(self):
        self.rt.assemble()
        record = {"page_id": "CUSTOM-7", "origin": "workflow_adaptation", "reason": "diagnostic",
                  "base_image_sha256": repairs.digest(self.rt.base), "bubble_bounds_px": {"B01": [0, 0, 100, 100]}}
        with self.assertRaisesRegex(ValueError, "explicit run approval"):
            self.rt.fit(self.write("fit.yaml", record))
        record.update(approved_for_run=True, bubble_bounds_px={"B01": [1050, 0, 100, 100]})
        with self.assertRaisesRegex(ValueError, "cross its actual panel"):
            self.rt.fit(self.write("fit.yaml", record))

    def test_frozen_generation_change_blocks_actual_pair(self):
        self.rt.actual_files()
        plan = repairs.read(self.rt.generation_plan)
        plan["unexpected_change"] = True
        self.write("plans/custom.yaml", plan)
        with self.assertRaisesRegex(ValueError, "Frozen generation"):
            self.rt.actual_files()

    def test_actual_plan_cannot_rewrite_story_text_or_panel_geometry(self):
        pp, plan, tp, target = self.rt.actual_files()
        plan["text_blocks"] = [{"id": "INVENTED", "text": "invented"}]
        runtime.write(pp, plan)
        with self.assertRaisesRegex(ValueError, "changed frozen story"):
            self.rt.actual_files()
        plan["text_blocks"] = []
        runtime.write(pp, plan)
        target["panels"][0]["bounds"] = [0, 0, .5, .5]
        runtime.write(tp, target)
        with self.assertRaisesRegex(ValueError, "cannot change frozen panel"):
            self.rt.actual_files()

    def test_unknown_tail_never_guessed(self):
        bubble = {"bubble_id": "B", "bounds": [.1, .1, .2, .2],
                  "tail": {"mode": "unknown", "anchor": None}}
        before = copy.deepcopy(bubble)
        self.assertIsNone(runtime.rebind_known_tip(bubble, [800, 800, 100, 100], (1080, 1440)))
        self.assertEqual(bubble, before)

    def test_canvas_text_zone_projection_retains_mutable_source_geometry(self):
        target = {"panels": [{"panel_id": "P01"}], "text_zones": [{"zone_id": "Z01",
            "scope": "canvas", "executable": True, "bounds": [.1, .1, .2, .2]}]}
        projected = runtime.mutable_containers(target)
        self.assertEqual(projected["TZ-Z01"]["panel_id"], "CANVAS")
        projected["TZ-Z01"]["bounds"] = [.2, .2, .3, .3]
        self.assertEqual(target["text_zones"][0]["bounds"], [.2, .2, .3, .3])
        self.assertEqual(target["panels"], [{"panel_id": "P01"}])

    def test_finish_rejects_changed_scene_assets_before_composition(self):
        self.rt.assemble()
        self.image("pages/assets/CUSTOM-7-P01-scene.png", (800, 600), "red")
        with self.assertRaisesRegex(ValueError, "changed evidence"):
            self.rt.finish()

    def test_known_tail_moves_only_the_existing_tip(self):
        bubble = {"bubble_id": "B", "bounds": [.1, .1, .2, .2], "tail": {
            "mode": "observed_polygon", "anchor_kind": "speaker", "anchor": [.4, .4],
            "polygon": [[.25, .25], [.4, .4], [.28, .25]]}}
        body = copy.deepcopy(bubble["tail"]["polygon"])
        changed = runtime.rebind_known_tip(bubble, [700, 800, 100, 100], (1080, 1440))
        self.assertIsNotNone(changed)
        self.assertEqual(bubble["tail"]["polygon"][0], body[0])
        self.assertEqual(bubble["tail"]["polygon"][2], body[2])
        self.assertNotEqual(bubble["tail"]["polygon"][1], body[1])

    def test_promote_cannot_invent_full_or_mobile_review(self):
        self.image("pages/renders/CUSTOM-7-base.png")
        self.image("pages/candidates/CUSTOM-7/checked-render.png")
        fake = self.write("fake-review.json", {"review_status": "passed", "checks": {k: "passed" for k in runtime.CHECKS}})
        with self.assertRaisesRegex(ValueError, "explicit current full-size"):
            self.rt.promote(fake)
        self.assertFalse(self.rt.canonical.exists())

    def repair_record(self):
        original = self.root / "pages/assets/CUSTOM-7-P01-scene.png"
        source = self.image("returned/edited.png", (800, 600), "green")
        record = {"page_id": "CUSTOM-7", "unit_id": "P01", "reason": "Diagnostic repair preservation regression",
                  "original_path": str(original), "generated_source_path": str(source),
                  "saved_path": "pages/assets/repairs/edited.png", "actual_edit_reviewed": True}
        return self.write("repair.json", record)

    def test_save_repair_forces_pending_and_preserves_original(self):
        record_path = self.repair_record()
        original = self.root / "pages/assets/CUSTOM-7-P01-scene.png"
        before = repairs.digest(original)
        result = repairs.save_repair(self.root, record_path)
        record = repairs.read(record_path)
        self.assertEqual(result["review_status"], "pending")
        self.assertIs(record["actual_edit_reviewed"], False)
        self.assertEqual(repairs.digest(original), before)
        with self.assertRaisesRegex(ValueError, "separate actual-image review"):
            repairs.register_repair(self.root, record_path, self.write("review.json", {"review_status": "passed"}))

    def test_reviewed_repair_hashes_rechecked_and_outside_edits_rejected(self):
        record_path = self.repair_record()
        repairs.save_repair(self.root, record_path)
        record = repairs.read(record_path)
        review_path = self.write("review.json", {"page_id": "CUSTOM-7", "unit_id": "P01", "review_status": "passed",
            "actual_image_checked": True, "synthetic": False, "reviewer": "diagnostic-test-fixture-not-human-review",
            "notes": ["This is a labeled synthetic regression, not production acceptance."],
            "repair_record_sha256": repairs.digest(record_path), "original_sha256": record["original_sha256"],
            "edited_sha256": record["edited_sha256"]})
        repairs.register_repair(self.root, record_path, review_path)
        item = repairs.read(self.root / "pages/asset-overrides.json")["CUSTOM-7/P01"]
        original = Path(record["original_path"])
        self.assertEqual(repairs.resolve_repair(self.root, "CUSTOM-7/P01", original, item), Path(record["saved_path"]))
        changed = copy.deepcopy(item); changed["edited_path"] = str(self.root.parent / "outside.png")
        with self.assertRaisesRegex(ValueError, "inside this isolated run"):
            repairs.resolve_repair(self.root, "CUSTOM-7/P01", original, changed)
        self.image("pages/assets/repairs/edited.png", (800, 600), "red")
        with self.assertRaisesRegex(ValueError, "stale repair"):
            repairs.resolve_repair(self.root, "CUSTOM-7/P01", original, item)

    def test_bare_legacy_repair_acceptance_is_rejected(self):
        record_path = self.repair_record()
        repairs.save_repair(self.root, record_path)
        record = repairs.read(record_path)
        item = {"original_path": record["original_path"], "original_sha256": record["original_sha256"],
                "edited_path": record["saved_path"], "edited_sha256": record["edited_sha256"],
                "actual_edit_reviewed": True, "reason": "diagnostic", "repair_record": str(record_path)}
        with self.assertRaisesRegex(ValueError, "no concrete manual review"):
            repairs.resolve_repair(self.root, "CUSTOM-7/P01", Path(record["original_path"]), item)


if __name__ == "__main__":
    unittest.main()
