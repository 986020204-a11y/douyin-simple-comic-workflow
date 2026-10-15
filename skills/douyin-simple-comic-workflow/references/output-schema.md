# v0.7-library-68 output schema and validation

## Complete target execution gate

All 68 source templates use their observed full-preview `canvas.width`, `canvas.height` and `canvas.aspect_ratio`. A desired delivery ratio is recorded separately as `workflow_output_preference` with inferred workflow evidence. It does not rewrite source observations. The approved adaptation compiler writes a separate 1080×1440 target snapshot and explicit deviations. Older run snapshots retain the source version they actually executed; metadata correction alone does not authorize rewriting their images.

Base layout reports retain `selected_layout`, `target_panel_count`, `actual_panel_count`, `target_panel_geometry`, `actual_panel_geometry`, `reading_order_match`, `storyboard_layout_match`, `layout_deviation`, and `base_image_modified: false`. Also report `execution_geometry_match`, `execution_style_match`, `full_template_execution`, `adapted_target_match`, and source-reference status. The full target result cannot pass while a required foreground crossing or final text effect lacks actual evidence.

The measured actual manifest links final text separately from its frozen no-text base:

```yaml
execution_style_evidence:
  text_containers:
    bubble_audit_path: /absolute/run/bubble-audit.json
    bubble_audit_sha256: <actual file digest>
    render_report_path: /absolute/run/render.yaml
    render_report_sha256: <actual file digest>
    final_image_sha256: <actual final PNG digest>
  broken_frame: # required only when the template requires foreground crossing
    method: deterministic_foreground_overlay_with_pixel_verification
    image_sha256: <frozen no-text base digest>
    before_overlay_image: /absolute/run/before-overlay.png
    before_overlay_image_sha256: <actual file digest>
    overlay_mask: /absolute/run/overlay-mask.png
    overlay_mask_sha256: <actual file digest>
    overlay_difference_sha256: <verified masked RGB difference digest>
    visible_foreground_crossing: true
    crossing_boundary: [[x1, y1], [x2, y2]] # actual executed panel edge
```

`broken_frame` may alternatively use a hash-bound `manual_visual_comparison`, with an identified reviewer, `geometry_observed_from_image: true`, and observed `visible_foreground_points` on both sides of the real panel edge. This is visual annotation with declared uncertainty, not exact segmentation. Synthetic algorithm tests are never actual artwork evidence.

## Analysis

`analysis/content-analysis.yaml` must distinguish:

- `source_facts`
- `reasonable_inferences`
- `design_additions`
- `open_questions`

It should also record theme, core events, characters/relationships, ordered beats, scenes, actions, emotion changes, turning points, visualizable content, and abstract content that needs visual metaphor.

## Bundled storyboard handoff

The storyboard is produced by this workflow's internal selector and then consumed by the same workflow. The selector reads only `references/comic-layouts/layouts.json` and bundled `SB-*.md` files:

```yaml
source_article: source/article.md
page_count: 3
panel_count: 7 # compatibility alias for the planned storyboard total
planned_story_units: 7
planned_panel_count: 7
visible_panel_count: null # filled only after final-base visual audit
panel_count_delta: null # visible_panel_count - planned_panel_count
panel_count_reconciliation: null # sources, per-page counts, explanation, and release status
selected_by: douyin-simple-comic-workflow
internal_layout_pool: 68
storyboard_handoff_status: ready-for-douyin-simple-comic-workflow
pages:
  - page_id: P01
    panel_count: 2
    planned_panel_count: 2 # page planning count; same value as panel_count
    visible_panel_count: null # final-base audit value, never copied back into panel_count
    layout_id: SB-003
    layout_name: "verified bundled name"
    layout_source: bundled-internal-comic-layouts
    selection_reason: "why this real layout serves the page function"
    selected_by: douyin-simple-comic-workflow
    selector_execution:
      status: executed
      selector: scripts/prompt_style.py
      output_contains_selected_layout: true
    panels: []
```

The handoff is valid only when the internal pool contains exactly 68 `comic-storyboard` entries, every prompt file exists, `panel_count` is a positive planning integer equal to that page's `panels` length, and the selector evidence is present. `planned_panel_count` is the sum of those page planning counts; `visible_panel_count` is measured later from final base images and must not be written back into `panel_count`. Downstream page storyboards and prompts copy the planning `panel_count`, `panels`, `layout_id`, `layout_name`, `layout_source`, and `selection_reason` unchanged. If the pool or handoff is missing, invalid, or incompatible, stop before image generation instead of choosing a replacement layout.

