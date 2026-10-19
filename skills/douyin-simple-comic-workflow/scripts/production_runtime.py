#!/usr/bin/env python3
"""Bridge frozen production inputs to independently reviewed actual comic pages.

Offline only: assemble existing assets, apply declared text geometry fits, bind
measured real regions, compose/audit, and promote an explicitly reviewed result.
No image generation or automatic visual acceptance occurs in this module.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
from pathlib import Path
import re
import shutil

from PIL import Image
import yaml

import audit_preview_bubbles as bubble_auditor
import audit_storyboard_layout as layout_auditor
import layout_executor as executor
import preflight_preview_text as text_preflight
import production_queue as queue
import scene_repairs as repairs
import text_compositor as compositor
from template_contract import executable_text_containers


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "references/comic-layouts"
CHECKS = queue.FINAL_CHECKS


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
                    if path.suffix.lower() in {".yaml", ".yml"} else
                    json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def binding(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": repairs.digest(path)}


def rect(value, label: str) -> list[float]:
    require(isinstance(value, (list, tuple)) and len(value) == 4, f"{label}: explicit xywh required")
    require(all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                for v in value), f"{label}: finite numeric xywh required")
    require(min(value[2:]) > 0, f"{label}: empty bounds")
    return list(value)


def contained(inner: list, outer: list, tolerance: float = 1.1) -> bool:
    x, y, w, h = inner
    a, b, c, d = outer
    return x >= a-tolerance and y >= b-tolerance and x+w <= a+c+tolerance and y+h <= b+d+tolerance


def affine_polygon(polygon: list, before: list, after: list) -> list:
    """The body polygon must undergo exactly the bounds' affine transform."""
    rect(before, "source bubble")
    rect(after, "fitted bubble")
    require(isinstance(polygon, list) and len(polygon) >= 3, "Body polygon requires at least three vertices")
    result = []
    for point in polygon:
        require(isinstance(point, (list, tuple)) and len(point) == 2
                and all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in point),
                "Invalid polygon vertex")
        result.append([after[0] + (point[0]-before[0])*after[2]/before[2],
                       after[1] + (point[1]-before[1])*after[3]/before[3]])
    return result


def mutable_containers(template: dict) -> dict[str, dict]:
    """Return actual target records, not the resolver's defensive deep copies."""
    result = {b["bubble_id"]: b for b in template.get("bubbles", [])}
    projected = {b["bubble_id"]: b for b in executable_text_containers(template)}
    for zone in template.get("text_zones", []) or []:
        if zone.get("executable") is not True:
            continue
        zid = zone.get("zone_id") or zone.get("text_zone_id")
        bid = f"TZ-{zid}"
        # These are explicit runtime projections of genuine source text zones,
        # never new story bubbles/panels or source-annotation changes.
        for key, value in projected[bid].items():
            zone.setdefault(key, copy.deepcopy(value))
        result[bid] = zone
    return result


def cover_fit(unit: dict, source_size: tuple[int, int], canvas: tuple[int, int]) -> dict:
    """Report the exact executor fit envelope, including polygon overhangs."""
    if unit.get("polygon"):
        xs, ys = zip(*unit["polygon"])
        bounds = [min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys)]
    else:
        bounds = [unit[k] for k in ("x", "y", "width", "height")]
    box = executor._clip_box(bounds, *canvas)
    width, height = box[2]-box[0], box[3]-box[1]
    require(width > 0 and height > 0, "Empty executor fit envelope")
    scale = max(width/source_size[0], height/source_size[1])
    return {"unit_id": unit["unit_id"], "asset_size": list(source_size),
            "target_size": [width, height], "target_pixel_envelope_xyxy": list(box),
            "uniform_scale": scale, "crop_after_scale_xy": [max(0, (source_size[0]*scale-width)/2),
                                                          max(0, (source_size[1]*scale-height)/2)],
            "stretched": False, "policy": "uniform_scale_cover"}


