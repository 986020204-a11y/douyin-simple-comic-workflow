# Production 0.8.1-rc.1 verification

This version packages the bounded production queue and the reusable actual-image
runtime/finalizer. New regression tests live under `regression/production/`;
historical `tests/`, `examples/`, `delivery/`, source templates and previews are
preserved. Test assets are temporary diagnostic fixtures, never comic artwork.

Run the portable regression from the repository root:

```sh
python -m pip install -r requirements.txt
python -B -m unittest discover -s regression/production -p 'test_*.py' -v
```

The regression covers complete declared source/quote coverage, proof evidence,
actual reference-image dispatch, bounded concurrency, claim ownership, attempt
limits, lease recovery, stale inputs, reuse of intact assets, text-only repair,
pilot gating, immutable plans, uniform-cover geometry, affine bubble polygons,
known/unknown tail ownership, reviewed scene repairs, actual font raster evidence,
source semantics, complete-page finalization and rejection of misleading passes.

The verification summary records the checks actually run for this package.
Structural library checks remain separate from actual-artwork acceptance. No
claim is made that all 68 layouts' real artwork, special effects, original font
or source-preview pixels match. Existing unsupported complex text treatments
remain blocked.

An isolated read-only source-plan comparison of the previous completed 20-page
run exposes one undeclared post-freeze system-caption wrapper/range change on
P09; the other 19 pages' text plans agree. Current complete acceptance also
requires the new per-page full/mobile review provenance and a separately saved
story review. The legacy records are not current acceptance evidence, so no
legacy page is promoted or treated as newly approved by this verification.
The old comic is not edited or retrospectively approved by this upgrade. The
new validation record contains counts and scope only, not private story images
or source copy. This rejection is evidence that immutable source checks work,
not a claim that the old run passes the new release gate.

The normal production delivery channel currently requires source-linked text on
each page. Fully silent pages with no executable text containers remain blocked;
the workflow does not invent bubbles to bypass that limitation.

Generation providers, model queue times and successful real-image retries were
not benchmarked by these offline tests. Bounded parallelism and reuse remove
avoidable work, but no fixed time reduction is promised. Human visual acceptance
must still be explicitly recorded for each real production run.
