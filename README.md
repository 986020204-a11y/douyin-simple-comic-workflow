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

68 个 SB 说明、索引和气泡约束均随包提供，并额外随候选包提供 68 张一一对应的预览图，路径记录在 `references/comic-layouts/layouts.json`。预览图来自候选包外部的相关本地图库，源路径不随仓库发布；它们只用于视觉参考，不能被当作 SB 文字说明、气泡规则或外部分镜来源。索引和气泡约束审计不能替代人工查看大图和手机预览。本案例的人工视觉验收已通过，用户已确认这些预览资产可随候选包再分发；`published` 仍为 `false`。

`comic-production-001-luzhaoling` 是本包的发布候选示例，包含 8 页和 24/37 统计解释。其状态为 `human_visual_acceptance: passed`、`published: false`。示例只保留可复用的说明、统计和关键验收报告，不捆绑历史漫画图片。

## 包格式说明

根目录 `plugin.json` 是便携插件清单，`.codex-plugin/plugin.json` 是 Codex 兼容清单；两者都指向包内的 `./skills/`。不同加载器可能只读取其中一种格式，因此本候选包保留双清单并在 README 中明确这项兼容差异。本候选包没有配置 MCP、hook 或外部服务。源 Skill 没有可靠的作者、许可证或仓库信息，因此清单不编造这些字段。源目录没有 `templates/` 目录；运行时 `text-layout.yaml` 只作为示例案例中的项目配置保留，不冒充 Skill 资源。

源 Skill 的版本仍是 `0.2-draft`。发布前核对发现镜像 Skill 在三个统计规则文档上落后于源目录；差异先记录后，已仅同步这三份文档，镜像其余资源未被覆盖。

## 68 个内置漫画分镜预览

这些预览图用于辅助查看和选择分镜。每张图片对应一个 SB 分镜编号；分镜说明仍以对应的 `SB-###.md` 文件为准，预览图不替代正式分镜规则。点击缩略图可以打开仓库内的原图。

### SB-001–SB-016

|  |  |  |  |
| --- | --- | --- | --- |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-001.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-001.webp" alt="SB-001" width="160"></a><br><sub>SB-001</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-002.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-002.webp" alt="SB-002" width="160"></a><br><sub>SB-002</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-003.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-003.webp" alt="SB-003" width="160"></a><br><sub>SB-003</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-004.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-004.webp" alt="SB-004" width="160"></a><br><sub>SB-004</sub> |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-005.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-005.webp" alt="SB-005" width="160"></a><br><sub>SB-005</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-006.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-006.webp" alt="SB-006" width="160"></a><br><sub>SB-006</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-007.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-007.webp" alt="SB-007" width="160"></a><br><sub>SB-007</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-008.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-008.webp" alt="SB-008" width="160"></a><br><sub>SB-008</sub> |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-009.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-009.webp" alt="SB-009" width="160"></a><br><sub>SB-009</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-010.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-010.webp" alt="SB-010" width="160"></a><br><sub>SB-010</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-011.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-011.webp" alt="SB-011" width="160"></a><br><sub>SB-011</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-012.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-012.webp" alt="SB-012" width="160"></a><br><sub>SB-012</sub> |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-013.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-013.webp" alt="SB-013" width="160"></a><br><sub>SB-013</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-014.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-014.webp" alt="SB-014" width="160"></a><br><sub>SB-014</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-015.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-015.webp" alt="SB-015" width="160"></a><br><sub>SB-015</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-016.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-016.webp" alt="SB-016" width="160"></a><br><sub>SB-016</sub> |

### SB-017–SB-032

|  |  |  |  |
| --- | --- | --- | --- |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-017.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-017.webp" alt="SB-017" width="160"></a><br><sub>SB-017</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-018.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-018.webp" alt="SB-018" width="160"></a><br><sub>SB-018</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-019.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-019.webp" alt="SB-019" width="160"></a><br><sub>SB-019</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-020.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-020.webp" alt="SB-020" width="160"></a><br><sub>SB-020</sub> |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-021.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-021.webp" alt="SB-021" width="160"></a><br><sub>SB-021</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-022.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-022.webp" alt="SB-022" width="160"></a><br><sub>SB-022</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-023.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-023.webp" alt="SB-023" width="160"></a><br><sub>SB-023</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-024.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-024.webp" alt="SB-024" width="160"></a><br><sub>SB-024</sub> |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-025.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-025.webp" alt="SB-025" width="160"></a><br><sub>SB-025</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-026.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-026.webp" alt="SB-026" width="160"></a><br><sub>SB-026</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-027.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-027.webp" alt="SB-027" width="160"></a><br><sub>SB-027</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-028.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-028.webp" alt="SB-028" width="160"></a><br><sub>SB-028</sub> |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-029.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-029.webp" alt="SB-029" width="160"></a><br><sub>SB-029</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-030.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-030.webp" alt="SB-030" width="160"></a><br><sub>SB-030</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-031.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-031.webp" alt="SB-031" width="160"></a><br><sub>SB-031</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-032.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-032.webp" alt="SB-032" width="160"></a><br><sub>SB-032</sub> |

