# Workflow rules for v0.7-library-68

## Defaults

All 68 SB files have individual native source annotation. See [the executable-library contract](comic-layouts/executable-library.md) for canvas lettering, unframed units, thought dots, physical surfaces, and capability gates. New template source annotation alone does not authorize a batch of actual story images; retain the complete-proof and actual-image pilot gates below.

- `visual_mode: douyin_simple_comic`
- `visual_density: low`
- `background_level: minimal`
- `mobile_reading_priority: true`
- `text_readability: high`
- delivery canvas: 1080×1440, 3:4, PNG
- Chinese text: post-layout raster overlay
- publish status: not-published

Keep the character reference sheet more detailed if useful, but simplify final pages: silhouettes, expressions, gestures, and plot props outrank furniture, plants, wall/floor texture, clothing wrinkles, hair strands, complex shadows, and paper texture. Per panel, keep one main action or emotion and at most the configured number of key props; this limit is per panel, not a whole-page deletion rule.

## Native layout proof v0.6

The source template remains in native full-preview coordinates, with its original preview hash, source size, visible feature evidence, and annotation uncertainty. `prompt_style.py --layout <SB-ID>` compiles that native canvas by default; it does not stretch the preview to the delivery ratio or silently crop the header. Compiler success is `compiled_not_rendered`, never a storyboard-match pass.

If the current session already authorizes 3:4 full bleed, compile with `--approved-3-4-adaptation`. The selector calls `template_canvas.compile_adapted_template`, performs uniform content-ROI cover, records clipped panel boundaries and same-panel bubble translation/resizing, and exposes the separate `resolved_template`, `canvas_transform`, and `source_target_deviation`. Use `resolved_template` as the target geometry authority for layout, text, and audits; do not let one stage reload source geometry and ignore the target. Save the resolved target in the isolated run when a downstream CLI requires a template path. This mode is always `match_policy: adapted`, `source_template_modified: false`, and `source_reference_geometry_match: failed`. A target-layout pass never changes that source result. Without this explicit option, source coordinates and dimensions remain unchanged.

For a selected template, annotate every visible story text-container instance before claiming full coverage. Separate actual phone messages from repeatable styles; include unboxed display text and prop labels where present. Page headings, explanatory sample labels, contact headers, timestamps, and scene signage may be declared source decorations rather than story containers, with an explicit exclusion list. The expected instance count comes from the selected template, not a fixed count for all tasks. Keep `field_evidence`: geometry observed in the image, manually completed or approximated polygons inferred, original font identity unknown, and workflow compatibility/avoidance decisions inferred. Preserve any declared source-pixel tracing tolerance; it is not pixel-perfect equality.

Use this execution sequence when validating a newly integrated template or renderer:

1. Compile the source-native or explicitly approved target and freeze its complete instance IDs. Produce a complete raster layout-and-text proof using the intended source-linked text, real polygon contours, observed tail geometry, and selected fonts. Resolve type conflicts, overflow, missing instances, and font failures before scene generation.
2. Mark proof-only regions `synthetic: true`, `actual_image_checked: false`, and `proof_binding_scope: synthetic_layout_only`. A simulated same-panel speaker/prop rectangle can test placement rules; it cannot establish actual story ownership. A messaging UI specimen using spoken quotations must be labelled as a quotation/layout demonstration, never a source event in which characters sent those messages.
3. Run `preflight_preview_text.py` against the same target and text plan. Require `generation_ready: true`, exit code 0, full instance coverage, and accepted proof rendering. Preliminary font capacity alone does not satisfy this proof gate.
4. Generate actual no-text scene assets per declared panel. Pass the real references and complete quiet text zones, then assemble panel masks, positions, borders, and phone shells with `layout_executor.py`. The model never chooses the page grid. Finish one actual-image pilot before extending a new integration to the remaining templates/pages.
5. Replace synthetic bindings with confirmed regions measured from the generated assets. Audit the no-text base first, then compose text without modifying the base. Keep `target_layout_match`, `source_reference_geometry_match`, real-page acceptance, and human review separate.

