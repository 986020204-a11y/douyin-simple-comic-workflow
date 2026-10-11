# v0.2-draft output schema and validation

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

Each page plan may include `layout_id` and the compositor resolves that ID
through `references/comic-layouts/bubble-constraints.yaml`. The mapping has one
profile per bundled SB and distinguishes source evidence (`source_rule_level`)
from workflow additions (`adaptation_rule`). It is valid for different SBs to
share the same compact bubble; a profile never implies a unique original
gallery shape unless the SB description explicitly says so.

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
    bubble_style: narration_box # or auto; auto resolves from layout profile + type
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
    selection_trace: [] # five ordered stage/result/reason records: type, speaker, emotional_intensity, carrier, whitespace
    speaker_status: confirmed # confirmed | missing | unknown | narrator
    warnings: []
    fallback_reason: null
    selection_status: selected # selected | fallback | needs-placement
    rendering: post-layout
```

`type` supports `narration`, `dialogue`, `thought`, `phone_dialogue`, `shout`, `note`, and `emphasis`. The corresponding default `bubble_style` values are `narration_box`, `rounded_speech`, `thought_bubble`, `phone_dialogue`, `shout_burst`, `note_embedded`, and `emphasis_box`. Apply [the five-stage rule](workflow-rules.md#text-style-selection-v02-draft) rather than treating this mapping as unconditional. Use `speaker: null` when no source-confirmed speaker exists; never invent one to add a tail.

The primary content fields stay separate: narration sources use `narration_text`, note/carrier sources use `note_text`, and character utterances/thought/phone/shout may stay in `dialogue_text` with explicit type metadata. An emphasis block retains its original source field. IDs and source links prevent duplicate drawing. An `anchor` resolves to a `kind` (`whitespace`, `speaker`, or `carrier`), a panel region and, for embedded text, its carrier ID; `anchor: auto` is not a final pixel placement. `selection_status` describes rule planning, never image completion. The renderer may add `duplicate-skipped` for an exact repeated source link; it is not a second draw and is summarized by `dedupe_status`.

## Formal text compositor

The reusable entry point is `scripts/text_compositor.py`. It accepts an existing base PNG, a YAML file containing linked `text_blocks`, and the project's `config/text-layout.yaml`; it writes a new PNG, a render report, and a placement report. The CLI parameters are `--base-image`, `--text-blocks`, `--text-layout`, `--output-image`, `--render-report`, `--placement-report`, and optional `--page-id`. The importable function is `compose_page()`.

The compositor reads `layout_id`, validates the exact 68-entry index/description/map pool, then reads the bundled layout profile, `bubble_style`, `anchor`, `placement_reason`, `avoid_regions`, `avoid_region_rects`, speaker/carrier metadata, and the legacy source arrays when present. It supports `narration_box`, `rounded_speech`, `thought_bubble`, `phone_dialogue`, `shout_burst`, `note_embedded`, and `emphasis_box`. `bubble_style: auto` keeps the semantic type authoritative while using the selected SB profile to record a compact candidate preference. An optional per-block `font_size` may be used for a known panel's available area; the renderer reduces the size conservatively to fit the resolved anchor instead of allowing glyphs to escape the box. Unknown styles and weak shout requests use the v0.1 narration-box fallback (or `rounded_speech` when a weak shout has an explicit speaker). A missing note carrier or unsafe placement is kept as `needs-placement`; its text is not moved to an unrelated box. Shapes and tails/connectors are painted behind the glyphs, and the report records `geometry_safety.text_inside_body`, visible connector collision, and draw order so a tail or border cannot cover the text. The base image is never overwritten.

Formal render reports additionally record:

```yaml
selection_trace: []        # type -> speaker -> emotional_intensity -> physical_carrier -> whitespace_avoidance
layout_map_validation: {}  # exact 68-SB index/description/adapter integrity result
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

A failed check keeps `check_status: not-checked` and is reported; it is never hidden by writing a prompt or YAML file.
