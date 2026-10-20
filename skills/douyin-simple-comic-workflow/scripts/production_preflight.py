#!/usr/bin/env python3
"""Prepare a whole comic batch offline: coverage, complete proofs and scene requests.

This command generates diagnostic layout proofs, never story artwork. Cached
library/geometry capabilities never stand in for new text or real-image checks.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import time
from pathlib import Path

import PIL
import yaml
from PIL import Image, ImageDraw

from audit_preview_bubbles import audit as audit_bubbles
from audit_storyboard_rhythm import audit_decision
from check_executable_templates import check as check_library
from layout_executor import compile_template_contract, render_layout
from preflight_preview_text import preflight
from prompt_style import verify as verify_selector
from text_compositor import compose_page
from template_contract import executable_text_containers

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / 'references/comic-layouts'
VERSION = '0.9-production-page-selection'


def load(path):
    value = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'Expected mapping: {path}')
    return value


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def resolve(value, base):
    p = Path(value)
    p = (p if p.is_absolute() else base / p).resolve()
    if not p.is_file():
        raise ValueError(f'Missing input file: {p}')
    return p


def binding(path):
    return {'path': str(Path(path).resolve()), 'sha256': digest(path)}


def capabilities(cache_dir):
    """Cache library integrity only, keyed by actual code/library contents."""
    inputs = sorted(list((ROOT / 'scripts').glob('*.py')) + [ROOT / 'SKILL.md']
                    + [p for p in LIBRARY.rglob('*') if p.is_file()])
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in inputs}
    key = fingerprint({'files': hashes, 'pillow': PIL.__version__, 'yaml': yaml.__version__})
    path = cache_dir / f'capabilities-{key}.json'
    if path.exists():
        report = load(path)
        if report.get('key') == key and report.get('status') == 'passed':
            return dict(report, cache_hit=True)
    selector = verify_selector()
    checked = check_library(LIBRARY, check_index=True)
    report = {'key': key, 'status': 'passed' if not checked['errors'] else 'blocked',
              'selector': selector, 'template_count': checked['template_count'],
              'errors': checked['errors'], 'cache_hit': False,
              'scope': 'library integrity and schema; no text capacity or actual image acceptance',
              'actual_image_checked': False}
    if report['status'] == 'passed':
        write(path, report)
    return report


def coverage(manifest, plans, contracts, source, source_sha256=None):
    errors, rows = [], []
    beats = manifest.get('story_beats') or []
    ids = [b.get('beat_id') for b in beats]
    if not ids or any(not b for b in ids) or len(ids) != len(set(ids)):
        errors.append('story_beats_require_unique_nonempty_ids')
    locations = {}
    for n, page in enumerate(manifest['pages']):
        pid = page['page_id']
        panel_orders = {p['panel_id']: p['order'] for p in contracts[pid]['panel_geometry']}
        for entry in page.get('beat_bindings', []):
            beat, panel = entry.get('beat_id'), entry.get('panel_id')
            if beat not in ids or panel not in panel_orders:
                errors.append(f'{pid}: invalid_beat_panel_binding:{beat}/{panel}')
                continue
            if entry.get('presentation') not in {'visual', 'text', 'both'}:
                errors.append(f'{pid}: missing_beat_presentation:{beat}')
            locations.setdefault(beat, []).append((n, panel_orders[panel], pid, panel))
        for block in plans[pid].get('text_blocks', []):
            span = block.get('source_article_range')
            text = block.get('text', '')
            if span is None:
                errors.append(f'{pid}/{block.get("id")}: missing_source_article_range')
            elif not valid_span(span, source) or source[span[0]:span[1]] != text:
                errors.append(f'{pid}/{block.get("id")}: source_excerpt_mismatch')
    last = (-1, -1)
    for beat in beats:
        bid, span = beat.get('beat_id'), beat.get('source_range')
        if not valid_span(span, source):
            errors.append(f'{bid}: invalid_source_range')
        found = sorted(locations.get(bid, []))
        if beat.get('required', True) and not found:
            errors.append(f'{bid}: uncovered_required_beat')
        if found:
            position = found[0][:2]
            if position < last:
                errors.append(f'{bid}: declared_story_order_reversed')
            last = position
        required_texts = beat.get('required_texts', [])
        bound_panels = {(x[2], x[3]) for x in found}
        beat_blocks = [b for p in manifest['pages']
                       for b in plans[p['page_id']].get('text_blocks', [])
                       if (p['page_id'], b.get('panel_id')) in bound_panels]
        quote_coverage = set()
        for block in beat_blocks:
            bs = block.get('source_article_range')
            if valid_span(bs, source) and source[bs[0]:bs[1]] == block.get('text'):
                quote_coverage.update(range(bs[0], bs[1]))
        for text in required_texts:
            # Quotes must come from this beat's own source span and be covered
            # by its linked excerpts. Concatenating unrelated blocks can
            # otherwise accidentally invent a supposedly verbatim quotation.
            covered = False
            if isinstance(text, str) and text and valid_span(span, source):
                start = source.find(text, span[0], span[1])
                while start >= 0:
                    if all(i in quote_coverage for i in range(start, start + len(text))):
                        covered = True
                        break
                    start = source.find(text, start + 1, span[1])
            if not covered:
                errors.append(f'{bid}: missing_required_verbatim_text')
        rows.append({'beat_id': bid, 'required': beat.get('required', True),
                     'source_range': span, 'bindings': [{'page_id': x[2], 'panel_id': x[3]} for x in found]})
    policy = manifest.get('text_policy', 'excerpts')
    if policy not in {'excerpts', 'verbatim'}:
        errors.append('unknown_text_policy')
    if policy == 'verbatim':
        span = manifest.get('source_content_range', [0, len(source)])
        if not valid_span(span, source):
            errors.append('invalid_source_content_range')
        else:
            covered = set()
            for plan in plans.values():
                for block in plan.get('text_blocks', []):
                    bs = block.get('source_article_range')
                    if valid_span(bs, source):
                        covered.update(range(bs[0], bs[1]))
            missing = [i for i in range(span[0], span[1]) if not source[i].isspace() and i not in covered]
            if missing:
                errors.append(f'verbatim_source_characters_missing:{len(missing)}')
    return {'status': 'passed' if not errors else 'blocked', 'errors': errors,
            'source_sha256': source_sha256 or hashlib.sha256(source.encode('utf-8')).hexdigest(),
            'beats': rows, 'text_policy': manifest.get('text_policy', 'excerpts'),
            'semantic_visual_coverage': 'pending_actual_image_review',
            'scope': 'declared beat coverage, narrative order and exact linked excerpts; no automatic semantic recognition'}


def valid_span(span, text):
    return (isinstance(span, list) and len(span) == 2
            and all(isinstance(x, int) and not isinstance(x, bool) for x in span)
            and 0 <= span[0] < span[1] <= len(text))


def scene_zones(unit, capacity_rows, plan):
    """Project page text areas into the exact unit; never default to page width."""
    x, y, w, h = [unit[k] for k in ('x', 'y', 'width', 'height')]
    blocks = {b['id']: b for b in plan.get('text_blocks', [])}
    result = []
    for row in capacity_rows:
        bounds = row.get('target_bounds_xywh')
        block = blocks[row['block_id']]
        bc = block.get('bubble_contract') or {}
        canvas_scope = bc.get('canvas_binding_id') == 'CANVAS'
        if row['panel_id'] != unit['panel_id'] and not canvas_scope and not bc.get('cross_panel_allowed'):
            continue
        if not bounds:
            continue
        bx, by, bw, bh = bounds
        left, top, right, bottom = max(x, bx), max(y, by), min(x+w, bx+bw), min(y+h, by+bh)
        if left >= right or top >= bottom:
            continue
        style = bc.get('visual_style') or {}
        unboxed = style.get('renderer') in {'preview_display', 'preview_brush', 'preview_vertical'} or bc.get('shape') in {'display_text', 'brush_text', 'unboxed_text'}
        ink = str(style.get('text_color') or block.get('font_color') or 'black').lower().strip()
        white_ink = ink in {'white', '#fff', '#ffffff', 'rgb(255,255,255)'}
        native_alpha = unboxed and unit.get('geometry_type') == 'unframed' and not white_ink
        background = ('quiet_dark_low_detail' if unboxed and white_ink else
                      'native_transparent_alpha' if native_alpha else 'quiet_light_low_detail')
        result.append({'bubble_id': row['bubble_id'], 'panel_id': row['panel_id'],
                       'bounds_page_px': bounds,
                       'bounds_unit_normalized_xywh': [round(v, 6) for v in ((left-x)/w, (top-y)/h, (right-left)/w, (bottom-top)/h)],
                       'shape': bc.get('shape'), 'renderer': style.get('renderer'),
                       'background_requirement': background, 'text_ink_color': ink,
                       'exclude': ['faces', 'hands', 'key_props', 'background_lines', 'lettering'],
                       'policy_origin': 'workflow_production_reservation_not_original_SB_rule',
                       'actual_image_checked': False})
    return result


def prepare(manifest_path, output, cache_dir=None, diagnostic=False):
    started = time.monotonic()
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output must be a new empty preparation directory; preserve previous proofs')
    output.mkdir(parents=True, exist_ok=True)
    base = manifest_path.parent
    manifest = load(manifest_path)
    if manifest.get('diagnostic_test_only') is True and not diagnostic:
        raise ValueError('Diagnostic/partial preparation requires --diagnostic')
    if diagnostic and manifest.get('diagnostic_test_only') is not True:
        raise ValueError('--diagnostic requires diagnostic_test_only: true')
    pages = manifest.get('pages') or []
    page_ids = [p.get('page_id') for p in pages]
    if not pages or len(page_ids) != len(set(page_ids)) or any(not isinstance(p, str) or not re.fullmatch(r'P\d{2,}', p) for p in page_ids):
        raise ValueError('Pages require unique P## IDs')
    source_path = resolve(manifest['source_path'], base)
    source = source_path.read_text(encoding='utf-8')
    decision_path = resolve(manifest['storyboard_decision_path'], base)
    decision = load(decision_path)
    if decision.get('selected_by') != 'douyin-simple-comic-workflow' or decision.get('internal_layout_pool') != 68:
        raise ValueError('Storyboard handoff must come from the bundled 68-layout selector')
    decision_pages = {p['page_id']: p for p in decision.get('pages', [])}
    decision_ids = [p['page_id'] for p in decision.get('pages', [])]
    if len(decision_ids) != len(set(decision_ids)):
        raise ValueError('Storyboard handoff contains duplicate pages')
    if not diagnostic and page_ids != decision_ids:
        raise ValueError('Production page IDs/order must cover the complete storyboard handoff; partial tests require explicit diagnostic mode')
    rhythm_path = output / 'storyboard-rhythm-audit.json'
    if not diagnostic:
        rhythm = audit_decision(decision, library_root=LIBRARY)
        rhythm['decision_binding'] = binding(decision_path)
        write(rhythm_path, rhythm)
        if rhythm['status'] != 'passed':
            summary = {'status': 'blocked', 'generation_ready': False,
                       'errors': rhythm['errors'], 'storyboard_rhythm': rhythm,
                       'images_generated': False, 'actual_image_checked': False}
            write(output / 'summary.json', summary)
            return summary
    if not diagnostic:
        declared_beats = {b.get('beat_id') for b in manifest.get('story_beats', [])}
        for page in pages:
            beat = decision_pages[page['page_id']].get('story_beat_id')
            if beat and (beat not in declared_beats or beat not in {b.get('beat_id') for b in page.get('beat_bindings', [])}):
                raise ValueError(f'{page["page_id"]}: primary storyboard beat is missing from content coverage')
    caps = capabilities(Path(cache_dir).resolve() if cache_dir else output.parent / '.production-cache')
    write(output / 'capabilities.json', caps)
    if caps['status'] != 'passed':
        raise ValueError('Bundled library integrity failed')
    plans, contracts, inputs = {}, {}, {}
    for page in pages:
        pid = page['page_id']
        template_path = resolve(page['template_path'], base)
        plan_path = resolve(page['text_plan_path'], base)
        config_path = resolve(page['text_layout_path'], base)
        template, plan, config = load(template_path), load(plan_path), load(config_path)
        contract = compile_template_contract(template)
        handoff = decision_pages.get(pid, {})
        if handoff.get('layout_id') != template.get('layout_id') or handoff.get('panel_count') != len(contract['panel_geometry']):
            raise ValueError(f'{pid}: target disagrees with bundled storyboard handoff')
        if plan.get('page_id') != pid or plan.get('layout_id') != template.get('layout_id'):
            raise ValueError(f'{pid}: text plan/template binding mismatch')
        if plan.get('match_policy') == 'adapted' and not plan.get('user_approved_adaptation'):
            raise ValueError(f'{pid}: adaptation must be explicitly approved')
        if any(contract['generator_constraints'].get(k) for k in ('allow_add_panels', 'allow_delete_panels', 'allow_merge_panels', 'allow_split_panels')):
            raise ValueError(f'{pid}: panel changes are prohibited after SB selection')
        plans[pid], contracts[pid] = plan, contract
        inputs[pid] = (template_path, plan_path, config_path, template, config)
    story = coverage(manifest, plans, contracts, source, digest(source_path))
    story.update(expected_page_ids=page_ids, storyboard_binding=binding(decision_path),
                 diagnostic_test_only=diagnostic)
    write(output / 'content-coverage.json', story)
    if story['status'] != 'passed':
        return {'status': 'blocked', 'generation_ready': False, 'errors': story['errors'], 'images_generated': False}
    requests, rows = [], []
    for page in pages:
        pid = page['page_id']
        folder = output / pid
        folder.mkdir()
        template_path, plan_path, config_path, template, config = inputs[pid]
        plan = copy.deepcopy(plans[pid])
        plan.update(synthetic=True, synthetic_input=True, actual_image_checked=False,
                    validation_scope='synthetic_complete_text_proof_not_actual_story_ownership')
        by_bubble = {b['bubble_id']: b for b in executable_text_containers(template)}
        for block in plan.get('text_blocks', []):
            block['synthetic_input'] = True
            if block.get('bubble_id') in by_bubble:
                block.setdefault('bubble_contract', copy.deepcopy(by_bubble[block['bubble_id']]))
        check = preflight(template, plan, config, config_path.parent)
        write(folder / 'text-preflight.json', check)
        dependency_paths = [source_path, decision_path, template_path, plan_path, config_path, ROOT/'SKILL.md']
        if not diagnostic:
            dependency_paths.append(rhythm_path)
        dependency_paths += sorted((ROOT/'scripts').glob('*.py'))
        dependency_paths += [LIBRARY/'layouts.json', LIBRARY/'template-index.yaml',
                             LIBRARY/'bubble-constraints.yaml', LIBRARY/'bubble-execution-profiles.yaml',
                             LIBRARY/f'executable-templates/{template["layout_id"]}.yaml']
        for name in ('font_file', 'brush_font_file'):
            if config.get(name):
                dependency_paths.append(resolve(config[name], config_path.parent))
        dependency_paths.append(resolve(str(LIBRARY/template['source']['preview_image']), base))
        readiness = {'page_id': pid, 'generation_ready': False, 'synthetic_input': True,
                     'diagnostic_test_only': diagnostic,
                     'actual_image_checked': False, 'images_generated': False,
                     'input_bindings': [binding(p) for p in dict.fromkeys(dependency_paths)],
                     'capability_key': caps['key'], 'errors': list(check['errors'])}
        if not diagnostic:
            readiness['storyboard_rhythm_binding'] = binding(rhythm_path)
        if check['generation_ready']:
            proof_base = folder / 'proof-base.png'
            # A neutral diagnostic interior reveals both white and black ink.
            # A white scaffold would falsely reject valid white brush text.
            diagnostic_assets = {}
            for unit in contracts[pid]['panel_geometry'] + contracts[pid].get('nested_units', []):
                asset = Image.new('RGBA', (160, 160), (205, 205, 205, 255))
                if unit.get('alpha_required'):
                    alpha = Image.new('L', asset.size, 0)
                    ImageDraw.Draw(alpha).ellipse((8, 8, 152, 152), fill=255)
                    asset.putalpha(alpha)
                ap = folder / f'{unit["unit_id"]}-diagnostic.png'
                asset.save(ap)
                diagnostic_assets[unit['unit_id']] = str(ap)
            render_layout(template, proof_base, assets=diagnostic_assets)
            proof_plan = folder / 'proof-plan.json'
            write(proof_plan, plan)
            proof_image, render_path = folder/'proof-text.png', folder/'proof-render.yaml'
            report = compose_page(proof_base, proof_plan, config_path, proof_image, render_path, folder/'proof-placement.yaml', pid)
            bubbles = audit_bubbles(template, plan, render_report=report, report_dir=folder)
            bubble_path = folder / 'proof-bubble-audit.json'
            write(bubble_path, bubbles)
            accepted = (report['page_acceptance_status'] == 'accepted'
                        and bubbles['execution_bubble_match'] == 'passed')
            readiness['generation_ready'] = accepted
            readiness['complete_proof'] = {'accepted': accepted, 'render_report_path': str(render_path),
                                           'render_report_sha256': digest(render_path), 'image_path': str(proof_image),
                                           'image_sha256': digest(proof_image), 'bubble_audit_path': str(bubble_path),
                                           'bubble_audit_sha256': digest(bubble_path)}
            if not accepted:
                readiness['errors'].append('complete_text_render_or_bubble_audit_blocked')
        readiness_path = folder / 'generation-readiness.json'
        write(readiness_path, readiness)
        rows.append({'page_id': pid, 'generation_ready': readiness['generation_ready'], 'errors': readiness['errors']})
        if not readiness['generation_ready']:
            continue
        units = contracts[pid]['panel_geometry'] + contracts[pid].get('nested_units', [])
        declared_assets = page.get('assets', [])
        descriptions = {j['unit_id']: j for j in declared_assets}
        if len(descriptions) != len(declared_assets):
            raise ValueError(f'{pid}: duplicate asset unit_id')
        expected = {u['unit_id'] for u in units if u.get('geometry_type') != 'phone_column'}
        if set(descriptions) != expected:
            raise ValueError(f'{pid}: asset descriptions must cover exact declared render units {sorted(expected)}')
        jobs = []
        for unit in units:
            if unit['unit_id'] not in descriptions:
                continue
            desc = descriptions[unit['unit_id']]
            if not isinstance(desc.get('scene_prompt'), str) or not desc['scene_prompt'].strip():
                raise ValueError(f'{pid}/{unit["unit_id"]}: missing scene prompt')
            refs = list(dict.fromkeys(resolve(p, base) for p in manifest.get('shared_reference_paths', []) + desc.get('reference_paths', [])))
            preview = LIBRARY / template['source']['preview_image']
            if preview.resolve() not in refs:
                refs.append(resolve(str(preview), base))
            zones = scene_zones(unit, check['blocks'], plan)
            prompt = (manifest.get('style_prompt', '') + '\n' + desc['scene_prompt']
                      + '\nContinuity contract: ' + json.dumps(manifest.get('continuity_contract', {}), ensure_ascii=False)
                      + '\nGenerate this single scene only. The executor owns final panel borders and placement. '
                      'No text, letters, bubble outlines, extra panels, inset panels or collage. '
                      'Keep the declared text regions free of faces, hands and key props. '
                      'Quiet regions belong inside this scene; do not add a page header or top explanatory margin. '
                      'For native_transparent_alpha regions use genuine alpha, never painted white rectangles or checkerboards. '
                      'Fit uniformly with cover, never stretch; actual crop and text space require later image checks.\n'
                      + json.dumps({'unit_id': unit['unit_id'], 'target_page_panel_geometry': unit,
                                    'page_reading_order': contracts[pid]['reading_order'], 'reserved_text_zones': zones}, ensure_ascii=False))
            request = {'prompt': prompt, 'referenced_image_paths': [str(p) for p in refs],
                       'transparent_background': bool(unit.get('alpha_required') or any(z['background_requirement'] == 'native_transparent_alpha' for z in zones))}
            jobs.append({'unit_id': unit['unit_id'], 'request': request, 'reference_paths': [str(p) for p in refs],
                         'reserved_text_zones': zones})
        requests.append({'page_id': pid, 'template_path': str(template_path),
                         'proof': {'report_path': str(readiness_path), 'sha256': digest(readiness_path)}, 'jobs': jobs})
    ready = len(requests) == len(pages)
    summary = {'status': 'passed' if ready else 'blocked', 'generation_ready': ready, 'pages': rows,
               'diagnostic_test_only': diagnostic,
               'page_count': len(pages), 'job_count': sum(len(p['jobs']) for p in requests),
               'capability_cache_hit': caps['cache_hit'], 'elapsed_seconds': round(time.monotonic()-started, 3),
               'images_generated': False, 'actual_image_checked': False, 'base_image_modified': False}
    if not diagnostic:
        summary['storyboard_rhythm_binding'] = binding(rhythm_path)
    write(output / 'summary.json', summary)
    if ready:
        write(output / 'generation-requests.json', {'schema_version': 1, 'pipeline_version': VERSION,
              'diagnostic_test_only': diagnostic, 'expected_page_ids': page_ids,
              'pilot_page_id': manifest.get('pilot_page_id', page_ids[0]), 'pages': requests,
              **({'storyboard_rhythm_binding': binding(rhythm_path)} if not diagnostic else {})})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache-dir', type=Path)
    parser.add_argument('--diagnostic', action='store_true', help='Explicitly allow a diagnostic-only partial story; never a production delivery')
    args = parser.parse_args()
    try:
        result = prepare(args.manifest, args.output, args.cache_dir, diagnostic=args.diagnostic)
    except (ValueError, KeyError, OSError) as exc:
        result = {'status': 'blocked', 'generation_ready': False, 'errors': [str(exc)], 'images_generated': False}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['generation_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
