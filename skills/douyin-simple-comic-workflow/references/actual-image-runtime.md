# Actual image runtime

Use this after the complete production preflight has frozen generation plans and
targets and the queue has returned actual scene images. The helpers are offline:
they consume existing images, execute geometry, compose text and check evidence.
They never call an image provider, decide what a person looks like, or create a
visual review. Source SB files and old comic runs remain unchanged.

## Per-page commands

All paths below are examples. `--run-root` is the explicit new isolated run;
`--manifest` is its existing production manifest from
[production-workflow.md](production-workflow.md). Page entries use the existing
`template_path`, `text_plan_path` and `text_layout_path`, relative to that manifest.
No fixed story, page count or installed-skill path is embedded in the scripts.

```powershell
python <SKILL>/scripts/production_runtime.py assemble --run-root <RUN> --manifest <RUN>/production.yaml --page P01 --state <RUN>/production-state.json
python <SKILL>/scripts/production_runtime.py fit --run-root <RUN> --manifest <RUN>/production.yaml --page P01 --record <RUN>/reports/P01-text-fit.json
python <SKILL>/scripts/production_runtime.py finish --run-root <RUN> --manifest <RUN>/production.yaml --page P01 --annotations <RUN>/reports/P01-actual-annotations.json
python <SKILL>/scripts/production_runtime.py promote --run-root <RUN> --manifest <RUN>/production.yaml --page P01 --review <RUN>/reports/P01-visual-final-check.json
```

`fit` is optional. `assemble` uses intact registered queue assets when `--state`
is supplied and rechecks readiness/template bindings. For existing run migration,
each page can declare `asset_paths: {P01: pages/assets/P01-P01-scene.png}` or an
`asset_path` on its existing `assets` entries. Without these, the compatible
filename is `pages/assets/<PAGE_ID>-<UNIT_ID>-scene.png`. Repair overrides come
from `pages/asset-overrides.json`; unreviewed, changed or outside-run edits block
assembly. Original scene assets are preserved.

The executor owns all panel borders, masks, nested units and declared overlays.
The base audit uses its raster samples and visible content evidence rather than
copying the target bounds as an observation. `asset_cover_adaptations` records
the exact clipped fit envelope, including polygon overhangs, uniform scale and
crop; `stretched` stays false. Image content, character identity and composition
still require an actual visual check. Unsupported special mechanisms remain
blocked by the existing executor/audit; no substitute generic grid is made.

`assemble` refuses an existing base. Subsequent stages preserve base pixels and
check its hash. A failed candidate remains diagnostic; use a new isolated attempt
to replace a base or a promoted final. `finish` may rebuild an unpromoted candidate
after an explicit text fit. The canonical final is created only by `promote`.

## Frozen and actual files

The input generation plan, target and manifest are never edited. The first stage
creates `plans/actual/<PAGE_ID>.yaml` and
`executed-targets/<PAGE_ID>-<SB_ID>.yaml`, recording their frozen input paths and
hashes. Later calls reject changed generation inputs, panel geometry/style or
story text/ownership. The actual plan binds its real annotations. A changed font
or story requires a new generation/preparation input rather than an undisclosed
runtime rewrite.

Actual text geometry is a workflow adaptation, never source-preview evidence.
An explicit fit record uses normalized bounds internally and pixels externally:

```yaml
page_id: P01
base_image_sha256: "current real base hash"
approved_for_run: true
origin: workflow_adaptation
reason: "Describe the observed obstruction and the permitted geometry adjustment."
bubble_bounds_px:
  B01: [40, 60, 420, 200]
# Optional: re-fit existing typography regions without adding/reordering them.
# Otherwise they receive the same affine transform as the body bounds.
bubble_typography_regions_px:
  B01: [[50, 70, 400, 70], [50, 150, 400, 90]]
```

The example only illustrates the schema; it is not acceptance evidence. The body
polygon receives exactly the bounds' affine transform. Existing observed tail
geometry moves with the body, and existing typography regions move with it unless
their explicit fit is supplied. The region count and order stay fixed. Bounds
cannot leave their owning actual panel. Genuine executable canvas text zones keep
their explicit `CANVAS` binding; this does not create a full-page default bubble.

## Actual base annotations

Draw/measure on the generated base, after assembly and before text. Required
fields are `page_id`, current `base_sha256`, `actual_image_checked: true`,
`geometry_visually_checked: true`, `visible_panel_count`, actual `reading_order`,
and one `panels` entry per actual panel. Never reuse a synthetic proof's regions
as real faces or speakers. Every panel must measure or explicitly confirm absence
of `face`, `hands`, and `key_props`:

