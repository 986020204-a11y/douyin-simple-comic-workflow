"""Offline FAST caption checks. Generated-looking assets are never production output.

The plain-color fixture below is explicitly simulated, lives only in TemporaryDirectory,
and is handed to a simulation-only queue. No image tool or network is used.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fast_caption
import fast_queue


def _font_path() -> Path | None:
    for value in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"):
        if Path(value).is_file():
            return Path(value)
    return None


@unittest.skipUnless(_font_path(), "local Chinese TrueType font is unavailable")
class FastCaptionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fast = self.root / "fast"
        self.fast.mkdir()
        self.font = _font_path()

    def write_json(self, path, value):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def fixture(self, captions=None, succeeded=True):
        if captions is None:
            captions = [{"text": "在那天的雨里，我们终于学会一起慢慢走。", "bounds": [0.05, 0.05, 0.9, 0.25]}]
        prompt = self.fast / "P01-prompt.txt"
        prompt.write_text("SIMULATION ONLY: no production image generation", encoding="utf-8")
        caption_path = self.fast / "P01-captions.json"
        self.write_json(caption_path, {"page_id": "P01", "captions": captions})
        caption_hash = fast_queue.sha256(caption_path)
        plan = {"schema_version": 1, "mode": "fast", "simulation": True, "max_attempts": 2,
                "first_page_id": "P01", "input_bindings": [{"path": str(caption_path), "sha256": caption_hash}],
                "pages": [{"page_id": "P01", "prompt_path": str(prompt),
                           "prompt_sha256": fast_queue.sha256(prompt), "reference_bindings": [],
                           "output_dir": str(self.fast / "images"),
                           "caption_plan_path": str(caption_path), "caption_plan_sha256": caption_hash}]}
        self.write_json(self.fast / "plan.json", plan)
        fast_queue.init_queue(self.root)
        self.base = None
        if succeeded:
            # Test-only simulation source; never marked as real GPT artwork.
            source = self.root / "SIMULATED-input.png"
            Image.new("RGB", (600, 800), (30, 80, 130)).save(source)
            request = fast_queue.claim_page(self.root)
            result = fast_queue.complete_page(self.root, "P01", request["claim_token"], source,
                                              "SIMULATED-call-1", provider="simulation")
            self.base = Path(result["output_path"])
        return caption_path

    def test_chinese_caption_saves_without_touching_source_or_attempts(self):
        self.fixture()
        before_base = self.base.read_bytes()
        before_state = (self.fast / "state.json").read_bytes()
        result = fast_caption.compose(self.root, "P01", self.font)
        self.assertEqual(result["status"], "saved")
        self.assertTrue(result["needs_human_review"])
        self.assertFalse(result["base_image_modified"])
        self.assertEqual(before_base, self.base.read_bytes())
        self.assertEqual(before_state, (self.fast / "state.json").read_bytes())
        with Image.open(result["output_path"]) as image:
            image.load()
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (600, 800))
            self.assertNotEqual(image.getpixel((40, 50)), (30, 80, 130))
            self.assertEqual(image.getpixel((500, 700)), (30, 80, 130))

    def test_repeat_is_idempotent_and_does_not_overwrite_another_final(self):
        self.fixture()
        result = fast_caption.compose(self.root, "P01", self.font)
        output = Path(result["output_path"])
        saved_stat = output.stat().st_mtime_ns
        second = fast_caption.compose(self.root, "P01", self.font)
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(second["output_path"], result["output_path"])
        self.assertEqual(output.stat().st_mtime_ns, saved_stat)
        occupied = self.fast / "final" / "P01-approved.png"
        occupied.write_bytes(b"historical approved bytes")
        with self.assertRaisesRegex(ValueError, "already exists"):
            fast_caption.compose(self.root, "P01", self.font, occupied)
        self.assertEqual(occupied.read_bytes(), b"historical approved bytes")

    def test_overflow_blocks_entire_output_without_shrinking_or_new_attempt(self):
        self.fixture([{"text": "中文故事" * 150, "bounds": [0.05, 0.05, 0.9, 0.1], "font_size": 40}])
        before_state = (self.fast / "state.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "overflows"):
            fast_caption.compose(self.root, "P01", self.font)
        self.assertFalse((self.fast / "final").exists())
        self.assertEqual(before_state, (self.fast / "state.json").read_bytes())

    def test_invalid_bounds_block_output(self):
        for bounds in ([0, 0, 1.1, 0.5], [-0.1, 0, 0.5, 0.5], [0, 0, 0, 0.5],
                       [0, 0, float("nan"), 0.5], [0, 0, True, 0.5]):
            with self.subTest(bounds=bounds):
                with tempfile.TemporaryDirectory() as task:
                    self.root, self.fast = Path(task), Path(task) / "fast"
                    self.fast.mkdir()
                    self.fixture([{"text": "检查", "bounds": bounds}])
                    with self.assertRaisesRegex(ValueError, "bounds"):
                        fast_caption.compose(self.root, "P01", self.font)
                    self.assertFalse((self.fast / "final").exists())

    def test_no_captions_produces_safe_png_copy(self):
        self.fixture([])
        result = fast_caption.compose(self.root, "P01", self.font)
        with Image.open(self.base) as source, Image.open(result["output_path"]) as output:
            self.assertEqual(source.tobytes(), output.tobytes())
        self.assertNotEqual(Path(result["output_path"]), self.base)

    def test_unsucceeded_or_changed_base_is_rejected(self):
        self.fixture(succeeded=False)
        with self.assertRaisesRegex(ValueError, "succeeded base"):
            fast_caption.compose(self.root, "P01", self.font)
        state = json.loads((self.fast / "state.json").read_text(encoding="utf-8"))
        state["pages"]["P01"].update(status="succeeded", output_path=str(self.root / "missing.png"),
                                       image_sha256=hashlib.sha256(b"old").hexdigest())
        self.write_json(self.fast / "state.json", state)
        with self.assertRaisesRegex(ValueError, "hash changed"):
            fast_caption.compose(self.root, "P01", self.font)
        self.assertFalse((self.fast / "final").exists())

    def test_frozen_caption_change_is_rejected_before_rendering(self):
        caption_path = self.fixture()
        caption_path.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Frozen input"):
            fast_caption.compose(self.root, "P01", self.font)
        state = json.loads((self.fast / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["pages"]["P01"]["attempts"], 1)
        self.assertEqual(state["status"], "stopped")
        self.assertFalse((self.fast / "final").exists())

    def test_text_revision_is_local_and_reuses_base_without_replanning(self):
        original_path = self.fixture()
        original = fast_caption.compose(self.root, "P01", self.font)
        before_state = (self.fast / "state.json").read_bytes()
        before_base = self.base.read_bytes()
        revision = json.loads(original_path.read_text(encoding="utf-8"))
        revision["captions"][0]["text"] = "雨停之后，我们一起回家。"
        revision_path = self.fast / "caption-revisions" / "P01-v2.json"
        revision_path.parent.mkdir()
        self.write_json(revision_path, revision)
        revised = fast_caption.compose(self.root, "P01", self.font, caption_plan_path=revision_path)
        self.assertNotEqual(revised["output_path"], original["output_path"])
        self.assertTrue(Path(original["output_path"]).is_file())
        self.assertEqual(before_state, (self.fast / "state.json").read_bytes())
        self.assertEqual(before_base, self.base.read_bytes())
        revision["captions"][0]["bounds"] = [0.1, 0.5, 0.8, 0.2]
        self.write_json(revision_path, revision)
        with self.assertRaisesRegex(ValueError, "change text only"):
            fast_caption.compose(self.root, "P01", self.font, caption_plan_path=revision_path)

    def test_revision_outside_run_and_invalid_fonts_are_rejected(self):
        caption_path = self.fixture([])
        with self.assertRaisesRegex(ValueError, "caption-revisions"):
            fast_caption.compose(self.root, "P01", self.font, caption_plan_path=caption_path)
        fake_font = self.root / "fake.ttf"
        fake_font.write_bytes(b"not a font")
        with self.assertRaisesRegex(ValueError, "font is not"):
            fast_caption.compose(self.root, "P01", fake_font)

    def test_output_must_stay_inside_this_fast_run(self):
        self.fixture()
        before_base = self.base.read_bytes()
        for output in (self.root / "historical.png", self.base, self.fast / "final" / "wrong.jpg"):
            with self.subTest(output=output):
                with self.assertRaisesRegex(ValueError, "inside this run"):
                    fast_caption.compose(self.root, "P01", self.font, output)
        self.assertEqual(self.base.read_bytes(), before_base)


if __name__ == "__main__":
    unittest.main()