### SB-033–SB-048

|  |  |  |  |
| --- | --- | --- | --- |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-033.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-033.webp" alt="SB-033" width="160"></a><br><sub>SB-033</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-034.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-034.webp" alt="SB-034" width="160"></a><br><sub>SB-034</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-035.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-035.webp" alt="SB-035" width="160"></a><br><sub>SB-035</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-036.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-036.webp" alt="SB-036" width="160"></a><br><sub>SB-036</sub> |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-037.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-037.webp" alt="SB-037" width="160"></a><br><sub>SB-037</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-038.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-038.webp" alt="SB-038" width="160"></a><br><sub>SB-038</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-039.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-039.webp" alt="SB-039" width="160"></a><br><sub>SB-039</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-040.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-040.webp" alt="SB-040" width="160"></a><br><sub>SB-040</sub> |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-041.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-041.webp" alt="SB-041" width="160"></a><br><sub>SB-041</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-042.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-042.webp" alt="SB-042" width="160"></a><br><sub>SB-042</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-043.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-043.webp" alt="SB-043" width="160"></a><br><sub>SB-043</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-044.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-044.webp" alt="SB-044" width="160"></a><br><sub>SB-044</sub> |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-045.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-045.webp" alt="SB-045" width="160"></a><br><sub>SB-045</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-046.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-046.webp" alt="SB-046" width="160"></a><br><sub>SB-046</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-047.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-047.webp" alt="SB-047" width="160"></a><br><sub>SB-047</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-048.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-048.webp" alt="SB-048" width="160"></a><br><sub>SB-048</sub> |

### SB-049–SB-064

|  |  |  |  |
| --- | --- | --- | --- |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-049.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-049.webp" alt="SB-049" width="160"></a><br><sub>SB-049</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-050.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-050.webp" alt="SB-050" width="160"></a><br><sub>SB-050</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-051.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-051.webp" alt="SB-051" width="160"></a><br><sub>SB-051</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-052.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-052.webp" alt="SB-052" width="160"></a><br><sub>SB-052</sub> |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-053.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-053.webp" alt="SB-053" width="160"></a><br><sub>SB-053</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-054.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-054.webp" alt="SB-054" width="160"></a><br><sub>SB-054</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-055.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-055.webp" alt="SB-055" width="160"></a><br><sub>SB-055</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-056.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-056.webp" alt="SB-056" width="160"></a><br><sub>SB-056</sub> |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-057.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-057.webp" alt="SB-057" width="160"></a><br><sub>SB-057</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-058.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-058.webp" alt="SB-058" width="160"></a><br><sub>SB-058</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-059.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-059.webp" alt="SB-059" width="160"></a><br><sub>SB-059</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-060.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-060.webp" alt="SB-060" width="160"></a><br><sub>SB-060</sub> |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-061.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-061.webp" alt="SB-061" width="160"></a><br><sub>SB-061</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-062.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-062.webp" alt="SB-062" width="160"></a><br><sub>SB-062</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-063.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-063.webp" alt="SB-063" width="160"></a><br><sub>SB-063</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-064.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-064.webp" alt="SB-064" width="160"></a><br><sub>SB-064</sub> |

### SB-065–SB-068

|  |  |  |  |
| --- | --- | --- | --- |
| <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-065.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-065.webp" alt="SB-065" width="160"></a><br><sub>SB-065</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-066.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-066.webp" alt="SB-066" width="160"></a><br><sub>SB-066</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-067.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-067.webp" alt="SB-067" width="160"></a><br><sub>SB-067</sub> | <a href="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-068.webp"><img src="skills/douyin-simple-comic-workflow/references/comic-layouts/preview-images/SB-068.webp" alt="SB-068" width="160"></a><br><sub>SB-068</sub> |