`tail.mode: observed_polygon` supplies a visible polygon and tip in the declared coordinate space. Preserve the polygon rather than replacing it with a generic triangle. Execute ownership according to `anchor_kind`: a speaker requires a visible, confirmed same-panel speaker and source-compatible dialogue; a prop label requires a confirmed same-panel `prop_id`/region; a `chat_ui_nib` requires a confirmed phone-screen region and messaging channel. UI nibs are not physical speaker pointers. Render tails before their body so the attachment is covered. Audit the visible tail pixels outside the body envelope; an echoed polygon record alone is insufficient. Unknown required geometry or ownership remains blocked.

Brush text has an executable bundled font at `assets/fonts/mashanzheng/MaShanZheng-Regular.ttf`, paired with `OFL.txt`. Set `brush_font_file` and a hash-bound `brush_font_verification` after inspecting a specimen: `status: verified`, `family_class: brush_calligraphy`, actual `sha256`, `expected_family: Ma Shan Zheng`, and a real evidence path. A loaded ordinary font is not a brush-font fallback. The selected family and licensed file demonstrate a usable brush rendering path; the preview's exact font and microtexture remain unverified.

## Storyboard fields

Use existing names for the page-level storyboard fields rather than replacing them. `panel_count` remains the planned count for that page and must equal `panels` length. Final-image visibility is recorded separately at handoff and delivery level:

```yaml
planned_story_units: 24
planned_panel_count: 24
visible_panel_count: 37
panel_count_delta: 13 # visible_panel_count - planned_panel_count
panel_count_reconciliation:
  status: explained
  planned_basis: storyboard page counts, 8 x 3
  visible_basis: final-base visible-panel audit
  difference_reason: selected SB layouts expand into inset or split visible panels
  release_rule: unexplained differences block publication; explained SB differences do not automatically fail
```

Never write `visible_panel_count` back into a page's planning `panel_count`, and never change a count only to conceal a structural difference.

Use the following page-level names unchanged:

```yaml
panel_count_policy: minimum_sufficient
panel_count: 3
panel_count_reason: "why this count is enough"
required_story_beats: []
panel_addition_log: []
narrative_function: "..."
layout_id: SB-000
layout_name: "verified name"
layout_reason: "story-function reason"
main_focus: "page-level first focus"
secondary_focus: "optional second focus"
key_objects: []
key_objects_max: 2
visual_mode: douyin_simple_comic
visual_density: low
background_level: minimal
text_readability: high
mobile_reading_priority: true
panels:
  - panel_id: P01-01
    focus: "panel-level focus"
    content: "what the reader sees"
    action: "one main action"
    emotion: "one main emotional beat"
    key_objects: []
    text:
      narration: ""
      dialogue: []
      note: []
```

When a page has an addition log, every entry must state the reading problem solved and why existing panels were insufficient. The prompt's `panel_structure.panel_count` and `panel_structure.panels` must be copied from the storyboard exactly.

## Storyboard selection from the bundled internal pool

The bundled selector is the required prerequisite and the authority for page/panel/layout decisions. Load and execute `scripts/prompt_style.py`; it reads only `references/comic-layouts/layouts.json` and its matching `SB-*.md` files. The pool must contain exactly 68 entries with `category: comic-storyboard`. No external Skill, absolute path, or unregistered default may be used.

The handoff file is `storyboard-decision.yaml` and must contain at least:

```yaml
source_article: source/article.md
page_count: 3
panel_count: 7
selected_by: douyin-simple-comic-workflow
internal_layout_pool: 68
storyboard_handoff_status: ready-for-douyin-simple-comic-workflow
pages:
  - page_id: P01
    panel_count: 2
    layout_id: SB-003
    layout_name: "verified bundled name"
    layout_source: bundled-internal-comic-layouts
    selection_reason: "why this real internal layout serves the page function"
    selected_by: douyin-simple-comic-workflow
    selector_execution:
      status: executed
      selector: scripts/prompt_style.py
      output_contains_selected_layout: true
    panels: []
```

