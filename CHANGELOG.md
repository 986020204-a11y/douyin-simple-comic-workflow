# Changelog

## v0.2.0-rc.1

- 根据分镜约束、文字类型和实际留白自动选择气泡，使用 `bubble_style: auto`。
- 纳入 68 个 SB 分镜资源、索引和气泡约束审计结果。
- 增加气泡尾巴、人物脸部、手部、关键动作和道具的避让要求。
- 修正 `planned_panel_count` 与 `visible_panel_count` 的统计口径，记录 `panel_count_delta` 和解释依据。
- 保留机器检查与人工视觉验收的区别，无法确认的说话者或保护区仍需暂停。
- 当前为发布候选版本，不是稳定正式发布版。
- 早期验收阶段曾记录 `human_visual_acceptance: pending`；该历史状态保留，并已被最终人工验收结果 supersede。
- 当前最终状态为 `human_visual_acceptance: passed`、`published: false`、`repository_submission: not_started`。
