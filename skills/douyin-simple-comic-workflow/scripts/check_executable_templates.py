#!/usr/bin/env python3
"""Validate the 68 structured storyboard templates without rendering images."""
from __future__ import annotations
import argparse, json, hashlib, math
from pathlib import Path
import yaml
from PIL import Image
from template_contract import executable_text_containers

REQUIRED = {"layout_id", "version", "source", "canvas", "panels", "bubbles", "constraints", "fallback", "evidence"}
MATCH_POLICIES = {"structure_exact", "pixel_reference", "adapted"}
GEOMETRY_TYPES = {"rect", "polygon", "approximate_polygon", "phone_column", "inset_scene", "ellipse", "unframed"}

def _deep_check(data, path, root):
    errors=[]
    def error(kind,**details):errors.append({'type':kind,'file':path.name,**details})
    def required(obj,keys,scope):
        missing=sorted(set(keys)-set(obj or {}))
        if missing:error('missing_fields',scope=scope,fields=missing)
    def bounds(value,scope):
        if not isinstance(value,list) or len(value)!=4 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in value):
            error('invalid_geometry',scope=scope);return
        x,y,w,h=value
        if min(x,y)<-1e-5 or min(w,h)<=0 or x+w>1.001 or y+h>1.001:error('bounds_outside_canvas',scope=scope,bounds=value)
    source=data.get('source') or {};canvas=data.get('canvas') or {};panels=data.get('panels') or [];ids={p.get('panel_id') for p in panels}
    required(source,['preview_image','source_note','annotation_status','visual_reference_only'],'source')
    for field,key in [('preview_image','preview_sha256'),('source_note','note_sha256')]:
        ref=root/str(source.get(field) or '__missing__')
        if not ref.is_file():error('missing_reference',field=field)
        elif source.get(key)!=hashlib.sha256(ref.read_bytes()).hexdigest():error('source_hash_mismatch',field=field)
    required(canvas,['aspect_ratio','coordinate_system'],'canvas')
    try:
        with Image.open(root/source['preview_image']) as im:
            if (canvas.get('width'),canvas.get('height'))!=im.size:error('native_canvas_mismatch',expected=im.size)
            a,b=[float(v) for v in canvas['aspect_ratio'].split(':')]
            if abs(a/b-im.width/im.height)>1e-5:error('native_aspect_mismatch')
    except Exception as exc:error('canvas_reference_error',error=str(exc))
    for p in panels:
        pid=p.get('panel_id');required(p,['panel_id','order','bounds','role','cross_panel_allowed'],pid);bounds(p.get('bounds'),pid)
        ev=p.get('field_evidence') or {}
        for field in ['bounds','role','order','cross_panel_allowed']:
            if field not in ev:error('unmarked_field_evidence',scope=pid,field=field)
        if p.get('polygon') and any(not isinstance(q,list) or len(q)!=2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in q) for q in p['polygon']):error('invalid_polygon',panel_id=pid)
        parent=p.get('parent_id') or p.get('parent_panel_id')
        if parent and parent not in ids:error('missing_parent_panel',panel_id=pid,parent=parent)
    bids=[]
    for b in data.get('bubbles') or []:
        bid=b.get('bubble_id');bids.append(bid)
        required(b,['bubble_id','panel_id','allowed_text_types','shape','position','bounds','tail','max_width_ratio','avoid'],bid)
        bounds(b.get('bounds'),bid);required(b.get('tail'),['mode','anchor'],str(bid)+'.tail')
        if not b.get('allowed_text_types'):error('empty_allowed_text_types',bubble_id=bid)
        if not {'face','hands','key_props'}<=set(b.get('avoid') or []):error('missing_avoid_regions',bubble_id=bid)
        if not isinstance(b.get('max_width_ratio'),(int,float)) or b.get('max_width_ratio',0)<=0:error('invalid_max_width_ratio',bubble_id=bid)
        for field in ['bounds','shape','panel_id','allowed_text_types','max_width_ratio','avoid','renderer']:
            if field not in (b.get('field_evidence') or {}):error('unmarked_field_evidence',scope=bid,field=field)
        tail=b.get('tail') or {}
        if tail.get('mode')=='observed_polygon' and (not tail.get('polygon') or not isinstance(tail.get('anchor'),list)):error('missing_observed_tail_geometry',bubble_id=bid)
        if tail.get('mode')=='observed_dots' and not tail.get('dots'):error('missing_observed_thought_dots',bubble_id=bid)
    if len(bids)!=len(set(bids)) or any(not b for b in bids):error('duplicate_or_empty_bubble_id')
    zids=[]
    for z in data.get('text_zones') or []:
        zid=z.get('zone_id') or z.get('text_zone_id');zids.append(zid);bounds(z.get('bounds'),zid)
        if z.get('executable') is not True:continue
        required(z,['shape','tail','allowed_text_types','avoid','field_evidence'],str(zid))
        if z.get('scope')=='canvas':
            if z.get('canvas_binding_id')!='CANVAS' or z.get('panel_id') is not None:error('canvas_text_binding',zone_id=zid)
        elif z.get('panel_id') not in ids:error('text_zone_binding',zone_id=zid)
    if len(zids)!=len(set(zids)) or any(not z for z in zids):error('duplicate_or_empty_zone_id')
    cs=data.get('constraints') or {}
    fields=['panel_count_exact','preserve_reading_order','allow_add_panels','allow_delete_panels','allow_merge_panels','allow_split_panels','allow_generic_long_box']
    required(cs,fields,'constraints')
    for f in fields:
        if cs.get(f) is not (f in ['panel_count_exact','preserve_reading_order']):error('unsafe_layout_constraint',field=f)
    required(data.get('fallback'),['policy','reason_required'],'fallback')
    required(data.get('evidence'),['panel_geometry','bubble_shape','bubble_position','tail_anchor','confidence'],'evidence')
    if (data.get('fallback') or {}).get('reason_required') is not True:error('fallback_reason_required')
    try:executable_text_containers(data)
    except Exception as exc:error('runtime_text_projection',error=str(exc))
    return errors