Every `panel_count` must equal the page's `panels` length. `layout_id` must be present in the internal index and its matching bundled prompt file must exist. A missing or invalid pool stops the run before image generation. The downstream workflow copies the handoff fields unchanged; it never reselects a layout or pads the page.

The dynamic panel rule remains minimum-sufficient: page and panel counts can vary by story, but any added panel needs `reading_problem_solved` and `why_existing_panels_are_insufficient`. Function examples (environment opener, object focus, continuous action, emotion close-up, dialogue, quiet ending) are inputs to the internal selector's reasoning. Different pages may use different bundled SB layouts when the handoff calls for it.

### Planned versus visible panel reconciliation

The selected SB may produce a final base with more or fewer visible panel borders than the storyboard planning units. This is valid when the final base conforms to the selected SB layout and the report records the per-page visible audit and the reason for the difference. The delivery manifest must show `planned_story_units`, `planned_panel_count`, `visible_panel_count`, `panel_count_delta`, and `panel_count_reconciliation` together. An unexplained difference is a publication blocker; an explained difference is recorded for review and does not become an automatic text-layer failure.

### Final-page uniqueness and retry filtering

One `page_id` is one story page and has one default final PNG. A render retry is not a new page and must not be written as another formal final. Use this record in the delivery manifest:

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

The only default final filename is `pages/final/<PAGE_ID>-final.png`. Put retries and discarded candidates under `pages/candidates/<PAGE_ID>/`; do not list that directory in the delivery outputs. Versioned names such as `-v001` through `-v005` may remain in historical runs for audit, but a new manifest must not treat them as final pages. A variant is permitted only when the user explicitly asks for multiple versions and the manifest records that request.

Before delivery, `scripts/check_page_uniqueness.py` must verify unique page IDs, `final_image_count: 1`, `generated_variants: 0` by default, the canonical retained filename, and one manifest entry per page. It also checks for a repeated `story_beat_id` across pages and identical adjacent panel signatures built from `action`/`visual_action`, `camera`/`shot`, and `emotion`. Such repetition is `duplicate_story_check: needs_review`. An SB that expands into multiple visible panels still yields one page final; if adjacent panels add no new action, expression, prop, or camera function, reduce the panel plan instead of generating a duplicate image.
`candidate_image_count` records all generated attempts. Candidate and discarded file lists belong in the page-uniqueness report or another internal audit record and never in delivery entries. The panel signature also includes `expression`/`emotion` and `key_objects`/`props`, so a changed prop or expression is treated as a distinct visual beat while a panel with no new action, expression, prop, or camera function is sent to review.
## Character/reference invariants

A character ID is not a reference image. Every generated page prompt must list actual reference paths and an input policy. At generation time pass those files as image inputs. Keep `approval_status` separate from `generated`; a generated reference is not automatically approved. If a new story needs new people, use a new ID namespace and record source facts versus provisional design additions.

## Text invariants

Use the exact text from the storyboard/page YAML. Keep narration, dialogue, and note text separate. `text_placement` is page-specific; do not force all text to the top. In v0.2-draft, `text_blocks` links this content to rule-selected `bubble_style` values and the reusable `scripts/text_compositor.py` consumes those blocks after base-image generation. If text is wrong, preserve the base image and redo only raster composition.

## Text style selection v0.2-draft

### Preview bubble contract v0.5

For preview fidelity, use the annotated `executable-templates/SB-###.yaml` before the legacy adaptation profile, or its separately recorded approved target under v0.6. Bind `layout_id` → existing `bubble_id` → its actual `panel_id`, then carry `allowed_text_types`, `shape`, `bounds`, `polygon`, `position`, `tail.mode`, `tail.polygon`, `tail.anchor`, and `visual_style` into the text plan. No preview bubbles means no invented bubble template. Preserve per-field `observed`/`inferred`/`unknown` evidence and label workflow-authored choices separately. Unknown required tails block exact execution; adapted diagnostics may leave them undrawn while reporting unverified fidelity.

