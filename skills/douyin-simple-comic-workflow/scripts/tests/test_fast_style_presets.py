"""Style selection and freeze contracts; artwork is disposable SIMULATION only."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import fast_caption
import fast_prepare
import fast_queue
import fast_style
import test_fast_workflow as workflow


class StylePresetsOffline(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow.FastWorkflowOffline("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def spec(self, preset="urban-webtoon"):
        value = copy.deepcopy(self.fixture.spec)
        value["style"] = {"preset_id": preset, "reference_paths": [str(self.fixture.reference)]}
        for page in value["pages"]:
            page["style_application"] = {
                "performance": "SIMULATION_ACTING: child gradually relaxes on returning home",
                "camera": "SIMULATION_CAMERA: view the light, then the reaction",
                "layout": "SIMULATION_LAYOUT: preserve the four authored return-home beats",
                "lettering": "LETTERING_LOCAL_ONLY: narration belongs inside its own panel"}
        return value

    def read(self, relative):
        return json.loads((self.fixture.run / relative).read_text(encoding="utf-8"))

    def test_three_choices_have_distinct_prompts_and_portable_previews(self):
        menu = fast_style.list_presets()
        self.assertEqual([p["preset_id"] for p in menu["presets"]],
                         ["urban-webtoon", "chibi-comedy", "ancient-fine-line"])
        prompts = set()
        for item in menu["presets"]:
            self.assertTrue(Path(item["preview_path"]).is_file())
            resolved = fast_style.resolve_style({"preset_id": item["preset_id"]})
            prompts.add(resolved["prompt"])
            self.assertEqual(resolved["reference_paths"], [])
        self.assertEqual(len(prompts), 3)

    def test_aliases_and_project_additions_preserve_inputs(self):
        original = {"preset_id": "都市韩漫", "prompt": "Keep the heroine's red coat.",
                    "reference_paths": [str(self.fixture.reference)]}
        before = copy.deepcopy(original)
        value = fast_style.resolve_style(original)
        self.assertEqual(original, before)
        self.assertEqual(value["preset_id"], "urban-webtoon")
        self.assertIn(original["prompt"], value["prompt"])
        self.assertEqual(value["reference_paths"], before["reference_paths"])
        self.assertEqual(fast_style.get_preset("q版轻喜剧")["preset_id"], "chibi-comedy")
        self.assertEqual(fast_style.get_preset("203")["preset_id"], "ancient-fine-line")

    def test_unknown_and_derived_fields_fail_before_creating_run(self):
        for style in ({"preset_id": "not-a-style"},
                      {"preset_id": "urban-webtoon", "preset_snapshot": {"prompt": "forged"}}):
            with self.subTest(style=style):
                spec = self.spec()
                spec["style"] = style
                with self.assertRaises(ValueError):
                    fast_prepare.prepare(self.fixture.write_spec(spec), self.fixture.run, simulation=True)
                self.assertFalse(self.fixture.run.exists())

    def test_custom_style_is_unchanged_and_needs_no_new_fields(self):
        original = copy.deepcopy(self.fixture.spec["style"])
        self.assertEqual(fast_style.resolve_style(original), original)
        self.fixture.prepare()
        style = self.read("fast/planning/style.json")
        self.assertEqual(style["prompt"], original["prompt"])
        self.assertNotIn("preset_id", style)

    def test_each_new_preset_page_needs_authored_application(self):
        for key in fast_style.APPLICATION_FIELDS:
            spec = self.spec()
            del spec["pages"][1]["style_application"][key]
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "P02"):
                fast_prepare.prepare(self.fixture.write_spec(spec), self.fixture.run, simulation=True)
            self.assertFalse(self.fixture.run.exists())

    def test_page_decisions_enter_art_and_caption_plans_without_reselecting_sb(self):
        spec = self.spec("Q版轻喜剧")
        self.fixture.prepare(spec=spec)
        style = self.read("fast/planning/style.json")
        self.assertEqual(style["preset_id"], "chibi-comedy")
        self.assertEqual(style["preset_snapshot"]["preset_id"], "chibi-comedy")
        boards = self.read("fast/planning/storyboard.json")["pages"]
        self.assertTrue(all(p["layout_id"] == "SB-002" for p in boards))
        self.assertEqual(boards[0]["style_application"], spec["pages"][0]["style_application"])
        prompt = (self.fixture.run / "fast/prompts/P01.txt").read_text(encoding="utf-8")
        for marker in ("SIMULATION_ACTING", "SIMULATION_CAMERA", "SIMULATION_LAYOUT"):
            self.assertIn(marker, prompt)
        self.assertNotIn("LETTERING_LOCAL_ONLY", prompt)
        caption = self.read("fast/captions/P01.json")
        self.assertEqual(caption["style_application"]["lettering"],
                         spec["pages"][0]["style_application"]["lettering"])
        counts = fast_queue.status(self.fixture.run)["counts"]
        self.assertEqual(counts["dispatched_attempts"], 0)

    def test_resume_ignores_catalog_changes_and_keeps_success_and_references(self):
        self.fixture.prepare(spec=self.spec())
        first = self.fixture.claim()
        shared = set(first["request"]["referenced_image_paths"])
        _, complete = self.fixture.complete(first)
        frozen_before = (self.fixture.run / "fast/plan.json").read_bytes()
        style_before = (self.fixture.run / "fast/planning/style.json").read_bytes()
        with patch.object(fast_style, "load_catalog", side_effect=AssertionError("resumed catalog")):
            fast_prepare.prepare(self.fixture.root / "missing-draft.json", self.fixture.run, simulation=True)
        self.assertEqual((self.fixture.run / "fast/plan.json").read_bytes(), frozen_before)
        self.assertEqual((self.fixture.run / "fast/planning/style.json").read_bytes(), style_before)
        second = self.fixture.claim("P02")
        references = set(second["request"]["referenced_image_paths"])
        self.assertTrue(shared.issubset(references))
        self.assertIn(str(Path(complete["output_path"]).resolve()), references)
        self.assertTrue(all("style-previews" not in path for path in references))

    def test_local_caption_reflow_keeps_preset_artwork_and_generation_state(self):
        font = next((Path(p) for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                     "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc") if Path(p).is_file()), None)
        if font is None:
            self.skipTest("local Chinese font required")
        spec = self.spec()
        spec["text_settings"] = {"font_path": str(font)}
        spec["pages"][0]["captions"] = [{"caption_id": "C01", "panel_id": "U01", "type": "narration",
                                          "text": "灯还亮着。", "bounds": [0.06, 0.18, 0.35, 0.09]}]
        self.fixture.prepare(spec=spec)
        claim = self.fixture.claim()
        fake = self.fixture.root / "SIMULATED-1080.png"
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("test_fixture", "SIMULATION ONLY - NOT GPT ARTWORK")
        Image.new("RGB", (1080, 1440), "white").save(fake, pnginfo=metadata)
        completed = fast_queue.complete_page(self.fixture.run, "P01", claim["claim_token"], fake,
                                             "SIMULATED-STYLE-CAPTION", provider="simulation")
        self.fixture.review("P01", completed["image_sha256"])
        caption = self.read("fast/captions/P01.json")
        caption["image_review"] = {"page_id": "P01", "image_sha256": completed["image_sha256"],
                                   "simulation": True, "geometry_observed_from_image": True,
                                   "caption_placements_verified": True,
                                   "panels": caption["panel_guidance"],
                                   "protected_regions": [], "speaker_regions": []}
        folder = self.fixture.run / "fast/caption-revisions"
        folder.mkdir()
        state_before = (self.fixture.run / "fast/state.json").read_bytes()
        art_before = Path(completed["output_path"]).read_bytes()
        with patch.object(fast_queue, "claim_page", side_effect=AssertionError("caption requested art")):
            for n, x in enumerate((0.06, 0.08), 1):
                caption["captions"][0]["bounds"][0] = x
                revision = folder / f"P01-v{n}.json"
                revision.write_text(json.dumps(caption, ensure_ascii=False), encoding="utf-8")
                result = fast_caption.compose(self.fixture.run, "P01", caption_plan_path=revision)
                self.assertTrue(Path(result["output_path"]).is_file())
        self.assertEqual((self.fixture.run / "fast/state.json").read_bytes(), state_before)
        self.assertEqual(Path(completed["output_path"]).read_bytes(), art_before)
        self.assertEqual(fast_queue.status(self.fixture.run)["counts"]["dispatched_attempts"], 1)
        self.assertEqual(caption["captions"][0]["type"], "narration")

    def test_menu_cli_runs_outside_skill_directory(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / "fast_style.py"), "show", "--preset", "清雅古风叙事"],
                                cwd=self.fixture.root, capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["preset_id"], "ancient-fine-line")


if __name__ == "__main__":
    unittest.main()
