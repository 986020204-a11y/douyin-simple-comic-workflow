#!/usr/bin/env python3
"""Test deterministic SB geometry with synthetic assets, never comic generation."""
from __future__ import annotations
import argparse,copy,hashlib,json
from pathlib import Path
import yaml
from PIL import Image,ImageDraw,ImageFont,ImageOps
from layout_executor import compile_template_contract,render_layout
from audit_storyboard_layout import audit

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def verify(root:Path,output:Path)->dict:
    output.mkdir(parents=True,exist_ok=True);rows=[]
    for path in sorted((root/'executable-templates').glob('SB-*.yaml')):
        template=yaml.safe_load(path.read_text(encoding='utf8'));lid=path.stem;folder=output/lid;folder.mkdir(parents=True,exist_ok=True)
        contract=compile_template_contract(template);assets={}
        for n,unit in enumerate(contract['panel_geometry'],1):
            color=(115+(n*31)%100,120+(n*47)%100,105+(n*61)%100)
            asset=Image.new('RGBA',(160,180),(*color,255));draw=ImageDraw.Draw(asset)
            for x in range(0,160,20):draw.line([(x,0),(x,180)],fill=(75,85,95),width=1)
            for y in range(0,180,20):draw.line([(0,y),(160,y)],fill=(75,85,95),width=1)
            if unit.get('alpha_required'):
                alpha=Image.new('L',asset.size,0);ImageDraw.Draw(alpha).ellipse((12,8,148,172),fill=255);asset.putalpha(alpha)
            ap=folder/f'{unit["panel_id"]}-synthetic.png';asset.save(ap);assets[unit['panel_id']]=str(ap)
        base=folder/'native-geometry.png'
        try:
            manifest=render_layout(template,base,assets=assets,strict_assets=True)
            manifest['synthetic_input']=True;manifest['evidence_scope']='synthetic_geometry_only_not_actual_comic'
            target={'selected_layout':lid,'layout_id':lid,'execution_contract':contract}
            result=audit(target,manifest,base_image=base,template=template,preview=root/template['source']['preview_image'])
            write(folder/'actual.json',manifest);write(folder/'audit.json',result)
            blank=folder/'negative-blank.png';Image.new('RGB',(contract['canvas']['width'],contract['canvas']['height']),'white').save(blank)
            original_hash=audit(target,manifest,base_image=blank,template=template)
            rebound=copy.deepcopy(manifest);rebound['measurement_evidence']['image_sha256']=digest(blank);rebound['output_image_sha256']=digest(blank)
            changed_hash=audit(target,rebound,base_image=blank,template=template)
            dropped=copy.deepcopy(manifest);dropped['panel_geometry']=dropped['panel_geometry'][:-1]
            wrong_count=audit(target,dropped,base_image=base,template=template)
            shifted=copy.deepcopy(manifest);shifted['panel_geometry'][0]['x']+=25
            wrong_bounds=audit(target,shifted,base_image=base,template=template)
            negatives={key:r['storyboard_layout_match']=='failed' for key,r in [('blank_original_hash',original_hash),('blank_rebound_hash',changed_hash),('deleted_panel',wrong_count),('shifted_panel',wrong_bounds)]}
            write(folder/'negative-results.json',{'all_rejected':all(negatives.values()),'checks':negatives,'rebound_blank_deviations':changed_hash['layout_deviation']})
            row={'layout_id':lid,'panel_count':len(contract['panel_geometry']),'bubble_count':len(template.get('bubbles') or []),'text_zone_count':contract['source_executable_text_zone_count'],
                'native_compile':'passed','execution_geometry_match':result['execution_geometry_match'],'reading_order_match':result['reading_order_match'],
                'synthetic_geometry_test':'passed' if result['execution_geometry_match']=='passed' else 'failed','negative_checks':negatives,
                'layout_deviation':result['layout_deviation'],'full_template_execution':'not_proven_by_geometry_test','actual_comic_tested':False,'base_image_modified':False}
        except Exception as exc:
            row={'layout_id':lid,'synthetic_geometry_test':'failed','error':str(exc),'actual_comic_tested':False}
        rows.append(row)
        print(lid,row['synthetic_geometry_test'],flush=True)
    sheets=[]
    diagnostic_font=Path('C:/Windows/Fonts/msyh.ttc')
    font=ImageFont.truetype(str(diagnostic_font),17) if diagnostic_font.is_file() else ImageFont.load_default()
    for start in range(0,len(rows),17):
        subset=rows[start:start+17];sheet=Image.new('RGB',(6*200,3*284+44),'#eceff3');draw=ImageDraw.Draw(sheet)
        draw.text((12,9),'SB synthetic geometry diagnostics - no story images',font=font,fill='black')
        for i,row in enumerate(subset):
            x=(i%6)*200;y=44+(i//6)*284
            file=output/row['layout_id']/'native-geometry.png'
            if file.is_file():
                with Image.open(file) as im:thumb=ImageOps.contain(im.convert('RGB'),(188,244))
                sheet.paste(thumb,(x+(200-thumb.width)//2,y+30))
            draw.text((x+8,y+3),row['layout_id']+' '+row['synthetic_geometry_test'],font=font,fill='black')
        sp=output/f'geometry-sheet-{start//17+1}.png';sheet.save(sp);sheets.append(str(sp))
    result={'template_count':len(rows),'native_geometry_passed':sum(r['synthetic_geometry_test']=='passed' for r in rows),
        'negative_cases':sum(len(r.get('negative_checks',{})) for r in rows),'negative_cases_rejected':sum(sum(r.get('negative_checks',{}).values()) for r in rows),
        'actual_comic_tested':False,'scope':'synthetic panel masks/positions/count/order only; no text/effect/source-pixel or real-artwork acceptance',
        'base_image_modified':False,'sheets':sheets,'rows':rows}
    write(output/'summary.json',result);return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    result=verify(args.root,args.output)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['native_geometry_passed']==result['template_count']==68 and result['negative_cases']==result['negative_cases_rejected'] else 1)
if __name__=='__main__':main()