Keep each block's source text, semantic type, and source link. A dialogue-shaped template zone cannot make narration into dialogue. If text semantics or ownership do not fit an annotated zone, strict composition is blocked; an explicitly adapted plan records its reason and cannot claim exact preview agreement. The default `bubble_selection_policy` is `all_template_bubbles`. Explicit `story_subset` requires `bubble_active_ids` and `bubble_subset_reason`; it records unused IDs and `full_bubble_structure_match: false`.

Prepare and preflight that text plan before generating scenes: check source semantics, allowed types, ownership, bubble count/bindings, and capacity at readable font sizes. Do not wait for completed artwork to discover that its text cannot fit. An unresolved preflight blocks generation without changing source meaning or widening zones.

Run `python scripts/preflight_preview_text.py --template <SB.yaml> --text-plan <page.yaml> --text-layout <text-layout.yaml> --output <preflight.json>`. `--text-layout` is optional. Only `generation_ready: true` with exit code 0 opens generation; failures return code 1 and explicit errors. The gate checks original legacy source links/wording/type categories, IDs, panel ownership, allowed types, coverage, transformed bounds, and preliminary Pillow font capacity. It does not infer semantics from the whole story or guarantee rendering. Unknown required tail geometry and missing `brush_font_file` prevent `exact_ready`; strict match policies also block generation. `minimum_readable_font_size` is configurable (conservative default 24 at 1080×1440), and the script never silently shrinks fonts or alters a plan.

`prompt_style.py` compiles every bubble instance's `bounds_px`, body/tail polygon pixels, shape, visual style, allowed text types, avoidance, and `reserved_no_subject_zones` into the generation contract. Generate quiet scene space in these zones and place faces, hands, and key props elsewhere. The image model draws neither glyphs nor bubble bodies/borders/tails; post-layout composition draws those. Reserving text space cannot change the selected target geometry. Any approved source-to-target bubble move must already be recorded by the target compiler.

Resolve the declared source coordinate system into final canvas pixels with an explicit `canvas_transform`: source/target sizes, uniform scale, translation, and crop. Keep both source bounds and transformed target bounds. Clipping, relocating, or resizing a bubble is a recorded deviation, even when needed to protect faces, hands, key props, or readability. A clipped/rearranged target may pass target placement and retain a similar style; it does not pass source geometry equality. Do not call it exact or hide changes by editing the target contract. Protected regions remain actual-page inputs, and bubbles remain inside their bound panel unless the template explicitly permits crossing.

Render into an isolated candidate directory from the existing base. Do not overwrite/regenerate the base or change historical outputs; verify its bytes/hash and record `base_image_modified: false`. Audit against actual accepted draw records (`body_rect`, `drawn_geometry`, actual renderer/visible tail), not `bubble_contract_bounds` or copied plan metadata. Missing actual evidence and rejected blocks fail the required checks.

```text
python scripts/audit_preview_bubbles.py \
  --template references/comic-layouts/executable-templates/SB-002.yaml \
  --text-plan <candidate-text-plan.yaml> \
  --render-report <candidate-render-report.yaml> \
  --transform <recorded-canvas-transform.json> \
  --target-coordinate-space source \
  --coordinate-space target \
  --output <candidate-bubble-audit.json>
```

Use the original template plus its recorded transform with `--target-coordinate-space source` when actual drawing coordinates are on the target canvas. If a separate transformed-target template is used, declare `--target-coordinate-space target`, omit another transform, and preserve a second source-preview comparison. `--coordinate-space source` is only for actual records still expressed in source coordinates. Never substitute an adapted target comparison for source-preview fidelity.

Report bubble IDs, panel binding, shape, position, bounds, tail, visual style, unused IDs, full-structure coverage, and deviations separately. Accepted text placement plus required passing bubble checks are candidate promotion gates; any failed or unresolved required field blocks an exact claim. Base storyboard layout failure cannot be repaired by adding text. Contract/style checks do not establish pixel equality: keep real-page and mobile human visual acceptance pending until reviewed. Preserve old finals while candidates are being checked.