def rebind_known_tip(bubble: dict, speaker: list, canvas: tuple[int, int]) -> dict | None:
    """Only observed speaker tails may move; unknown ownership stays unknown."""
    tail = bubble.get("tail") or {}
    if tail.get("mode") != "observed_polygon":
        return None
    require(tail.get("anchor_kind", "speaker") == "speaker", "Only confirmed speaker tails can be rebound")
    require(tail.get("anchor") and tail.get("polygon"), "Observed tail lacks its actual polygon/anchor")
    require(tail.get("coordinate_space", "template_normalized") in
            {"template_normalized", "final_canvas_px"}, "Unsupported tail coordinate space")
    scale = (1, 1) if tail.get("coordinate_space") == "final_canvas_px" else canvas
    old = [tail["anchor"][i]*scale[i] for i in range(2)]
    x, y, w, h = rect(speaker, "confirmed visible speaker")
    bx, by, bw, bh = [v*s for v, s in zip(bubble["bounds"], [*canvas, *canvas])]
    cx, cy = bx+bw/2, by+bh/2
    candidates = [[x, max(y, min(y+h, cy))], [x+w, max(y, min(y+h, cy))],
                  [max(x, min(x+w, cx)), y], [max(x, min(x+w, cx)), y+h]]
    new = min(candidates, key=lambda q: math.dist(q, [cx, cy]))
    if math.dist(old, new) < 2:
        return None
    tip = min(range(len(tail["polygon"])),
              key=lambda i: math.dist(old, [tail["polygon"][i][j]*scale[j] for j in range(2)]))
    require(math.dist(old, [tail["polygon"][tip][j]*scale[j] for j in range(2)]) <= 3,
            "Known anchor does not identify a unique observed tail tip")
    tail["polygon"][tip] = [new[i]/scale[i] for i in range(2)]
    tail["anchor"] = [new[i]/scale[i] for i in range(2)]
    tail["anchor_evidence"] = "workflow_actual_visible_speaker_adaptation"
    return {"kind": "known_tail_tip_actual_speaker_fit", "bubble_id": bubble["bubble_id"],
            "old_tip_px": old, "new_tip_px": new, "speaker_region_px": speaker,
            "evidence": "workflow_adaptation_not_source_observation"}


