# Workflow rules for v0.2-draft

## Defaults

- `visual_mode: douyin_simple_comic`
- `visual_density: low`
- `background_level: minimal`
- `mobile_reading_priority: true`
- `text_readability: high`
- delivery canvas: 1080×1440, 3:4, PNG
- Chinese text: post-layout raster overlay
- publish status: not-published

Keep the character reference sheet more detailed if useful, but simplify final pages: silhouettes, expressions, gestures, and plot props outrank furniture, plants, wall/floor texture, clothing wrinkles, hair strands, complex shadows, and paper texture. Per panel, keep one main action or emotion and at most the configured number of key props; this limit is per panel, not a whole-page deletion rule.

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
## Character/reference invariants

A character ID is not a reference image. Every generated page prompt must list actual reference paths and an input policy. At generation time pass those files as image inputs. Keep `approval_status` separate from `generated`; a generated reference is not automatically approved. If a new story needs new people, use a new ID namespace and record source facts versus provisional design additions.

## Text invariants

Use the exact text from the storyboard/page YAML. Keep narration, dialogue, and note text separate. `text_placement` is page-specific; do not force all text to the top. In v0.2-draft, `text_blocks` links this content to rule-selected `bubble_style` values and the reusable `scripts/text_compositor.py` consumes those blocks after base-image generation. If text is wrong, preserve the base image and redo only raster composition.

## Text style selection v0.2-draft

### Layout-aware bubble adaptation

Before applying the type mapping, validate `layouts.json`, all 68 matching `SB-*.md` files, and `references/comic-layouts/bubble-constraints.yaml`, then resolve the page's `layout_id`. The adapter contains one profile for each of the 68 bundled SB entries. `source_rule_level: explicit` means the matching SB description actually mentions a text, bubble, caption, phone, or negative-space affordance; `source_rule_level: none` means the SB description contains no bubble-specific evidence. A profile's `preferred_bubble_candidates` is a preference and placement constraint for this workflow, not a claim that the original layout gallery supplies a unique bubble drawing. The compositor records the validation result and the `none` profiles as missing SB-specific reference.

For a block with `bubble_style: auto`, choose the semantic type's default style when it is compatible with the selected profile, then resolve its compact body, speaker/carrier anchor, tail/connector, and protected regions from the actual page PNG. For an explicit style, retain the style only when it matches the semantic type; otherwise record `style_type_mismatch` and use the semantic default. Layouts may share the same compact balloon. Do not invent a layout-specific tail or shape when the SB text does not document one.

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

The reusable compositor in `scripts/text_compositor.py` implements these seven drawing methods for raster post-layout output. It passes the fitted font size into the actual draw call and rolls back failed carrier/anchor attempts, so a too-small writable region cannot leave partial text or outlines behind. A style render is still only accepted for a real page after its PNG and mobile preview have been checked. The safety fallback is the v0.1 warm-white rounded box: fill `#FFFDF7`, fill opacity 245/255, border `#2B2621` width 3, radius 12, padding 22, Microsoft YaHei, dark ink `#1F1B17`, and nominal font size 42 on a 1080×1440 canvas. Its coordinates must still follow the current panel's available whitespace; do not reuse a fixed top-left position.

### Required decision order

Resolve the selected SB profile first, then resolve each block in the following five stages and record `selection_trace` in this order. The layout profile is recorded separately as `layout_constraint_status`, `layout_preferred_bubble_candidates`, and `style_selection_reason`; it is not silently treated as evidence of a source-documented bubble:

1. **Text type.** Use explicit block metadata or confirmed source/storyboard semantics to select the default mapping. Do not infer shouting from an exclamation mark alone, turn a sentence beginning with “我想” into a thought without evidence, or promote narration to dialogue because a character is pictured. Keep the exact source text and original type, including an unknown type that triggers fallback.
2. **Explicit speaker.** `narrator` is a non-character attribution; `null`, unknown IDs, an absent person, or an unspecified speaker never get a character-pointing tail. A tail/connector requires a stable character ID, a matching visible speaker/thinker region in this panel, and a clear attribution. An explicitly typed `dialogue` with no speaker keeps `rounded_speech` but records `speaker_status: missing` and has no tail; missing ownership is a warning, not permission to invent a speaker. For remote phone speech, never point to the silent recipient: use the remote speaker's separate phone panel if visible, otherwise no character tail. Do not depict a phone screen as a video call to explain the source.
3. **Emotional intensity.** Use `neutral`, `low`, `medium`, or `high`; missing/unsupported values are treated conservatively as neutral and logged. Use `shout_burst` only for a block explicitly typed `shout` with intensity `high`. A weak/unknown-intensity `shout` uses `rounded_speech` when an explicit character speaker is identified, otherwise the v0.1 `narration_box`, with the suppression reason recorded. A high-intensity narration, note, thought, or telephone line keeps its own type-specific style; intensity alone never converts it into shouting.
4. **Physical carrier.** Resolve whether the text belongs to a note, paper, phone screen, or another confirmed surface. Such text must be embedded in that surface with `bubble_style: note_embedded`, an object anchor, and no external tail, while its semantic `type` stays unchanged. This style key describes direct surface text even when the surface is a phone screen. A `note` requires an actual carrier target; never relocate it to a narration box if the target is missing or too small. Mark `needs-placement` and preserve the text. Live telephone audio without a screen transcript remains `phone_dialogue`.
5. **Whitespace and avoidance.** Inspect current panel whitespace, speaker/carrier locations, reading order, and `avoid_regions` before resolving the anchor. Prefer an area that fits readable text and preserves faces, main actions, key props, and already placed text blocks. Reposition first; wrap without changing wording. Do not cover protected content, move a block to an unrelated panel, or shrink text until unreadable just to retain a decorative shape. If a non-carrier style cannot be identified or fitted, try the v0.1 box without a tail and log the fallback. If no safe fit remains, record `selection_status: needs-placement`, leave the anchor unresolved, and keep the page unaccepted. For embedded text, avoid the carrier's identifying contour or other protected details, while allowing ink on the designated writable surface; avoid-region checks must not forbid the required note text itself. Only the matched carrier's designated writable surface has this exception, not other key props. Recheck tail/connector paths as well as text bounds before actual rendering.