Base layout acceptance separately requires hash-bound `measurement_evidence` from the actual PNG (`geometry_observed_from_image: true`; method `manual_visual_annotation`, `image_panel_detection`, or `deterministic_render_with_pixel_verification`). Preview style acceptance requires hash-bound `style_verification` with `method: manual_visual_comparison` and an actual `matched` result. Target/transform echoes and a nonempty style contract cannot supply either proof. Missing observation blocks acceptance.

### Layout-aware bubble adaptation

The following rules remain the legacy/adapted compatibility path; they cannot override an annotated preview contract. Before applying the type mapping, validate `layouts.json`, all 68 matching `SB-*.md` files, `references/comic-layouts/bubble-constraints.yaml`, and its paired `references/comic-layouts/bubble-execution-profiles.yaml`, then resolve the page's `layout_id`. The source adapter contains one profile for each bundled SB entry. `source_rule_level: explicit` means the description mentions a text/bubble affordance; it is not geometry evidence. The companion workflow-authored profile must contain `bubble_style`, `bubble_bounds` or `allowed_zone`, `max_width`, `tail_anchor`, `speaker_direction`, `text_type`, and `fallback`. A missing/non-executable required profile blocks composition.

Resolve each block in this order: selected SB bubble profile, current `panel_id`, semantic text type, explicit speaker and position, emotional intensity, then actual whitespace and avoidance. For `bubble_style: auto`, choose only from the selected profile's approved candidates and record `bubble_style_requested` and `bubble_style_resolved`; do not map `auto` directly to an ordinary long box. Use the profile's `bubble_bounds`, `allowed_zone`, `max_width`, `tail_anchor`, and `speaker_direction` when resolving the anchor. Layouts may share a compact balloon, but a preview-only SB must never be described as source geometry. Any fallback is finite, explicit, and logged with `fallback_reason`; drawing failure alone cannot silently produce a default box.

The adapter's generic placement contract is additive: use an explicit pixel `anchor` inside the current panel, keep ordinary dialogue compact, keep narration/metadata boxes separate from speech, and recheck the entire drawn body, tail/connector, borders, later text blocks, faces, main actions, and key props. Speech tails/connectors are painted behind the bubble body and the visible connector envelope is checked separately, so no border or tail can cover a glyph. If the actual image does not provide a reliable safe region, keep the block `needs-placement`; do not stretch a box across the panel or reduce glyphs below readable size.

### Default type-to-style mapping

| `type` | `bubble_style` | Appearance and ownership constraint |
| --- | --- | --- |
| `narration` | `narration_box` | v0.1 warm-white rounded narration box; never a speaker tail or speech balloon. |
| `dialogue` | `rounded_speech` | Clear rounded speech balloon; tail only to its explicit, visible speaker in the same panel. |
| `thought` | `thought_bubble` | Soft cloud outline; optional dot connector only to the explicitly identified thinker, never an audible speech tail. |
| `phone_dialogue` | `phone_dialogue` | Rounded box with a restrained dashed/double border or small phone-source symbol; visually distinguish the phone channel from onsite speech. |
| `shout` | `shout_burst` | Restrained burst outline, only when intensity is explicitly `high`; do not let spikes reduce readability. |
| `note` | `note_embedded` | Direct post-layout ink on the note/paper itself; no floating box, speech tail, or duplicate note text. |
| `emphasis` | `emphasis_box` | Modestly heavier border or tint, no speaker tail; do not invent a shouted line or a speaker. |

The reusable compositor in `scripts/text_compositor.py` implements these seven drawing methods for raster post-layout output. It passes the fitted font size into the actual draw call and rolls back failed carrier/anchor attempts, so a too-small writable region cannot leave partial text or outlines behind. A style render is still only accepted for a real page after its PNG and mobile preview have been checked. A profile may declare the v0.1 warm-white rounded box as a finite fallback: fill `#FFFDF7`, fill opacity 245/255, border `#2B2621` width 3, radius 12, padding 22, Microsoft YaHei, dark ink `#1F1B17`, and nominal font size 42 on a 1080×1440 canvas. Its coordinates must still follow the current panel's available whitespace; do not reuse a fixed top-left position. Without that declaration, drawing failure remains `needs-placement` or `blocked`.

