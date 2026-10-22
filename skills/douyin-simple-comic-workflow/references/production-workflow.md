# Stable production, v0.9.0

This document belongs to **STRICT**. New everyday FAST runs use the independent
[FAST workflow](fast-workflow.md); do not run this preflight/scene queue for FAST.
Resume existing STRICT projects here. The original strict helpers and acceptance
requirements below are unchanged. All actual artwork uses the built-in Codex
`image_gen` tool; no API-key or external-provider fallback is authorized.

Use this path for a new static comic after the library is installed. The output
continues to use real SB geometry, post-layout text and one canonical final per
page. Template research and renderer benchmarks belong to capability validation;
they are not repeated as part of every story. The production helpers are offline
and use only Pillow/PyYAML plus Python's standard library. They do not call an
image provider or create story artwork on their own.

## Prepare once for the whole story

Save the exact source, analysis, cast/style/wardrobe references and bundled
selector handoff in the new run. Plan minimum-sufficient panels, with one main
action or emotion per unit. Combine repeated scenery before selecting an SB,
never by deleting units from an already selected template. Preserve causal
events, emotion turns, critical dialogue/conditions and the ending. Record
inferences and design additions separately.

Select multi-page layouts with `prompt_style.py --pages <RUN>/page-plan.yaml
--output <RUN>/storyboard-decision.yaml`; see [the page selection schema](storyboard-rhythm.md).
The page plan gives each page its own narrative function, panel-count reason and
story units. A previous single-layout result or an accepted pilot does not choose
the layout for other pages. Inspect the whole set's layout/text proofs for pacing
and image scale before dispatch. A new preparation must contain a current
`storyboard-rhythm-audit.json` bound to the complete decision; a legacy handoff
without page-specific selection evidence must return to selection, not be expanded.

Build a production manifest with paths relative to that manifest or absolute:

```yaml
source_path: source/article.md
storyboard_decision_path: storyboard-decision.yaml
pilot_page_id: P01
text_policy: excerpts  # use verbatim for a full-text request
style_prompt: "The current run's approved master visual specification"
continuity_contract:
  character_version: cast-v1
  wardrobe_version: wardrobe-v1
shared_reference_paths:
  - characters/N01/references/approved.png
story_beats:
  - beat_id: B01
    required: true
    source_range: [0, 20]  # exact Python character indices in saved source
    required_texts: []    # exact key quotations that must appear in captions
pages:
  - page_id: P01
    template_path: targets/P01-SB-055.yaml
    text_plan_path: plans/P01.yaml
    text_layout_path: config/text-layout.yaml
    beat_bindings:
      - {beat_id: B01, panel_id: P01, presentation: both}
    assets:
      - unit_id: P01
        scene_prompt: "The declared scene, action, expression and camera"
        reference_paths: []  # add current location or specific character refs
```

The example illustrates fields, not valid story indices or an approved cast.
Normal production requires the page IDs/order to cover the complete selector
handoff, including its primary story-beat bindings. A subset is allowed only
with `diagnostic_test_only: true` and explicit `--diagnostic` on preparation and
queue initialization; these artifacts cannot be delivered as a normal comic.
Every text block carries its exact `source_article_range`; ranges must reproduce
its text literally. `story_beats` follows the intended comic reading order,
including deliberately placed flashbacks. Required quotations must occur in the
panels bound to their beat. For `verbatim`, all non-whitespace characters inside
`source_content_range` (default: entire saved source) must be covered. Any title
exclusion must be explicit. The coverage report checks declared mappings, not the
meaning of artwork; the final story review checks that meaning.

The text plan is the existing complete, source-linked plan, including every
required selected container, its explicit font size and valid preview contract.
Proof speaker/carrier regions may be explicitly synthetic. Unknown required
tails or source-incompatible container types remain blocked. The helper copies
the plan for a diagnostic proof and never edits the input or claims its
synthetic bindings are real speakers.

```powershell
python <SKILL>/scripts/production_preflight.py --manifest <RUN>/production.yaml --output <RUN>/preparation-001 --cache-dir <RUN>/.production-cache
```

The output directory must be new/empty. This one command:

- verifies the bundled 68-layout library and selector, caching only library
  integrity by actual program/library/version hashes;
- checks beat/panel bindings, required source quotations and linked excerpts;
- blocks unreasoned whole-story uniform layouts, long repeated runs and copied
  page-selection evidence before creating any scene requests;
- runs current text capacity checks for every page, draws its complete neutral
  diagnostic proof and executes the real text/bubble audit;
- writes hash-bound `generation-readiness.json` per page and, only when every
  page is ready, `generation-requests.json` for the queue.

Each readiness proof and the request manifest contain the same hash-bound
`storyboard_rhythm_binding`. Queue initialization, sync and resume dispatch
revalidate the underlying whole-story decision, page order, selected target and
the current audit rather than trusting a saved `passed` label. Final delivery
checks that binding too. Diagnostic-only renderer tests remain explicitly marked
and cannot enter a normal queue or production package.

The generation requests contain each real unit's target geometry, full page
reading order and only the text reservations intersecting that unit, expressed
in both page pixels and unit-local normalized coordinates. No full-page generic
text box is introduced. The model draws a single scene; the executor owns
borders, masks, gutters, phone shells and page arrangement. Genuine alpha is
requested for relevant unboxed text areas in unframed art. This is an explicit
workflow requirement, not a source SB annotation or proof of model compliance.
Actual cover cropping and the reserved space still need image checks.

Reserve contrast as well as space: observed white unboxed lettering requires a
quiet dark scene region, not alpha over a white page. For nonphysical fictional
system messages, keep `note` semantics. A run-only adapted caption contract can
declare `note_scope: nonphysical_system_overlay` plus `compatibility_adaptation`
with `kind: system_note_semantic_adaptation`, `approved_for_run: true`,
`origin: workflow_adaptation`, a nonempty `reason` and its
`source_allowed_text_types`. This applies only to tailless `rect`/`rounded_rect`
caption bodies with a `system` speaker, `type`/`source_type: note`, and an explicit
preview contract. It never overrides a physical carrier or becomes an original
SB rule. Source fidelity remains failed when compatibility is adapted.

Keep generation-bound plans, targets and manifests frozen. Write real-image
speaker/protected-region bindings and any permitted actual text fits to separate
actual plans and executed targets. A local text repair must not mutate the
readiness inputs that the scene queue is still using. Recheck the executed text
geometry and all final-image evidence independently.

Special templates whose image overlays or carrier mechanisms need extra
generation units must have those units explicitly declared in the preparation
input and executor. A blocked special mechanism returns to the existing
template workflow; never bypass it with a generic panel grid.

## Dispatch, checkpoint and resume

```powershell
python <SKILL>/scripts/production_queue.py init --manifest <RUN>/preparation-001/generation-requests.json --state <RUN>/production-state.json --max-concurrency 4 --max-attempts 3
python <SKILL>/scripts/production_queue.py claim --state <RUN>/production-state.json --worker worker-1 --limit 4
```

The state uses atomic writes and a process lock. `claim` returns independent
tool requests and claim tokens up to the concurrency limit. Before pilot
acceptance, only the pilot's requests can be claimed. Call the available image
tool with each exact request, including actual `referenced_image_paths` and
`transparent_background`; use bounded parallel calls when supported. Do not
relabel the emitted requests as generated images. Register each returned,
readable asset separately:

```powershell
python <SKILL>/scripts/production_queue.py complete --state <RUN>/production-state.json --job-id P01/P01 --claim-token TOKEN --asset <RUN>/pages/assets/P01-P01.png
python <SKILL>/scripts/production_queue.py fail --state <RUN>/production-state.json --job-id P01/P01 --claim-token TOKEN --reason "actual failure description"
```

Assemble the pilot with `production_runtime.py assemble` and run the actual
base audit before adding text. Measure geometry from the generated base and bind
that evidence to its hash; do not substitute copied target coordinates. Then
replace synthetic regions with confirmed real face/hand/prop/speaker regions,
compose text, audit bubbles and full template execution, and review the full-size
candidate. Explicit font sizes are fixed by default. A failed fit
blocks that block and rolls back its pixels; use layout repair or an explicitly
recorded adaptation rather than silently shrinking it. An explicit
`font_size_policy: fit` can search down to the configured readable minimum, with
actual drawn sizes reported in `font_raster_evidence`.

