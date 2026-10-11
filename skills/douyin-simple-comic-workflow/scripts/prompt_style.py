#!/usr/bin/env python3
"""Select and render a prompt from the bundled 68 comic storyboard layouts.

This entry point is intentionally self-contained: it reads only the local
references/comic-layouts directory and never imports or resolves another Skill.
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
POOL = SKILL_ROOT / "references" / "comic-layouts"
INDEX = POOL / "layouts.json"


def load_pool() -> list[dict]:
    if not INDEX.exists():
        raise RuntimeError(f"Missing bundled layout index: {INDEX}")
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    if len(data) != 68 or any(x.get("category") != "comic-storyboard" for x in data):
        raise RuntimeError(f"Bundled comic layout pool must contain exactly 68 comic-storyboard entries; got {len(data)}")
    for x in data:
        pf = POOL / x["prompt_file"]
        if not pf.exists():
            raise RuntimeError(f"Missing bundled prompt file for {x['id']}: {pf}")
    return data


def verify() -> dict:
    pool = load_pool()
    return {
        "status": "passed",
        "pool_size": len(pool),
        "category": "comic-storyboard",
        "all_prompt_files_present": True,
        "layout_source": "bundled-internal-comic-layouts",
        "external_runtime_dependency": False,
        "ids": [x["id"] for x in pool],
    }


def _tokens(text: str) -> set[str]:
    text = (text or "").lower()
    parts = re.findall(r"[\u4e00-\u9fff]|[a-z0-9]+", text)
    grams = set(parts)
    for n in (2, 3, 4):
        grams.update(text[i:i+n] for i in range(max(0, len(text)-n+1)) if text[i:i+n].strip())
    return grams


def select(pool: list[dict], story_function: str, theme: str, layout_id: str | None) -> tuple[dict, str]:
    if layout_id:
        item = next((x for x in pool if x["id"].upper() == layout_id.upper()), None)
        if item is None:
            raise ValueError(f"Unknown bundled layout: {layout_id}")
        return item, "explicit layout requested; validated against bundled internal index"
    query = f"{story_function} {theme}".strip()
    q = _tokens(query)
    scored=[]
    for item in pool:
        hay = " ".join([item.get("name", ""), item.get("name_en", ""), " ".join(item.get("keywords", [])), item.get("layout_structure", "")])
        h = _tokens(hay)
        score = sum(1 for t in q if t in h)
        # Exact phrase matches are stronger than isolated characters.
        for phrase in (story_function, theme):
            if phrase and phrase in hay:
                score += 12
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    score, item = scored[0]
    if score <= 0:
        item = next(x for x in pool if x["id"] == "SB-001")
        return item, "no direct term match; used the internally bundled regular-grid baseline and kept selection internal"
    return item, f"matched story-function/theme terms against bundled metadata (score={score})"


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--layout")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--story-function", default="")
    ap.add_argument("--theme", default="")
    ap.add_argument("--output", type=Path)
    args=ap.parse_args()
    if args.verify:
        result=verify()
    else:
        pool=load_pool()
        if args.list:
            result={"pool_size":len(pool),"layouts":[{"id":x["id"],"name":x["name"],"panel_count":x["panel_count"],"prompt_file":x["prompt_file"]} for x in pool]}
        else:
            if not args.auto and not args.layout:
                raise SystemExit("Use --layout SB-xxx, --auto, or --verify.")
            item, reason=select(pool,args.story_function,args.theme,args.layout)
            prompt=(POOL/item["prompt_file"]).read_text(encoding="utf-8")
            result={
                "selected_by":"douyin-simple-comic-workflow",
                "layout_source":"bundled-internal-comic-layouts",
                "internal_layout_pool":68,
                "layout_id":item["id"],
                "layout_name":item["name"],
                "layout_name_en":item["name_en"],
                "panel_count":item["panel_count"],
                "selection_reason":reason,
                "prompt_file":str(POOL/item["prompt_file"]),
                "prompt_text":prompt,
            }
    payload=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(payload+"\n",encoding="utf-8")
    print(payload)

if __name__ == "__main__":
    main()
