"""Exercise selection, preflight and resumed queue boundaries without an image API."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image
import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import audit_storyboard_rhythm as rhythm
import production_preflight as preflight
import production_queue as queue
import prompt_style


class StoryboardGateIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return path

    @staticmethod
    def page(number, layout='SB-001', count=4):
        pid = f'P{number:02d}'
        narrative = f'母女第{number}段对话以表情变化交代孩子逐渐安心'
        alternative = 'SB-002' if layout == 'SB-001' else 'SB-001'
        return {'page_id': pid, 'layout_id': layout, 'panel_count': count,
                'narrative_function': narrative,
                'panel_count_reason': '哭醒、寻找、拥抱与承诺分别需要独立的情绪节点',
                'panels': [{'focus': f'第{i}个动作', 'main_action_or_emotion': f'第{i}个情绪'}
                           for i in range(count)],
                'selection_evidence': {'page_id': pid, 'selected_layout_id': layout,
                    'narrative_function': narrative, 'selection_reason': '通过表情对照让孩子从惊恐逐步安心',
                    'candidates': [{'layout_id': lid, 'compatible': True,
                                    'reason': '原生格数兼容且可以表达本页的情绪变化'}
                                   for lid in (layout, alternative)]}}

    def decision(self):
        return {'selected_by': 'douyin-simple-comic-workflow', 'internal_layout_pool': 68,
                'page_count': 2, 'pages': [self.page(1), self.page(2, 'SB-002')]}

    def audit_fixture(self, decision=None):
        decision = self.decision() if decision is None else decision
        dp = self.write('decision.json', decision)
        report = rhythm.audit_decision(decision)
        self.assertEqual(report['status'], 'passed', report)
        report['decision_binding'] = queue._file_binding(dp)
        rp = self.write('rhythm.json', report)
        return queue._file_binding(rp), dp, rp

    def queue_fixture(self):
        audit_binding, decision_path, _ = self.audit_fixture()
        image = self.root / 'synthetic-layout-proof.png'
        Image.new('RGB', (8, 8), 'white').save(image)
        render = self.write('proof-render.json', {'page_acceptance_status': 'accepted',
            'synthetic_input': True, 'actual_image_checked': False, 'canonical_block_count': 0,
            'rendered_count': 0, 'unresolved_count': 0, 'output_image_sha256': queue.sha256(image)})
        bubbles = self.write('proof-bubbles.json', {'execution_bubble_match': 'passed'})
        pages = []
        for number, layout in [(1, 'SB-001'), (2, 'SB-002')]:
            pid = f'P{number:02d}'
            target = self.write(f'{pid}-target.json', {'layout_id': layout})
            proof = self.write(f'{pid}-ready.json', {'page_id': pid, 'generation_ready': True,
                'synthetic_input': True, 'actual_image_checked': False,
                'storyboard_rhythm_binding': audit_binding,
                'input_bindings': [queue._file_binding(target), queue._file_binding(decision_path), audit_binding],
                'complete_proof': {'accepted': True, 'image_path': str(image), 'image_sha256': queue.sha256(image),
                    'render_report_path': str(render), 'render_report_sha256': queue.sha256(render),
                    'bubble_audit_path': str(bubbles), 'bubble_audit_sha256': queue.sha256(bubbles)}})
            pages.append({'page_id': pid, 'template_path': str(target),
                'proof': {'report_path': str(proof), 'sha256': queue.sha256(proof)},
                'jobs': [{'unit_id': 'P01', 'reference_paths': [], 'request': {'prompt': 'Test handoff only'}}]})
        manifest = self.write('requests.json', {'schema_version': 1, 'pipeline_version': 'integration-test',
            'expected_page_ids': ['P01', 'P02'], 'pilot_page_id': 'P01', 'pages': pages,
            'storyboard_rhythm_binding': audit_binding})
        return manifest

    def test_uniform_plan_stops_preflight_before_rendering_or_requests(self):
        source = self.root / 'source.txt'
        source.write_text('母女故事', encoding='utf-8')
        decision = self.decision()
        decision['pages'] = [self.page(i, 'SB-007') for i in range(1, 11)]
        decision['page_count'] = 10
        for page in decision['pages']:
            page.pop('selection_evidence')
        dp = self.write('legacy-ten-page.json', decision)
        mp = self.write('production.json', {'source_path': str(source), 'storyboard_decision_path': str(dp),
                                         'pages': [{'page_id': p['page_id']} for p in decision['pages']]})
        output = self.root / 'preparation'
        result = preflight.prepare(mp, output)
        self.assertFalse(result['generation_ready'])
        self.assertFalse(result['images_generated'])
        self.assertFalse((output / 'generation-requests.json').exists())
        self.assertFalse(list(output.rglob('*.png')))
        self.assertEqual(json.loads((output / 'storyboard-rhythm-audit.json').read_text(encoding='utf-8'))['status'], 'blocked')

    def test_current_rhythm_binding_is_accepted_and_page_layout_is_checked(self):
        binding, _, _ = self.audit_fixture()
        target = self.write('target.json', {'layout_id': 'SB-001'})
        queue._validate_storyboard_rhythm(binding, self.root, page_id='P01', template_path=target,
                                         expected_page_ids=['P01', 'P02'])
        self.write('target.json', {'layout_id': 'SB-002'})
        with self.assertRaisesRegex(queue.QueueError, 'Page/template differs'):
            queue._validate_storyboard_rhythm(binding, self.root, page_id='P01', template_path=target)

    def test_saved_pass_cannot_hide_a_changed_or_newly_blocked_decision(self):
        binding, dp, rp = self.audit_fixture()
        changed = self.decision()
        changed['pages'][1] = self.page(2)
        dp.write_text(json.dumps(changed, ensure_ascii=False), encoding='utf-8')
        with self.assertRaisesRegex(queue.QueueError, 'changed evidence'):
            queue._validate_storyboard_rhythm(binding, self.root)
        forged = json.loads(rp.read_text(encoding='utf-8'))
        forged['decision_binding'] = queue._file_binding(dp)
        rp.write_text(json.dumps(forged, ensure_ascii=False), encoding='utf-8')
        with self.assertRaisesRegex(queue.QueueError, 'rhythm audit is missing, stale or blocked'):
            queue._validate_storyboard_rhythm(queue._file_binding(rp), self.root)

    def test_subset_cannot_be_passed_off_as_whole_story(self):
        binding, _, _ = self.audit_fixture()
        with self.assertRaisesRegex(queue.QueueError, 'entire prepared page set'):
            queue._validate_storyboard_rhythm(binding, self.root, expected_page_ids=['P01'])

    def test_missing_rhythm_evidence_stops_queue_initialization(self):
        manifest = self.queue_fixture()
        document = json.loads(manifest.read_text(encoding='utf-8'))
        document.pop('storyboard_rhythm_binding')
        manifest.write_text(json.dumps(document), encoding='utf-8')
        with self.assertRaises(queue.QueueError):
            queue.init_queue(manifest, self.root / 'state.json')
        self.assertFalse((self.root / 'state.json').exists())

    def test_resumed_queue_rechecks_rhythm_before_dispatch(self):
        manifest = self.queue_fixture()
        state = self.root / 'state.json'
        queue.init_queue(manifest, state)
        # The requests and page proof stay unchanged; the referenced decision drifts.
        decision = self.root / 'decision.json'
        document = json.loads(decision.read_text(encoding='utf-8'))
        document['pages'][1]['narrative_function'] = '更改后的故事功能'
        decision.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
        result = queue.claim_jobs(state, 'resumed-worker', limit=1)
        self.assertEqual(result['jobs'], [])
        stored = json.loads(state.read_text(encoding='utf-8'))
        self.assertFalse(stored['pages']['P01']['generation_ready'])
        self.assertEqual(stored['jobs']['P01/P01']['attempts'], 0)

    def test_missing_proof_page_id_cannot_skip_audited_target_check(self):
        manifest = self.queue_fixture()
        document = json.loads(manifest.read_text(encoding='utf-8'))
        page = document['pages'][1]
        target = Path(page['template_path'])
        target.write_text(json.dumps({'layout_id': 'SB-001'}), encoding='utf-8')
        proof_path = Path(page['proof']['report_path'])
        proof = json.loads(proof_path.read_text(encoding='utf-8'))
        proof.pop('page_id')
        proof['input_bindings'][0] = queue._file_binding(target)
        proof_path.write_text(json.dumps(proof), encoding='utf-8')
        page['proof']['sha256'] = queue.sha256(proof_path)
        manifest.write_text(json.dumps(document), encoding='utf-8')
        with self.assertRaisesRegex(queue.QueueError, 'explicit page_id'):
            queue.init_queue(manifest, self.root / 'state.json')
        self.assertFalse((self.root / 'state.json').exists())

    def test_another_pages_proof_cannot_authorize_a_repeated_target(self):
        manifest = self.queue_fixture()
        document = json.loads(manifest.read_text(encoding='utf-8'))
        # P02 borrows P01's otherwise valid proof and target. Both hashes are
        # current; only the outer page identity exposes the mismatch.
        document['pages'][1]['proof'] = copy.deepcopy(document['pages'][0]['proof'])
        document['pages'][1]['template_path'] = document['pages'][0]['template_path']
        manifest.write_text(json.dumps(document), encoding='utf-8')
        with self.assertRaisesRegex(queue.QueueError, 'differs from its request page'):
            queue.init_queue(manifest, self.root / 'state.json')
        self.assertFalse((self.root / 'state.json').exists())

    def test_valid_queue_still_hands_off_pilot_scene(self):
        manifest = self.queue_fixture()
        state = self.root / 'state.json'
        queue.init_queue(manifest, state)
        result = queue.claim_jobs(state, 'normal-worker', limit=1)
        self.assertEqual([j['page_id'] for j in result['jobs']], ['P01'])
        self.assertEqual(result['jobs'][0]['render_status'], 'not-generated')

    def test_actual_single_page_cli_output_can_be_audited(self):
        item = next(x for x in prompt_style.load_pool() if x['id'] == 'SB-001')
        contract = prompt_style.compile_execution_contract(item, 4)
        result = rhythm.audit_decision({'layout_id': 'SB-001', 'panel_count': 4, 'execution_contract': contract})
        self.assertEqual(result['status'], 'passed', result)

    def test_library_change_invalidates_cached_native_counts(self):
        library = self.root / 'library'
        library.mkdir()
        pool, entries = [], []
        for number in range(1, 69):
            lid = f'SB-{number:03d}'
            pool.append({'id': lid, 'category': 'comic-storyboard', 'name': lid,
                         'prompt_file': f'{lid}.md'})
            entries.append({'layout_id': lid, 'template_path': f'{lid}.yaml', 'panel_count': 1})
            (library / f'{lid}.md').write_text('Native layout', encoding='utf-8')
            (library / f'{lid}.yaml').write_text(yaml.safe_dump({'layout_id': lid,
                                                'panels': [{'panel_id': 'P01'}]}), encoding='utf-8')
        (library / 'layouts.json').write_text(json.dumps(pool), encoding='utf-8')
        (library / 'template-index.yaml').write_text(yaml.safe_dump({'templates': entries}), encoding='utf-8')
        self.assertEqual(rhythm._library(library)['SB-001']['panel_count'], 1)
        (library / 'SB-001.yaml').write_text(yaml.safe_dump({'layout_id': 'SB-001',
            'panels': [{'panel_id': 'P01'}, {'panel_id': 'P02'}]}), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'count mismatch'):
            rhythm._library(library)

    def test_actual_multi_page_cli_selects_real_compatible_geometry(self):
        pages = []
        for number, lid, count in [(1, 'SB-001', 4), (2, 'SB-013', 3), (3, 'SB-055', 1)]:
            page = self.page(number, lid, count)
            page.pop('selection_evidence')
            pages.append(page)
        source = self.write('page-plan.json', {'pages': pages})
        output = self.root / 'handoff.json'
        process = subprocess.run([sys.executable, '-X', 'utf8', str(SCRIPTS / 'prompt_style.py'),
            '--pages', str(source), '--output', str(output)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(process.returncode, 0, process.stderr[-5000:])
        handoff = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual([p['layout_id'] for p in handoff['pages']], ['SB-001', 'SB-013', 'SB-055'])
        self.assertEqual([len(p['execution_contract']['panel_geometry']) for p in handoff['pages']], [4, 3, 1])
        self.assertEqual(rhythm.audit_decision(handoff)['status'], 'passed')
        self.assertFalse(list(self.root.rglob('*.png')))


if __name__ == '__main__':
    unittest.main()