At delivery level, `planned_story_units`, `planned_panel_count`, `visible_panel_count`, `panel_count_delta`, and `panel_count_reconciliation` are required together. A difference is allowed when the final base visibly follows the selected SB's expanded, inset, or split structure and the reconciliation records that evidence. An unexplained difference blocks publication; changing a planning number to make the totals match is invalid.

## Base image measurement evidence

Measure geometry from the actual no-text PNG after assembly. Target contract or canvas-transform copies never count as observations. Bind evidence to that PNG's SHA-256:

```yaml
measurement_evidence:
  image_sha256: "<actual base PNG hash>"
  method: manual_visual_annotation # or image_panel_detection | deterministic_render_with_pixel_verification
  geometry_observed_from_image: true
style_verification:
  image_sha256: "<same actual base PNG hash>"
  method: manual_visual_comparison
  matched: true # only after actual comparison, otherwise false
```

`actual_panel_geometry` and actual reading order accompany this evidence. `scripts/audit_storyboard_layout.py` blocks missing or mismatched evidence; the mere presence of a template/style contract cannot pass. Keep geometry and style results separate, and preserve the base bytes.

## Page output uniqueness

`page_id` identifies one story page, not one render attempt. A default delivery manifest records exactly one final image per page:

```yaml
page_id: P10
story_beat_id: B14
candidate_image_count: 0
final_image_count: 1
generated_variants: 0
duplicate_story_check: passed
retained_final_image: P10-final.png
final_image: pages/final/P10-final.png
```

The canonical final filename is `<PAGE_ID>-final.png`. Versioned names such as `P10-final-v001.png` are legacy or candidate artifacts and must not be added to a new manifest. Retry renders belong under `pages/candidates/<PAGE_ID>/` and are excluded from the delivery list. A variant may be delivered only after the user explicitly requests variants; the run must then record that request and keep `generated_variants` explicit. Historical versioned files are not renamed retroactively by this rule.

`candidate_image_count` counts every generated attempt for the page, including the retained attempt and discarded retries. The candidate file list and discarded-file list belong in the page-uniqueness report or an internal audit record, not in the delivery list. A historical versioned file may be recorded there during a read-only audit, but it must never be copied into the delivery list under its versioned name.

`scripts/check_page_uniqueness.py` validates the invariant, checks that a page is not listed more than once, and reports versioned files left in an old `pages/final/` directory. It also compares `story_beat_id` values across pages and adjacent panel metadata (`action`/`visual_action`, `expression`/`emotion`, `key_objects`/`props`, and `camera_function`/`camera`/`shot`). Repeated story beats or identical adjacent visual signatures produce `duplicate_story_check: needs_review`; they do not silently create another final PNG. Multiple visible panels expanded by one SB still belong to the same page final.
## Character cards

Each card needs `character_id`, `display_name`, `story_role`, relationships, source/inference/design/open-question sections, `age_version`, appearance, provisional wardrobe, identifying features, emotional states, important props, `reference_asset_status`, `turnaround_status`, `approval_status`, and actual reference paths. `reference_asset_status: generated` is valid only after a file exists; `approval_status: not-reviewed` remains until a person approves it.

## Page prompt additions

Beyond the storyboard fields, a page prompt should include:

```yaml
canvas: {aspect_ratio: '3:4', width: 1080, height: 1440}
reference_assets: []
reference_input_policy:
  mode: actual-image-input
  path_registration_is_not_image_input: true
  if_reference_unavailable: stop-before-generation
characters: []
wardrobe_versions: []
scene: ""
time: ""
panel_structure:
  panel_count: 3
  planned_panel_count: 3 # storyboard planning value; do not replace with visible count
  visible_panel_count: null # optional until final-base audit
  layout_id: SB-000
  layout_name: "verified name"
  reading_order: "..."
  panels: []
dialogue_text: []
narration_text: []
note_text: []
text_placement: []
text_blocks: [] # linked source entries; select style once and compose each block once
image_prompt: "describe visual construction, not long Chinese prose"
negative_prompt: []
prompt_status: draft
render_status: not-generated
final_status: not-generated
check_status: not-checked
```

## Text blocks v0.2-draft

