"""Compile an explicitly approved 3:4 adaptation without rewriting the SB source.

Instruction headers are excluded. Artwork is scaled uniformly; panel clipping
and any same-panel bubble translation/resize are recorded as adaptations.
"""
from __future__ import annotations
import argparse, copy, json, math
from pathlib import Path
import yaml


def _clip_polygon(points, width, height):
    points=[list(p) for p in points]
    for axis, limit, lower in [(0,0,True),(0,width,False),(1,0,True),(1,height,False)]:
        output=[]
        for a,b in zip(points,points[1:]+points[:1]):
            ai=a[axis]>=limit if lower else a[axis]<=limit
            bi=b[axis]>=limit if lower else b[axis]<=limit
            if ai: output.append(a)
            if ai!=bi:
                t=(limit-a[axis])/(b[axis]-a[axis])
                output.append([a[0]+t*(b[0]-a[0]),a[1]+t*(b[1]-a[1])])
        points=output
        if not points: break
    return points


def compile_adapted_template(template, width=1080, height=1440, *, approved=False):
    if not approved: raise ValueError('3:4 cropping and readable bubble adaptation require explicit user selection')
    reference=template.get('preview_contract') or {}
    sw,sh=reference['source_size']; rx,ry,rw,rh=reference['content_roi']
    scale=max(width/(rw*sw),height/(rh*sh))
    left=rx*sw*scale+(rw*sw*scale-width)/2
    after=(rh*sh*scale-height)/2
    transform={'type':'uniform_scale_cover','source_canvas':[sw,sh], 'scale':scale,
        'crop_left_px':left,'crop_top_px':ry*sh,'crop_top_after_resize_px':after,
        'fill_target_canvas':[width,height],'preserve_aspect_ratio':True,
        'source_roi_normalized':[rx,ry,rw,rh], 'user_approved_adaptation':True,
        'authorization':'User selected 3:4 full-bleed and explicit adaptation labels in this session.'}
    def point(p): return [p[0]*sw*scale-left,(p[1]*sh-ry*sh)*scale-after]
    def rect(b):
        x,y=point(b[:2]); return [x,y,b[2]*sw*scale,b[3]*sh*scale]
    def norm(b): return [round(b[0]/width,8),round(b[1]/height,8),round(b[2]/width,8),round(b[3]/height,8)]
    def norm_points(p):return [[round(x/width,8),round(y/height,8)] for x,y in p]
    def clipped(b):
        x,y,w,h=b; a=max(0,x); c=min(width,x+w); z=max(0,y); d=min(height,y+h)
        if c<=a or d<=z: raise ValueError('adaptation would delete a declared panel')
        return [a,z,c-a,d-z]
    target=copy.deepcopy(template); changes=[]; panel_px={}
    panel_px['CANVAS']=[0,0,width,height]
    for p in target['panels']:
        source=rect(p['bounds']); actual=clipped(source)
        p['source_bounds']=copy.deepcopy(p['bounds']); p['bounds']=norm(actual); panel_px[p['panel_id']]=actual
        if p.get('geometry_type')=='ellipse' and source!=actual:
            x,y,w,h=source
            samples=[[x+w/2+w/2*math.cos(t*math.tau/96),y+h/2+h/2*math.sin(t*math.tau/96)] for t in range(96)]
            p['polygon']=norm_points(_clip_polygon(samples,width,height))
            p['geometry_type']='approximate_polygon'
            changes.append({'kind':'ellipse_clipped_to_polygon','panel_id':p['panel_id'],'evidence':'workflow_adaptation'})
        elif p.get('polygon'): p['polygon']=norm_points(_clip_polygon([point(q) for q in p['polygon']],width,height))
        if any(abs(a-b)>1e-6 for a,b in zip(source,actual)): changes.append({'kind':'panel_clipped','panel_id':p['panel_id'],'source_mapped_xywh':source,'target_xywh':actual,'evidence':'workflow_adaptation'})
    containers=list(target.get('bubbles',[]))+[z for z in target.get('text_zones',[]) if z.get('executable') is True]
    for b in containers:
        original=rect(b['bounds']); body=list(original)
        polygons={}
        if b.get('polygon'): polygons['body']=[point(p) for p in b['polygon']]
        if (b.get('tail') or {}).get('polygon'): polygons['tail']=[point(p) for p in b['tail']['polygon']]
        dots=[]
        for dot in (b.get('tail') or {}).get('dots',[]):
            dots.append(rect(dot['bounds'] if isinstance(dot,dict) else dot))
        anchor=point(b['tail']['anchor']) if isinstance((b.get('tail') or {}).get('anchor'),list) else None
        xs=[body[0],body[0]+body[2]]; ys=[body[1],body[1]+body[3]]
        for ps in polygons.values():xs.extend(p[0] for p in ps);ys.extend(p[1] for p in ps)
        for dx,dy,dw,dh in dots:xs.extend([dx,dx+dw]);ys.extend([dy,dy+dh])
        if anchor:xs.append(anchor[0]);ys.append(anchor[1])
        gx,gy,gw,gh=min(xs),min(ys),max(xs)-min(xs),max(ys)-min(ys)
        binding='CANVAS' if b.get('scope')=='canvas' or b.get('canvas_binding_id')=='CANVAS' or b.get('cross_panel_allowed') is True else b.get('panel_id')
        px,py,pw,ph=panel_px[binding]; margin=10
        sx=min(1,(pw-2*margin)/gw); sy=min(1,(ph-2*margin)/gh)
        tx=max(px+margin,min(gx,px+pw-margin-gw*sx)); ty=max(py+margin,min(gy,py+ph-margin-gh*sy))
        def local(p):return [tx+(p[0]-gx)*sx,ty+(p[1]-gy)*sy]
        bx,by=local(body[:2]); body=[bx,by,body[2]*sx,body[3]*sy]
        b['source_bounds']=copy.deepcopy(b['bounds']); b['bounds']=norm(body)
        if 'body' in polygons:b['polygon']=norm_points([local(p) for p in polygons['body']])
        if 'tail' in polygons:
            b['tail']['polygon']=norm_points([local(p) for p in polygons['tail']]); b['tail']['coordinate_space']='template_normalized'
        if anchor:b['tail']['anchor']=norm_points([local(anchor)])[0]
        if dots:
            b['tail']['dots']=[norm([*local(d[:2]),d[2]*sx,d[3]*sy]) for d in dots]
            b['tail']['coordinate_space']='template_normalized'
        for zone in b.get('typography_regions',[]):
            zx,zy,zw,zh=rect(zone['bounds']); zx,zy=local([zx,zy])
            zone['bounds']=norm([zx,zy,zw*sx,zh*sy])
            zone['coordinate_space']='template_normalized'
            # Hand-traced source envelopes have a declared few-pixel
            # precision. Expand the adapted text-only body to encompass its
            # explicitly observed line regions; never loosen containment.
            ox,oy,ow,oh=body
            body=[min(ox,zx),min(oy,zy),max(ox+ow,zx+zw*sx)-min(ox,zx),max(oy+oh,zy+zh*sy)-min(oy,zy)]
        b['bounds']=norm(body)
        if isinstance(b.get('visual_style'),dict) and anchor:b['visual_style']['tail_anchor']=b['tail']['anchor']
        if any(abs(a-c)>.01 for a,c in zip(original,body)):
            changes.append({'kind':'text_container_fit','bubble_id':b.get('bubble_id') or b.get('zone_id'),'panel_id':binding,
                            'source_mapped_xywh':original,'target_xywh':body,'evidence':'workflow_adaptation'})
        b['target_geometry_evidence']='workflow_adaptation'
    structure=target.get('structure') or {}
    for segment in structure.get('frame_segments',[]):
        segment['points']=norm_points([point(p) for p in segment['points']])
        segment['target_geometry_evidence']='workflow_adaptation'
    if (structure.get('shared_canvas_art') or {}).get('bounds'):
        structure['shared_canvas_art']['bounds']=norm(rect(structure['shared_canvas_art']['bounds']))
    structure.update(units=[dict(p,unit_id=p['panel_id']) for p in target['panels']],nested_units=[])
    target['structure']=structure
    # Preserve authored page lettering and required overlays; never replace
    # them with extra panels or silently remove special structural effects.
    target['text_zones']=[z for z in target.get('text_zones',[]) if z.get('executable') is True]
    for overlay in target.get('overlays',[]):
        if overlay.get('bounds'):overlay['bounds']=norm(rect(overlay['bounds']))
        if overlay.get('polygon'):overlay['polygon']=norm_points([point(p) for p in overlay['polygon']])
        if overlay.get('points'):overlay['points']=norm_points([point(p) for p in overlay['points']])
        overlay['target_geometry_evidence']='workflow_adaptation'
    target['canvas']={'aspect_ratio':'3:4','width':width,'height':height,'coordinate_system':'normalized_xywh_0_to_1 (x,y,width,height)'}
    target.update(match_policy='adapted',user_approved_adaptation=True,canvas_transform=transform,
                  source_target_deviation=changes,source_reference_geometry_match='failed',
                  execution_target='approved_3_4_full_bleed_adaptation', source_preview_size=[sw,sh])
    target['preview_contract']['source_size']=[width,height]
    target['preview_contract']['content_roi']=[0,0,1,1]
    return target,transform


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--template',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True)
    ap.add_argument('--user-approved-adaptation',action='store_true');args=ap.parse_args()
    source=yaml.safe_load(args.template.read_text(encoding='utf8'))
    target,transform=compile_adapted_template(source,approved=args.user_approved_adaptation)
    target['source_template_path']=str(args.template.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(yaml.safe_dump(target,allow_unicode=True,sort_keys=False),encoding='utf8')
    args.manifest.parent.mkdir(parents=True,exist_ok=True);args.manifest.write_text(json.dumps({'canvas_transform':transform,'source_target_deviation':target['source_target_deviation']},ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':main()
