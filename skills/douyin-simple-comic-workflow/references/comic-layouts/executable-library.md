# Executable source library v0.7

`executable-templates/SB-001.yaml` through `SB-068.yaml` describe the real paired preview and source note. `template-index.yaml` records each count, source evidence, review status, and validation scope. A valid annotation is an executable contract to test; it is not evidence that a generated story obeyed it.

## Source geometry and evidence

Keep the source-native canvas, file hashes, content ROI, continuous reading order, individual bounds, traced polygons, ellipse masks, inset parents, layers, and visible frame segments. Visible existence/shape is `observed`; numeric hand tracing and hidden contour completion are `inferred` with source-pixel tolerance. Original font, new-story speaker/prop identity, invisible tails, and unknown Bezier controls remain `unknown`. Safety constraints, allowed semantic types, renderer choices, and fallback policies are workflow decisions marked inferred.

Count distinct narrative image units, including genuine inset and unframed narrative scenes. Separately retain the visible bordered count and source-numbered-group count where they differ. A physical mirror partition, book fold, backing sheet, or corkboard is not automatically another panel. An independent central unframed scene can be a unit; its transparent silhouette must not become an opaque rectangular replacement.

`geometry_type` supports `rect`, `polygon`, `approximate_polygon`, `ellipse`, `unframed`, `phone_column`, and `inset_scene`. `border.visible: false` or `border_visible: false` prevents invented outlines. `structure.frame_segments` describes partial dividers, while `shared_canvas_art` declares genuine continuous panorama requirements. Per-panel asset placement alone cannot prove continuous panorama or foreground crossings.

## Text instances

Every raw `bubbles` item binds a real `panel_id`. Include all visible authored instances rather than a single style sample. No visible source balloon means no invented balloon. Preserve unboxed lettering as `display_text`; it is not a caption rectangle.

For genuine story lettering outside the image units, use `text_zones` with unique `zone_id`, `executable: true`, `scope: canvas`, `canvas_binding_id: CANVAS`, and `panel_id: null`. Retain bounds, shape, types, tail, avoidance, visual style, and field evidence. `template_contract.executable_text_containers()` projects such instances to runtime `TZ-<zone_id>` IDs with `panel_id: CANVAS`; it does not add CANVAS to source `panels` or fabricate a source bubble. Instructional headers and sample-number strips remain explicit non-executable decorations. Panel-scoped zones bind existing panels.

`tail.mode: observed_dots` contains individual thought-dot `bounds` in template-normalized coordinates and an observed anchor. Execute the actual dots and verify visible changed pixels; never substitute a speech triangle. Unknown thought ownership remains unresolved until a real same-panel owner is confirmed.

`preview_surface_text` writes ink onto a confirmed physical surface without drawing a new carrier or balloon. Runtime carrier evidence requires its identity, same-panel binding, polygon, writable region, and matching actual base-image hash. Do not reinterpret semantic `note` as a renderer name. A source surface annotation cannot establish the carrier location in newly generated art.

Source-observed overflow must be explicit. Canvas text and allowed overflow require full-page protected-region evidence, including all affected panels; same-panel-only avoidance is insufficient. Preserve protection of faces, hands, and key props. Unknown ownership or unsafe placement blocks composition.

## Validation and acceptance

Run `scripts/check_executable_templates.py` for source set, hashes, native dimensions, required fields, unique IDs, continuous order, binding, evidence, and constraints. Run `scripts/verify_template_library.py` for deterministic native geometry using clearly marked synthetic assets in a new isolated output directory. Diagnostic geometry diagrams are not new comic illustrations.

The actual geometry audit requires PNG-bound pixel evidence. Unframed areas require visible asset pixels; metadata-only regions cannot pass. Unknown overlays are not drawn as placeholder rectangles. `execution_requirements` may be a list of named `mechanism`/`feature` entries or a mapping with `required_mechanisms`; each unresolved requirement blocks `full_template_execution`. Real acceptance still requires every text instance, final-text audits, required effects, source uncertainty review, and an actual-image pilot.

Multi-region fill/text colors and rotated glyphs require their own renderer; an unsupported treatment blocks text preflight and rendering. Basic observed color families use a declared implementation palette, not a claim of original pixel equality. A plain white fill or horizontal ordinary font is not an implicit replacement for a complex source treatment.

For approved 3:4 full bleed, use the separate cover adaptation. It preserves executable page text, overlays, and frame segments and records clipping/reflow. A clipped ellipse becomes a clipped polygon rather than a squeezed oval. If cropping would delete a unit, stop that adaptation. `storyboard_layout_match` and source geometry must stay failed for an adapted result even when its target execution passes.

Do not overwrite source previews, completed prior templates, old comic outputs, or historical proof directories while upgrading this library. Do not use a preview itself as the alleged generated no-text base. Never claim all 68 templates passed real artwork testing from schema or synthetic diagnostics.