Legacy page plans carry `layout_id` and the compositor resolves that ID through
`references/comic-layouts/bubble-constraints.yaml` plus the paired
`references/comic-layouts/bubble-execution-profiles.yaml`. The source map has one
profile per bundled SB and distinguishes source evidence (`source_rule_level`)
from workflow additions (`adaptation_rule`). Execution profiles expose the
required fields `bubble_style`, `bubble_bounds` or `allowed_zone`, `max_width`,
`tail_anchor`, `speaker_direction`, `text_type`, and `fallback`. A preview/source
profile is always marked `visual_reference_only: true`; this does not claim that
an SB image contains executable geometry. For preview-matching runs, the annotated
executable template below takes precedence over this compatibility profile.

New storyboards, page prompts, and text-composition plans carry the same `text_blocks`. Keep accepted v0.1 pages and their legacy text arrays unchanged. A block's required fields are `id`, `type`, `speaker`, `text`, `emotional_intensity`, `bubble_style`, `anchor`, `placement_reason`, and `avoid_regions`; use the linkage and result fields below when planning selection/placement:

```yaml
text_blocks:
  - id: T01
    panel_id: P01-01
    source_field: narration_text
    source_index: 0 # zero-based index in the existing text array
    type: narration
    speaker: narrator
    text: ""
    emotional_intensity: neutral
    bubble_style: auto # auto resolves only inside the selected SB execution profile
    anchor: auto # planning only; resolve against actual panel/carrier regions before composition
    placement_reason: ""
    avoid_regions:
      - face
      - main_action
      - key_object
    avoid_region_rects: [] # synthetic or actual panel rectangles used for collision checks
    synthetic_geometry: {} # no-image tests only; every named region has [x, y, width, height]
    carrier:
      kind: none # none | note | paper | phone_screen | other_surface
      asset_id: null
      target_region: null
    tail:
      enabled: false
      target_character: null
      target_region: null
      reason: "旁白没有人物指向尾巴"
    selection_trace: [] # selected layout/profile -> panel -> type -> speaker -> emotion -> carrier -> whitespace
    speaker_status: confirmed # confirmed | missing | unknown | narrator
    warnings: []
    fallback_reason: null
    selection_status: selected # selected | fallback | needs-placement | blocked
    rendering: post-layout
```

