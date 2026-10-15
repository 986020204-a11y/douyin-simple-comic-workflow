# douyin-simple-comic-workflow 0.7.0-rc.1

这是 `douyin-simple-comic-workflow` 的独立发布候选包，内含 Skill 版本 `0.7-library-68`。它把中文文案转换为静态抖音漫画组图：逐页选择内置 SB 模板，先验证画格和文字结构，再生成画格素材、确定性拼版，最后合成中文文字并检查实际图片。

## 当前完成范围

SB-001 至 SB-068 均提供原始预览、来源说明和程序可读取的 YAML 模板。每个模板记录原生画布、画格数量和几何、阅读顺序、具体气泡或文字区域、约束、回退规则及 `observed`、`inferred`、`unknown` 证据。

本轮补齐剩余 63 个模板，保留先前 5 个模板。68 个模板共记录 350 个叙事图像单元、547 个画格绑定文字实例和 62 个可执行额外文字区。编号组、可见图像单元与有边框画格分别记录，不能仅凭 SB 名称或编号推算画格数。

| 验证层级 | 当前范围 |
| --- | --- |
| 模板、预览、说明齐全及字段/绑定/索引检查 | 68/68 通过 |
| 原生画布编译及独立 3:4 适配编译 | 各 68/68 通过 |
| 纯色网格素材结构拼版和 PNG 像素检查 | 68/68 通过 |
| 空白图、重绑哈希空白图、删格、移格反例 | 272/272 正确拒绝 |
| 新增文字处理与原 5 个模板回归 | 14/14 通过 |
| 本轮新增 63 个模板的真实漫画成图验收 | 63 个待验证 |

这些结果验证模板和确定性结构执行能力。纯色诊断图不是漫画成图，不能证明角色连续性、对白归属、特殊效果、完整文字排版或与原预览像素相等。模板有值、编译成功或结构检查通过，都不能单独建立 `full_template_execution: passed`。

9 个布局仍包含当前文字渲染器不支持的旋转文字或多区域配色：**SB-006、SB-040、SB-041、SB-042、SB-043、SB-044、SB-045、SB-046、SB-057**。相关文字实例会被预检和渲染阻止；程序不会默认为普通长框。其他模板仍需实际说话者、载体、安全区、字体容量和所需特殊机制的证据。

## 调用与执行流程

提供中文文案并明确要求使用 `douyin-simple-comic-workflow`。工作流读取包内 68 个 SB 资源，在新的隔离输出目录中执行：

1. 分析故事，建立角色与来源边界，运行内置分镜选择器。
2. 读取选中 SB 的真实 YAML 模板，编译明确的画格边界、数量、比例与阅读顺序。
3. 按已有文字实例和真实几何制作完整结构与文字验证稿，处理容量、语义及绑定问题。
4. 生成每个声明画格的场景素材，由程序执行遮罩、画格边界、层次和拼版；生图模型不能自行增删、合并或拆分画格。
5. 先审核实际无字底图，再绑定实际说话者、实体载体及保护区，按模板合成中文文字。
6. 检查气泡形状、位置、尾巴和遮挡，并交付每页唯一的最终 PNG 与报告。

无需调用外部分镜 Skill。生图需要运行环境提供图像生成能力；缺失时只能完成模板、提示和验证，不应把提示文件标记为图片。

## 文字与证据规则

- 每个气泡绑定真实 `panel_id`；无框文字、思考链、实体表面文字及页边文字分别执行，不统一替换为长框。
- 画格外的真实文字使用明确的 `CANVAS` 文字区，不创建虚构画格。
- 保持对白、旁白、思考、喊话、音效、手机对白和便笺的来源语义，不能为了匹配容器而改写成另一种类型。
- 说话者、尾巴方向、载体或保护区无法确认时阻止相关实例，不伪造证据。
- 跨格及页边文字需要所有受影响画格的脸部、手部与关键道具保护；未知或不支持的效果不能静默降级。
- 直接看到的形态标为 `observed`；手描坐标、隐藏轮廓、程序规则等标为 `inferred`；原字体、笔触和无法判断的内容保留 `unknown`。

完整契约见 [Skill 使用说明](skills/douyin-simple-comic-workflow/SKILL.md)、[模板库规则](skills/douyin-simple-comic-workflow/references/comic-layouts/executable-library.md)和[模板索引](skills/douyin-simple-comic-workflow/references/comic-layouts/template-index.yaml)。

## 画布与验收

源模板保留原生预览比例。选择 3:4 满版时，必须使用显式适配：去除顶部说明区后等比例放大并记录裁切、边界和文字调整，不能把源模板直接拉伸成 3:4。适配可以通过目标检查，但源预览严格几何匹配仍标为失败；目标合规、源预览一致与人工视觉接受分别报告。

最终交付 PNG 为 1080×1440，每页仅有一个规范最终文件。`planned_story_units`、`planned_panel_count`、`visible_panel_count`、`panel_count_delta` 和 `panel_count_reconciliation` 分别记录规划与实际画格，不能通过改数字隐藏偏差。

## 本地检查

运行环境使用 Python 3.10+、PyYAML、Pillow 和 NumPy，依赖见 `requirements.txt`。正式中文文字合成与预检默认使用 Windows 微软雅黑，可在文字布局配置中指定可用的中文 `font_file`。包内另附马善政字体及其 OFL 许可证；选用该字体也不能证明它与原预览字体相同。

在仓库根目录执行以下检查，输出写到新的临时目录，避免覆盖旧结果：

```powershell
python -X utf8 -m pip install -r requirements.txt
python -X utf8 skills/douyin-simple-comic-workflow/scripts/check_executable_templates.py --root skills/douyin-simple-comic-workflow/references/comic-layouts --check-index --output .local-validation/template-check.json
python -X utf8 skills/douyin-simple-comic-workflow/scripts/verify_template_library.py --root skills/douyin-simple-comic-workflow/references/comic-layouts --output .local-validation/native-geometry
```

第二项检查只产生纯色网格结构诊断图，不生成漫画。实际漫画仍须逐页通过图片几何、完整文字、特殊效果与人工视觉验收。

## 包结构与历史记录

根目录 `plugin.json` 与 `.codex-plugin/plugin.json` 均为 `0.7.0-rc.1` 并指向 `./skills/`。当前包没有 MCP、hook 或外部服务配置。Skill 自身以 `0.7-library-68` 标识本次模板库升级；插件候选包版本与 Skill 内部版本分别记录。

`examples/`、`tests/` 和 `delivery/` 保留此前发布候选的案例与报告。旧案例的人工验收结果只适用于对应案例，不能替代当前新增 63 个模板的真实成图验收。历史漫画图片不作为本次升级内容打包。

预览资产的再分发授权在此前候选包准备时已记录。本轮保持原始预览内容不变。新模板读取 `references/comic-layouts/previews/`，下面的历史图库继续链接既有 `preview-images/` 路径。

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


