# Passing sample: tests/e2e-001

This is the first verified run for v0.1. It demonstrates the workflow with a new story and a new character namespace; the names and page count are not defaults.

- Input: `tests/e2e-001/source/article.md`
- New characters: N01, N02, N03; actual reference sheets are under `tests/e2e-001/characters/`
- Pages: 3
- E01: 3 panels, `SB-003` (establish rain, raincoat handoff, Xiaoyu's turn)
- E02: 4 panels, `SB-027` (turn back, retrieve umbrella, share umbrella, walk back); the fourth panel has a recorded reading problem and insufficiency reason
- E03: 2 panels, `SB-054` (next-day placement and quiet open ending)
- Base renders: `tests/e2e-001/pages/renders/`
- Final post-layout PNGs: `tests/e2e-001/pages/final/`
- Continuity/technical report: `tests/e2e-001/reports/continuity-technical-report.yaml`
- Delivery manifest: `tests/e2e-001/delivery/manifest.yaml`

The run passed structural, image-existence, size, post-layout text, story-order, and continuity checks. A minor N01 hair-shape difference in one angle was recorded as an acceptable visual variation. New references remain `not-reviewed` until a person approves them. The run did not modify the old P01–P04 assets or publish anywhere.