`type` supports `narration`, `caption`, `dialogue`, `thought`, `phone_dialogue`, `shout`, `note`, and `emphasis`. `caption` is a narration display type linked to `narration_text`, with the compatibility style `narration_box`; it does not turn narration into character dialogue. The other corresponding default `bubble_style` values are `narration_box`, `rounded_speech`, `thought_bubble`, `phone_dialogue`, `shout_burst`, `note_embedded`, and `emphasis_box`. Apply [the five-stage rule](workflow-rules.md#text-style-selection-v02-draft) rather than treating this mapping as unconditional. Use `speaker: null` when no source-confirmed speaker exists; never invent one to add a tail.

The primary content fields stay separate: narration sources use `narration_text`, note/carrier sources use `note_text`, and character utterances/thought/phone/shout may stay in `dialogue_text` with explicit type metadata. An emphasis block retains its original source field. IDs and source links prevent duplicate drawing. An `anchor` resolves to a `kind` (`whitespace`, `speaker`, or `carrier`), a panel region and, for embedded text, its carrier ID; `anchor: auto` is not a final pixel placement. `selection_status` describes rule planning, never image completion. The renderer may add `duplicate-skipped` for an exact repeated source link; it is not a second draw and is summarized by `dedupe_status`.

## Preview bubble contract v0.5

Read `executable-templates/SB-###.yaml`, its real preview, and source note. Each printable block binds to one existing `bubble_id` and that bubble's real `panel_id`; a preview with no bubbles supplies no invented dialogue zones. Keep source linkage, wording, type, and speaker unchanged. `allowed_text_types` is a compatibility check, not permission to rewrite narration as dialogue. An incompatible or unknown binding blocks strict composition.

```yaml
layout_id: SB-002
match_policy: structure_exact
bubble_selection_policy: all_template_bubbles # default; story_subset is an explicit adaptation
text_blocks:
  - id: T01
    bubble_id: B01
    panel_id: P01
    source_field: dialogue_text
    source_index: 0
    type: dialogue
    speaker: null
    text: "原文台词"
    geometry_source: bubble_contract
    use_preview_contract: true
    bubble_contract:
      shape: rounded_speech
      bounds: [x, y, width, height]
      position: upper-right
      tail: {mode: unknown, anchor: unknown}
      visual_style: {} # copy the annotated template renderer/style, not a generic default
      coordinate_space: final_canvas_px
    evidence:
      shape: observed
      bounds: observed
      position: observed
      tail_anchor: unknown
```

Template bounds use the declared coordinate system. Preserve source bounds and record the full source→target `canvas_transform` (source and target dimensions, scale, translation, crop) when resolving final pixel bounds. Never transform twice. Record clipping, movement, resizing, and missing bubbles in `layout_deviation`/`bubble_deviation`; a modified target cannot serve as proof of source-preview equality. Source geometry match, transformed-target placement, and style match are separate results. `bubble_selection_policy: story_subset` additionally requires `bubble_active_ids` and `bubble_subset_reason`; it records unused IDs and always leaves `full_bubble_structure_match: false`. Omitted bubbles cannot pass a full exact check.

Annotation evidence is per field: `observed` comes directly from a visible feature, `inferred` is a marked visual interpretation, and `unknown` stays unresolved. Workflow choices such as source-to-target scaling, readable font sizing, and avoidance regions are recorded as workflow additions. Unknown tail anchors produce no invented direction and remain unverified. Preserve source preview files.

Before scene generation, preflight source semantics, ownership, template coverage, and readable text capacity. The compiled `execution_contract.bubbles` preserves each bubble's `bounds_px`, shape/style, allowed types, and avoidance; `reserved_no_subject_zones` binds the same pixel bounds to `bubble_id`/`panel_id` and excludes faces, hands, and key props. Generation draws quiet no-text scene art there, without bubble bodies or tails. Unresolved preflight prevents generation; later composition does not repair an incompatible story/template binding.

`scripts/preflight_preview_text.py` emits `generation_ready`, `exact_ready`, `errors`, `exact_blockers`, per-block `capacity`, and input hashes. Strict requests require both structural/semantic validity and resolved exact blockers; an explicit subset or adapted policy never becomes exact-ready. `capacity_check_stage: preliminary` and `capacity_guaranteed: false` distinguish conservative font measurement from a verified rendering. The semantic check is limited to legacy source categories and explicit source metadata; it cannot validate a source array already rewritten upstream.

The render report separates requested contracts from evidence of drawing:

```yaml
bubble_id: B01
selected_panel: P01
bubble_contract_bounds: [] # requested target; never actual-geometry evidence
body_rect: [] # actual drawing result, explicit xyxy
drawn_geometry: [] # actual body/text/tail/connector drawing envelopes
actual_geometry_source: renderer_draw_operations
actual_render_verified: true | false
preview_bubble_shape_match: true | false | not-checked
preview_bubble_position_match: true | false | not-checked
preview_bubble_bounds_match: true | false | not-checked
preview_bubble_tail_match: true | false | not-checked
preview_bubble_visual_style_match: true | false | not-checked
active_bubbles_match: true | false
full_bubble_structure_match: true | false
preview_style_match: passed | failed | not-checked
bubble_deviation: []
base_image_modified: false
human_visual_review: pending
```

Run `scripts/audit_preview_bubbles.py` with both the text plan and actual render report using [the workflow invocation](workflow-rules.md#preview-bubble-contract-v05). Missing draw evidence, rejected blocks, or a required mismatch blocks an exact pass. A passing target or style audit cannot repair a failed base storyboard audit. Preserve the base bytes and write candidate outputs before review and promotion.

## Native layout proof v0.6

The selector's source-native default uses the preview's real dimensions. Only `--approved-3-4-adaptation` compiles the separate 1080×1440 content-cover target with `template_canvas.py`. A compiler result is a geometry handoff, not proof of a rendered image:

```yaml
execution_contract:
  execution_status: compiled_not_rendered
  source_template_path: /absolute/path/to/SB-###.yaml
  source_template_sha256: actual_sha256
  source_template_modified: false
  user_approved_adaptation: true
  match_policy: adapted
  canvas: {width: 1080, height: 1440, aspect_ratio: '3:4', coordinate_space: approved_target}
  resolved_template: {} # complete target; preserve separately if another CLI needs a path
  canvas_transform: {} # uniform scale, source ROI and all crop translations
  source_target_deviation: [] # panel clipping and per-bubble translation/resize
  source_reference_geometry_match: failed
  annotation_coverage: {} # actual instances and explicit decoration exclusions
  source_annotation_uncertainties: []
  bubbles: [] # every real instance, never one sample representing multiple messages
  reserved_no_subject_zones: [] # all instance bodies plus known body/tail polygons
```

Without the option, `user_approved_adaptation: false`, `canvas.coordinate_space: native_full_preview`, original width/height, unchanged normalized source geometry, and `source_reference_geometry_match: not-checked` remain explicit. For source-native compilation, an empty deviation list is not a measurement pass. Source font identity, occluded boundaries, and hand-traced polygon precision remain separately reported. Do not recategorize an inferred three-pixel contour approximation as observed pixel equality.

Proof-only plans set `synthetic: true` and `proof_binding_scope: synthetic_layout_only`; render reports retain `synthetic_input: true` and `actual_image_checked: false`. They may prove full container coverage, shape execution, readable glyph fit, and preflight validity. They cannot establish story continuity, actual speaker ownership, real-page obstacle avoidance, or production readiness. A real pilot uses actual asset hashes and measured speaker/prop/face/hand regions and clears all synthetic bindings before acceptance. A quotation in a technical messaging specimen does not imply a new story event.

Known tails retain their measured polygon and primary tip:

```yaml
bubble_contract:
  shape: rounded_rect # ellipse | polygon | display_text as appropriate
  bounds: [] # body only, final pixel xywh; tail tip is separate
  polygon: [] # body vertices where applicable
  coordinate_space: final_canvas_px
  tail:
    mode: observed_polygon
    polygon: []
    anchor: [x, y]
    coordinate_space: final_canvas_px
    anchor_kind: speaker # prop | chat_ui_nib
    speaker_binding_required: true
    required: true
speaker: actual_character_id
speaker_status: confirmed
speaker_panel_id: P01
speaker_region_visibility: confirmed
speaker_region: [x, y, width, height]
speaker_region_format: xywh
```

For `anchor_kind: prop`, replace speaker binding with `prop_id`, `prop_status: confirmed`, `prop_panel_id`, `prop_region`, and `prop_region_format`; semantic type may remain `caption` linked to narration. For `chat_ui_nib`, require `type: phone_dialogue`, a messaging `channel`, `phone_screen_status: confirmed`, `phone_screen_panel_id`, `phone_screen_region`, and `phone_screen_region_format`. An onsite speaker region is irrelevant to this UI-only nib. Actual tail evidence records all vertices, tip, binding kind/ID/panel, and pixel change in the visible polygon after subtracting the body; generic triangles and copied contract tails cannot pass this check.

The bundled brush font config is:

```yaml
brush_font_file: /absolute/skill/path/assets/fonts/mashanzheng/MaShanZheng-Regular.ttf
brush_font_verification:
  status: verified
  family_class: brush_calligraphy
  expected_family: Ma Shan Zheng
  sha256: 6d2546bb189c732a8ca29af9e22457b152387d158aa459e4ac2ce1e51788b7fb
  evidence: /absolute/run/path/to/inspected-font-specimen.png
```

Use the actual font bytes' current hash and a real inspected specimen, not a nonexistent evidence path. The companion `assets/fonts/mashanzheng/OFL.txt` records the license. Report the loaded family/hash and `preview_font_pixel_match: unverified`; a verified selected brush family is not the unknown source font's exact reproduction.

## Formal text compositor

The reusable entry point is `scripts/text_compositor.py`. It accepts an existing base PNG, a YAML file containing linked `text_blocks`, and the project's `config/text-layout.yaml`; it writes a new PNG, a render report, and a placement report. The CLI parameters are `--base-image`, `--text-blocks`, `--text-layout`, `--output-image`, `--render-report`, `--placement-report`, and optional `--page-id`. The importable function is `compose_page()`.

The compositor reads `layout_id`, validates the bundled index/description/map pool, and loads the compatibility profile. Preview-bound blocks additionally load the executable template's `bubble_id` contract, which takes precedence for its annotated shape, geometry, and style. It retains the seven legacy styles and supports preview-native rounded speech, caption, impact burst, phone message, brush display, vertical note, and caption note renderers. `bubble_style: auto` is resolved only inside the permitted contract/profile; it cannot default directly to an ordinary long box. Any declared finite fallback records `fallback_used`, `fallback_reason`, and `render_source: fallback`; strict preview matching still fails when fallback deviates from its contract. An optional per-block `font_size` may be fitted to the known region without letting glyphs escape or becoming unreadable. Missing carrier or unsafe geometry remains blocked. Shapes and visible connectors are painted behind glyphs, with actual drawing geometry and safety checks reported. The base is never overwritten.

Formal render reports additionally record:

```yaml
selected_layout: SB-###
selected_panel: P##-##
bubble_profile_id: SB-###-bubble-execution-v1
bubble_style_requested: auto
bubble_style_resolved: rounded_speech
bubble_bounds: [x0, y0, x1, y1]
bubble_bounds_format: xyxy
allowed_zone: {}
tail_anchor: [x0, y0, x1, y1] | null
tail_anchor_format: xyxy | null
fallback_used: false
fallback_reason: null
render_source: layout_profile | text_type_rule | fallback
selection_trace: []        # selected layout/profile -> panel -> type -> speaker -> emotional_intensity -> carrier -> whitespace_avoidance
layout_map_validation: {}  # exact 68-SB index/description/adapter/execution integrity result
coordinate_adapter: semantic-prefix | none
drawn_geometry: []         # text, shape, visible tail, thought_connector, or carrier rectangles
dedupe_status: clean | deduped | blocked
    page_acceptance_status: accepted | blocked
    geometry_safety: {text_inside_body: true, connector_drawn_before_text: true}
unsafe_content_excluded: false
actual_image_checked: true | false
synthetic_input: true | false
published: false
```

The formal entry requires an explicit pixel `anchor.rect` plus `rect_format`, concrete protected-region rectangles, and a final `panel_id`; `anchor: auto` is not renderable. Rounded speech and thought connectors require a confirmed visible speaker region in the same panel when that upstream metadata is used. A carrier must have matching `anchor.carrier_id` and `carrier.asset_id`, a carrier polygon, and a writable rectangle containing the anchor. Existing pages use a recorded legacy outer-polygon bounding-box and writable-rect adapter; exact writable-polygon point containment is not yet implemented. Body, tail, thought-dot, and carrier geometry are checked with conservative axis-aligned rectangles for collision. Exact repeated source links render once; conflicting duplicate IDs/source links and legacy/structured text mismatches are blocked before drawing.

For a no-image test, save the source arrays, inputs, selected `text_blocks`, and a handoff copy to an independent test directory. Test regions use canvas-pixel rectangles `[x, y, width, height]` explicitly marked `synthetic`; a result without rectangle geometry is not a placement pass. Validate the mapping, exact text/source linkage, speaker/tail ownership, intensity guard, physical binding, avoidance/collision or unresolved placement, fallback, and handoff to prompt/composition-plan copies. Record `rule_check_status: passed` only for those rule assertions and `actual_image_checked: false`; retain `render_status: not-generated`, `final_status: not-generated`, `check_status: not-checked`, and `published: false`. An expected `needs-placement` case can pass the rule test but blocks page acceptance. For a real base PNG, call the formal compositor and record the generated PNG and both reports; do not use a rules-only pass as proof of real-page quality.

## Completion checks

A run can be marked complete only when:

1. `panel_count` equals `panels` length in every storyboard and prompt.
2. Every SB ID exists in the current active layout index and its description was read.
3. The required story beats are present and no unknown plot fact was invented.
4. Reference images were actually passed during generation, not merely listed.
5. Each base render and final PNG exists and is 1080×1440, 3:4.
6. Final images differ from the base because of post-layout text, and all text is exact/readable.
7. Character, prop, text ownership, page order, and reading order checks are recorded.
8. Delivery manifest records paths, SB IDs, statuses, `published: false`, and the separate `planned_story_units`, `planned_panel_count`, `visible_panel_count`, `panel_count_delta`, and `panel_count_reconciliation` fields.
9. Existing approved assets outside the isolated run are unchanged.
10. Text selection retains semantic type and wording; narration has no speech tail, remote phone speech is distinguished from onsite speech, weak emotion has no shout burst, and notes/screens stay on their actual carrier. Placement respects protected regions; a `needs-placement` block prevents page acceptance.
11. A rule-selected style or a passed no-image test is not proof of a rendered bubble. The formal compositor must produce a PNG and placement report; new shapes still require real-page and mobile visual validation before they are treated as production-ready.
12. `panel_count_delta` equals `visible_panel_count - planned_panel_count`, and the reconciliation contains a per-page audit or an equivalent traceable basis.
13. An explainable SB-structure difference does not fail the run by itself; an unresolved difference blocks publication and remains visible in the report.
14. Each page has `final_image_count: 1`, `generated_variants: 0` by default, a canonical `retained_final_image`, and a recorded `duplicate_story_check`. Candidate and legacy version files are not delivery outputs.
15. Preview-matching pages include actual-render bubble audits. Copied contracts, a selected SB value, a passing style-only result, or an adapted target are insufficient for exact geometry acceptance. Source-to-target changes and unused bubbles remain explicit; human visual acceptance stays pending until reviewed.

A failed check keeps `check_status: not-checked` and is reported; it is never hidden by writing a prompt or YAML file.