### Required decision order

Resolve the annotated preview contract first when applicable, otherwise the selected SB compatibility profile. Record `selection_trace` in this order: selected layout/contract/profile → selected panel → text type → speaker/position → emotional intensity → physical carrier → whitespace/avoidance. Expose `selected_layout`, `selected_panel`, `bubble_profile_id`, `bubble_id` when preview-bound, requested/resolved style, actual bounds, allowed zone, tail, fallback, and render source. Source previews alone cannot drive geometry; annotated executable templates can. A missing/non-executable required contract is `blocked`/`needs-placement`, never a silent default:

1. **Selected layout/profile and panel.** Validate the exact SB ID, load its execution profile, and bind the block to the same `panel_id`. If either is missing, stop the block before type mapping.
2. **Text type.** Use explicit block metadata or confirmed source/storyboard semantics to select the default mapping. Do not infer shouting from an exclamation mark alone, turn a sentence beginning with “我想” into a thought without evidence, or promote narration to dialogue because a character is pictured. Keep the exact source text and original type, including an unknown type that triggers fallback.
3. **Explicit speaker.** `narrator` is a non-character attribution; `null`, unknown IDs, an absent person, or an unspecified speaker never get a character-pointing tail. A tail/connector requires a stable character ID, a matching visible speaker/thinker region in this panel, and a clear attribution. An explicitly typed `dialogue` with no speaker keeps `rounded_speech` but records `speaker_status: missing` and has no tail; missing ownership is a warning, not permission to invent a speaker. For remote phone speech, never point to the silent recipient: use the remote speaker's separate phone panel if visible, otherwise no character tail. Do not depict a phone screen as a video call to explain the source.
4. **Emotional intensity.** Use `neutral`, `low`, `medium`, or `high`; missing/unsupported values are treated conservatively as neutral and logged. Use `shout_burst` only for a block explicitly typed `shout` with intensity `high`. A weak/unknown-intensity `shout` uses a profile-declared finite fallback when an explicit character speaker is identified; otherwise it remains `needs-placement`, with the suppression reason recorded. A high-intensity narration, note, thought, or telephone line keeps its own type-specific style; intensity alone never converts it into shouting.
5. **Physical carrier.** Resolve whether the text belongs to a note, paper, phone screen, or another confirmed surface. Such text must be embedded in that surface with `bubble_style: note_embedded`, an object anchor, and no external tail, while its semantic `type` stays unchanged. This style key describes direct surface text even when the surface is a phone screen. A `note` requires an actual carrier target; never relocate it to a narration box if the target is missing or too small. Mark `needs-placement` and preserve the text. Live telephone audio without a screen transcript remains `phone_dialogue`.
6. **Whitespace and avoidance.** Inspect current panel whitespace, speaker/carrier locations, reading order, and `avoid_regions` before resolving the anchor. Prefer an area that fits readable text and preserves faces, main actions, key props, and already placed text blocks. Reposition first; wrap without changing wording. Do not cover protected content, move a block to an unrelated panel, or shrink text until unreadable just to retain a decorative shape. If a non-carrier style cannot be identified or fitted, use only a profile-declared fallback without a tail and log the fallback. If no safe fit remains, record `selection_status: needs-placement`, leave the anchor unresolved, and keep the page unaccepted. For embedded text, avoid the carrier's identifying contour or other protected details, while allowing ink on the designated writable surface; avoid-region checks must not forbid the required note text itself. Only the matched carrier's designated writable surface has this exception, not other key props. Recheck tail/connector paths as well as text bounds before actual rendering.

### Fallback and compatibility