def check(root: Path, *, check_index: bool = False) -> dict:
    pool = root / "executable-templates"
    templates = sorted(pool.glob("SB-*.yaml"))
    errors, warnings, rows = [], [], []
    expected = {f"SB-{i:03d}" for i in range(1, 69)}
    found = {p.stem for p in templates}
    if found != expected:
        errors.append({"type": "template_set", "missing": sorted(expected-found), "extra": sorted(found-expected)})
    for path in templates:
        error_start=len(errors)
        try: data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"type":"yaml_parse","file":path.name,"error":str(exc)}); continue
        miss = sorted(REQUIRED - set(data or {}))
        if miss: errors.append({"type":"missing_top_level","file":path.name,"fields":miss})
        lid = data.get("layout_id")
        source = data.get("source") or {}
        preview_rel = source.get("preview_image")
        note_rel = source.get("source_note")
        if preview_rel and not (root / preview_rel).exists(): errors.append({"type":"missing_reference","file":path.name,"reference":preview_rel})
        if note_rel and not (root / note_rel).exists(): errors.append({"type":"missing_reference","file":path.name,"reference":note_rel})
        if source.get("visual_reference_only") is not True:
            warnings.append({"type":"visual_reference_flag","file":path.name,"message":"source.visual_reference_only should be true for bundled previews"})
        panels = data.get("panels") or []
        if not panels:
            panels = (data.get("structure") or {}).get("units") or []
        if panels:
            if not data.get("structure"):
                warnings.append({"type":"missing_structure_contract","file":path.name,"message":"annotated panels should declare structure/style details when preview matching is required"})
            if not data.get("style_contract"):
                warnings.append({"type":"missing_style_contract","file":path.name,"message":"preview style details are not executable until style_contract is annotated"})
        else:
            panels = []
        ids=[p.get("panel_id") for p in panels]; orders=[p.get("order") for p in panels]
        if len(ids) != len(set(ids)): errors.append({"type":"duplicate_panel_id","file":path.name})
        if orders and orders != list(range(1,len(orders)+1)): errors.append({"type":"reading_order","file":path.name,"orders":orders})
        for panel in panels:
            pid = panel.get("panel_id")
            bounds = panel.get("bounds")
            if not isinstance(bounds, list) or len(bounds) != 4:
                errors.append({"type":"panel_geometry","file":path.name,"panel":pid,"message":"bounds must be normalized xywh"})
            ptype = panel.get("geometry_type", "rect")
            if ptype not in GEOMETRY_TYPES:
                errors.append({"type":"geometry_type","file":path.name,"panel":pid,"value":ptype})
            if ptype in {"polygon", "approximate_polygon"} and not panel.get("polygon"):
                errors.append({"type":"missing_polygon","file":path.name,"panel":pid})
        structure = data.get("structure") or {}
        nested = structure.get("nested_units") or data.get("nested_units") or []
        nested_ids = [u.get("unit_id") for u in nested]
        if len(nested_ids) != len(set(nested_ids)):
            errors.append({"type":"duplicate_nested_unit_id","file":path.name})
        for unit in nested:
            if not unit.get("parent_id") and not unit.get("parent_panel_id"):
                errors.append({"type":"nested_parent_binding","file":path.name,"unit":unit.get("unit_id")})
            elif (unit.get("parent_id") or unit.get("parent_panel_id")) not in ids:
                errors.append({"type":"nested_parent_binding","file":path.name,"unit":unit.get("unit_id")})
        if not (data.get("preview_contract") or data.get("preview")) and panels:
            warnings.append({"type":"missing_preview_contract","file":path.name,"message":"crop/header/ROI evidence is not declared"})
        for bubble in data.get("bubbles") or []:
            if bubble.get("panel_id") not in ids: errors.append({"type":"bubble_panel_binding","file":path.name,"bubble":bubble.get("bubble_id")})
            if bubble.get("tail",{}).get("mode") in {"speaker","thought"} and not bubble.get("tail",{}).get("anchor"):
                warnings.append({"type":"unknown_tail_anchor","file":path.name,"bubble":bubble.get("bubble_id")})
            bounds=bubble.get("bounds")
            if bounds and bounds[2] >= 0.95 and any(x in (bubble.get("shape") or "").lower() for x in ("long","generic")):
                errors.append({"type":"generic_full_width_box","file":path.name,"bubble":bubble.get("bubble_id")})
        ev=data.get("evidence",{})
        if data.get("source",{}).get("annotation_status") == "pending_visual_annotation" and not data.get("missing_fields"):
            errors.append({"type":"unmarked_unknown","file":path.name})
        # A template can be structurally valid but not executable until its
        # preview has been annotated. Keep that distinction in the index.
        executable = bool(panels) and not source.get("annotation_status", "").startswith("pending")
        deep_errors=_deep_check(data,path,root);errors.extend(deep_errors)
        rows.append({"layout_id":lid,"yaml":True,"panel_id_unique":len(ids)==len(set(ids)),"reading_order_continuous":not orders or orders==list(range(1,len(orders)+1)),"bubble_bindings_valid":all(b.get("panel_id") in ids for b in data.get("bubbles") or []),"missing_fields":data.get("missing_fields",[]),"confidence":ev.get("confidence"),"executable":executable and not deep_errors,"match_policies":(["adapted"] if not executable else ["structure_exact","pixel_reference","adapted"]),
            'template_path':'executable-templates/'+path.name,'preview_path':preview_rel,'panel_count':len(panels),'bubble_count':len(data.get('bubbles') or []),'text_zone_count':sum(z.get('executable') is True for z in data.get('text_zones',[])),
            'annotation_status':source.get('annotation_status'),'review_status':data.get('review_status'),
            'annotation_complete':executable and len(errors)==error_start and not data.get('missing_fields'),
            'full_template_execution':'not_tested','real_image_validation_status':data.get('actual_art_validation_status','not_proven_by_this_check')})
    if check_index:
        try:
            index=yaml.safe_load((root/'template-index.yaml').read_text(encoding='utf8'))
            entries=index.get('templates',[]) if isinstance(index,dict) else index
            by_id={r.get('layout_id'):r for r in entries}
            if set(by_id)!=expected:errors.append({'type':'index_template_set'})
            for row in rows:
                for field in ['template_path','preview_path','panel_count','bubble_count','annotation_status','missing_fields','confidence','review_status']:
                    if by_id.get(row['layout_id'],{}).get(field)!=row[field]:errors.append({'type':'index_mismatch','layout_id':row['layout_id'],'field':field})
        except Exception as exc:errors.append({'type':'index_unreadable','error':str(exc)})
    return {"expected_count":68,"template_count":len(templates),"completed_count":sum(r['annotation_complete'] for r in rows),"needs_review_count":sum('pending' in str(r.get('review_status')) for r in rows),"missing_preview_count":sum(1 for i in range(1,69) if not (root/f"previews/SB-{i:03d}.webp").exists()),"errors":errors,"warnings":warnings,"rows":rows,'scope':'source annotation and schema only; generated-image conformity is not implied'}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,required=True); ap.add_argument("--output",type=Path,required=True);ap.add_argument('--check-index',action='store_true'); a=ap.parse_args()
    result=check(a.root,check_index=a.check_index); a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(json.dumps({k:result[k] for k in ("expected_count","template_count","completed_count","needs_review_count","missing_preview_count","errors","warnings")},ensure_ascii=False,indent=2)); raise SystemExit(1 if result["errors"] else 0)
if __name__ == "__main__": main()