class Runtime:
    def __init__(self, run_root: Path, manifest_path: Path, page_id: str, state_path: Path | None = None):
        self.root = run_root.resolve()
        require(self.root.is_dir(), "Explicit existing isolated run root required")
        require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", page_id)), "Unsafe page ID")
        self.pid = page_id
        self.manifest_path = repairs.inside(self.root, manifest_path)
        self.manifest = repairs.read(self.manifest_path)
        pages = [p for p in self.manifest.get("pages", []) if p.get("page_id") == page_id]
        require(len(pages) == 1, "Page must occur exactly once in production manifest")
        self.page = pages[0]
        self.generation_plan = self.input(self.page["text_plan_path"])
        self.generation_target = self.input(self.page["template_path"])
        self.config = self.input(self.page["text_layout_path"])
        self.plan, self.target = repairs.read(self.generation_plan), repairs.read(self.generation_target)
        require(self.plan.get("page_id") == self.pid, "Text plan page ID differs from manifest")
        self.layout_id = self.target["layout_id"]
        require(bool(re.fullmatch(r"SB-\d{3}", self.layout_id)), "Invalid layout ID")
        self.contract = executor.compile_template_contract(self.target)
        self.canvas = tuple(self.contract["canvas"][k] for k in ("width", "height"))
        require(self.canvas == (1080, 1440), "Production pages must use 1080x1440 approved geometry")
        self.state_path = repairs.inside(self.root, state_path) if state_path else None

    def input(self, value: str | Path) -> Path:
        path = Path(value)
        return repairs.inside(self.root, path if path.is_absolute() else self.manifest_path.parent/path)

    def out(self, name: str) -> Path:
        return repairs.inside(self.root, name)

    def report(self, name: str) -> Path:
        return self.out(f"reports/{self.pid}-{name}")

    def write(self, path: Path, value: dict) -> None:
        if self.manifest.get("diagnostic_test_only") is True:
            value["diagnostic_test_only"] = True
        write(path, value)

    @property
    def base(self) -> Path:
        return self.out(f"pages/renders/{self.pid}-base.png")

    @property
    def candidate(self) -> Path:
        return self.out(f"pages/candidates/{self.pid}/checked-render.png")

    @property
    def canonical(self) -> Path:
        return self.out(f"pages/final/{self.pid}-final.png")

    def unpromoted(self) -> None:
        require(not self.canonical.exists(), "Preserve promoted final; use a new isolated attempt for revisions")

    def actual_files(self) -> tuple[Path, dict, Path, dict]:
        pp = self.out(f"plans/actual/{self.pid}.yaml")
        tp = self.out(f"executed-targets/{self.pid}-{self.layout_id}.yaml")
        require(pp.exists() == tp.exists(), "Incomplete actual plan/target pair; inspect before continuing")
        if not pp.exists():
            actual = copy.deepcopy(self.plan)
            actual.update(generation_plan_path=str(self.generation_plan),
                          generation_plan_sha256=repairs.digest(self.generation_plan),
                          generation_template_path=str(self.generation_target),
                          generation_template_sha256=repairs.digest(self.generation_target),
                          execution_template_path=str(tp), production_manifest_binding=binding(self.manifest_path))
            self.write(tp, copy.deepcopy(self.target))
            self.write(pp, actual)
        p, t = repairs.read(pp), repairs.read(tp)
        require(p.get("generation_plan_sha256") == repairs.digest(self.generation_plan)
                and p.get("generation_template_sha256") == repairs.digest(self.generation_target),
                "Frozen generation plan/target changed")
        require(p.get("production_manifest_binding") == binding(self.manifest_path), "Frozen production manifest changed")
        require(t.get("layout_id") == self.layout_id, "Executed target changed layout identity")
        text_fit_fields = {"bubbles", "text_zones", "source_target_deviation", "match_policy",
                           "user_approved_adaptation", "diagnostic_test_only"}
        require({k: v for k, v in t.items() if k not in text_fit_fields} ==
                {k: v for k, v in self.target.items() if k not in text_fit_fields},
                "Actual text fit cannot change frozen panel geometry, style or mechanisms")
        compiled = executor.compile_template_contract(t)
        require(compiled["panel_geometry"] == self.contract["panel_geometry"]
                and compiled.get("nested_units") == self.contract.get("nested_units"),
                "Actual text fit cannot change frozen panel geometry/order")
        original = self.plan.get("text_blocks", [])
        actual = p.get("text_blocks", [])
        keys = ("id", "text", "type", "source_type", "speaker", "panel_id", "source_article_range",
                "font_size", "font_size_policy", "bubble_id")
        require([{k: b.get(k) for k in keys} for b in original] ==
                [{k: b.get(k) for k in keys} for b in actual], "Actual plan changed frozen story text/ownership")
        return pp, p, tp, t

    def audit(self, target: dict, actual: dict) -> dict:
        contract = executor.compile_template_contract(target)
        contract.update(match_policy=target.get("match_policy", "structure_exact"),
                        user_approved_adaptation=target.get("user_approved_adaptation", False),
                        canvas_transform=target.get("canvas_transform"))
        return layout_auditor.audit({"selected_layout": self.layout_id, "execution_contract": contract},
                                    actual, self.base,
                                    template=repairs.read(LIBRARY/f"executable-templates/{self.layout_id}.yaml"),
                                    preview=LIBRARY/f"previews/{self.layout_id}.webp")

    def assets(self) -> tuple[dict[str, str], list[dict]]:
        units = self.contract["panel_geometry"] + self.contract.get("nested_units", [])
        wanted = {u["unit_id"] for u in units if u.get("geometry_type") != "phone_column"}
        assets = {}
        if self.state_path:
            state = repairs.read(self.state_path)
            require(state.get("diagnostic_test_only") is not True
                    or self.manifest.get("diagnostic_test_only") is True,
                    "Diagnostic queue assets cannot enter a normal production runtime")
            require(self.pid in state.get("pages", {}), "Queue does not contain this page")
            require(state["pages"][self.pid]["template_binding"] == binding(self.generation_target),
                    "Queue template is not this frozen target")
            queue._check_binding(state["manifest_binding"], self.state_path.parent)
            page = state["pages"][self.pid]
            queue._validate_proof(page["proof_binding"], page["template_binding"],
                                  diagnostic=state.get("diagnostic_test_only") is True)
            for job in state.get("jobs", {}).values():
                if job.get("page_id") != self.pid:
                    continue
                require(job.get("status") == "generated_unreviewed" and queue._asset_intact(job),
                        f"Queue asset not generated/intact: {job.get('job_id')}")
                assets[job["unit_id"]] = str(repairs.inside(self.root, job["asset"]["path"]))
        else:
            explicit = self.page.get("asset_paths") or {}
            for row in self.page.get("assets", []):
                if row.get("asset_path"):
                    explicit = {**explicit, row["unit_id"]: row["asset_path"]}
            assets = {uid: str(self.input(path)) for uid, path in explicit.items()}
            for uid in wanted:
                assets.setdefault(uid, str(self.out(f"pages/assets/{self.pid}-{uid}-scene.png")))
        require(wanted.issubset(assets), f"Assets missing executable units: {sorted(wanted-set(assets))}")
        for path in assets.values():
            repairs.image_ok(Path(path))
        overrides_path = self.out("pages/asset-overrides.json")
        overrides = repairs.read(overrides_path) if overrides_path.exists() else {}
        used = []
        for uid, original in list(assets.items()):
            key = f"{self.pid}/{uid}"
            if key in overrides:
                assets[uid] = str(repairs.resolve_repair(self.root, key, Path(original), overrides[key]))
                used.append({"job_id": key, **copy.deepcopy(overrides[key])})
        return assets, used

    def assemble(self) -> dict:
        self.unpromoted()
        require(not self.base.exists(), "Preserve existing base; create a new isolated attempt")
        self.actual_files()  # freeze the original inputs before raster assembly
        assets, overrides = self.assets()
        actual = executor.render_layout(self.target, self.base, assets=assets, strict_assets=True)
        actual["actual_scene_repairs"] = overrides
        actual["scene_asset_bindings"] = {uid: binding(Path(path)) for uid, path in assets.items()}
        actual["scene_repair_bindings"] = []
        if overrides:
            actual["scene_repair_bindings"].append(binding(self.out("pages/asset-overrides.json")))
            for item in overrides:
                actual["scene_repair_bindings"].append(binding(repairs.inside(self.root, item["repair_record"])))
                if item.get("review_binding"):
                    actual["scene_repair_bindings"].append(item["review_binding"])
        fits = []
        for unit in self.contract["panel_geometry"] + self.contract.get("nested_units", []):
            if unit["unit_id"] not in assets:
                continue
            with Image.open(assets[unit["unit_id"]]) as image:
                fits.append(cover_fit(unit, image.size, self.canvas))
        actual["asset_cover_adaptations"] = fits
        self.write(self.report("base-actual.json"), actual)
        audit = self.audit(self.target, actual)
        self.write(self.report("base-layout-audit.json"), audit)
        require(audit["execution_geometry_match"] == "passed", str(audit["layout_deviation"]))
        return {"page_id": self.pid, "base": str(self.base), "base_sha256": repairs.digest(self.base),
                "execution_geometry_match": audit["execution_geometry_match"],
                "storyboard_layout_match": audit["storyboard_layout_match"], "base_image_modified": False}

    def fit(self, fit_path: Path) -> dict:
        self.unpromoted()
        fit_path = repairs.inside(self.root, fit_path)
        fit = repairs.read(fit_path)
        require(fit.get("approved_for_run") is True and fit.get("origin") == "workflow_adaptation"
                and isinstance(fit.get("reason"), str) and fit["reason"].strip()
                and fit.get("page_id") == self.pid and fit.get("base_image_sha256") == repairs.digest(self.base),
                "Actual text fit needs explicit run approval, origin, reason and current base hash")
        pp, plan, tp, target = self.actual_files()
        bubbles = mutable_containers(target)
        panels = {u["panel_id"]: [u[k] for k in ("x", "y", "width", "height")]
                  for u in executor.compile_template_contract(target)["panel_geometry"]}
        fits = fit.get("bubble_bounds_px")
        require(isinstance(fits, dict) and bool(fits), "Explicit nonempty bubble_bounds_px mapping required")
        for bid, box in fits.items():
            require(bid in bubbles, f"Unknown bubble {bid}")
            bubble = bubbles[bid]
            box = rect(box, bid)
            panel_box = ([0, 0, *self.canvas] if bubble.get("canvas_binding_id") == "CANVAS"
                         else panels[bubble["panel_id"]])
            require(contained(box, panel_box), "Bubble cannot cross its actual panel boundary")
            before = copy.deepcopy(bubble["bounds"])
            after = [v/s for v, s in zip(box, [*self.canvas, *self.canvas])]
            bubble["bounds"] = after
            if bubble.get("polygon"):
                bubble["polygon"] = affine_polygon(bubble["polygon"], before, after)
                bubble["polygon_fit_evidence"] = "workflow_actual_image_body_polygon_same_transform"
            declared_regions = fit.get("bubble_typography_regions_px", {}).get(bid)
            if declared_regions is not None:
                require(isinstance(declared_regions, list)
                        and len(declared_regions) == len(bubble.get("typography_regions", [])),
                        "A typography fit preserves the existing region count/order")
            for index, region in enumerate(bubble.get("typography_regions", [])):
                old = rect(region["bounds"], "existing typography region")
                space = region.get("coordinate_space", "template_normalized")
                require(space in {"template_normalized", "final_canvas_px"}, "Unsupported typography coordinate space")
                if space == "final_canvas_px":
                    old = [v/s for v, s in zip(old, [*self.canvas, *self.canvas])]
                if declared_regions is not None:
                    new = rect(declared_regions[index], "explicit typography fit")
                    new = [v/s for v, s in zip(new, [*self.canvas, *self.canvas])]
                else:
                    new = [after[0]+(old[0]-before[0])*after[2]/before[2],
                           after[1]+(old[1]-before[1])*after[3]/before[3],
                           old[2]*after[2]/before[2], old[3]*after[3]/before[3]]
                require(contained(new, after, tolerance=0.00001), "Typography region leaves fitted body")
                region.update(bounds=new, coordinate_space="template_normalized",
                              evidence="workflow_actual_image_fit_adaptation")
            # Tail bases move with their body. Its observed tip is subsequently
            # rebound only with an explicit same-panel speaker adaptation.
            tail = bubble.get("tail") or {}
            if tail.get("mode") == "observed_polygon" and tail.get("polygon"):
                scale = (1, 1) if tail.get("coordinate_space") == "final_canvas_px" else self.canvas
                normalized = [[q[i]*scale[i]/self.canvas[i] for i in range(2)] for q in tail["polygon"]]
                moved = affine_polygon(normalized, before, after)
                tail["polygon"] = [[q[i]*self.canvas[i]/scale[i] for i in range(2)] for q in moved]
                if tail.get("anchor"):
                    q = [tail["anchor"][i]*scale[i]/self.canvas[i] for i in range(2)]
                    q = [after[i]+(q[i]-before[i])*after[i+2]/before[i+2] for i in range(2)]
                    tail["anchor"] = [q[i]*self.canvas[i]/scale[i] for i in range(2)]
            bubble["target_geometry_evidence"] = "workflow_actual_image_fit_adaptation"
            target.setdefault("source_target_deviation", []).append({"kind": "actual_text_container_fit",
                "bubble_id": bid, "source_bounds": before, "target_bounds": after,
                "reason": fit["reason"], "evidence": "workflow_adaptation_not_source_observation",
                "approval_binding": binding(fit_path)})
        plan["source_target_deviation"] = copy.deepcopy(target.get("source_target_deviation", []))
        target.update(match_policy="adapted", user_approved_adaptation=True)
        plan.update(match_policy="adapted", user_approved_adaptation=True)
        self.write(tp, target)
        self.write(pp, plan)
        return {"page_id": self.pid, "fitted_bubble_ids": list(fits), "base_image_modified": False}

    def annotations(self, path: Path, actual: dict) -> dict:
        ann = repairs.read(path)
        base_hash = repairs.digest(self.base)
        require(ann.get("page_id") == self.pid and ann.get("base_sha256") == base_hash
                and ann.get("actual_image_checked") is True and ann.get("geometry_visually_checked") is True
                and ann.get("synthetic") is not True, "Current hash-bound actual base annotations required")
        panels = actual["panel_geometry"]
        require(ann.get("visible_panel_count") == len(panels)
                and ann.get("reading_order") == actual.get("reading_order"),
                "Actual visual panel count/order does not match raster geometry")
        require(set(ann.get("panels", {})) == {u["panel_id"] for u in panels},
                "Every actual panel needs explicit real-region observations")
        for unit in panels:
            regions = ann["panels"][unit["panel_id"]]
            require(bool(regions.get("observed")), "Actual annotations require concrete observations")
            bounds = [unit[k] for k in ("x", "y", "width", "height")]
            protected = regions.get("avoid_region_rects", {})
            absent = regions.get("confirmed_absent_regions", [])
            for kind in ("face", "hands", "key_props"):
                require(kind in absent or any(key == kind or key.startswith(kind+"_") for key in protected),
                        f'{unit["panel_id"]}: missing actual {kind} measurement or confirmed absence')
            for name, box in protected.items():
                require(contained(rect(box, name), bounds), f"Protected region leaves its panel: {name}")
            for name, box in regions.get("speakers", {}).items():
                require(contained(rect(box, name), bounds), f"Speaker leaves its confirmed panel: {name}")
        return ann

    def finish(self, annotation_path: Path | None = None) -> dict:
        self.unpromoted()
        pp, plan, tp, target = self.actual_files()
        base_hash = repairs.digest(self.base)
        actual = repairs.read(self.report("base-actual.json"))
        require(actual.get("output_image_sha256") == base_hash, "Base differs from assembled raster evidence")
        queue._base_audit_valid(self.report("base-layout-audit.json"), self.base)
        for asset in actual.get("scene_asset_bindings", {}).values():
            queue._check_binding(asset, self.root, image=True)
        for item in actual.get("scene_repair_bindings", []):
            queue._check_binding(item, self.root)
        annotation_path = repairs.inside(self.root, annotation_path or self.report("actual-annotations.json"))
        ann = self.annotations(annotation_path, actual)
        panels = {u["panel_id"]: u for u in actual["panel_geometry"]}
        bubbles = mutable_containers(target)
        plan.update(synthetic=False, synthetic_input=False, actual_image_checked=True,
                    actual_scene_binding_status="actual_generated_image_viewed_and_regions_measured",
                    base_image_sha256=base_hash, actual_annotations_binding=binding(annotation_path))
        tail_approval = ann.get("tail_tip_adaptation") or {}
        if ann.get("allow_observed_tail_tip_adaptation") is True:
            require(tail_approval.get("approved_for_run") is True
                    and tail_approval.get("origin") == "workflow_adaptation" and tail_approval.get("reason"),
                    "Tail adaptation needs explicit approval, origin and reason; a bare boolean is insufficient")
        for block in plan.get("text_blocks", []):
            if block["panel_id"] == "CANVAS":
                require(bubbles[block["bubble_id"]].get("canvas_binding_id") == "CANVAS",
                        "CANVAS ownership requires an original explicit executable canvas text zone")
                unit = {"x": 0, "y": 0, "width": self.canvas[0], "height": self.canvas[1]}
                regions = {"avoid_region_rects": {}, "confirmed_absent_regions": [], "observed": []}
                for pid, panel_regions in ann["panels"].items():
                    regions["avoid_region_rects"].update({f"{key}_{pid}": value
                        for key, value in panel_regions.get("avoid_region_rects", {}).items()})
                    regions["observed"].extend(panel_regions["observed"])
                regions["confirmed_absent_regions"] = [kind for kind in ("face", "hands", "key_props")
                    if all(kind in r.get("confirmed_absent_regions", []) for r in ann["panels"].values())]
            else:
                unit, regions = panels[block["panel_id"]], ann["panels"][block["panel_id"]]
            block.pop("synthetic_owner_placeholder", None)
            block.update(synthetic_input=False, actual_regions_verified=True,
                         actual_panel_bounds=[unit[k] for k in ("x", "y", "width", "height")],
                         actual_panel_bounds_format="xywh", avoid_regions=["face", "hands", "key_props"],
                         avoid_region_rects=copy.deepcopy(regions.get("avoid_region_rects", {})),
                         confirmed_absent_regions=regions.get("confirmed_absent_regions", []),
                         actual_region_evidence={"source": "manual_visual_annotation_of_actual_generated_base",
                             "image_sha256": base_hash, "synthetic": False,
                             "annotation_binding": binding(annotation_path),
                             "observed": regions["observed"],
                             "inferred_extra_protection": regions.get("inferred_extra_protection", [])})
            # Remove synthetic speaker rectangles; retain channel identities.
            for key in ("speaker_region", "speaker_region_visibility", "speaker_panel_id"):
                block.pop(key, None)
            speaker = regions.get("speakers", {}).get(block.get("speaker"))
            if speaker:
                block.update(speaker_region=speaker, speaker_region_format="xywh", speaker_status="confirmed",
                             speaker_region_visibility="visible", speaker_panel_id=block["panel_id"])
                if ann.get("allow_observed_tail_tip_adaptation") is True:
                    change = rebind_known_tip(bubbles[block["bubble_id"]], speaker, self.canvas)
                    if change:
                        change.update(reason=tail_approval["reason"], approval_binding=binding(annotation_path))
                        target.setdefault("source_target_deviation", []).append(change)
                        target.update(match_policy="adapted", user_approved_adaptation=True)
                        plan.update(match_policy="adapted", user_approved_adaptation=True)
            elif block.get("type") == "dialogue":
                block["speaker_status"] = "unknown"
            block["bubble_contract"] = copy.deepcopy(bubbles[block["bubble_id"]])
        plan["source_target_deviation"] = copy.deepcopy(target.get("source_target_deviation", []))
        self.write(tp, target)
        self.write(pp, plan)
        check = text_preflight.preflight(target, plan, repairs.read(self.config), self.config.parent)
        self.write(self.report("actual-preflight.json"), check)
        require(check["generation_ready"], str(check["errors"]))
        report_path = self.report("render.yaml")
        report = compositor.compose_page(self.base, pp, self.config, self.candidate,
                                         report_path, self.report("placement.yaml"), self.pid)
        if self.manifest.get("diagnostic_test_only") is True:
            self.write(report_path, report)
        require(repairs.digest(self.base) == base_hash, "Base changed during composition")
        require(report["page_acceptance_status"] == "accepted", str([
            (b.get("id"), b.get("failure_reason")) for b in report.get("rendered_blocks", [])]))
        fonts = {"base_image_sha256": base_hash, "output_image_sha256": repairs.digest(self.candidate),
                 "actual_image_checked": True, "blocks": [{"block_id": b["id"],
                     "requested_font_size": b.get("requested_font_size"), "actual_font_sizes": b.get("actual_font_sizes"),
                     "font_raster_evidence": b.get("font_raster_evidence")} for b in report["rendered_blocks"]]}
        self.write(self.report("actual-font-raster.json"), fonts)
        bubble = bubble_auditor.audit(target, plan, render_report=report,
                                      target_coordinate_space="target", report_dir=report_path.parent)
        bubble_path = self.report("bubble-audit.json")
        self.write(bubble_path, bubble)
        require(bubble.get("execution_bubble_match") == "passed", str(bubble.get("bubble_deviation")))
        actual["style_verification"] = {"method": "manual_visual_comparison", "image_sha256": base_hash,
                                        "matched": False, "source_exact_claim": False,
                                        "evidence": ann.get("style_notes", [])}
        actual["mechanism_verification"] = {}
        for name, item in ann.get("mechanisms", {}).items():
            require(item.get("status") in {"passed", "failed", "pending"} and item.get("reviewer")
                    and item.get("evidence"), "Mechanism review needs actual status, reviewer and observations")
            actual["mechanism_verification"][name] = {**copy.deepcopy(item), "image_sha256": base_hash,
                                                     "method": "manual_visual_comparison"}
        actual["execution_style_evidence"] = {"text_containers": {
            "bubble_audit_path": str(bubble_path), "bubble_audit_sha256": repairs.digest(bubble_path),
            "render_report_path": str(report_path), "render_report_sha256": repairs.digest(report_path),
            "final_image_sha256": repairs.digest(self.candidate)}}
        audit = self.audit(target, actual)
        audit.update(base_image_sha256=base_hash, final_image_sha256=repairs.digest(self.candidate),
                     actual_image_checked=True)
        self.write(self.report("final-layout-audit.json"), audit)
        self.write(self.report("base-actual-linked.json"), actual)
        require(audit["full_template_execution"] == "passed", str(audit["execution_style_evidence"]))
        return {"page_id": self.pid, "candidate": str(self.candidate),
                "full_template_execution": audit["full_template_execution"],
                "storyboard_layout_match": audit["storyboard_layout_match"],
                "visual_review_status": "pending", "base_image_modified": False}

    def promote(self, review_path: Path) -> dict:
        review_path = repairs.inside(self.root, review_path)
        review = repairs.read(review_path)
        base_hash, final_hash = repairs.digest(self.base), repairs.digest(self.candidate)
        require(review.get("page_id") == self.pid and review.get("review_status") == "passed"
                and review.get("image_sha256") == final_hash and review.get("base_image_sha256") == base_hash
                and review.get("actual_image_checked") is True
                and review.get("synthetic") is False and review.get("reviewer") and review.get("notes"),
                "Promotion requires an explicit current full-size visual review")
        require(all(review.get("checks", {}).get(key) == "passed" for key in CHECKS),
                "All seven actual review checks must be recorded; no automatic acceptance")
        self.actual_files()
        queue._base_audit_valid(self.report("base-layout-audit.json"), self.base)
        names = {"render_report": self.report("render.yaml"), "bubble_audit": self.report("bubble-audit.json"),
                 "font_raster": self.report("actual-font-raster.json"),
                 "base_audit": self.report("base-layout-audit.json"),
                 "final_layout_audit": self.report("final-layout-audit.json")}
        for name, path in names.items():
            require(review.get("evidence_files", {}).get(name) == binding(path), f"Visual review lacks current {name} binding")
        pp, plan, tp, _ = self.actual_files()
        required_inputs = [binding(pp), binding(tp), plan["actual_annotations_binding"]]
        for item in required_inputs:
            require(item in review.get("input_bindings", []), "Review must bind current actual plan, target and annotations")
            queue._check_binding(item, self.root)
        render = repairs.read(names["render_report"])
        count = render.get("canonical_block_count")
        require(render.get("page_acceptance_status") == "accepted" and render.get("actual_image_checked") is True
                and render.get("synthetic_input") is False and render.get("output_image_sha256") == final_hash
                and queue._render_base_hash_matches(render, base_hash) and type(count) is int
                and count >= 0 and render.get("rendered_count") == count and render.get("unresolved_count") == 0
                and (count == 0 or render.get("pixel_difference_nonempty") is True), "Actual render evidence failed")
        bubbles = repairs.read(names["bubble_audit"])
        pixels = bubbles.get("image_evidence") or {}
        require(queue._bubble_pass(bubbles) and bubbles.get("actual_render_verified") is True
                and pixels.get("verified") is True and pixels.get("output_image_sha256") == final_hash
                and pixels.get("base_hash_match") is True, "Actual bubble raster evidence failed")
        layout = repairs.read(names["final_layout_audit"])
        require(layout.get("full_template_execution") == "passed" and layout.get("final_image_sha256") == final_hash
                and layout.get("base_image_sha256") == base_hash, "Final layout evidence failed/stale")
        if self.canonical.exists():
            require(repairs.digest(self.canonical) == final_hash, "Refuse to overwrite a different promoted final")
        else:
            self.canonical.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.candidate, self.canonical)
        # Preserve the supplied observation fields; this only translates already
        # validated evidence into the queue/delivery schema, never creates truth.
        qa = copy.deepcopy(review)
        qa.update(image_sha256=final_hash, final_image_sha256=final_hash, base_image_sha256=base_hash,
                  synthetic_input=False, review_binding=binding(review_path),
                  evidence_files={k: binding(v) for k, v in names.items()},
                  input_bindings=required_inputs + [binding(names["base_audit"]), binding(names["final_layout_audit"])])
        self.write(self.report("production-review.json"), qa)
        return {"page_id": self.pid, "final": str(self.canonical), "sha256": final_hash,
                "visual_review_status": "passed", "base_image_modified": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["assemble", "fit", "finish", "promote"])
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--page", required=True)
    parser.add_argument("--state", type=Path, help="Use intact registered queue assets when assembling")
    parser.add_argument("--record", type=Path, help="Explicit fit adaptation record")
    parser.add_argument("--annotations", type=Path, help="Hash-bound actual base annotation file")
    parser.add_argument("--review", type=Path, help="Explicit full-size visual review for promotion")
    args = parser.parse_args()
    if args.action == "fit" and not args.record:
        parser.error("fit requires --record")
    if args.action == "promote" and not args.review:
        parser.error("promote requires --review")
    runtime = Runtime(args.run_root, args.manifest, args.page, args.state)
    result = (runtime.assemble() if args.action == "assemble" else runtime.fit(args.record)
              if args.action == "fit" else runtime.finish(args.annotations) if args.action == "finish"
              else runtime.promote(args.review))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