- If type/style is unclear, use only the selected profile's declared fallback policy. Set `fallback_used: true`, write a non-empty `fallback_reason`, and set `render_source: fallback`. A missing/non-executable profile is `blocked`/`needs-placement`; it does not silently become `narration_box`.
- If `scripts/text_compositor.py` cannot draw a newly selected speech/thought/phone/burst/emphasis shape, keep the block `needs-placement` unless the selected profile explicitly declares a finite fallback. Preserve the explicit speaker/channel in metadata and record the resolved style and reason. Never claim a new shape was rendered when it was not.
- A physical note/screen always remains embedded. Missing or unwritable carrier regions block placement; fallback never moves their text off the carrier.
- Preserve old `narration_text`, `dialogue_text`, `note_text`, and `text_placement`; no retroactive rewrite of accepted pages. New blocks link to source entries by `source_field` and `source_index` (zero-based). Plain old text entries adapt to their known type; thought/phone/shout/emphasis require explicit metadata or verified semantics. Scalar text is one entry at index 0; empty/null legacy arrays contain no blocks. Render linked entries once, never once from each representation. Duplicate IDs/source links or conflicting text copies must be reconciled before composition without silently changing source wording. Empty template text is not printable content; flag it for completion rather than accepting it as a rendered block.
- Carry selected blocks from storyboard to page prompt, then to the text-composition plan; page identity and `panel_id` must stay consistent. The image prompt reserves needed blank space and blank carriers; full Chinese text is kept for post-layout composition.

### Reusable compositor entry

The formal reusable entry is `scripts/text_compositor.py`. It can be called as a CLI or imported as `compose_page()`:

```text
python scripts/text_compositor.py \
  --base-image <existing PNG> \
  --text-blocks <YAML containing text_blocks> \
  --text-layout <config/text-layout.yaml> \
  --output-image <new PNG> \
  --render-report <render-report.yaml> \
  --placement-report <placement-check.yaml> \
  --page-id <page id>
```

The entry reads `bubble_style`, `anchor`, `placement_reason`, `avoid_regions`, carrier metadata, speaker metadata, and the legacy text fields when they are present in the input plan. It writes one new PNG and two reports; it never overwrites the base image. The seven styles are rasterized with post-layout drawing. Unknown styles or weak `shout_burst` requests use only an explicit profile fallback while preserving the semantic type and source text; missing/non-executable profiles block placement. A missing note carrier or an unsafe placement remains `needs-placement` and is not silently moved into a narration box. Legacy `narration_text`, `dialogue_text`, `note_text`, and `text_placement` arrays remain source-of-truth fields and are linked once through `text_blocks`.

#### Formal coordinate and identity contract

The compositor is a renderer, not a vision-based locator. Upstream storyboard/prompt data must supply a canvas-pixel coordinate contract: top-left origin, numeric rectangles with an explicit `rect_format` (`xywh` or `xyxy`), `panel_id`, and concrete `avoid_region_rects`. Semantic labels such as `face`, `main_action`, and `key_object` may resolve to concrete keys with the recorded `coordinate_adapter: semantic-prefix`; malformed or unresolvable regions block placement. `anchor: auto` is not renderable.

Speech tails and thought connectors require an explicit speaker ID and a confirmed visible region in the same panel. Absent/unknown speaker geometry never authorizes a direction; a permitted tail-free body may still render with ownership/preview-tail review pending. Telephone blocks require a phone channel or telephone anchor and never point a tail to the silent recipient. A physical note/carrier block requires matching `anchor.carrier_id` and `carrier.asset_id`, a carrier kind, a carrier polygon, and a writable rectangle containing the anchor. Missing, mismatched, or ambiguous carrier data blocks the note; it never moves to a narration box. Decorative preview caption/vertical-note styles are not evidence of a physical note carrier. Existing carrier adapters use a recorded outer-polygon bounding box and writable rectangle until an exact writable-polygon contract is supplied.

