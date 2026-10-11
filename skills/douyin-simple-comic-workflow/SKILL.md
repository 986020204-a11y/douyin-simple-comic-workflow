---
name: douyin-simple-comic-workflow
description: Convert new Chinese copy into a validated static Douyin comic image set with dynamic page and panel decisions, real SB layouts, character references, post-layout Chinese text, and delivery checks; use for static image groups, not video.
metadata:
  version: "0.2-draft"
  text-style-stage: "rules-and-reusable-compositor"
  short-description: "中文文案到抖音简洁漫画组图的可验收工作流"
---

# 抖音简洁漫画工作流 v0.2-draft

The v0.2-draft change adds text-type/style selection rules, a reusable post-layout compositor, and validation formats. The compositor is callable, but each new style still requires real-page and mobile visual checks before it is treated as production-ready. v0.1's post-layout default box remains the safety fallback.

Use this skill when the user wants a new Chinese story, article, or copy turned into a static Douyin image group. The default visual mode is `douyin_simple_comic`. This skill produces still PNG pages and a delivery package; it does not make video, audio, timelines, MP4, SRT, transitions, or platform posts.

## Run boundary

Work in an isolated run directory supplied by the user or created for the task. Preserve existing approved pages, character references, prompts, storyboards, delivery files, and project state. Do not overwrite an old page just because a new run uses a similar story. Use the existing project assets only when the user explicitly selects them and bind their actual reference paths.

If the request lacks a source text, an output location, or an existing character reference that is required to keep identity, ask one minimal clarification only when the missing information would change the plot or make image generation impossible. Otherwise proceed with the defaults below.

## Bundled storyboard authority

Before this skill generates characters, pages, or prompts, it must load and execute its own bundled storyboard selector:

- selector: `scripts/prompt_style.py`
- index: `references/comic-layouts/layouts.json`
- prompt files: `references/comic-layouts/SB-001.md` through `SB-068.md`

The bundled pool is the sole storyboard authority. It contains exactly 68 entries from the `comic-storyboard` category. The selector must validate the pool before choosing a layout and must write a handoff artifact named `storyboard-decision.yaml` (or an equivalent path supplied for the run) containing page count, positive panel counts, real `SB-*` IDs, `layout_name`, `layout_source: bundled-internal-comic-layouts`, `selection_reason`, `selected_by: douyin-simple-comic-workflow`, `internal_layout_pool: 68`, and ordered panel content.

The workflow may analyze the copy to supply story beats and minimum-sufficient constraints, but it must not call another storyboard Skill, read an external storyboard library, or use an unregistered fallback. If the internal index or any matching `SB-*.md` is missing, invalid, or inconsistent, stop before image generation and report the blocking reason.

The bundled layout-to-bubble adapter is `references/comic-layouts/bubble-constraints.yaml`. Read its `source_rule_level` before treating a layout description as evidence. Profiles marked `none` have no SB-specific bubble evidence; use only the workflow's generic type/placement rules and say so in the report.

This release candidate also carries optional visual preview assets under `references/comic-layouts/preview-images/`. The packaged copy of `layouts.json` records `preview_image_path` for each SB. These 68 files come from a related local gallery and are explicitly marked in `preview-assets-manifest.yaml`; the source Skill and its original index did not contain preview images. A preview is a visual reference only: it is not evidence for a bubble shape, tail, writable area, or any other source rule, and it does not replace the bundled SB markdown or authorize an external storyboard selector.

The storyboard `panel_count` is a planning field for that page and must equal its `panels` list. It is not a claim about the number of visible borders in the rendered base image. At handoff and delivery level, keep these fields separate: `planned_story_units` is the total planned story units, `planned_panel_count` is the sum of the storyboard page counts, `visible_panel_count` is the audited count of panels visibly present in the final base images, `panel_count_delta = visible_panel_count - planned_panel_count`, and `panel_count_reconciliation` records both sources and the explanation for any difference.
## Execution