Unlock later pages using real evidence:

```powershell
python <SKILL>/scripts/production_queue.py accept-pilot --state <RUN>/production-state.json --base-image <RUN>/pages/renders/P01-base.png --base-audit <RUN>/reports/P01-base-layout-audit.json --final-image <RUN>/pages/final/P01-final.png --final-audit <RUN>/reports/P01-production-review.json
```

The production review records current base/final hashes, `actual_image_checked:
true`, `synthetic: false`, a passed review status, and passed `checks` for
`full_size_readability`, `character_continuity`, `speaker_binding`, `text_integrity`,
`critical_occlusion`, `full_template_execution`, and `execution_style_match`.
Its `evidence_files` bind the real base-layout, render, bubble and actual-font
reports. See the queue's CLI help/API validation errors for its evidence fields.
A bare `accepted: true`, nonempty `selected_layout`, or synthetic proof cannot
unlock the run. Any changed pilot image/evidence invalidates the prior unlock.

Use the `reports/<PAGE_ID>-production-review.json` emitted by the runtime's
reviewed promotion step. It preserves the named reviewer and observations,
binds the original full-size review through `review_binding`. Its five
`evidence_files` are `render_report`,
`bubble_audit`, `font_raster`, `base_audit`, and `final_layout_audit`.
Its `input_bindings` include the actual plan, executed target and actual
annotations. Pilot unlock checks these current files and their actual font,
layout and image evidence; seven passed labels alone cannot unlock it.
Explicitly diagnostic records cannot enter a normal production queue.

After acceptance, schedule roughly 4–6 pages per planning batch while keeping
actual concurrent requests within the configured limit. Reuse approved current
references throughout; add a passed location reference when needed. Check and
compose completed pages while other independent scenes generate. The queue
tracks generation fingerprints from request/reference/template/version, and
separately rechecks the current readiness proof. Rebuilding a valid text-only
proof preserves intact artwork when its actual generation inputs are unchanged;
changed text areas, poses or style must change those actual request inputs.
Pilot acceptance is reset even when artwork is reused. It never reuses an old
image's acceptance result for a different image.

Use `status --state ...` for attempts, waits and timings. `sync --manifest ...
--state ...` reconciles revised inputs; a changed job loses its reusable state.
`recover --state ...` recovers expired leases only; `--worker NAME` is for a
worker known to have stopped. Recovering a lease does not reset attempt counts.
Use `record-text-issue --state ... --page-id ... --reason ...` to track text-only
repair without invalidating good scene assets. Exhausted retries stop that
unit; preserve other successes and report the actual failure. Never launch
unbounded retries or send the whole set through generation again.

## Bind the actual image and repair only the failed unit

Use [the actual-image runtime contract](actual-image-runtime.md) for annotation,
fit and repair schemas. The reusable commands resolve the selected page from
the production manifest instead of relying on a story-specific Python script:

```powershell
python <SKILL>/scripts/production_runtime.py assemble --run-root <RUN> --manifest <RUN>/production.yaml --page P01 --state <RUN>/production-state.json
python <SKILL>/scripts/production_runtime.py finish --run-root <RUN> --manifest <RUN>/production.yaml --page P01
python <SKILL>/scripts/production_runtime.py promote --run-root <RUN> --manifest <RUN>/production.yaml --page P01 --review <RUN>/reports/P01-visual-review.json
```

The actual base annotations and separate full-size review must exist before
their corresponding steps. These commands never perform the visual review or
guess a speaker, protected region or tail direction. A bound actual annotation
is not a human acceptance record. Keep all inference and review sources explicit.

Generation plans and targets stay frozen; actual plans and executed targets use
separate files. A permitted text fit needs explicit approval and a reason. Move
the bubble body polygon with the same affine transform as its bounds, and
recheck the resulting containment, contrast, tail and face/hand/prop avoidance.
Keep adapted positions reported as workflow adaptations rather than source
observations. An undeclared post-freeze change to source text or its range blocks
finalization, even when the edited text is still a literal source excerpt.

