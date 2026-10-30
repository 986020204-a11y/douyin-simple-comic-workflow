"""Image-facing FAST handoff regression checks; all projects are SIMULATION.

Sentinels distinguish necessary visual instructions from local production data.
No image generator or external service is called. TemporaryDirectory and the
labelled image fixtures live outside the installed skill and historical runs.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fast_prepare
import fast_queue
import fast_storyboard
import test_fast_workflow as workflow


class CompactPromptOffline(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow.FastWorkflowOffline("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.spec = copy.deepcopy(self.fixture.spec)
        self.spec["pages"] = self.spec["pages"][:2]
        self.spec["analysis"] = {"facts": ["LOCAL_ANALYSIS_SENTINEL"]}
        self.fixture.source.write_text("LOCAL_SOURCE_SENTINEL", encoding="utf-8")
        self.spec["characters"] = [
            {"character_id": "N01", "description": "VISUAL_IDENTITY_SENTINEL: short hair, one red glove.",
             "reference_paths": [], "private_note": "LOCAL_CARD_AUDIT_SENTINEL",
             "wardrobe": "VISUAL_WARDROBE_SENTINEL: worn navy coat."},
            {"character_id": "N02", "description": "INACTIVE_CHARACTER_SENTINEL", "reference_paths": []},
        ]
        self.spec["style"] = {"preset_id": "urban-webtoon", "reference_paths": [],
                              "prompt": "VISUAL_PALETTE_SENTINEL: navy and warm amber."}
        for page in self.spec["pages"]:
            page["character_ids"] = ["N01"]
            page["narrative_function"] = "LOCAL_NARRATIVE_ANALYSIS_SENTINEL: one return-home response"
            page["panel_count_reason"] = "LOCAL_PANEL_COUNT_REASON_SENTINEL: four distinct beats"
            page["prompt"] = "VISUAL_AUTHOR_SENTINEL: keep the red glove visible near the open door."
            page["style_application"] = {
                "performance": "VISUAL_ACTING_SENTINEL: a guarded smile gradually relaxes",
                "camera": "VISUAL_CAMERA_SENTINEL: alternate hand close-up and eye-level reaction",
                "layout": "VISUAL_LAYOUT_SENTINEL: preserve the sequential four-beat rhythm",
                "lettering": "LOCAL_LETTERING_SENTINEL: narration is set with the frozen font",
            }
            for index, panel in enumerate(page["panels"], 1):
                panel.update(panel_id=f"U{index:02d}",
                             visual=f"VISUAL_ACTION_{index}: N01 opens the door a little further.",
                             camera=f"VISUAL_PANEL_CAMERA_{index}: eye-level view.",
                             private_note="LOCAL_PANEL_AUDIT_SENTINEL")

    def prepare(self):
        self.fixture.prepare(spec=self.spec)
        return self.fixture.read_plan()

    def prompt(self, page_id="P01"):
        return (self.fixture.run / "fast" / "prompts" / f"{page_id}.txt").read_text(encoding="utf-8")

    def local_json(self, relative):
        return json.loads((self.fixture.run / relative).read_text(encoding="utf-8"))

    @staticmethod
    def font():
        return next((Path(value) for value in (
            "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc") if Path(value).is_file()), None)

    @unittest.skipUnless(font(), "local font required for actual caption capacity preflight")
    def test_artwork_keeps_story_and_caption_ownership_while_local_details_stay_local(self):
        self.spec["text_settings"] = {"font_path": str(self.font()), "canvas_size": [1080, 1440]}
        self.spec["pages"][0]["captions"] = [
            {"caption_id": "C01", "panel_id": "U01", "type": "dialogue", "speaker_id": "N01",
             "text": "灯还亮着。", "bounds": [0.06, 0.15, 0.38, 0.19],
             "placement_intention": "VISUAL_RESERVATION_SENTINEL: beside the speaker, avoid the glove"},
            {"caption_id": "C02", "panel_id": "U02", "type": "thought", "owner_id": "N01",
             "text": "我到家了。", "bounds": [0.56, 0.15, 0.38, 0.19]},
        ]
        self.prepare()
        prompt = self.prompt()
        for marker in ("VISUAL_IDENTITY_SENTINEL", "VISUAL_WARDROBE_SENTINEL",
                       "VISUAL_PALETTE_SENTINEL", "VISUAL_AUTHOR_SENTINEL",
                       "VISUAL_ACTING_SENTINEL", "VISUAL_CAMERA_SENTINEL", "VISUAL_LAYOUT_SENTINEL",
                       "VISUAL_RESERVATION_SENTINEL", *[f"VISUAL_ACTION_{i}" for i in range(1, 5)],
                       *[f"VISUAL_PANEL_CAMERA_{i}" for i in range(1, 5)]):
            with self.subTest(visual_marker=marker):
                self.assertIn(marker, prompt)
        for marker in ("LOCAL_ANALYSIS_SENTINEL", "LOCAL_SOURCE_SENTINEL", "LOCAL_CARD_AUDIT_SENTINEL",
                       "LOCAL_PANEL_AUDIT_SENTINEL", "LOCAL_NARRATIVE_ANALYSIS_SENTINEL",
                       "LOCAL_PANEL_COUNT_REASON_SENTINEL", "LOCAL_LETTERING_SENTINEL",
                       "INACTIVE_CHARACTER_SENTINEL"):
            with self.subTest(local_marker=marker):
                self.assertNotIn(marker, prompt)
        # The original SB mechanism survives, without forwarding its source metadata.
        boards = self.local_json("fast/planning/storyboard.json")
        board = boards["pages"][0]
        for beat in ("introduction", "development", "twist", "punchline"):
            self.assertIn(beat, prompt)
        self.assertIn("N01", prompt)
        for caption in self.spec["pages"][0]["captions"]:
            self.assertNotIn(caption["text"], prompt)
            bounds = json.dumps(caption["bounds"], separators=(",", ":"))
            self.assertIn(f'{caption["panel_id"]} xywh={bounds} owner=N01', prompt)
            self.assertEqual(prompt.count(bounds), 1)
        self.assertNotIn("source_panel_id", prompt)
        self.assertNotIn(str(self.fixture.root), prompt)
        self.assertEqual(self.local_json("fast/planning/analysis.json"), self.spec["analysis"])
        self.assertEqual(self.local_json("fast/planning/characters.json"), self.spec["characters"])
        self.assertEqual((self.fixture.run / "source/article.md").read_text(encoding="utf-8"),
                         "LOCAL_SOURCE_SENTINEL")
        self.assertEqual(board["panels"], self.spec["pages"][0]["panels"])
        self.assertEqual(board["narrative_function"], self.spec["pages"][0]["narrative_function"])
        caption_plan = self.local_json("fast/captions/P01.json")
        self.assertEqual([c["text"] for c in caption_plan["captions"]],
                         [c["text"] for c in self.spec["pages"][0]["captions"]])
        self.assertEqual(caption_plan["captions"][0]["speaker_id"], "N01")
        self.assertEqual(caption_plan["captions"][1]["owner_id"], "N01")
        self.assertEqual(caption_plan["style_application"]["lettering"],
                         self.spec["pages"][0]["style_application"]["lettering"])

    def test_long_authored_visual_fields_are_preserved_without_silent_truncation(self):
        description = "The red glove remains visible. " * 180 + "IDENTITY_TAIL_SENTINEL"
        style = "Keep the background warm amber. " * 180 + "PALETTE_TAIL_SENTINEL"
        author = "The doorway frames N01's gesture. " * 180 + "AUTHOR_TAIL_SENTINEL"
        self.spec["characters"][0]["description"] = description
        self.spec["style"]["prompt"] = style
        self.spec["pages"][0]["prompt"] = author
        self.prepare()
        prompt = self.prompt()
        for authored in (description, style, author):
            with self.subTest(tail=authored[-30:]):
                self.assertIn(authored, prompt)

    def test_no_initial_reference_still_allows_dynamic_first_page_identity_reference(self):
        self.prepare()
        first = self.fixture.claim("P01")
        self.assertNotIn("referenced_image_paths", first["request"])
        self.assertFalse(first["reference_roles"])
        _, result = self.fixture.complete(first)
        frozen_second = (self.fixture.run / "fast/prompts/P02.txt").read_bytes()
        second = self.fixture.claim("P02")
        reference = str(Path(result["output_path"]).resolve())
        self.assertIn(reference, second["request"]["referenced_image_paths"])
        self.assertTrue(any(role["role"] == "first_page_identity_style" and not role["copy_layout"]
                            for role in second["reference_roles"]))
        self.assertEqual((self.fixture.run / "fast/prompts/P02.txt").read_bytes(), frozen_second)
        self.assertIn(self.prompt("P02"), second["request"]["prompt"])
        self.assertGreater(len(second["request"]["prompt"]), len(self.prompt("P02")))

    def test_existing_frozen_resume_ignores_new_builder_and_preserves_local_inputs(self):
        self.prepare()
        saved = {p: p.read_bytes() for p in (self.fixture.run / "fast").rglob("*")
                 if p.is_file() and p.name not in {"state.json", "state.json.lock"}}
        self.fixture.source.unlink()
        with mock.patch.object(fast_storyboard, "select_pages", side_effect=AssertionError("replanned frozen run")), \
                mock.patch.object(fast_prepare, "build_generation_prompt", side_effect=AssertionError("rewrote prompt")):
            resumed = fast_prepare.prepare(self.fixture.root / "missing-draft.json", self.fixture.run, simulation=True)
        self.assertEqual(resumed["counts"]["dispatched_attempts"], 0)
        for path, original in saved.items():
            with self.subTest(file=path.name):
                self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