1. **Read and scope the source.** Save the exact Chinese copy in the run's `source/article.md`. Produce an analysis file that separates `source_facts`, `reasonable_inferences`, `design_additions`, and `open_questions`. Extract theme, core events, relationships, timeline, scenes, actions, emotion turns, turning points, visualizable beats, and abstract content. Do not turn an inference or a design addition into a source fact.
2. **Create or bind characters.** Make one card per important character with stable IDs (for a new run use a new namespace such as `N01`, `N02`; never reuse an unrelated project's `C01`/`C02`). Record age/version, appearance, provisional wardrobe, identifying features, props, emotions, and source boundaries. Existing characters may be reused only with their actual card and reference-image paths. Generate at least one reference sheet for each character when image generation is available; record `generated`, `not-reviewed`, and the actual path. If references are required but cannot be passed as image inputs, stop before page generation.
3. **Run the bundled storyboard selector and accept its handoff.** Analyze the copy for story functions and minimum-sufficient page/panel needs, then execute `scripts/prompt_style.py` against the local 68-layout pool. Validate `storyboard-decision.yaml`: page/panel counts are positive and minimum-sufficient, every page has a real compatible SB layout, and every panel has one main action or emotion. Dynamic page and panel counts remain allowed, but the decision owner is this workflow's bundled selector.
4. **Consume the bundled handoff without redesign.** Read the handoff and copy its planning `panel_count`, `panels`, `layout_id`, `layout_name`, `layout_source`, `selection_reason`, and `selected_by` into `storyboard/pages/<PAGE>.yaml` and prompts unchanged. Check only the bundled internal index and matching prompt file to validate the handoff. Do not choose a replacement SB, add padding panels, or reinterpret the page function. If the handoff is incompatible or invalid, stop and return the handoff error. Do not overwrite the planning count with a later visible-panel audit.
5. **Hand off to prompts.** Derive each page prompt from the accepted storyboard without changing `panel_count`, `panels`, or any SB field. Carry forward the simple-comic controls: `visual_mode: douyin_simple_comic`, `visual_density: low`, `background_level: minimal`, `mobile_reading_priority: true`, page `main_focus`, per-panel `focus`, `secondary_focus`, `key_objects`, `key_objects_max` (interpreted per panel), and `text_readability`. Keep one main action or emotion per panel and use only location cues in the background.
6. **Generate actual base images.** When an image generator is available, pass every bound reference image as an actual image input, not just a path in the prompt. Keep style, palette, canvas, and character versions from the approved run data. If the generator is unavailable or a required reference cannot be passed, stop at prompts and report that images were not generated. Never mark a prompt as a finished image.
7. **Select and compose text.** Keep each page's `narration_text`, `dialogue_text`, `note_text`, and `text_placement` fields compatible with v0.1; create linked `text_blocks` without adding, rewriting, or rendering text twice. Validate `references/comic-layouts/layouts.json`, all 68 matching `SB-*.md` files, and the bundled layout-to-bubble profile before resolving the selected `layout_id`. This file distinguishes wording explicitly present in the SB description from workflow-added preferences; it never claims that every SB has a unique bubble design. Profiles marked `source_rule_level: none` must be reported as lacking SB-specific bubble evidence. Apply [the text selection rules](references/workflow-rules.md#text-style-selection-v02-draft) in this exact order: selected layout constraints → text type → explicit speaker → emotional intensity → physical carrier → actual whitespace and avoidance regions. The default mappings are narration→narration_box, dialogue→rounded_speech, thought→thought_bubble, phone_dialogue→phone_dialogue, shout→shout_burst, note→note_embedded, and emphasis→emphasis_box. A block may use `bubble_style: auto`; the compositor then resolves the semantic type against the selected SB's candidate preferences and records the reason. Ordinary dialogue should use a compact rounded speech balloon and should not span a whole panel by default. Record the chosen style, layout profile, anchor, placement reason, avoidance regions, tail decision, and any fallback. Speech tails/connectors are drawn behind their bodies and their visible geometry is checked against the text bounds. Then call the reusable entry point [scripts/text_compositor.py](scripts/text_compositor.py) with an existing base PNG, a `text_blocks` YAML, `config/text-layout.yaml`, an output PNG, and two report paths. It must compose Chinese after image generation, preserve legacy source arrays, and never regenerate the base. Do not turn narration into speech, invent a speaker, point a tail to a silent listener, put a note outside its carrier, or choose a shout shape for weak emotion. Preserve all core story text even when more than two text blocks are needed. A successful compositor run is still a render artifact, not proof that every style is production-ready on every real page.
   The formal entry requires explicit pixel coordinates for the anchor and protected regions (`rect_format: xywh|xyxy`) and a final `panel_id`; `anchor: auto` is planning-only. A speaker tail or thought connector requires a confirmed, visible speaker region in the same panel. A carrier requires matching `anchor.carrier_id`/`carrier.asset_id`, a carrier polygon, and a writable rect; missing or ambiguous carrier geometry blocks placement. Existing pages use a recorded outer-polygon bounding-box/writable-rect adapter; exact writable-polygon point containment is outside this draft. The entry reports the ordered five-stage trace, actual drawn geometry (body, tail, thought connector, or carrier), conservative axis-aligned collision results, dedupe status, and `page_acceptance_status`. Unsafe content is removed from the output before the page is written as blocked. Exact repeated source links are rendered once; legacy/structured text conflicts block the conflicting block. `published` remains `false`.
8. **Check and deliver.** Verify story order, character identity, props, text content and ownership, panel reading order, real SB structure, absence of unauthorized plot additions, and image dimensions. A final image is complete only when it exists, is PNG, is 1080×1440 (3:4), and contains post-layout text. Write a continuity/technical report and a delivery manifest with page order, SB IDs, the separate `planned_story_units`, `planned_panel_count`, `visible_panel_count`, `panel_count_delta`, and `panel_count_reconciliation` fields, base/final paths, statuses, and `published: false`. Keep human visual acceptance pending until a person reviews the images.

## Dynamic panel policy

Use `panel_count_policy: minimum_sufficient`. For every page write `panel_count`, `panel_count_reason`, `required_story_beats`, `panel_addition_log`, `narrative_function`, and `panels`. `panel_count` must equal the number of `panels` entries.

Add a panel only when it fixes a concrete reading problem: an unclear action or relationship, a missing emotional transition, an unclear appearance/use/change of a key prop, text that remains crowded after shortening and layout adjustment, or a core event that cannot otherwise be understood. Every added panel must include both `reading_problem_solved` and `why_existing_panels_are_insufficient`. Stop adding when the next panel would not improve understanding, emotion, or reading rhythm. Empty `panel_addition_log` is valid when no panel was added.

Planning and visible-panel reconciliation is a separate delivery check:

1. `planned_story_units` records the story units selected by the storyboard handoff.
2. `planned_panel_count` is the sum of the page-level planning `panel_count` values; each page still requires `panel_count == len(panels)`.
3. `visible_panel_count` is measured from the final base images after the selected SB layouts are expanded, including documented inset or split panels.
4. The counts may differ when the final base conforms to the selected SB structure. A documented and explainable difference does not automatically fail the run.
5. If the difference cannot be explained from the selected SB structure and the final base audit, block publication and report the unresolved reconciliation. Never alter a planning count merely to hide a structural difference.

## Text and status invariants

Keep `narration_text`, `dialogue_text`, and `note_text` separate. Use `text_strategy: post-layout` and linked `text_blocks` as defined in [references/output-schema.md](references/output-schema.md#text-blocks-v02-draft). `bubble_style` records a rule decision and is consumed by [scripts/text_compositor.py](scripts/text_compositor.py). When a style or type cannot be determined, use the v0.1 warm-white rounded narration box without a character tail and record `fallback_reason`; preserve any physical-carrier binding. If no safe area or carrier is available, keep placement unresolved instead of hiding a face, action, or prop. A page prompt starts as `prompt_status: draft`, `render_status: not-generated`, `final_status: not-generated`, `check_status: not-checked`; update those fields only after the corresponding artifact exists and has been checked. If a page fails, repair the smallest affected unit: recompose text first for text errors, redo only the problem page for identity or image errors, and never regenerate the whole set without a reason.

## Required output tree

At minimum, produce:

- `source/article.md`
- `analysis/content-analysis.yaml`
- `characters/<ID>/character.yaml` and `characters/<ID>/references/`
- `storyboard-decision.yaml` and `storyboard/pages/<PAGE>.yaml`
- `prompts/pages/<PAGE>-prompt.yaml`
- `pages/renders/<PAGE>-v001.png`
- `pages/final/<PAGE>-final-v001.png`
- `reports/continuity-technical-report.yaml`
- `delivery/manifest.yaml`

Use the schemas and validation checklist in [references/output-schema.md](references/output-schema.md). The rules and storyboard handoff contract are in [references/workflow-rules.md](references/workflow-rules.md). The first passing end-to-end example is summarized in [references/e2e-001-example.md](references/e2e-001-example.md); it is a validation example, not a hard-coded cast or page template.
