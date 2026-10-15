"""Resolve declared source text zones without inventing story panels or bubbles."""
from __future__ import annotations
import copy

CANVAS_BINDING = "CANVAS"

def executable_text_containers(template: dict) -> list[dict]:
    """Project explicit canvas lettering into the text renderer's contract schema.

    Source YAML keeps genuine panel-bound bubbles separate from page lettering.
    The runtime CANVAS binding is never added to panel_geometry or panel_count.
    """
    result = [copy.deepcopy(b) for b in template.get('bubbles', []) if isinstance(b, dict)]
    for zone in template.get('text_zones', []) or []:
        if not isinstance(zone, dict) or zone.get('executable') is not True:
            continue
        contract=copy.deepcopy(zone)
        zid=str(zone.get('zone_id') or zone.get('text_zone_id') or '')
        if not zid:
            raise ValueError('Executable text zone requires zone_id')
        canvas_scope=zone.get('scope')=='canvas' or zone.get('canvas_binding_id')==CANVAS_BINDING
        contract.update(bubble_id=f'TZ-{zid}',source_text_zone_id=zid,
                        source_container_kind='canvas_text_zone' if canvas_scope else 'panel_text_zone')
        if canvas_scope:
            contract.update(panel_id=CANVAS_BINDING,canvas_binding_id=CANVAS_BINDING,scope='canvas')
        if not contract.get('panel_id'):
            raise ValueError(f'Executable non-canvas text zone {zid} requires panel_id')
        contract.setdefault('tail',{'mode':'none','anchor':None,'required':False,'evidence':'observed'})
        contract.setdefault('allowed_text_types',['narration','caption','emphasis'])
        result.append(contract)
    return result

def canvas_text_binding(contract: dict) -> bool:
    return contract.get('source_container_kind')=='canvas_text_zone' and contract.get('canvas_binding_id')==CANVAS_BINDING
