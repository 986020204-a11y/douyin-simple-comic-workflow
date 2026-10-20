# douyin-simple-comic-workflow 0.9.0-rc.1

把中文文案制作成静态抖音漫画组图，内含 Skill `0.9.0-production`。工作流先逐页选择分镜并检查整篇节奏、完成文字样稿，再完成一页真实样稿，随后通过可续作队列生成独立场景，按 SB 模板拼版并添加中文气泡，最后检查与打包。

## 使用方式

安装本包后，可以直接提出：

> 使用 douyin-simple-comic-workflow，将以下文案制作成静态漫画组图。合理拆页并自动选 SB，保持人物和服装连续；输出 1080×1440、3:4 满版，去掉顶部说明区，等比例适配并记录裁切；先验证一页完整样稿，通过后继续。使用新的隔离目录。文案：……

也可以只要求拆页、分镜和生图提示词。提示词输出不算图片生成完成。风格、情绪强度和改编范围由当前任务决定，不把某篇故事的人物、关系或措辞固定为全部项目的规则。

## 本次升级

- **逐页选择分镜**：`prompt_style.py --pages` 根据每页叙事功能和真实故事单元比较兼容候选，不能把一次选型直接复制到整篇；人物和画风连续性单独保持。
- **生成前检查重复**：整篇同一SB或连续三页以上使用同一SB，必须有具体叙事理由或用户明确要求统一格式的记录。准备、恢复领取任务与交付核对同一份审核，缺失、过期或页面不一致时阻断。
- **保留合理重复**：允许对照或持续对话使用相同版式，不要求每页不同，也不规定必须使用几种模板。自动检查不能代替整套样稿的视觉节奏审查。
- **减少重复准备**：整篇一次完成文字容量、情节覆盖和关键引文预检，随后冻结用于生成的计划与模板。
- **并行与续作**：默认最多 4 个独立画格请求，失败只重试该画格；任务有领取标识、超时恢复和最多 3 次尝试。真实样稿通过前不放行后续页面。
- **实图适配**：底图结构先验收，再根据实际人脸、手部、道具和说话者位置绑定字幕；调整气泡时同步变换其轮廓，只在有明确证据及适配授权时调整已知尾巴。
- **局部修图**：保留原素材，使用原图/修图哈希和明确审核记录选择替换图，图片损坏、记录过期或未审核时阻止使用。
- **完整交付**：按实际准备的页数检查，不固定 5 页或 20 页；核对来源文字、全部页序、冻结输入、分镜与气泡证据、唯一最终 PNG 和整篇实际视觉审核，再输出阅读器与图片 ZIP。
- **保留事实边界**：3:4 满版适配可以通过目标验收，原始 SB 严格匹配失败仍保留；程序不自动声称人工看过图片。
- **移除手机预览产物**：生产流程只生成和审核 1080×1440 完整图，不再创建 360×480 手机预览，也不再把手机图绑定或手机可读性作为晋级条件。

完整流程见 [Skill](skills/douyin-simple-comic-workflow/SKILL.md)、[生产流程](skills/douyin-simple-comic-workflow/references/production-workflow.md)和[实图运行说明](skills/douyin-simple-comic-workflow/references/actual-image-runtime.md)。图像生成由运行环境提供；这些离线脚本负责准备、调度、拼版、文字合成和验收，不内置图像服务或账号凭据。

逐页规划输入、全篇审核和重复版式的例外记录见[分镜节奏说明](skills/douyin-simple-comic-workflow/references/storyboard-rhythm.md)。旧的单页选择入口仍可用于单页任务，其结果不能充当多页分镜决策。

## 分镜与画布

SB-001 至 SB-068 均有原始预览、来源说明、结构化 YAML 和索引。模板记录画格几何、阅读顺序、具体文字容器和 observed/inferred/unknown 证据。画格由程序执行，场景模型不能自行增删、合并或拆分画格。

默认最终图为 1080×1440、3:4 满版；去掉顶部说明区后等比例适配，记录裁切，禁止拉伸。每页交付一个 `Pxx-final.png`，候选图留在本次运行内，不混进交付包。字幕不改写无字底图文件。

68 个模板的字段/绑定/索引与结构诊断已有验证。此版本保留 9 个复杂文字处理限制：**SB-006、SB-040、SB-041、SB-042、SB-043、SB-044、SB-045、SB-046、SB-057** 的相关旋转或多区域配色实例仍会被阻止，不降级成普通长框。结构诊断和本次生产回归均不能证明全部 68 个模板的真实漫画成图通过，也不承诺与预览像素相同。

当前正式交付通道仍要求每页有来源绑定的文字实例。完全没有可执行文字区的纯画面页会被阻止，不会为通过检查而强行创造气泡。原生 `CANVAS` 文字区仅在模板明确声明并绑定到同一实例时执行。

## 检查与依赖

需要 Python 3.10+，依赖见 `requirements.txt`。正式中文文字必须配置可用中文字体；Windows 默认使用微软雅黑，包内另附马善政字体与 OFL 许可证。结构诊断使用跨平台后备字体，不依赖私人磁盘目录。

```sh
python -m pip install -r requirements.txt
python -B skills/douyin-simple-comic-workflow/scripts/check_executable_templates.py --root skills/douyin-simple-comic-workflow/references/comic-layouts --check-index --output .local-validation/templates.json
python -B skills/douyin-simple-comic-workflow/scripts/verify_template_library.py --root skills/douyin-simple-comic-workflow/references/comic-layouts --output .local-validation/geometry
python -B -m unittest discover -s regression/production -p 'test_*.py' -v
python -B -m unittest discover -s skills/douyin-simple-comic-workflow/scripts/tests -p 'test_storyboard*.py' -v
```

回归使用临时目录及明确标注的诊断素材，不调用图像模型，不生成新漫画。生产通道验证见 [0.8.1 验证](validation/production-0.8.1-rc.1/README.md)，手机预览移除见 [0.8.2 验证](validation/production-0.8.2-rc.1/README.md)，逐页分镜与整篇节奏检查见 [0.9.0 验证](validation/production-0.9.0-rc.1/README.md)。离线检查不能证明实际生图耗时降低固定比例。

## 包与历史文件

`plugin.json` 与 `.codex-plugin/plugin.json` 均为 `0.9.0-rc.1`，指向 `./skills/`。旧 `examples/`、`tests/`、`delivery/` 以及先前验证记录保留原样；生产回归位于 `regression/production/`，逐页分镜回归位于 Skill 的 `scripts/tests/`。仓库发布包含通用能力与验证代码，不上传本次故事的漫画图片或私人角色素材。

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