Collision checks cover the complete drawn text body, speech shape, visible tail, thought connector, and carrier geometry using conservative axis-aligned rectangles for each part. The renderer rolls back the block if any of these envelopes intersect a protected region, another block in the same panel, the canvas boundary, or the text body itself. It records `unsafe_content_excluded: true` and keeps the page blocked. Blocks are keyed by `id` and `(source_field, source_index)`; exact repeated links are rendered once, while conflicting duplicates or legacy/structured text mismatches are blocked before drawing.

### No-image verification boundary

A dry run may exercise all seven mappings, missing speaker/intensity, unclear type, carrier targeting, avoidance, and fallback with synthetic regions. Mark these regions `synthetic`, and record `actual_image_checked: false`. A successful rule check is `rule_check_status: passed`; page `render_status`/`final_status` remain `not-generated` and `check_status` remains `not-checked`. For an actual base PNG, call `scripts/text_compositor.py` and record the output and placement reports. A real render still requires visual checks for glyph fit, phone-screen perspective, bubble outline quality, and mobile readability.

## Failure handling

### Complete execution evidence

Keep geometry, required effects, and original-source equality separate. `execution_geometry_match` checks the executed target's frames and reading order; `execution_style_match` checks required observable treatments and the linked final text layer; `full_template_execution` requires both. An approved 3:4 adaptation can pass the executable target while retaining `storyboard_layout_match: failed` and source geometry/bubble failures. Do not promote a geometry-only proof to complete template capability.

A complete pre-generation proof includes every required structural effect, using explicitly synthetic stand-ins where actual art does not yet exist. For a foreground-crossing template, demonstrate a transparent synthetic silhouette crossing the declared edge as well as the impact text. For a phone layout, draw the actual phone shells and all enumerated messages. A frame-only diagnostic is useful but cannot satisfy this complete proof gate. Synthetic effect evidence proves the renderer's mechanics only; replace it with hash-bound actual artwork evidence before final acceptance.

For a required foreground breakout, use the executor's explicitly bound image overlay with genuine source alpha, an asset hash, an owning `source_panel_id`, declared allowed receiver panels and crossing bounds. Paste the foreground after the panel frames, and verify visible foreground pixels on both sides of the actual executed boundary. A slanted border, an opaque rectangular portrait, or copied crossing coordinates is insufficient. Preserve before-overlay, alpha-mask and after-overlay evidence. Freeze the resulting no-text base before applying text. The body and tail safety checks still protect actual faces, hands, key props and reserved text zones.

Text style evidence links the actual bubble audit and compositor report by file hashes and the final PNG hash. Its compositor input hash must match the no-text base. The final PNG hash is a distinct identity and must not be replaced by the base hash. Brush text, vertical notes, impact polygons, phone messages and unboxed handwritten subtitles must use their individually annotated renderers; none may be silently replaced by generic long boxes.

For the pre-text layout CLI check, pass `--geometry-only`; for an explicitly approved adapted target also pass `--accept-adapted-target`. This option changes the exit criterion only: style/full-execution fields still report missing evidence and source equality is not waived. After linking final text and required effects, omit `--geometry-only`; `--accept-adapted-target` then requires complete target execution rather than a frame-only success.

For a bound prop callout, retain `key_props_*` avoidance regions. Only the verified tail tip may contact the exact matching bound prop edge; the body or tail path entering the prop remains unsafe. Never delete the protected prop from the avoidance map to make the label pass.

An observed multi-point tail silhouette does not establish every point's speaker ownership. Actual-image composition blocks unconfirmed auxiliary tips. If the approved adapted target omits them, record `omit_unconfirmed_auxiliary_tail_points`, preserve the confirmed primary speaker binding, and mark the changed tail geometry as inferred. A synthetic proof may demonstrate the original silhouette but cannot establish real speaker ownership for these tips. Do not draw an unknown secondary tip toward a different visible person and count the primary binding as full success.

- Missing required reference input or generator: stop before page generation and report incomplete.
- Character drift: rerun only the affected page after checking the reference input.
- Text error: preserve the base and redo the text layer.
- Single-page failure: do not restart the entire set.
- Unknown plot fact that changes the story: ask one minimal clarification.
- YAML, prompts, or a status flag never count as an image artifact.
