"""Regression tests for narrative choices, not implementation-shaped image tests.

The fixture library is loaded from the actual installed 68-entry SB registry
once. Individual cases then share that verified immutable metadata to avoid
reparsing 68 YAML files per assertion. CLI cases exercise real disk loading.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import audit_storyboard_rhythm as rhythm


class StoryboardRhythmRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = rhythm._library(rhythm.DEFAULT_LIBRARY)

    def setUp(self):
        self.parser = patch.object(rhythm, "_library", return_value=self.library)
        self.parser.start()
        self.addCleanup(self.parser.stop)

    def page(self, number, layout="SB-001"):
        page_id = f"P{number:02d}"
        count = self.library[layout]["panel_count"]
        narrative = f"第{number}页母亲抱起哭醒的女儿并作出承诺"
        same_count_alternative = next(
            lid for lid, metadata in self.library.items()
            if lid != layout and metadata["panel_count"] == count)
        return {
            "page_id": page_id, "layout_id": layout, "panel_count": count,
            "panel_count_reason": f"第{number}页需要呈现哭醒、靠近与承诺之间的情绪变化",
            "narrative_function": narrative,
            "panels": [{"panel_id": f"P{index:02d}", "focus": f"第{index}个情绪节点"}
                       for index in range(1, count + 1)],
            "selection_evidence": {
                "page_id": page_id, "selected_layout_id": layout,
                "narrative_function": narrative,
                "selection_reason": f"第{number}页的拥抱承诺需要让表情之间保持连续阅读",
                "candidates": [
                    {"layout_id": layout, "compatible": True, "score": 9,
                     "reason": "原生叙事单元数量一致且能容纳本页动作"},
                    {"layout_id": same_count_alternative, "compatible": True, "score": 7,
                     "reason": "原生数量兼容，但表情转折的突出程度略弱"},
                ],
            },
        }

    def document(self, layouts):
        return {"page_count": len(layouts),
                "pages": [self.page(index, layout) for index, layout in enumerate(layouts, 1)]}

    def assert_blocked(self, document, fragment):
        result = rhythm.audit_decision(document)
        self.assertEqual(result["status"], "blocked", result)
        self.assertFalse(result["generation_ready"])
        self.assertTrue(any(fragment in error for error in result["errors"]), result)
        self.assertFalse(result["images_generated"])
        return result

    def test_real_ten_page_SB007_failure_cannot_start_new_generation(self):
        document = self.document(["SB-007"] * 10)
        for page in document["pages"]:
            page.pop("selection_evidence")
            page["panel_count_reason"] = "本次续作保留既有四格SB-007，分别承担四个连续动作或情绪节点。"
        result = self.assert_blocked(document, "missing per-page selection_evidence")
        self.assertTrue(any("Repeated layout SB-007" in error for error in result["errors"]))
        self.assertEqual(result["metrics"]["layout_histogram"], {"SB-007": 10})
        self.assertEqual(result["metrics"]["max_consecutive_same_layout"], 10)

    def test_adding_fresh_evidence_does_not_hide_uniform_ten_page_run(self):
        self.assert_blocked(self.document(["SB-007"] * 10), "Repeated layout SB-007")

    def test_real_mixed_templates_and_native_counts_pass(self):
        result = rhythm.audit_decision(self.document(["SB-001", "SB-002", "SB-013"]))
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["metrics"]["unique_layout_count"], 3)
        self.assertEqual(result["metrics"]["panel_count_histogram"], {"3": 1, "4": 2})
        self.assertEqual(result["scope"], "metadata_narrative_rhythm_gate_not_visual_quality")
        self.assertFalse(result["visual_quality_checked"])

    def test_two_different_layouts_with_same_panel_count_are_valid(self):
        result = rhythm.audit_decision(self.document(["SB-001", "SB-002"]))
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["metrics"]["panel_count_histogram"], {"4": 2})

    def test_adjacent_two_page_repeat_with_another_layout_is_valid(self):
        result = rhythm.audit_decision(self.document(["SB-001", "SB-001", "SB-002"]))
        self.assertEqual(result["status"], "passed", result)

    def test_all_two_pages_identical_need_a_declared_reason(self):
        self.assert_blocked(self.document(["SB-001", "SB-001"]), "Repeated layout")

    def test_three_consecutive_repeats_need_reason_even_in_mixed_story(self):
        self.assert_blocked(self.document(["SB-002", "SB-001", "SB-001", "SB-001", "SB-013"]),
                            "Repeated layout SB-001 on P02, P03, P04")

    def test_copied_cross_page_selection_evidence_is_blocked(self):
        document = self.document(["SB-001", "SB-002"])
        document["pages"][1]["selection_evidence"] = copy.deepcopy(document["pages"][0]["selection_evidence"])
        self.assert_blocked(document, "selection_evidence.page_id does not bind")

    def test_relabelled_evidence_still_requires_page_narrative_binding(self):
        document = self.document(["SB-001", "SB-002"])
        evidence = document["pages"][1]["selection_evidence"]
        evidence["narrative_function"] = document["pages"][0]["narrative_function"]
        self.assert_blocked(document, "selection_evidence.narrative_function does not bind")

    def repetition(self, members):
        return {"page_ids": members, "layout_id": "SB-001",
                "reason": "母女在同一房间连续三次对话，保持视线位置才能比较表情变化",
                "narrative_purpose": "让孩子逐步安心的变化在相同画框内形成可读对照",
                "alternatives_considered": ["SB-002", "SB-003"]}

    def test_specific_narrative_repetition_passes_as_declared_adaptation(self):
        document = self.document(["SB-001"] * 3)
        document["repetition_justifications"] = [self.repetition(["P01", "P02", "P03"])]
        result = rhythm.audit_decision(document)
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["declared_adaptations"][0]["status"],
                         "declared_adaptation_not_visual_acceptance")

    def test_partial_repetition_exception_cannot_cover_whole_run(self):
        document = self.document(["SB-001"] * 4)
        document["repetition_justifications"] = [self.repetition(["P01", "P02", "P03"])]
        self.assert_blocked(document, "Repeated layout")

    def test_non_contiguous_justification_is_blocked(self):
        document = self.document(["SB-001"] * 3)
        document["repetition_justifications"] = [self.repetition(["P01", "P03"])]
        self.assert_blocked(document, "contiguous range")

    def test_repetition_cannot_invent_alternatives(self):
        document = self.document(["SB-001"] * 3)
        justification = self.repetition(["P01", "P02", "P03"])
        justification["alternatives_considered"] = ["SB-999"]
        document["repetition_justifications"] = [justification]
        self.assert_blocked(document, "real other SB IDs")

    def test_explicit_user_uniform_request_is_allowed(self):
        document = self.document(["SB-007"] * 10)
        document.update(layout_policy="uniform_by_user_request",
                        uniform_layout_request={"source": "user", "instruction_excerpt": "这篇统一用同一种四格分镜"})
        result = rhythm.audit_decision(document)
        self.assertEqual(result["status"], "passed", result)
        self.assertEqual(result["declared_adaptations"][0]["type"], "uniform_layout_by_user_request")

    def test_assistant_preference_is_not_user_uniform_authorization(self):
        document = self.document(["SB-007"] * 3)
        document.update(layout_policy="uniform_by_user_request",
                        uniform_layout_request={"source": "assistant", "instruction_excerpt": "为了方便拼接继续沿用"})
        self.assert_blocked(document, "requires source:user")

    def test_current_single_page_needs_no_variety(self):
        result = rhythm.audit_decision(self.document(["SB-001"]))
        self.assertEqual(result["status"], "passed", result)

    def test_legacy_single_layout_CLI_is_supported_without_multi_page_evidence(self):
        page = self.page(1)
        page.pop("selection_evidence")
        page.pop("page_id")
        page.pop("panel_count_reason")
        page.pop("narrative_function")
        result = rhythm.audit_decision(page)
        self.assertEqual(result["status"], "passed", result)

    def test_old_single_choice_cannot_be_expanded_to_ten_pages(self):
        page = self.page(1)
        page.pop("selection_evidence")
        page["page_count"] = 10
        self.assert_blocked(page, "single selected layout cannot stand for multiple pages")

    def test_fake_layout_and_fake_candidate_are_blocked(self):
        document = self.document(["SB-001", "SB-002"])
        document["pages"][0]["layout_id"] = "SB-999"
        self.assert_blocked(document, "not a real bundled SB ID: SB-999")
        document = self.document(["SB-001", "SB-002"])
        document["pages"][0]["selection_evidence"]["candidates"].append(
            {"layout_id": "SB-999", "compatible": True, "reason": "伪造一个看起来兼容的候选模板"})
        self.assert_blocked(document, "candidate is not a real bundled SB ID")

    def test_native_count_and_planned_list_cannot_be_falsified(self):
        document = self.document(["SB-001", "SB-002"])
        document["pages"][0]["panel_count"] = 3
        document["pages"][0]["panels"].pop()
        self.assert_blocked(document, "differs from SB-001 native count=4")
        document = self.document(["SB-001", "SB-002"])
        document["pages"][0]["panels"].pop()
        self.assert_blocked(document, "panel_count must equal len(panels)")

    def test_candidate_compatible_claim_is_checked_against_native_count(self):
        document = self.document(["SB-001", "SB-002"])
        document["pages"][0]["selection_evidence"]["candidates"].append(
            {"layout_id": "SB-013", "compatible": True, "reason": "声称原生数量兼容但实际只有三个叙事单元"})
        self.assert_blocked(document, "compatible candidate SB-013 has a different native panel count")

    def test_malformed_metadata_blocks_instead_of_crashing(self):
        document = self.document(["SB-001", "SB-002"])
        document["pages"][0]["layout_id"] = {"id": "SB-001"}
        self.assert_blocked(document, "layout_id is not a real bundled SB ID")

    def test_page_count_is_checked(self):
        document = self.document(["SB-001", "SB-002"])
        document["page_count"] = 3
        self.assert_blocked(document, "page_count does not equal len(pages)")

    def test_cli_blocks_before_images_and_writes_report(self):
        with tempfile.TemporaryDirectory() as directory:
            decision = Path(directory) / "decision.yaml"
            output = Path(directory) / "reports" / "rhythm.json"
            decision.write_text(yaml.safe_dump(self.document(["SB-007"] * 10), allow_unicode=True), encoding="utf-8")
            result = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPTS / "audit_storyboard_rhythm.py"),
                                     "--decision", str(decision), "--output", str(output)],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 2, result.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(report["generation_ready"])
            self.assertFalse(report["images_generated"])
            self.assertFalse(list(Path(directory).rglob("*.png")))


if __name__ == "__main__":
    unittest.main()
