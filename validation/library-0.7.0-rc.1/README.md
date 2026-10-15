# Library 0.7.0-rc.1 verification

The remaining 63 source layouts were annotated individually; the library now contains all 68 structured templates. Source preview/note hashes, native dimensions, geometry, order, text ownership and uncertainty are recorded with each template. Original preview images were not modified.

- 68/68 templates parse and pass required-field, binding and index validation.
- 68/68 source-native geometry diagnostics pass with synthetic grid assets.
- 272/272 blank-image, hash-rebinding, deleted-panel and shifted-panel cases fail as required.
- Deleting SB-016's partial divider also fails after rebinding the PNG hash.
- 14/14 focused text-renderer and existing-five regression checks pass; existing-five regression covers 38 text instances.
- Full real-artwork acceptance for the newly annotated 63 layouts remains untested.

Known text-renderer blockers: SB-006, SB-040, SB-041, SB-042, SB-043, SB-044, SB-045, SB-046, SB-057. Unsupported rotation or composite color regions block preflight/rendering rather than silently falling back to ordinary boxes. Other layouts still require actual speaker/carrier ownership, safety, capacity and special-mechanism verification.

The source annotations are manually traced with explicit uncertainty, not original-preview pixel identity. Approved 3:4 cover is separately reported as adaptation. Synthetic diagnostics are not comic illustrations and do not establish real-story acceptance. Historical examples elsewhere in this repository keep their original validation scope.

Reproduce structural validation from the repository root:

```sh
python -m pip install -r requirements.txt
python skills/douyin-simple-comic-workflow/scripts/check_executable_templates.py --root skills/douyin-simple-comic-workflow/references/comic-layouts --output .validation/templates.json --check-index
python skills/douyin-simple-comic-workflow/scripts/verify_template_library.py --root skills/douyin-simple-comic-workflow/references/comic-layouts --output .validation/geometry
```

Runtime Python: 3.10 or newer. Structural diagnostics do not require a Windows font. Real Chinese text composition requires a configured font file; Windows defaults use Microsoft YaHei, and the bundled Ma Shan Zheng font is reserved for explicitly selected brush lettering with its OFL license.
