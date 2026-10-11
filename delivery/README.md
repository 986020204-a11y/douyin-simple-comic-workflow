# Delivery

这是 `douyin-simple-comic-workflow` 0.2.0-rc.1 的独立发布候选目录。封装只复制源 Skill 的实际可复用资源和当前案例的关键报告，不包含漫画图片、历史测试目录、临时探针或重复附件。

发布候选案例保留 8 页、`planned_story_units: 24`、`planned_panel_count: 24`、`visible_panel_count: 37`、`panel_count_delta: 13`，差异状态为 `explained`。`human_visual_acceptance` 已为 `passed`，`published` 保持 `false`。

源 Skill 和镜像本身都没有展示图；候选包额外包含 68 张按 SB 编号一一对应的预览图，来自相关本地图库。它们不是源 Skill 原始资源，也不作为气泡规则或外部分镜证据；来源和路径校验记录在 `delivery/packaging-report.yaml` 与 `references/comic-layouts/preview-assets-manifest.yaml`。用户已确认预览资产可随候选包再分发；最终门禁记录见 `delivery/final-release-gate.yaml`。
