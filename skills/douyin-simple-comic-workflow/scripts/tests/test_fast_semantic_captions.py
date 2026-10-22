"""Offline semantic FAST text tests; all artwork fixtures are temporary simulations."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fast_caption
import fast_queue
import fast_text


def _font():
    for candidate in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                      "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if Path(candidate).is_file():
            return Path(candidate)
    return None


@unittest.skipUnless(_font(), "a local Chinese font is required")
class SemanticCaptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fast = self.root / "fast"
        self.fast.mkdir()
        self.font = _font()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def page(self, captions=None, panels=None):
        return {"page_id": "P01", "narrative_function": "双方试探，随后安静下来",
                "panels": panels or [{"panel_id": "U01", "bounds": [0, 0, 1, 1]}],
                "layout": {"layout_id": "SB-025", "guidance": {"panels": panels or [
                    {"panel_id": "U01", "bounds": [0, 0, 1, 1]}], "text_zones": []}},
                "captions": captions if captions is not None else [
                    {"text": "你愿意留下吗？", "type": "dialogue", "panel_id": "U01",
                     "speaker_id": "N01", "bounds": [0.05, 0.05, 0.65, 0.18], "font_size": 32}]}

    def planned(self, page=None):
        return fast_caption.prepare_caption_plan(page or self.page(), {
            "font_size": 32, "canvas_size": [800, 1200],
            "font_binding": {"path": str(self.font), "sha256": fast_queue.sha256(self.font)}})

    def fixture(self, page=None, visual_review_required=False, no_font=False):
        caption_plan = self.planned(page)
        if no_font:
            caption_plan["text_settings"].pop("font_binding", None)
        self.caption_path = self.fast / "captions" / "P01.json"
        self.write(self.caption_path, caption_plan)
        prompt = self.fast / "prompt.txt"
        prompt.write_text("SIMULATION ONLY: never generate production artwork", encoding="utf-8")
        plan = {"schema_version": 1, "mode": "fast", "simulation": True, "max_attempts": 2,
                "first_page_id": "P01", "visual_review_required": visual_review_required,
                "input_bindings": [{"path": str(self.caption_path), "sha256": fast_queue.sha256(self.caption_path)}],
                "pages": [{"page_id": "P01", "prompt_path": str(prompt),
                           "prompt_sha256": fast_queue.sha256(prompt), "reference_bindings": [],
                           "caption_plan_path": str(self.caption_path),
                           "caption_plan_sha256": fast_queue.sha256(self.caption_path),
                           "output_dir": str(self.fast / "images")}]}
        self.write(self.fast / "plan.json", plan)
        fast_queue.init_queue(self.root)
        source = self.root / "SIMULATED-plain-fixture.png"
        Image.new("RGB", (800, 1200), (70, 110, 150)).save(source)
        claim = fast_queue.claim_page(self.root)
        result = fast_queue.complete_page(self.root, "P01", claim["claim_token"], source,
                                          "SIMULATED-call-1", provider="simulation")
        self.base = Path(result["output_path"])
        return caption_plan

    def revision(self, original, name="P01-v1.json"):
        revised = copy.deepcopy(original)
        revised["image_review"] = {
            "page_id": "P01", "image_sha256": fast_queue.sha256(self.base),
            "geometry_observed_from_image": True, "caption_placements_verified": True,
            "panels": [{"panel_id": "U01", "bounds": [0, 0, 1, 1]}],
            "protected_regions": [{"bounds": [0.7, 0.5, 0.2, 0.25]}],
            "speaker_regions": [{"speaker_id": "N01", "panel_id": "U01", "bounds": [0.2, 0.4, 0.2, 0.3]}]}
        path = self.fast / "caption-revisions" / name
        self.write(path, revised)
        return revised, path

    def pass_image_review(self, revision):
        document = copy.deepcopy(revision["image_review"])
        document["checks"] = {name: {"passed": True, "reason": "Explicit simulation observation for this offline fixture"}
                              for name in ("character_consistency", "story_coverage", "storyboard_execution")}
        path = self.root / "SIMULATION-image-review.json"
        self.write(path, document)
        return fast_queue.review_page(self.root, "P01", path)

    def test_selected_original_sb_zone_supplies_bounds_without_retyping_narration(self):
        page = self.page([{"text": "他终于开口。", "type": "narration", "panel_id": "U01"}])
        page["layout"]["guidance"]["text_zones"] = [{"panel_id": "U01", "bounds": [0.1, 0.1, 0.7, 0.2],
                                                     "shape": "speech", "allowed_text_types": ["narration", "dialogue"]}]
        result = self.planned(page)
        self.assertEqual(result["captions"][0]["bounds"], [0.1, 0.1, 0.7, 0.2])
        self.assertEqual(result["captions"][0]["bubble_style"], "narration_box")
        self.assertEqual(result["captions"][0]["type"], "narration")

    def test_authored_bounds_win_over_template_and_no_global_grid_fallback(self):
        page = self.page()
        page["layout"]["guidance"]["text_zones"] = [{"panel_id": "U01", "bounds": [0.5, 0.5, 0.4, 0.3]}]
        self.assertEqual(self.planned(page)["captions"][0]["bounds"], [0.05, 0.05, 0.65, 0.18])
        del page["captions"][0]["bounds"]
        page["layout"]["guidance"]["text_zones"] = []
        with self.assertRaisesRegex(ValueError, "author bounds"):
            self.planned(page)

    def test_explicit_type_and_multi_panel_ownership_are_required(self):
        page = self.page()
        del page["captions"][0]["type"]
        with self.assertRaisesRegex(ValueError, "source text type"):
            self.planned(page)
        page = self.page(panels=[{"panel_id": "U01"}, {"panel_id": "U02"}])
        del page["captions"][0]["panel_id"]
        with self.assertRaisesRegex(ValueError, "explicit panel_id"):
            self.planned(page)

    def test_real_font_preflight_reuses_original_six_semantic_renderers(self):
        kinds = ["narration", "dialogue", "thought", "shout", "note", "emphasis"]
        captions = [{"text": "短句", "type": kind, "panel_id": "U01", "font_size": 28,
                     "bounds": [0.05, 0.03 + i * 0.16, 0.7, 0.13]} for i, kind in enumerate(kinds)]
        plan = self.planned(self.page(captions))
        result = fast_caption.preflight_caption_plan(plan, self.font, [800, 1200])
        self.assertEqual(result["status"], "passed")
        self.assertEqual([r["used_style"] for r in result["rendered_layouts"]], [
            "narration_box", "rounded_speech", "thought_bubble", "shout_burst", "preview_caption_note", "emphasis_box"])
        self.assertEqual(result["font_sha256"], fast_queue.sha256(self.font))
        for row in result["rendered_layouts"]:
            self.assertEqual(row["font_raster_evidence"]["actual_font_sizes"], [28])
            self.assertEqual(row["renderer"], "original_text_compositor._draw_block")
            self.assertEqual(row["geometry_evidence"], "planning_only")

    def test_thought_cloud_has_no_internal_ellipse_strokes_in_text_corridor(self):
        page = self.page([{"text": "原有心声气泡", "type": "thought", "panel_id": "U01",
                          "bounds": [0.06, 0.08, 0.86, 0.6], "font_size": 36}])
        plan = self.planned(page)
        size = (900, 350)
        blank = Image.new("RGB", size, "white")
        fixed, layouts = fast_text.render_caption_plan(plan, blank, self.font)
        row = layouts[0]
        body = next(p["rect"] for p in row["geometry"] if p["part"] == "shape")
        x0, y0, x1, y1 = body
        config = {"font_file": str(self.font), "font_size": 36, "font_size_policy": "fixed",
                  "minimum_readable_font_size": 24, "_explicit_font_size": True}
        glyph_layer = Image.new("RGBA", size, (0, 0, 0, 0))
        fast_text.compositor._draw_text(ImageDraw.Draw(glyph_layer), "原有心声气泡",
            (x0 + 12, y0 + 14, x1 - 12, y1 - 16), config, size=36, align="center")
        glyph_mask = glyph_layer.getchannel("A").point(lambda value: 255 if value else 0)
        # This interior corridor includes the old ellipse seams and excludes the outer silhouette.
        corridor = (x0 + int((x1 - x0) * 0.22), y0 + int((y1 - y0) * 0.35),
                    x0 + int((x1 - x0) * 0.80), y0 + int((y1 - y0) * 0.65))
        fixed_ink = ImageChops.difference(fixed, blank).convert("L").point(lambda value: 255 if value else 0)
        self.assertIsNone(ImageChops.subtract(fixed_ink, glyph_mask).crop(corridor).getbbox())
        old = blank.convert("RGBA")
        old_block, rect = fast_text._block(plan["captions"][0], size, None)
        fast_text.compositor._draw_block(ImageDraw.Draw(old), old_block, rect, config)
        old_ink = ImageChops.difference(old.convert("RGB"), blank).convert("L").point(lambda value: 255 if value else 0)
        self.assertIsNotNone(ImageChops.subtract(old_ink, glyph_mask).crop(corridor).getbbox())
        self.assertTrue(row["contour_adaptation"]["internal_strokes_removed"])
        self.assertTrue(row["contour_adaptation"]["same_fixed_font_and_text_bounds"])
        self.assertEqual(row["font_raster_evidence"]["actual_font_sizes"], [36])

    def test_overflow_is_caught_offline_before_any_generation_queue_exists(self):
        page = self.page()
        page["captions"][0].update(text="这是很长的中文对白" * 100, bounds=[0.05, 0.05, 0.3, 0.08])
        plan = self.planned(page)
        with self.assertRaisesRegex(ValueError, "overflows"):
            fast_caption.preflight_caption_plan(plan, self.font, [800, 1200])
        self.assertFalse((self.fast / "state.json").exists())
        self.assertFalse((self.fast / "plan.json").exists())

    def test_actual_image_review_is_required_before_final_selection(self):
        self.fixture()
        before = (self.fast / "state.json").read_bytes()
        result = fast_caption.compose(self.root, "P01")
        self.assertEqual(result["status"], "pending-placement")
        self.assertFalse(result["selected_final"])
        self.assertFalse((self.fast / "final").exists())
        self.assertFalse((self.fast / "caption-selection.json").exists())
        self.assertEqual((self.fast / "state.json").read_bytes(), before)

    def test_bad_or_pending_image_review_cannot_become_selected_final(self):
        self.fixture(visual_review_required=True)
        result = fast_caption.compose(self.root, "P01")
        self.assertEqual(result["status"], "pending-image-review")
        self.assertFalse((self.fast / "caption-selection.json").exists())

    def test_tampered_passed_visual_review_blocks_selection_without_mutating_queue(self):
        original = self.fixture(visual_review_required=True)
        revision, path = self.revision(original)
        reviewed = self.pass_image_review(revision)
        Path(reviewed["visual_review_path"]).write_text("{}", encoding="utf-8")
        before_state = (self.fast / "state.json").read_bytes()
        result = fast_caption.compose(self.root, "P01", caption_plan_path=path)
        self.assertEqual(result["status"], "pending-image-review")
        self.assertEqual((self.fast / "state.json").read_bytes(), before_state)
        self.assertFalse((self.fast / "caption-selection.json").exists())

    def test_concurrent_review_revocation_cannot_select_a_stale_render(self):
        original = self.fixture(visual_review_required=True)
        revision, path = self.revision(original)
        self.pass_image_review(revision)
        renderer = fast_caption.render_caption_plan

        def revoke_after_render(*args, **kwargs):
            result = renderer(*args, **kwargs)
            state = json.loads((self.fast / "state.json").read_text(encoding="utf-8"))
            state["pages"]["P01"]["visual_review_status"] = "pending"
            self.write(self.fast / "state.json", state)
            return result

        with patch.object(fast_caption, "render_caption_plan", side_effect=revoke_after_render):
            with self.assertRaisesRegex(ValueError, "visual review changed"):
                fast_caption.compose(self.root, "P01", caption_plan_path=path)
        self.assertFalse((self.fast / "caption-selection.json").exists())

    def test_position_revision_is_local_persisted_and_resumes_latest(self):
        original = self.fixture()
        revision, path = self.revision(original)
        first = fast_caption.compose(self.root, "P01", caption_plan_path=path)
        old_output = Path(first["output_path"])
        before_state = (self.fast / "state.json").read_bytes()
        before_base = self.base.read_bytes()
        revision["captions"][0]["bounds"] = [0.1, 0.24, 0.6, 0.15]
        second_path = self.fast / "caption-revisions" / "P01-v2.json"
        self.write(second_path, revision)
        with patch.object(fast_queue, "claim_page", side_effect=AssertionError("caption edit requested generation")):
            second = fast_caption.compose(self.root, "P01", caption_plan_path=second_path)
            resumed = fast_caption.compose(self.root, "P01")
        self.assertEqual(resumed["status"], "skipped")
        self.assertEqual(resumed["output_path"], second["output_path"])
        self.assertEqual(resumed["caption_plan_path"], str(second_path))
        self.assertNotEqual(first["output_path"], second["output_path"])
        self.assertTrue(old_output.is_file())
        self.assertEqual((self.fast / "state.json").read_bytes(), before_state)
        self.assertEqual(self.base.read_bytes(), before_base)
        manifest = json.loads((self.fast / "caption-selection.json").read_text(encoding="utf-8"))["pages"]["P01"]
        self.assertEqual(manifest["caption_plan_sha256"], fast_queue.sha256(second_path))
        self.assertEqual(manifest["output_sha256"], fast_queue.sha256(second["output_path"]))
        self.assertEqual(manifest["base_image_sha256"], fast_queue.sha256(self.base))

    def test_semantic_ownership_and_source_wording_cannot_silently_change(self):
        original = self.fixture()
        for field, value in (("type", "narration"), ("panel_id", "other"), ("speaker_id", "N02"), ("source_text", "改写")):
            revision, path = self.revision(original)
            revision["captions"][0][field] = value
            self.write(path, revision)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "preserve source text"):
                fast_caption.compose(self.root, "P01", caption_plan_path=path)
        revision, path = self.revision(original)
        revision["captions"][0]["text"] = "我会留下。"
        self.write(path, revision)
        with self.assertRaisesRegex(ValueError, "text_revision_reason"):
            fast_caption.compose(self.root, "P01", caption_plan_path=path)
        revision["captions"][0]["text_revision_reason"] = "用户明确修改这一句对白"
        self.write(path, revision)
        self.assertTrue(fast_caption.compose(self.root, "P01", caption_plan_path=path)["selected_final"])

    def test_stale_review_protection_overlap_and_wrong_panel_are_rejected(self):
        original = self.fixture()
        revision, path = self.revision(original)
        revision["image_review"]["image_sha256"] = "0" * 64
        self.write(path, revision)
        with self.assertRaisesRegex(ValueError, "current base image hash"):
            fast_caption.compose(self.root, "P01", caption_plan_path=path)
        revision, path = self.revision(original)
        revision["image_review"]["protected_regions"] = [{"bounds": [0.05, 0.05, 0.6, 0.2]}]
        self.write(path, revision)
        with self.assertRaisesRegex(ValueError, "protected region"):
            fast_caption.compose(self.root, "P01", caption_plan_path=path)
        revision, path = self.revision(original)
        revision["image_review"]["panels"][0]["bounds"] = [0, 0.4, 1, 0.6]
        self.write(path, revision)
        with self.assertRaisesRegex(ValueError, "actual panel"):
            fast_caption.compose(self.root, "P01", caption_plan_path=path)

    def test_unconfirmed_tail_never_guesses_a_speaker_or_another_panel(self):
        original = self.fixture()
        revision, path = self.revision(original)
        revision["captions"][0]["tail_requested"] = True
        revision["image_review"]["speaker_regions"] = []
        self.write(path, revision)
        with self.assertRaisesRegex(ValueError, "confirmed speaker/owner"):
            fast_caption.compose(self.root, "P01", caption_plan_path=path)
        revision["captions"][0]["tail_requested"] = False
        self.write(path, revision)
        result = fast_caption.compose(self.root, "P01", caption_plan_path=path)
        self.assertFalse(result["rendered_layouts"][0]["tail_enabled"])

    def test_selected_revision_and_final_hashes_are_revalidated_on_resume(self):
        original = self.fixture()
        revision, path = self.revision(original)
        first = fast_caption.compose(self.root, "P01", caption_plan_path=path)
        revised_bytes = path.read_bytes()
        path.write_bytes(revised_bytes + b"\n")
        with self.assertRaisesRegex(ValueError, "selected caption revision"):
            fast_caption.compose(self.root, "P01")
        path.write_bytes(revised_bytes)
        Path(first["output_path"]).write_bytes(b"changed final")
        with self.assertRaisesRegex(ValueError, "selected final output"):
            fast_caption.compose(self.root, "P01")

    def test_one_global_style_cannot_override_semantic_text_types(self):
        page = self.page()
        page["captions"][0]["bubble_style"] = "narration_box"
        with self.assertRaisesRegex(ValueError, "source text semantics"):
            self.planned(page)

    def test_new_textless_page_does_not_require_a_font_or_placement_annotation(self):
        self.fixture(self.page([]), no_font=True)
        result = fast_caption.compose(self.root, "P01")
        self.assertTrue(result["selected_final"])
        self.assertEqual(result["caption_count"], 0)
        with Image.open(self.base) as source, Image.open(result["output_path"]) as final:
            self.assertEqual(source.tobytes(), final.tobytes())


if __name__ == "__main__":
    unittest.main()
