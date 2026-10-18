"""Production font/semantic regression; fixtures are diagnostics, never artwork."""
from pathlib import Path
import copy
import sys
import unittest

from PIL import Image, ImageDraw, ImageChops

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT/'skills/douyin-simple-comic-workflow'
sys.path.insert(0, str(SKILL/'scripts'))
import text_compositor as tc


class TextSemanticsTests(unittest.TestCase):
    def setUp(self):
        font = str(SKILL/'assets/fonts/mashanzheng/MaShanZheng-Regular.ttf')
        self.config = {'font_file':font, 'font_bold_file':font,
                       'font_size':48, 'minimum_readable_font_size':24,
                       'text_box_style':{'padding':8}, '_explicit_font_size':True}

    def test_fixed_font_cannot_silently_shrink(self):
        draw = ImageDraw.Draw(Image.new('RGBA',(320,120),'white'))
        text = '完整的文字必须保留字号并且能够看清。'*5
        measured = tc._measure_text_layout(draw,text,(0,0,300,100),self.config,size=48)
        self.assertFalse(measured['fit_ok'])
        self.assertEqual(measured['font_size'],48)
        with self.assertRaises(tc._TextFitError):
            tc._draw_text(draw,text,(0,0,300,100),self.config,size=48)

    def test_explicit_fitting_never_goes_below_readable_minimum(self):
        draw = ImageDraw.Draw(Image.new('RGBA',(320,180),'white'))
        config = dict(self.config,font_size_policy='fit')
        measured = tc._measure_text_layout(draw,'请保留完整文字，不遮挡人物。',(0,0,300,130),config,size=64)
        self.assertTrue(measured['fit_ok'])
        self.assertGreaterEqual(measured['font_size'],24)
        self.assertLess(measured['font_size'],64)

    def test_raster_font_evidence_records_executed_size(self):
        before = Image.new('RGBA',(400,180),'white')
        picture = before.copy()
        block = {'id':'D01','text':'可读字幕','font_size':48,'type':'narration',
                 'bubble_style':'narration_box','diagnostic_test_only':True}
        _, result = tc._draw_block(ImageDraw.Draw(picture),block,(10,10,390,170),self.config)
        self.assertTrue(result['rendered'],result)
        self.assertEqual(result['actual_font_sizes'],[48])
        self.assertTrue(result['font_raster_evidence']['draw_calls'])
        self.assertIsNotNone(ImageChops.difference(before.convert('RGB'),picture.convert('RGB')).getbbox())

    def system_block(self):
        return {'type':'note','source_type':'note','speaker':'system','use_preview_contract':True,
                'bubble_contract':{'shape':'rect','note_scope':'nonphysical_system_overlay',
                                   'allowed_text_types':['note'], 'tail':{'mode':'none'},
                                   'compatibility_adaptation':{
                                       'kind':'system_note_semantic_adaptation',
                                       'approved_for_run':True,'origin':'workflow_adaptation',
                                       'reason':'Explicitly approved nonphysical fictional system caption.',
                                       'source_allowed_text_types':['narration']}}}

    def test_explicit_system_note_preserves_semantics(self):
        block = self.system_block()
        self.assertTrue(tc._system_note_overlay_allowed(block,'preview_caption_box'))
        self.assertEqual(block['type'],'note')
        self.assertEqual(block['source_type'],'note')

    def test_physical_or_unapproved_notes_do_not_use_system_exception(self):
        cases = []
        for field, value in [('speaker','N01'),('source_type','dialogue')]:
            block = self.system_block(); block[field] = value; cases.append(block)
        block = self.system_block(); block['carrier'] = {'asset_id':'physical-note'}; cases.append(block)
        block = self.system_block(); block['bubble_contract']['tail']={'mode':'unknown'}; cases.append(block)
        block = self.system_block(); block['bubble_contract']['compatibility_adaptation']['approved_for_run']=False; cases.append(block)
        block = self.system_block(); block['bubble_contract']['compatibility_adaptation']['reason']=''; cases.append(block)
        for block in cases:
            with self.subTest(block=block):
                self.assertFalse(tc._system_note_overlay_allowed(block,'preview_caption_box'))


if __name__ == '__main__':
    unittest.main()
