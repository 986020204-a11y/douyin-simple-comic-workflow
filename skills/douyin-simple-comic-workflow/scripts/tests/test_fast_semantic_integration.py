"""Whole-page semantic FAST lifecycle, using disposable SIMULATION art only."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, PngImagePlugin

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import fast_caption
import fast_prepare
import fast_queue


def _font_path():
    return next((Path(value) for value in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf',
                                         '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
                 if Path(value).is_file()), None)


@unittest.skipUnless(_font_path(), 'local Chinese font required')
class SemanticLifecycle(unittest.TestCase):
    def test_prepare_review_reflow_cli_resume_and_first_page_skip(self):
        with tempfile.TemporaryDirectory(prefix='semantic-lifecycle-SIMULATION-') as temporary:
            root = Path(temporary)
            source = root / 'article.txt'
            source.write_text('妈妈问：“今天很累吧？”小海答：“还好。”', encoding='utf-8')
            page = {'page_id': 'P01', 'layout_id': 'SB-025',
                    'narrative_function': '妈妈询问、小海回应，正反打表现试探而克制的交谈。',
                    'panel_count_reason': '问与答是两个完整回应，用两格保持说话者和阅读顺序。',
                    'layout_adaptation': {'reason': '保留原正反打机制，以两个连续回应适配两格，省去其他示例机位。'},
                    'panels': [
                        {'panel_id': 'U01', 'focus': '妈妈询问', 'main_action_or_emotion': '关心地问一句',
                         'bounds': [0.04, 0.04, 0.92, 0.44]},
                        {'panel_id': 'U02', 'focus': '小海回应', 'main_action_or_emotion': '克制地答一句',
                         'bounds': [0.04, 0.52, 0.92, 0.44]}],
                    'prompt': 'A complete two-panel exchange using the selected original shot-reverse-shot mechanism.',
                    'captions': [
                        {'caption_id': 'C01', 'panel_id': 'U01', 'type': 'dialogue', 'speaker_id': 'N02',
                         'text': '今天很累吧？', 'bounds': [0.08, 0.06, 0.65, 0.16]},
                        {'caption_id': 'C02', 'panel_id': 'U02', 'type': 'dialogue', 'speaker_id': 'N01',
                         'text': '还好。', 'bounds': [0.13, 0.70, 0.65, 0.16]}]}
            draft = {'mode': 'fast', 'source_path': str(source),
                     'analysis': {'source_facts': ['妈妈问今天很累吧，小海回答还好。']},
                     'characters': [{'character_id': 'N01', 'description': '小海，短黑发蓝衣'},
                                    {'character_id': 'N02', 'description': '妈妈，短发米色上衣'}],
                     'style': {'prompt': 'Chinese hand-drawn diary comic with consistent characters.'},
                     'text_settings': {'font_path': str(_font_path()), 'font_size': 40,
                                       'canvas_size': [1080, 1440]}, 'pages': [page]}
            draft_path = root / 'draft.json'
            draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
            run = root / 'run'
            fast_prepare.prepare(draft_path, run, simulation=True)
            claim = fast_queue.claim_page(run)
            self.assertIn('N02', claim['request']['prompt'])
            fake = root / 'SIMULATED.png'
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text('simulation', 'MECHANICAL FIXTURE ONLY - NOT GPT ARTWORK')
            Image.new('RGB', (1080, 1440), (220, 225, 230)).save(fake, pnginfo=metadata)
            saved = fast_queue.complete_page(run, 'P01', claim['claim_token'], fake,
                                             'SIMULATED-INTEGRATION-CALL', provider='simulation')
            self.assertEqual(fast_caption.compose(run, 'P01')['status'], 'pending-image-review')
            evidence = {'page_id': 'P01', 'image_sha256': saved['image_sha256'], 'simulation': True,
                        'geometry_observed_from_image': True, 'caption_placements_verified': True,
                        'checks': {key: {'passed': True, 'reason': 'SIMULATION fixture transport declaration only'}
                                   for key in ('character_consistency', 'story_coverage', 'storyboard_execution')},
                        'panels': [{'panel_id': p['panel_id'], 'bounds': p['bounds']} for p in page['panels']],
                        'protected_regions': [{'bounds': [0.76, 0.27, 0.15, 0.15]}],
                        'speaker_regions': [{'speaker_id': 'N02', 'panel_id': 'U01', 'bounds': [0.76, 0.27, 0.15, 0.15]},
                                            {'speaker_id': 'N01', 'panel_id': 'U02', 'bounds': [0.1, 0.53, 0.14, 0.12]}]}
            review_path = root / 'SIMULATED-review.json'
            review_path.write_text(json.dumps(evidence), encoding='utf-8')
            fast_queue.review_page(run, 'P01', review_path)
            self.assertEqual(fast_caption.compose(run, 'P01')['status'], 'pending-placement')
            original = json.loads((run / 'fast/captions/P01.json').read_text(encoding='utf-8'))
            revision = copy.deepcopy(original)
            revision['image_review'] = evidence
            folder = run / 'fast/caption-revisions'
            folder.mkdir()
            first_path = folder / 'P01-first.json'
            first_path.write_text(json.dumps(revision), encoding='utf-8')
            state_before = (run / 'fast/state.json').read_bytes()
            base_before = Path(saved['output_path']).read_bytes()
            with patch.object(fast_queue, 'claim_page', side_effect=AssertionError('caption requested image work')):
                first = fast_caption.compose(run, 'P01', caption_plan_path=first_path)
                revision['captions'][0]['bounds'] = [0.12, 0.24, 0.58, 0.14]
                second_path = folder / 'P01-second.json'
                second_path.write_text(json.dumps(revision), encoding='utf-8')
                second = fast_caption.compose(run, 'P01', caption_plan_path=second_path)
            source.unlink()
            draft_path.unlink()
            fast_prepare.prepare(root / 'missing.json', run, simulation=True)
            after_resume = (run / 'fast/state.json').read_bytes()
            result = subprocess.run([sys.executable, str(SCRIPTS / 'fast_caption.py'), '--run-root', str(run),
                                     '--page-id', 'P01'], capture_output=True, text=True, encoding='utf-8', timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            resumed = json.loads(result.stdout)
            self.assertEqual(resumed['output_path'], second['output_path'])
            self.assertNotEqual(first['output_path'], second['output_path'])
            self.assertTrue(Path(first['output_path']).is_file())
            self.assertEqual((run / 'fast/state.json').read_bytes(), after_resume)
            self.assertEqual(Path(saved['output_path']).read_bytes(), base_before)
            self.assertEqual(fast_queue.claim_page(run)['status'], 'complete')
            summary = fast_queue.status(run)
            self.assertEqual(summary['counts']['dispatched_attempts'], 1)
            self.assertEqual(summary['counts']['recorded_builtin_image_gen_calls'], 0)


if __name__ == '__main__':
    unittest.main()