```yaml
page_id: P01
base_sha256: "current real base hash"
actual_image_checked: true
geometry_visually_checked: true
visible_panel_count: 1
reading_order: [P01]
panels:
  P01:
    avoid_region_rects:
      face_N01: [430, 390, 180, 180]
      hands_N01: [420, 700, 200, 120]
      key_props_document: [400, 880, 240, 160]
    confirmed_absent_regions: []
    speakers: {N01: [430, 390, 180, 180]}
    observed: ["Concrete observations of this actual panel and character."]
    inferred_extra_protection: []
allow_observed_tail_tip_adaptation: true
tail_tip_adaptation:
  approved_for_run: true
  origin: workflow_adaptation
  reason: "The observed source tail belongs to this confirmed visible same-panel speaker."
style_notes: ["Actual style/composition observations; no exact preview-font claim."]
mechanisms: {}
```

An observed speaker tail can move only its identified existing tip to the confirmed
speaker region. Tail body vertices remain unchanged during that tip adjustment.
Unknown tail modes, prop labels and UI nibs are never assigned a speaker direction
by this helper. Missing required ownership remains blocked. A bare
`allow_observed_tail_tip_adaptation: true` is insufficient without the reasoned
adaptation record. Required special mechanisms carry their actual `status`, named
`reviewer` and concrete `evidence` in `mechanisms`; the helper never invents them.

`finish` replaces synthetic placeholders, preflights the executed target,
composes a candidate, audits real text/bubble pixels and font evidence, then runs
the final full-template audit. It creates the 360×480 mobile preview. Successful
mechanical checks leave `visual_review_status: pending`; they do not imply visual
acceptance. Source-preview fidelity stays failed when an approved target crop or
text adaptation differs from the source.

## Explicit review and promotion

Review the full-size candidate and its mobile preview. Supply an actual review
file with `page_id`, `review_status: passed`, nonempty `reviewer` and `notes`,
`synthetic: false`, `actual_image_checked: true`, `mobile_image_checked: true`, and
the current `image_sha256`, `base_image_sha256`, `mobile_image_sha256`.
The `checks` mapping must explicitly pass all seven:

- `mobile_readability`
- `character_continuity`
- `speaker_binding`
- `text_integrity`
- `critical_occlusion`
- `full_template_execution`
- `execution_style_match`

Its `evidence_files` map binds each current report as `{path, sha256}`:
`render_report`, `bubble_audit`, `font_raster`, `base_audit`, `final_layout_audit`.
Its `input_bindings` list includes the actual plan, executed target and annotation
file with their current `{path, sha256}`. These fields are required observations
and hashes, not a template for automatically marking every check passed.

Promotion independently validates the render, bubble raster and final layout
reports as well as the supplied review. It copies only the reviewed candidate to
`pages/final/<PAGE_ID>-final.png`, then writes the compatible
`reports/<PAGE_ID>-production-review.json`. Use this report for queue
`accept-pilot` and the delivery manifest's `visual_review`. It never overwrites a
different canonical final. Whole-story coverage, page count reconciliation and
story review are still required by the delivery/finalize stage.

The translated production review preserves the supplied reviewer/observations,
adds `review_binding` for that original review, and binds the checked mobile PNG
as `mobile_image: {path, sha256}`. These are provenance fields for existing
evidence, not new visual observations. Normal queue and delivery validation require
the same current full/mobile, actual plan/target/annotation, font and layout
bindings; bare passed checkboxes or explicitly diagnostic records cannot replace
them.

## Preserve and register scene repairs

After an actual image edit has returned, create a record inside the run with
`page_id`, `unit_id`, nonempty `reason`, `original_path`, `generated_source_path`
and separate `saved_path`. Only the returned source may live outside the run.

```powershell
python <SKILL>/scripts/scene_repairs.py save --run-root <RUN> --record <RUN>/reports/P01-P01-repair.json
python <SKILL>/scripts/scene_repairs.py register --run-root <RUN> --record <RUN>/reports/P01-P01-repair.json --review <RUN>/reports/P01-P01-repair-review.json
```

Saving verifies the images, preserves originals, writes both hashes and always
sets `actual_edit_reviewed: false` / `review_status: pending`. A separate review
must name the same page/unit, declare `review_status: passed`,
`actual_image_checked: true`, `synthetic: false`, a `reviewer` and concrete `notes`,
and bind `repair_record_sha256`, `original_sha256`, and `edited_sha256`.
Registration hashes this review and the repair record in the override; assembly
and finish recheck them. A legacy v0.8 override is accepted only with its original
and edit hashes plus a linked same-job repair record containing explicit manual
`visual_review_notes` and `actual_edit_reviewed: true`. A boolean alone fails.

These helpers do not alter accepted pages to use later repairs. Reassemble only
inside a new isolated attempt. Diagnostic inputs propagate
`diagnostic_test_only: true`; their files cannot serve as production acceptance.