For a returned local scene edit, use `scene_repairs.py save` to preserve the
original and save a pending repair. Supply a separate actual-image review to
`scene_repairs.py register`; assembly rechecks both image hashes and the review
binding. Saving an edit does not make it reviewed. Repair only the failed unit,
then assemble a new unaccepted attempt; preserve an existing accepted base/final.

## Check and package once

Every page still needs the actual base audit, real text/bubble reports, final
template execution and a visual review. A contact sheet helps review all pages;
use the full-size views to resolve legibility, ownership or continuity concerns.
Keep approved target adaptation separate from original-preview fidelity:
3:4 clipping may pass the approved target while the strict source match remains
failed. Source annotations and previews remain immutable.

Build the delivery input:

```yaml
title: "Story title"
source_path: source/article.md
content_coverage_path: preparation-001/content-coverage.json
production_manifest_path: production.yaml
generation_requests_path: preparation-001/generation-requests.json
expected_page_ids: [P01]  # all accepted storyboard pages, not a partial subset
story_review: reports/story-visual-review.json
pages:
  - page_id: P01
    base_image: pages/renders/P01-base.png
    final_image: pages/final/P01-final.png
    base_audit: reports/P01-base-layout-audit.json
    final_layout_audit: reports/P01-final-layout-audit.json
    render_report: reports/P01-render.yaml
    bubble_audit: reports/P01-bubble-audit.json
    visual_review: reports/P01-production-review.json
    actual_text_plan: plans/actual/P01.yaml
```

`visual_review` uses the same seven checks as the queue pilot review. It records
`page_id`, `image_sha256`, `base_image_sha256`, `actual_image_checked: true`,
`synthetic: false`, `review_status: passed`, a named reviewer, concrete notes,
all seven passed `checks`, the full-size review binding, and all five report
bindings described above. The render report includes current
actual font evidence. A whole-story review does not substitute for these
per-page checks. Legacy metadata missing these records stays blocked until an
actual review supplies them; do not create a reviewer or missing observations.
`story_review` is a separately saved whole-story visual/content review with
`status: passed`, current `source_sha256` and `coverage_sha256`,
`reviewed_page_hashes` for every final page, `actual_image_checked: true`,
`synthetic: false`, `no_missing_required_beats: true`, a reviewer and concrete
semantic observations. It is not auto-created from the coverage map. Never
invent these observations.

Save this draft as `delivery-input.pending.yaml`. The finalizer derives the
complete page list and required frozen input bindings from the production
manifest and generation requests, rechecks source text and the actual render,
and writes accepted metadata only after all checks pass:

```powershell
python <SKILL>/scripts/production_finalize.py --run-root <RUN> --production-manifest <RUN>/production.yaml --generation-requests <RUN>/preparation-001/generation-requests.json --manifest <RUN>/delivery-input.pending.yaml --check-only
python <SKILL>/scripts/production_finalize.py --run-root <RUN> --production-manifest <RUN>/production.yaml --generation-requests <RUN>/preparation-001/generation-requests.json --manifest <RUN>/delivery-input.pending.yaml
```

This handles the prepared page count without a fixed five-page or twenty-page
assumption. `--check-only` makes no writes. Finalization does not modify images,
promote a candidate, invent visual acceptance or generate an archive.

```powershell
python <SKILL>/scripts/production_delivery.py --manifest <RUN>/delivery-input.yaml --output-dir <RUN>/delivery --check-only
python <SKILL>/scripts/production_delivery.py --manifest <RUN>/delivery-input.yaml --output-dir <RUN>/delivery
```

The command validates actual files/hashes, required evidence, complete page IDs,
and the hash-bound complete storyboard handoff recorded by preparation,
dimensions and canonical uniqueness before packaging. Failed/pending checks
produce diagnostics, never a completed comic archive. An accepted set gets one
reader, one archive and an aggregate report, with all source/crop deviations and
`published: false`. Packaging copies current final PNGs; it does not edit bases
or finals. Diagnostic test fixtures require `--diagnostic` and cannot enter a
normal comic delivery. Record measured generation/retry/local-processing time
to compare later runs; do not promise a fixed speedup from offline tests.
