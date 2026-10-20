# Page-specific storyboard selection

Choose layout after deciding what each page must communicate. Preserve character,
wardrobe and drawing-style continuity independently. A reusable layout can help a
comparison or sustained conversation, but production convenience, an already
working renderer or resuming a run does not determine the remaining pages.

## Input and execution

Create a page plan with real story units and concrete panel-count reasons:

```yaml
layout_policy: narrative_variety
pages:
  - page_id: P01
    story_beat_id: B01
    narrative_function: 母亲安慰哭醒的孩子，让孩子重新感到安全
    panel_count_reason: 用哭醒和拥抱两个连续节点完成从惊恐到安心的变化
    panels:
      - focus: 孩子从失去家的噩梦中哭醒
        main_action_or_emotion: 惊恐地寻找母亲
        source_lines: [31, 36]
      - focus: 母亲抱住孩子并承诺永远在一起
        main_action_or_emotion: 拥抱与安心
        source_lines: [37, 40]
```

The source references above illustrate the schema; replace them with the current
story's actual references. Add pages and units as their narrative needs require.
Do not copy this example's count to other pages. Then run:

```powershell
python <SKILL>/scripts/prompt_style.py --pages <RUN>/page-plan.yaml --output <RUN>/storyboard-decision.yaml
```

When the user selected 3:4 content-cover adaptation, also use
`--approved-3-4-adaptation`; preserve its source-deviation reporting. The selector
evaluates real executable candidates for each page's native unit count, records
semantic scores and incompatibility reasons, and copies each page's actual story
units into the selected template's original IDs. It considers repetition only
among near-scoring compatible choices; a stronger narrative match is not replaced
just to cycle layouts. If no compatible template exists, revise the unfrozen plan
without dropping core events, then rerun. The single-page CLI remains available;
its output is not a multi-page handoff.

Every selected page contains `selection_evidence` with its `page_id`,
`selected_layout_id`, `narrative_function`, evaluated `candidates`, and a
page-specific `selection_reason`. The evidence must agree with that page. No
handwritten claim that a selection came from the library replaces execution.

## Repetition that needs review

`audit_storyboard_rhythm.py` blocks a story of two or more pages using one SB,
or a run of three or more consecutive pages using one SB, unless the affected
range has a concrete narrative reason or the user explicitly requested a uniform
format. Two repeated pages within a varied story are allowed. Different layouts
may legitimately have the same number of panels. No minimum number or percentage
of distinct SBs is imposed, and there is no mandatory rotating sequence.

A planned narrative comparison may declare:

```yaml
repetition_justifications:
  - page_ids: [P02, P03, P04]
    layout_id: SB-002
    reason: 同一场对话中保持人物视线位置，使三次回应的表情变化可比较
    narrative_purpose: 让孩子逐步安心的变化在相同画框内形成对照
    alternatives_considered: [SB-001, SB-003]
```

Use real evaluated alternatives and the exact contiguous range. This is a design
decision the agent can make within the requested work; it does not itself require
another permission question. The user may instead explicitly request one format:

```yaml
layout_policy: uniform_by_user_request
uniform_layout_request:
  source: user
  instruction_excerpt: 全部使用同一种四格版式
```

Copy an actual user instruction, never fabricate one. Supply the intended
`layout_id` on each page when the request specifies a particular SB. Per-page
narrative and native-count checks still apply under either exception.

## Generation gate and review boundary

Normal preparation re-audits the complete decision and writes
`storyboard-rhythm-audit.json`. Its report and the underlying decision are
hash-bound inputs to every readiness proof and request manifest. Missing evidence,
changed hashes, a subset disguised as a complete story, inconsistent page targets,
or a newly blocked decision stops dispatch. Rebuilding a proof does not authorize
reuse of image acceptance; use the existing queue's asset-reuse rules.

Passing this gate proves metadata consistency and a recorded selection rationale.
It cannot judge whether the actual drawings tell the story well. Review all
complete layout/text proof thumbnails together before scene generation, then
perform the existing real-image checks. Look for emotional pauses, clear action
transitions, useful subject scale and text space; revise planning when needed.
Do not treat the number of different SB IDs or a `passed` field as creative review.

On interruption/resume, preserve the current artifacts. If the old handoff fails
the new gate, save a separate planning revision and revalidate before new dispatch.
Do not alter delivered historical images or retroactively claim they passed this
new rule.
