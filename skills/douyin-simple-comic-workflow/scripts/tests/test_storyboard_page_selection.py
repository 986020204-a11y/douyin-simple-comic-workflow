"""Regression checks for independent page selection and its audit boundary."""
from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prompt_style


class PageSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pool = [
            self.item("SB-001", "home calm dialogue"),
            self.item("SB-002", "urgent chase action"),
            self.item("SB-003", "quiet memory reflection"),
            self.item("SB-031", "urgent chase action"),
            self.item("SB-068", "home calm dialogue urgent chase action"),
        ]
        self.counts = {"SB-001": 4, "SB-002": 4, "SB-003": 4, "SB-031": 2, "SB-068": 4}
        for item in self.pool:
            (self.root / item["prompt_file"]).write_text("Scene-only storyboard", encoding="utf-8")
        self.audit_module = types.ModuleType("audit_storyboard_rhythm")
        self.audit_module.audit_decision = Mock(return_value={"status": "passed", "errors": []})
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(prompt_style, "POOL", self.root))
        stack.enter_context(patch.object(prompt_style, "compile_execution_contract", side_effect=self.compile))
        stack.enter_context(patch.object(prompt_style, "_contract_prompt", return_value="Compiled geometry"))
        stack.enter_context(patch.dict(sys.modules, {"audit_storyboard_rhythm": self.audit_module}))

    @staticmethod
    def item(layout_id, words):
        return {"id": layout_id, "name": words, "name_en": words,
                "keywords": words.split(), "layout_structure": words,
                "prompt_file": f"{layout_id}.md"}

    def compile(self, item, count=None, match_policy="structure_exact", **kwargs):
        if item["id"] == "SB-068":
            raise ValueError("Unreviewed source geometry cannot compile")
        native_count = self.counts[item["id"]]
        if count != native_count:
            raise ValueError(f"Requested {count} units does not match native count {native_count}")
        return {"layout_id": item["id"], "match_policy": match_policy,
                "panel_geometry": [{"panel_id": f"N{index + 1}"} for index in range(count)]}

    @staticmethod
    def page(page_id, narrative, count=4, layout_id=None):
        page = {"page_id": page_id, "narrative_function": narrative,
                "panel_count_reason": f"Separate {count} distinct actions in this page's {narrative} sequence",
                "story_beat_id": f"{page_id}-beat",
                "panels": [{"panel_id": f"input-{index}", "focus": narrative,
                            "main_action_or_emotion": narrative, "source_lines": [index + 1]}
                           for index in range(count)]}
        if layout_id:
            page["layout_id"] = layout_id
        return page

    def select(self, pages, **extra):
        return prompt_style.select_pages({"pages": pages, **extra}, self.pool)

    def test_each_page_uses_its_own_narrative_and_preserves_story_units(self):
        pages = [self.page("P01", "home calm dialogue"),
                 self.page("P02", "urgent chase action")]
        before = copy.deepcopy(pages)
        result = self.select(pages)
        self.assertEqual([page["layout_id"] for page in result["pages"]], ["SB-001", "SB-002"])
        self.assertEqual(result["selection_scope"], "per_page")
        self.assertEqual(result["page_count"], 2)
        self.assertEqual(result["planned_story_units"], 8)
        self.assertEqual(result["planned_panel_count"], 8)
        for original, selected in zip(before, result["pages"]):
            self.assertEqual(selected["panels"][0]["source_panel_id"], "input-0")
            self.assertEqual(selected["panels"][0]["panel_id"], "N1")
            self.assertEqual(selected["panels"][0]["source_lines"], [1])
            self.assertEqual(selected["panels"][0]["focus"], original["panels"][0]["focus"])
            self.assertEqual(selected["selection_evidence"]["page_id"], original["page_id"])
            self.assertIn(original["narrative_function"], selected["selection_reason"])
        self.assertEqual(pages, before, "Selection must not mutate the input story")

    def test_native_count_filters_a_high_scoring_incompatible_template(self):
        result = self.select([self.page("P01", "urgent chase action", count=2)])
        selected = result["pages"][0]
        self.assertEqual(selected["layout_id"], "SB-031")
        evidence = selected["selection_evidence"]
        incompatible = next(candidate for candidate in evidence["candidates"]
                            if candidate["layout_id"] == "SB-002")
        self.assertFalse(incompatible["compatible"])
        self.assertIn("native count 4", incompatible["reason"])
        self.assertEqual(evidence["compatible_candidate_count"], 1)
        self.assertTrue(evidence["fewer_than_three_candidates_reason"])

    def test_non_executable_candidates_are_excluded_even_when_their_words_match(self):
        result = self.select([self.page("P01", "home calm dialogue urgent chase action")])
        selected = result["pages"][0]
        self.assertNotEqual(selected["layout_id"], "SB-068")
        rejected = next(candidate for candidate in selected["selection_evidence"]["candidates"]
                        if candidate["layout_id"] == "SB-068")
        self.assertFalse(rejected["compatible"])
        self.assertIn("Unreviewed source geometry", rejected["reason"])

    def test_distinctly_stronger_match_is_not_replaced_just_for_variety(self):
        result = self.select([self.page("P01", "home calm dialogue"),
                              self.page("P02", "home calm dialogue")])
        self.assertEqual([page["layout_id"] for page in result["pages"]], ["SB-001", "SB-001"])
        self.audit_module.audit_decision.assert_called_once()

    def test_equal_narrative_candidates_can_break_a_consecutive_repeat(self):
        self.pool[1] = self.item("SB-002", "home calm dialogue")
        result = self.select([self.page("P01", "home calm dialogue"),
                              self.page("P02", "home calm dialogue")])
        self.assertEqual([page["layout_id"] for page in result["pages"]], ["SB-001", "SB-002"])

    def test_explicit_uniform_request_is_retained_but_requires_user_provenance(self):
        pages = [self.page("P01", "home calm dialogue", layout_id="SB-001"),
                 self.page("P02", "urgent chase action", layout_id="SB-001")]
        with self.assertRaisesRegex(ValueError, "source: user"):
            self.select(pages, layout_policy="uniform_by_user_request")
        result = self.select(pages, layout_policy="uniform_by_user_request",
                             uniform_layout_request={"source": "user", "instruction_excerpt": "全部使用同一个版式"})
        self.assertEqual([page["layout_id"] for page in result["pages"]], ["SB-001", "SB-001"])

    def test_page_count_mismatch_and_missing_page_narrative_are_blocked(self):
        page = self.page("P01", "home calm dialogue")
        page["panel_count"] = 2
        with self.assertRaisesRegex(ValueError, "disagrees"):
            self.select([page])
        page = self.page("P01", "home calm dialogue")
        del page["narrative_function"]
        with self.assertRaisesRegex(ValueError, "narrative_function"):
            self.select([page])

    def test_blocked_audit_exits_cli_without_writing_a_generation_handoff(self):
        source = self.root / "pages.yaml"
        source.write_text(json.dumps({"pages": [self.page("P01", "home calm dialogue")]}), encoding="utf-8")
        output = self.root / "handoff.json"
        self.audit_module.audit_decision.return_value = {"status": "blocked", "errors": ["Unsupported repetition"]}
        with patch.object(prompt_style, "load_pool", return_value=self.pool), \
                patch.object(sys, "argv", ["prompt_style.py", "--pages", str(source), "--output", str(output)]), \
                contextlib.redirect_stderr(io.StringIO()) as errors, contextlib.redirect_stdout(io.StringIO()) as stdout:
            with self.assertRaises(SystemExit) as failure:
                prompt_style.main()
        self.assertNotEqual(failure.exception.code, 0)
        self.assertFalse(output.exists())
        self.assertFalse(stdout.getvalue())
        self.assertIn("Unsupported repetition", errors.getvalue())

    def test_legacy_single_page_cli_still_compiles_an_explicit_layout(self):
        output = self.root / "single.json"
        with patch.object(prompt_style, "load_pool", return_value=self.pool), \
                patch.object(sys, "argv", ["prompt_style.py", "--layout", "SB-002", "--panel-count", "4", "--output", str(output)]), \
                contextlib.redirect_stdout(io.StringIO()):
            prompt_style.main()
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["layout_id"], "SB-002")
        self.assertEqual(result["panel_count"], 4)
        self.assertNotIn("pages", result)
        self.audit_module.audit_decision.assert_not_called()


if __name__ == "__main__":
    unittest.main()
