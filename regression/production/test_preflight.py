"""Offline declared-content and real compositor proofs in isolated diagnostics.

Tiny generated scaffolds exercise execution, never artistic acceptance. No
provider is contacted and no historical comic or test directory is modified.
"""
from pathlib import Path
import copy
import json
import sys
import tempfile
import unittest

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT/'skills/douyin-simple-comic-workflow'
sys.path.insert(0, str(SKILL/'scripts'))
import production_preflight as pre
import production_queue as queue
from layout_executor import compile_template_contract
from template_contract import executable_text_containers


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.source = '甲乙。丙丁。戊己。'
        self.manifest = {'pages': [
            {'page_id': 'P01', 'beat_bindings': [{'beat_id': 'B1', 'panel_id': 'U01', 'presentation': 'both'}]},
            {'page_id': 'P02', 'beat_bindings': [{'beat_id': 'B2', 'panel_id': 'U01', 'presentation': 'both'}]}],
            'story_beats': [{'beat_id': 'B1', 'source_range': [0, 3], 'required_texts': ['甲乙。']},
                            {'beat_id': 'B2', 'source_range': [3, 6], 'required_texts': ['丙丁。']}],
            'text_policy': 'excerpts'}
        self.plans = {'P01': {'text_blocks': [{'id': 'T1', 'panel_id': 'U01', 'text': '甲乙。', 'source_article_range': [0, 3]}]},
                      'P02': {'text_blocks': [{'id': 'T2', 'panel_id': 'U01', 'text': '丙丁。', 'source_article_range': [3, 6]}]}}
        self.contracts = {p: {'panel_geometry': [{'panel_id': 'U01', 'order': 1}]} for p in self.plans}

    def report(self):
        return pre.coverage(self.manifest, self.plans, self.contracts, self.source)

    def test_declared_coverage_keeps_actual_semantic_review_pending(self):
        report = self.report()
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['semantic_visual_coverage'], 'pending_actual_image_review')

    def test_missing_story_beat_blocks(self):
        self.manifest['pages'][1]['beat_bindings'] = []
        self.assertIn('B2: uncovered_required_beat', self.report()['errors'])

    def test_invalid_panel_binding_blocks(self):
        self.manifest['pages'][0]['beat_bindings'][0]['panel_id'] = 'unknown'
        self.assertEqual(self.report()['status'], 'blocked')

    def test_invented_excerpt_blocks(self):
        self.plans['P01']['text_blocks'][0]['text'] = '甲乙改'
        self.assertIn('P01/T1: source_excerpt_mismatch', self.report()['errors'])

    def test_quote_from_other_beat_cannot_be_reassigned(self):
        self.manifest['story_beats'][0]['required_texts'] = ['丙丁。']
        self.plans['P01']['text_blocks'].append(copy.deepcopy(self.plans['P02']['text_blocks'][0]))
        self.assertIn('B1: missing_required_verbatim_text', self.report()['errors'])

    def test_unrelated_excerpts_cannot_invent_quote_by_concatenation(self):
        self.source = '甲乙。甲。乙。丙丁。'
        self.manifest['story_beats'][0].update(source_range=[0, 3], required_texts=['甲乙'])
        self.manifest['story_beats'][1].update(source_range=[7, 10])
        self.plans['P01']['text_blocks'] = [
            {'id':'T1', 'panel_id':'U01', 'text':'甲', 'source_article_range':[3, 4]},
            {'id':'T2', 'panel_id':'U01', 'text':'乙', 'source_article_range':[5, 6]}]
        self.plans['P02']['text_blocks'][0]['source_article_range'] = [7, 10]
        self.assertIn('B1: missing_required_verbatim_text', self.report()['errors'])

    def test_contiguous_exact_quote_may_span_two_linked_blocks(self):
        self.plans['P01']['text_blocks'] = [
            {'id':'T1', 'panel_id':'U01', 'text':'甲', 'source_article_range':[0, 1]},
            {'id':'T2', 'panel_id':'U01', 'text':'乙。', 'source_article_range':[1, 3]}]
        self.assertEqual(self.report()['status'], 'passed')

    def test_story_reading_order_cannot_reverse(self):
        self.manifest['story_beats'].reverse()
        self.assertEqual(self.report()['status'], 'blocked')

    def test_verbatim_policy_rejects_uncovered_source(self):
        self.manifest['text_policy'] = 'verbatim'
        self.assertIn('verbatim_source_characters_missing:3', self.report()['errors'])

    def test_invalid_boolean_source_spans_rejected(self):
        for span in ([True, 3], [-1, 3], [3, 3], [0, len(self.source)+1], None):
            with self.subTest(span=span):
                self.assertFalse(pre.valid_span(span, self.source))


class PreparedRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='comic-preflight-diagnostic-')
        self.root = Path(self.temp.name)
        self.template = pre.load(SKILL/'references/comic-layouts/executable-templates/SB-053.yaml')
        # A uniformly contained target exercises the compositor at delivery
        # size without modifying source previews. This deliberately labelled
        # diagnostic does not certify a full-bleed story or source exactness.
        native = dict(self.template['canvas'])
        y_factor = native['height'] * (1080/native['width']) / 1440
        seen = set()
        for row in self.template['panels'] + self.template['bubbles'] + self.template.get('structure',{}).get('units',[]):
            if id(row) in seen:
                continue
            seen.add(id(row))
            if row.get('bounds'):
                x,y,w,h = row['bounds']; row['bounds'] = [x,y*y_factor,w,h*y_factor]
            if row.get('polygon'):
                row['polygon'] = [[x,y*y_factor] for x,y in row['polygon']]
        self.template['canvas'].update(width=1080,height=1440,aspect_ratio='3:4')
        self.template.update(diagnostic_test_only=True,match_policy='adapted',user_approved_adaptation=True)
        panel_geometry = {u['panel_id']:u for u in compile_template_contract(self.template)['panel_geometry']}
        for bubble in self.template['bubbles']:
            panel = panel_geometry[bubble['panel_id']]
            x,y,w,h = bubble['bounds']
            bubble['bounds'] = [max(x,(panel['x']+1)/1080), max(y,(panel['y']+1)/1440),w,h]
            if bubble.get('visual_style',{}).get('font_style') == 'unknown':
                bubble['visual_style'].pop('font_style')
                bubble['source_font_style_identity'] = 'unknown'
        containers = executable_text_containers(self.template)
        self.source = '甲乙丙丁戊己'
        (self.root/'source.txt').write_text(self.source, encoding='utf-8')
        dump(self.root/'template.json', self.template)
        # Explicit bundled font makes these execution fixtures portable. This
        # is not a claim that it reproduces the source preview's unknown font.
        font = str(SKILL/'assets/fonts/mashanzheng/MaShanZheng-Regular.ttf')
        dump(self.root/'font.json', {'font_file':font, 'font_bold_file':font,
                                     'font_size':24, 'minimum_readable_font_size':24})
        self.plan = {'page_id':'P01', 'layout_id':'SB-053', 'selected_layout':'SB-053',
                     'canvas':self.template['canvas'], 'synthetic':True,
                     'diagnostic_test_only':True, 'match_policy':'adapted', 'user_approved_adaptation':True,
                     'bubble_selection_policy':'all_template_bubbles',
                     'narration_text':list(self.source), 'dialogue_text':[], 'note_text':[],
                     'text_blocks':[]}
        bindings, beats = [], []
        units = compile_template_contract(self.template)['panel_geometry']
        by_panel = {u['panel_id']:u for u in units}
        for i, (text, bubble) in enumerate(zip(self.source, containers)):
            panel = by_panel[bubble['panel_id']]
            self.plan['text_blocks'].append({'id':f'T{i+1}', 'bubble_id':bubble['bubble_id'],
                'panel_id':bubble['panel_id'], 'source_field':'narration_text', 'source_index':i,
                'source_article_range':[i,i+1], 'text':text, 'type':'narration',
                'source_type':'narration', 'speaker':'narrator', 'font_size':24,
                'actual_panel_bounds':[panel[k] for k in ('x','y','width','height')],
                'actual_panel_bounds_format':'xywh', 'actual_regions_verified':True,
                'actual_region_evidence':{'source':'diagnostic_neutral_scaffold', 'synthetic':True},
                'confirmed_absent_regions':['face','hands','key_props'],
                'bubble_contract':copy.deepcopy(bubble)})
            bid = f'B{i+1}'
            bindings.append({'beat_id':bid, 'panel_id':bubble['panel_id'], 'presentation':'both'})
            beats.append({'beat_id':bid, 'source_range':[i,i+1], 'required_texts':[text]})
        dump(self.root/'plan.json', self.plan)
        Image.new('RGB',(16,16),'navy').save(self.root/'reference.png')
        dump(self.root/'decision.json', {'selected_by':'douyin-simple-comic-workflow',
             'internal_layout_pool':68, 'pages':[{'page_id':'P01', 'layout_id':'SB-053',
             'panel_count':len(units), 'story_beat_id':'B1'}]})
        self.manifest = {'diagnostic_test_only':True, 'source_path':'source.txt',
            'storyboard_decision_path':'decision.json', 'text_policy':'verbatim',
            'story_beats':beats, 'shared_reference_paths':['reference.png'],
            'pages':[{'page_id':'P01', 'template_path':'template.json',
                      'text_plan_path':'plan.json', 'text_layout_path':'font.json',
                      'beat_bindings':bindings,
                      'assets':[{'unit_id':u['unit_id'], 'scene_prompt':'Diagnostic neutral interior only.'} for u in units]}]}
        dump(self.root/'manifest.json', self.manifest)

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_rendered_proof_emits_hash_bound_actual_references(self):
        result = pre.prepare(self.root/'manifest.json', self.root/'prepared', diagnostic=True)
        self.assertTrue(result['generation_ready'], result)
        self.assertFalse(result['images_generated'])
        self.assertFalse(result['actual_image_checked'])
        proof = pre.load(self.root/'prepared/P01/generation-readiness.json')
        self.assertTrue(proof['complete_proof']['accepted'])
        report = pre.load(proof['complete_proof']['render_report_path'])
        self.assertEqual(report['canonical_block_count'],6)
        self.assertEqual(report['rendered_count'],6)
        self.assertTrue(report['pixel_difference_nonempty'])
        request_path = self.root/'prepared/generation-requests.json'
        state = self.root/'queue.json'
        queue.init_queue(request_path, state, diagnostic=True)
        claims = queue.claim_jobs(state, 'offline-diagnostic')['jobs']
        self.assertEqual(len(claims),4)
        for job in claims:
            self.assertEqual(job['reference_paths'],job['request']['referenced_image_paths'])
            self.assertIn(str(self.root/'reference.png'),job['request']['referenced_image_paths'])
            self.assertTrue(all(Path(p).is_file() and Path(p).is_absolute() for p in job['reference_paths']))

    def test_partial_diagnostic_requires_explicit_mode(self):
        with self.assertRaisesRegex(ValueError, 'requires --diagnostic'):
            pre.prepare(self.root/'manifest.json', self.root/'blocked')

    def test_diagnostic_switch_requires_explicit_manifest_mark(self):
        self.manifest.pop('diagnostic_test_only')
        dump(self.root/'manifest.json',self.manifest)
        with self.assertRaisesRegex(ValueError, 'requires diagnostic_test_only'):
            pre.prepare(self.root/'manifest.json', self.root/'blocked',diagnostic=True)

    def test_normal_preparation_cannot_drop_handoff_pages(self):
        self.manifest.pop('diagnostic_test_only')
        dump(self.root/'manifest.json',self.manifest)
        decision = pre.load(self.root/'decision.json')
        decision['pages'].append(dict(decision['pages'][0],page_id='P02'))
        dump(self.root/'decision.json',decision)
        with self.assertRaisesRegex(ValueError, 'complete storyboard handoff'):
            pre.prepare(self.root/'manifest.json',self.root/'blocked')

    def test_existing_output_is_preserved(self):
        folder = self.root/'existing'; folder.mkdir()
        marker = folder/'retained.txt'; marker.write_text('protected',encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'new empty'):
            pre.prepare(self.root/'manifest.json',folder,diagnostic=True)
        self.assertEqual(marker.read_text(encoding='utf-8'),'protected')

    def test_white_unboxed_text_reserves_dark_scene_region(self):
        unit = {'panel_id':'U1','x':100,'y':200,'width':400,'height':500,'geometry_type':'unframed'}
        row = {'block_id':'T1','bubble_id':'B1','panel_id':'U1','target_bounds_xywh':[140,250,160,150]}
        block = {'id':'T1','bubble_contract':{'shape':'display_text',
                  'visual_style':{'renderer':'preview_display','text_color':'white'}}}
        zone = pre.scene_zones(unit,[row],{'text_blocks':[block]})[0]
        self.assertEqual(zone['background_requirement'],'quiet_dark_low_detail')
        self.assertEqual(zone['bounds_unit_normalized_xywh'],[.1,.1,.4,.3])
        row['panel_id'] = 'U2'
        self.assertEqual(pre.scene_zones(unit,[row],{'text_blocks':[block]}),[])


if __name__ == '__main__':
    unittest.main()
