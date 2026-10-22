"""Offline semantic planning checks against the original bundled SB library.

Any bitmap fixture is a labelled SIMULATION in a TemporaryDirectory. These tests
do not call image generation, edit historical projects, or assert visual quality.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fast_prepare
import fast_storyboard as storyboard


def page(number=1, count=4, layout_id=None, narrative="人物的回应逐渐改变当前的情绪"):
    result = {"page_id": f"P{number:02d}", "narrative_function": narrative,
              "panel_count_reason": f"用{count}个原文中的动作与反应呈现这一页的情绪变化",
              "panels": [{"panel_id": f"U{n:02d}", "focus": f"人物第{n}次回应",
                          "main_action_or_emotion": f"第{n}个回应中的迟疑与释然"} for n in range(1, count + 1)],
              "prompt": "SIMULATION planning only. Complete no-text comic page.", "captions": []}
    if layout_id:
        result["layout_id"] = layout_id
    return result


class SemanticSelectionTests(unittest.TestCase):
    def test_shortlist_uses_original_semantics_not_ordinal_rotation(self):
        result = storyboard.shortlist("正反打 对话 心理交锋", 3)
        self.assertEqual(result[0]["id"], "SB-025")
        self.assertEqual(result[0]["native_panel_count"], 6)
        self.assertIn("fast_compatibility", result[0])
        self.assertEqual(len(storyboard.load_pool()), 68)

    def test_selected_single_unit_uses_real_single_compatible_sb(self):
        selected = storyboard.select_pages({"pages": [page(count=1, narrative="全幅大画面突出重逢的瞬间") ]})
        p = selected["pages"][0]
        self.assertIn(p["layout_id"], {"SB-055", "SB-056"})
        self.assertIsNotNone(p["layout"])
        self.assertEqual(len(p["layout"]["guidance"]["panels"]), 1)

    def test_authored_story_counts_and_original_regions_are_preserved(self):
        document = {"pages": [page(1, 6, "SB-025", "两个人交替试探并发生言语交锋"),
                               page(2, 5, "SB-023", "由远到近逐渐看到人物的情绪崩溃"),
                               page(3, 1, "SB-055", "全幅拥抱承接最终安心的高潮") ]}
        result = storyboard.select_pages(document)
        self.assertEqual([p["panel_count"] for p in result["pages"]], [6, 5, 1])
        self.assertEqual([p["layout_id"] for p in result["pages"]], ["SB-025", "SB-023", "SB-055"])
        self.assertEqual(document["pages"][0]["panels"][0]["panel_id"], "U01")
        self.assertNotEqual(result["pages"][0]["layout"]["guidance"]["panels"],
                            result["pages"][1]["layout"]["guidance"]["panels"])

    def test_distinct_original_sbs_with_same_count_have_real_distinct_regions(self):
        selected = storyboard.select_pages({"pages": [page(1, 5, "SB-023"), page(2, 5, "SB-054")]})["pages"]
        first, second = [p["layout"]["guidance"]["panels"] for p in selected]
        self.assertNotEqual([p.get("bounds") for p in first], [p.get("bounds") for p in second])
        self.assertNotEqual(selected[0]["layout"]["source_sha256"], selected[1]["layout"]["source_sha256"])

    def test_six_and_twelve_page_semantic_story_does_not_use_one_global_layout(self):
        beats = [(4, "用全景开场交代雨夜街道与孩子独自回家的环境"),
                 (6, "正反打呈现母亲和孩子的对话与试探"),
                 (4, "动作分解：母亲开门、伸手接包、拉孩子进门"),
                 (5, "由远到近，孩子从门口走向母亲，最后眼睛含泪"),
                 (8, "节奏骤停：先快速推进多个短动作，然后静止在孩子的反应"),
                 (1, "全幅大画面以温暖拥抱完成收束")]
        for size in (6, 12):
            pages = [page(i, beats[(i - 1) % len(beats)][0],
                          narrative=beats[(i - 1) % len(beats)][1]) for i in range(1, size + 1)]
            with self.subTest(pages=size):
                result = storyboard.select_pages({"pages": pages})
                ids = [p["layout_id"] for p in result["pages"]]
                self.assertEqual(ids[:5], ["SB-004", "SB-025", "SB-027", "SB-023", "SB-030"])
                # Both have four story units, but their different story purposes
                # select different original structures; count is not the selector.
                self.assertNotEqual(ids[0], ids[2])
                self.assertIsNone(result["rhythm_audit"]["distinct_layout_quota"])

    def test_only_selected_sb_prompt_and_template_are_read(self):
        reads = []
        original = Path.read_text
        previously_imported = set(sys.modules)

        def record(path, *args, **kwargs):
            reads.append(path)
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", new=record):
            storyboard.select_pages({"pages": [page(1, 6, "SB-025"), page(2, 1, "SB-055")]})
        sb_reads = {p.name for p in reads if p.name.startswith("SB-")}
        self.assertEqual(sb_reads, {"SB-025.md", "SB-025.yaml", "SB-055.md", "SB-055.yaml"})
        self.assertNotIn("prompt_style", set(sys.modules) - previously_imported)

    def test_narrative_and_panel_count_reason_are_required(self):
        for field in ("narrative_function", "panel_count_reason"):
            p = page()
            p.pop(field)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                storyboard.select_pages({"pages": [p]})
        p = page()
        p["panels"][0].pop("main_action_or_emotion")
        with self.assertRaisesRegex(ValueError, "main_action_or_emotion"):
            storyboard.select_pages({"pages": [p]})

    def test_author_panel_bounds_override_approximate_source_regions(self):
        p = page(1, 1, "SB-055")
        p["panels"][0]["bounds"] = [0.05, 0.2, 0.9, 0.7]
        region = storyboard.select_pages({"pages": [p]})["pages"][0]["layout"]["guidance"]["panels"][0]
        self.assertEqual(region["bounds"], p["panels"][0]["bounds"])
        self.assertEqual(region["bounds_source"], "authored_page_plan")

    def test_two_panel_adaptation_keeps_real_sb_semantics_and_authored_regions(self):
        p = page(1, 2, "SB-025", "用两次正反打呈现试探和回答")
        p["layout_adaptation"] = {"reason": "原文只有一次问答，保留正反打关系并减少到两个镜头"}
        p["panels"][0]["bounds"] = [0.04, 0.04, 0.92, 0.43]
        p["panels"][1]["bounds"] = [0.04, 0.53, 0.92, 0.43]
        selected = storyboard.select_pages({"pages": [p]})["pages"][0]
        self.assertEqual(selected["layout_id"], "SB-025")
        self.assertEqual(selected["panel_count"], 2)
        self.assertEqual(selected["layout"]["guidance"]["text_zones"], [])
        self.assertEqual(selected["layout"]["guidance"]["source"], "authored_adaptation_of_selected_original_template")

    def test_count_mismatch_does_not_silently_make_a_generic_grid(self):
        p = page(1, 2, "SB-025")
        with self.assertRaisesRegex(ValueError, "authored panel bounds"):
            storyboard.select_pages({"pages": [p]})
        p["layout_id"] = "SB-002"
        p["layout_adaptation"] = {"reason": "不能把原始固定四格模板静默改成两个画格"}
        for panel in p["panels"]:
            panel["bounds"] = [0, 0, 1, 1]
        with self.assertRaises(ValueError):
            storyboard.select_pages({"pages": [p]})

    def test_complex_sb_is_labelled_approximate_and_not_filtered_for_variety(self):
        p = storyboard.select_pages({"pages": [page(1, 4, "SB-007")]})["pages"][0]
        compat = p["layout"]["fast_compatibility"]
        self.assertEqual(p["layout_id"], "SB-007")
        self.assertEqual(compat["level"], "approximate_complex_requires_review")
        self.assertFalse(compat["pixel_exact"])
        self.assertTrue(compat["actual_image_review_required"])

    def test_source_example_tail_coordinates_are_never_reused(self):
        p = storyboard.select_pages({"pages": [page(1, 6, "SB-025")]})["pages"][0]
        zones = p["layout"]["guidance"]["text_zones"]
        self.assertTrue(zones)
        for zone in zones:
            self.assertNotIn("tail", zone)
            self.assertTrue(zone["source_tail_removed"])
            self.assertIn(zone["panel_id"], {p["panel_id"] for p in p["panels"]})

    def test_explicit_identical_pages_need_concrete_narrative_justification(self):
        doc = {"pages": [page(i, 4, "SB-002") for i in range(1, 4)]}
        with self.assertRaisesRegex(ValueError, "repetition_justifications"):
            storyboard.select_pages(doc)
        doc["repetition_justifications"] = [{"page_ids": ["P01", "P02", "P03"], "layout_id": "SB-002",
                "reason": "同一场谈话保持人物视线，让三次回应形成可读的表情对照",
                "narrative_purpose": "在固定画框内让人物从迟疑逐步转为信任",
                "alternatives_considered": ["SB-001", "SB-003"]}]
        result = storyboard.select_pages(doc)
        self.assertEqual([p["layout_id"] for p in result["pages"]], ["SB-002"] * 3)
        self.assertIsNone(result["rhythm_audit"]["distinct_layout_quota"])

    def test_actual_user_uniform_instruction_is_preserved(self):
        doc = {"pages": [page(1, 4, "SB-002"), page(2, 4, "SB-002")],
               "layout_policy": "uniform_by_user_request",
               "uniform_layout_request": {"source": "user", "instruction_excerpt": "这两页全部使用同一种四格版式"}}
        self.assertEqual(storyboard.select_pages(doc)["rhythm_audit"]["status"], "passed")
        doc["uniform_layout_request"]["source"] = "agent"
        with self.assertRaisesRegex(ValueError, "actual user instruction"):
            storyboard.select_pages(doc)

    def test_semantic_best_is_not_replaced_with_distant_scoring_layout(self):
        def scores(item, narrative, content=""):
            return 100 if item["id"] == "SB-025" else 2
        doc = {"pages": [page(1, 6), page(2, 6)],
               "repetition_justifications": [{"page_ids": ["P01", "P02"], "layout_id": "SB-025",
                    "reason": "两页维持相同的正反打位置比较说话者前后语气",
                    "narrative_purpose": "让逐步信任的回应在固定镜头中形成对照",
                    "alternatives_considered": ["SB-006"]}]}
        with mock.patch.object(storyboard, "layout_score", side_effect=scores):
            result = storyboard.select_pages(doc)
        self.assertEqual([p["layout_id"] for p in result["pages"]], ["SB-025", "SB-025"])

    def test_near_scoring_real_compatible_alternative_can_reduce_repeat(self):
        def scores(item, narrative, content=""):
            return {"SB-001": 20, "SB-002": 20}.get(item["id"], 1)
        with mock.patch.object(storyboard, "layout_score", side_effect=scores):
            result = storyboard.select_pages({"pages": [page(1), page(2)]})
        self.assertEqual([p["layout_id"] for p in result["pages"]], ["SB-001", "SB-002"])


class SemanticPrepareTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="semantic-planning-SIMULATION-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.txt"
        self.source.write_text("孩子回到家，母亲在门边拥抱了他。", encoding="utf-8")
        self.draft = {"mode": "fast", "source_path": str(self.source),
                      "analysis": {"facts": ["孩子回家", "母亲拥抱"]}, "characters": [],
                      "style": {"prompt": "Chinese diary comic, white paper, black lines."},
                      "pages": [page(1, 1, "SB-055", "母亲拥抱孩子完成安心的收束")]}
        self.run = self.root / "new-project"

    def prepare(self):
        draft = self.root / "draft.json"
        draft.write_text(json.dumps(self.draft, ensure_ascii=False), encoding="utf-8")
        return fast_prepare.prepare(draft, self.run, simulation=True)

    @staticmethod
    def font():
        return next((Path(value) for value in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                      "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc") if Path(value).is_file()), None)

    def test_new_empty_caption_run_retains_whole_page_and_visual_review_gate(self):
        self.prepare()
        frozen = json.loads((self.run / "fast/plan.json").read_text(encoding="utf-8"))
        self.assertTrue(frozen["visual_review_required"])
        self.assertEqual(frozen["max_attempts"], 2)
        self.assertTrue(frozen["reuse_first_page_reference"])
        prompt = Path(frozen["pages"][0]["prompt_path"]).read_text(encoding="utf-8")
        self.assertIn("ONE complete portrait 3:4 page", prompt)
        self.assertIn("Do not copy a reference page's", prompt)
        self.assertIn("Joint artwork/text design", prompt)
        self.assertEqual(len(frozen["pages"]), 1)

    def test_nonempty_new_captions_require_explicit_semantics(self):
        self.draft["pages"][0]["captions"] = [{"text": "终于回家。", "bounds": [0.05, 0.05, 0.9, 0.15]}]
        with self.assertRaisesRegex(ValueError, "explicit text type"):
            self.prepare()
        self.assertFalse(self.run.exists())

    @unittest.skipUnless(font(), "local Chinese font unavailable")
    def test_real_font_capacity_preflight_blocks_before_run_creation(self):
        self.draft["text_settings"] = {"font_path": str(self.font()), "canvas_size": [1080, 1440]}
        self.draft["pages"][0]["captions"] = [{"caption_id": "C01", "panel_id": "U01", "type": "narration",
                "text": "这句文字在一个太小的区域里面一定无法正常排版。" * 30,
                "bounds": [0.1, 0.2, 0.08, 0.04], "font_size": 40}]
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.run.exists())

    @unittest.skipUnless(font(), "local Chinese font unavailable")
    def test_successful_preflight_freezes_font_copy_with_caption_ownership(self):
        self.draft["text_settings"] = {"font_path": str(self.font()), "canvas_size": [1080, 1440]}
        self.draft["pages"][0]["captions"] = [{"caption_id": "C01", "panel_id": "U01", "type": "narration",
                "text": "终于回家。", "bounds": [0.1, 0.2, 0.6, 0.15], "font_size": 40}]
        self.prepare()
        frozen = json.loads((self.run / "fast/plan.json").read_text(encoding="utf-8"))
        font = Path(frozen["text_settings"]["font_path"])
        self.assertTrue(font.is_file())
        self.assertNotEqual(font.resolve(), self.font().resolve())
        self.assertIn({"path": str(font), "sha256": fast_prepare.digest(font)}, frozen["input_bindings"])
        captions = json.loads(Path(frozen["pages"][0]["caption_plan_path"]).read_text(encoding="utf-8"))
        self.assertEqual(captions["captions"][0]["panel_id"], "U01")
        self.assertEqual(captions["captions"][0]["type"], "narration")
        self.assertIn("capacity_preflight", captions)

    def test_resume_does_not_reselect_storyboard_or_rewrite_frozen_plan(self):
        self.prepare()
        frozen = self.run / "fast/plan.json"
        before = frozen.read_bytes()
        with mock.patch.object(storyboard, "select_pages", side_effect=AssertionError("resume must not replan")):
            fast_prepare.prepare(self.root / "missing-original.json", self.run, simulation=True)
        self.assertEqual(before, frozen.read_bytes())


if __name__ == "__main__":
    unittest.main()
