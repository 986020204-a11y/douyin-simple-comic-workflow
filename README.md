# douyin-simple-comic-workflow 0.2.0-rc.1

这是 `douyin-simple-comic-workflow` 的独立发布候选包。它把中文文案转换为静态漫画组图：分析故事，选择内置分镜，生成角色参考图和无字底图，再按分镜、文字类型及实际留白调用正式文字合成器，最后输出带字 PNG、手机预览和交付清单。

## 调用方式

直接提供一段中文文案，并明确要求使用 `douyin-simple-comic-workflow`。工作流会读取本包内的资源，不调用外部分镜 Skill。

## 自动流程

1. 分析文案，决定页面和故事单元。
2. 从内置 68 个 SB 分镜中选择布局。
3. 生成角色参考图和无字漫画底图。
4. 根据布局约束、对白/旁白/思考/喊话/音效/手机对白等文字类型，以及底图的真实留白，选择 `bubble_style: auto` 的气泡候选、尺寸、位置和尾巴。
5. 调用正式 `scripts/text_compositor.py` 合成文字，并进行遮挡、避脸、避手、避动作和避道具检查。
6. 输出带字 PNG、手机预览、统计信息和交付报告。

## 输出规格

- 漫画 PNG：1080×1440，3:4。
- 手机预览：360×480。
- 交付清单同时记录规划数量、最终可见画格数量和检查状态。

## 统计口径

`planned_story_units` 是故事规划单元数；`planned_panel_count` 是分镜规划中的画格数；`visible_panel_count` 是最终无字底图中实际可见的画格数；`panel_count_delta` 是可见画格数减规划画格数；`panel_count_reconciliation` 记录两者的依据、差异原因和是否已解释。

规划数量不等于最终可见画格数量。当前发布候选案例记录为：

```yaml
page_count: 8
planned_story_units: 24
planned_panel_count: 24
visible_panel_count: 37
panel_count_delta: 13
panel_count_reconciliation:
  status: explained
  reason: 所选 SB 的展开、插格、嵌套格或分格结构使最终可见画格多于 8×3 的规划基数
```

只有差异有可追溯的 SB 结构解释时才可继续；无法解释的差异必须阻断发布，不能通过改数字掩盖分镜结构。

## 文字框规则

- 默认使用 `bubble_style: auto`，由布局约束、文字类型、说话者位置和真实保护区共同决定。
- 普通对白、旁白、思考、喊话、音效和手机对白可以使用不同候选样式；不能为了增加样式而错误改变文字类型。
- 气泡边框和尾巴不得遮挡文字、人脸、手部、关键动作或道具，也不得跨格误指。
- 无法确认说话者或实际保护区时必须暂停该文字块，并报告原因，不伪造人物绑定或尾巴。

## 证据边界和当前案例

68 个 SB 说明、索引和气泡约束均随包提供，并额外随候选包提供 68 张一一对应的预览图，路径记录在 `references/comic-layouts/layouts.json`。预览图来自相关本地图库 `D:\A抖音\.tmp_handraw_style\images\layouts\comic-storyboards`，不是源 Skill 原本携带的资源；它们只用于视觉参考，不能被当作 SB 文字说明、气泡规则或外部分镜来源。索引和气泡约束审计不能替代人工查看大图和手机预览。本案例的人工视觉验收已通过，用户已确认这些预览资产可随候选包再分发；`published` 仍为 `false`。

`comic-production-001-luzhaoling` 是本包的发布候选示例，包含 8 页和 24/37 统计解释。其状态为 `human_visual_acceptance: passed`、`published: false`。示例只保留可复用的说明、统计和关键验收报告，不捆绑历史漫画图片。

## 包格式说明

根目录 `plugin.json` 是便携插件清单，`.codex-plugin/plugin.json` 是 Codex 兼容清单；两者都指向包内的 `./skills/`。不同加载器可能只读取其中一种格式，因此本候选包保留双清单并在 README 中明确这项兼容差异。本候选包没有配置 MCP、hook 或外部服务。源 Skill 没有可靠的作者、许可证或仓库信息，因此清单不编造这些字段。源目录没有 `templates/` 目录；运行时 `text-layout.yaml` 只作为示例案例中的项目配置保留，不冒充 Skill 资源。

源 Skill 的版本仍是 `0.2-draft`。发布前核对发现 `D:\CodexData\skills\douyin-simple-comic-workflow` 镜像在三个统计规则文档上落后于源目录；差异先记录后，已仅同步这三份文档，镜像其余资源未被覆盖。