### Fallback and compatibility

- If type/style is unclear, choose `narration_box` using the verified v0.1 style with no tail; write `fallback_reason`. This changes presentation only, not the block's text, semantic type, or physical ownership. An explicit dialogue with a missing speaker is not type-unclear: keep `rounded_speech`, add a missing-speaker warning, and omit the tail.
- If `scripts/text_compositor.py` cannot draw a newly selected speech/thought/phone/burst/emphasis shape, record `rendering_capability: unavailable` and the default-box fallback. Preserve the explicit speaker/channel in metadata and page-specific attribution; if fallback would make ownership unclear, keep `needs-placement` for review. Do not claim that the new shape was rendered.
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

The entry reads `bubble_style`, `anchor`, `placement_reason`, `avoid_regions`, carrier metadata, speaker metadata, and the legacy text fields when they are present in the input plan. It writes one new PNG and two reports; it never overwrites the base image. The seven styles are rasterized with post-layout drawing. Unknown styles and weak `shout_burst` requests use the v0.1 `narration_box` fallback while preserving the semantic type and source text. A missing note carrier or an unsafe placement remains `needs-placement` and is not silently moved into a narration box. Legacy `narration_text`, `dialogue_text`, `note_text`, and `text_placement` arrays remain source-of-truth fields and are linked once through `text_blocks`.

#### Formal coordinate and identity contract

The compositor is a renderer, not a vision-based locator. Upstream storyboard/prompt data must supply a canvas-pixel coordinate contract: top-left origin, numeric rectangles with an explicit `rect_format` (`xywh` or `xyxy`), `panel_id`, and concrete `avoid_region_rects`. Semantic labels such as `face`, `main_action`, and `key_object` may resolve to concrete keys with the recorded `coordinate_adapter: semantic-prefix`; malformed or unresolvable regions block placement. `anchor: auto` is not renderable.

For `rounded_speech` and `thought_bubble`, the speaker ID must be explicit and its `speaker_region` must be supplied as a confirmed visible region in the same panel; when those upstream metadata fields are absent or contradictory, placement is blocked (a weak shout may fall back to a rounded box without a tail when the speaker ID is known but no visible region is available). Telephone blocks require a phone channel or telephone anchor and never point a tail to the silent recipient. A note/carrier block requires matching `anchor.carrier_id` and `carrier.asset_id`, a carrier kind, a carrier polygon, and a writable rectangle that contains the anchor. Missing, mismatched, or ambiguous carrier data blocks the note; it never moves to a narration box. Existing pages use a recorded legacy outer-polygon bounding-box and writable-rect adapter until an exact writable-polygon contract is supplied.

Collision checks cover the complete drawn text body, speech shape, visible tail, thought connector, and carrier geometry using conservative axis-aligned rectangles for each part. The renderer rolls back the block if any of these envelopes intersect a protected region, another block in the same panel, the canvas boundary, or the text body itself. It records `unsafe_content_excluded: true` and keeps the page blocked. Blocks are keyed by `id` and `(source_field, source_index)`; exact repeated links are rendered once, while conflicting duplicates or legacy/structured text mismatches are blocked before drawing.

### No-image verification boundary

A dry run may exercise all seven mappings, missing speaker/intensity, unclear type, carrier targeting, avoidance, and fallback with synthetic regions. Mark these regions `synthetic`, and record `actual_image_checked: false`. A successful rule check is `rule_check_status: passed`; page `render_status`/`final_status` remain `not-generated` and `check_status` remains `not-checked`. For an actual base PNG, call `scripts/text_compositor.py` and record the output and placement reports. A real render still requires visual checks for glyph fit, phone-screen perspective, bubble outline quality, and mobile readability.

## Failure handling

- Missing required reference input or generator: stop before page generation and report incomplete.
- Character drift: rerun only the affected page after checking the reference input.
- Text error: preserve the base and redo the text layer.
- Single-page failure: do not restart the entire set.
- Unknown plot fact that changes the story: ask one minimal clarification.
- YAML, prompts, or a status flag never count as an image artifact.
