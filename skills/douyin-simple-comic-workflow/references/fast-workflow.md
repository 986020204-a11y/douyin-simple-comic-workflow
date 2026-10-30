# FAST：按叙事选择分镜，整页生成，画面检查与本地文字

适用于日常静态漫画与故事插画。选中 SB 只表示构图参考，`match_policy: fast_visual_guide` 不表示严格几何通过。精确画格、气泡、分镜结构或模板验收要求进入 [STRICT](strict-workflow.md)。FAST 不运行 `production_preflight.py`、严格逐格队列或整库回归。

## 1. 一次准备与冻结

先检查目标目录是否已有 `fast/plan.json` / `fast/state.json`。已有任务直接执行 `fast_queue.py status`；只读状态、当前页请求和必要的参考图，不重新分析源故事、不重写已冻结提示词。旧 STRICT 任务沿用旧状态。

新任务在同一次规划中确定原文事实、人物卡、画风、逐页叙事功能、最少充分画格、文字归属和完整提示词。每页写明 `narrative_function`、`panel_count_reason`，每格写 `focus` 和 `main_action_or_emotion`；一个主要动作或情绪一格，不按句子数机械分格或为模板凑格。所有画格仍在一次整页请求中生成。

新项目先按 [三套画风选择与应用](style-presets.md) 确定都市韩漫、Q版轻喜剧、清雅古风叙事，或保留用户自定义风格。预设用 `style.preset_id` 选择，可省略 `style.prompt`，也可添加项目补充；每页必须写 `style_application.performance/camera/layout/lettering`，把本页表演、镜头、分镜和文字决定落实到规划，不能只替换一个画风词。预设与应用会快照冻结，恢复不重读画风库。旧版和无预设的自定义草案继续使用原字段。

复用 [原有逐页选择原则](storyboard-rhythm.md)，从原有 68 套 SB 按叙事适配选择；该文档中的 STRICT 命令不用于 FAST。叙事匹配优先，仅在近似适配候选中考虑重复。有具体叙事理由可重复，不设最低版式数量或固定轮换。全组统一或连续三页相同 SB 时，用原有 `repetition_justifications` 记录范围、理由、叙事目的和兼容替代；真实用户要求统一时记录原话，不编造授权。

本地评分复用原词项匹配，只提供候选和理由依据；Codex 应根据原文完成创作判断并可明确选择 SB，不能把关键词得分当作完整的情绪理解。

### 将图文检查并入现有准备，不增加生图轮次

- 公共画风、人物卡、原文分析各保存一次。`style.prompt` 只补充全组必需的视觉特征，不堆放后页故事、完整角色库或全篇制作说明；每页 `prompt` 只补充当前动作、镜头、构图和文字空间中尚未由结构化字段表达的要求，不再重述全部画格、坐标和公共规范。每页填写 `character_ids`，包括实际入镜的配角与对白/心声主人；脚本据此裁减人物卡和人物专属参考，不靠名字猜测删人。旧草案未填该字段时保留全部人物的原行为。
- 同一次规划就确定文字相对人物的位置，并用已有本地字体试排；不默认再调用模型制作一整套预览或重读全文。对白归属清楚，旁白占局部空间，留白随本页所选SB与场景安排。统一底栏有叙事用途或用户明确指定时可用，并写本页 `caption_band_reason`；单纯方便排字不构成叙事理由。
- 准备脚本在创建新项目之前，本地检查已知的“每格统一下方空白”强制指令。缺少本页理由时先修规划；这只是风险检查，不声称能自动判断画面审美，也不规定留白比例或模板数量。
- 首张直接生成正式第1页；新计划首张含文字时，队列要求先本地排字、实际查看成品并记录分镜表达、图文关系及阅读顺序，再领取后续页。后续页面沿用原有实际看图检查，并检查图文关系；不要增加整篇重新分析、额外试图或每页用户确认。程序校验审核记录及当前版本绑定，画面好坏仍由实际看图判断。
- 已冻结任务按原快照恢复，成功页跳过；这些新草案检查不回写旧计划或历史成品。需要纠正已冻结的整体图文构图时，在新修订项目处理。

### 生图请求默认精简，完整制作数据留在本地

新准备的 FAST 请求使用可直接阅读的紧凑画面说明。保留选定画风、本页人物辨识特征与适用年龄、原 SB 叙事机制、按阅读顺序排列的每格动作/表情/镜头、必要画格和留白坐标、对白归属及无字底图要求。重要人物、关键物件和图文关系不能因精简而丢失，也不能把不同场景合并成一格。

人物的重要身份、年龄、外貌、服装和自定义视觉约束集中写入 `description`；可选的文本字段 `appearance`、`wardrobe`、`visual_notes` 也进入请求。完整人物卡仍保存在本地，其他附加字段不自动发给生图；不要把必需的画面要求只写在备注或来源字段里。

自动拼接不再倾倒整份人物卡、分镜、字幕规划 JSON 或重复发送同一组坐标。分析、叙事作用、选型理由、容量预检、字幕正文、字体、容器样式、路径、哈希和审核记录继续完整保存在本地；生图只接收影响当前画面的内容。参考规则由领取队列按实际参考图片追加，包含后页动态复用的第1页，不在准备阶段重复说明。图像和本地文字的语义归属保持原计划。

Codex 在原有一次规划中检查实际拼接后的逐页请求，合并重复表达，移除本页不出场人物及后页专属说明，核对用户关键要求仍完整，再冻结。公共风格和作者写入的 `page.prompt` 不由脚本猜测语义删改；长文本应在草案阶段人工精简。没有固定字符上限，不为缩短文本硬截断、静默删剧情或牺牲连续性。此规则不新增分析轮次、测试图或候选图。

这项改进只适用于新准备的项目；恢复已有冻结任务仍使用原提示词。已冻结项目需要改写生图提示词时建立新修订项目，保留原图、原文案和尝试记录。网络错误只按实际返回登记，未经对照验证不宣称由提示词长度导致，也不宣称精简后保证成功或更快。

短候选显示原生格数和 FAST 适用性。复杂破框、嵌套、手机界面、文字构成结构骨架等不能直接按普通留白页处理；应明确近似改编或使用 STRICT。原生格数不同时，显式指定 SB、`layout_adaptation.reason` 和每格 `bounds`，不自动制造网格。人物一致性优先，分镜表达其次，背景丰富度最后。

需要选 SB 时，使用轻量候选：

```powershell
python <SKILL>/scripts/fast_prepare.py layouts --query "四格漫画 起承转合 日常对白" --limit 5
```

它只读索引并输出最多 8 条摘要。规划可明确选择真实 `SB-###`；冻结只加载当前用到的模板文字，同一模板在该次准备中复用。单幅插画可以不选 SB。不要把 68 套模板、全部 STRICT 规则或历史长日志读入上下文。

分镜确认或按已有创作授权采用后，保存以下 `fast-draft.yaml`。路径相对草案文件；这是一份由 Codex 一次写好的计划，本地脚本不分析故事：

```yaml
mode: fast
source_path: article.md
analysis:
  source_facts: ["小雨把最后一块饼干留给妈妈。"]
  reasonable_inferences: []
  design_additions: ["使用餐桌场景。"]
  open_questions: []
characters:
  - character_id: N01
    description: "小雨，六岁女孩，齐耳黑发，黄色毛衣；各页外观一致。"
    reference_paths: []  # 有现成参考时填写真实路径
style:
  prompt: "采用本次项目确认的简洁手绘规范，低视觉密度，少量背景提示。"
  reference_paths: []
text_settings:
  font_path: C:/Windows/Fonts/msyh.ttc
  canvas_size: [1080, 1440]
  font_size: 40
  minimum_readable_font_size: 24
pages:
  - page_id: P01
    character_ids: [N01]
    narrative_function: "发现小雨为妈妈留了饼干"
    panel_count_reason: "这一页只有把饼干留在妈妈座位的完整瞬间，用单幅表达关心。"
    layout_id: SB-054
    layout_adaptation:
      reason: "借用白场分镜的留白机制，近似适配一个完整瞬间，不复制示例的多个画格。"
    panels:
      - panel_id: U01
        focus: "小雨与留在妈妈座位的最后一块饼干"
        main_action_or_emotion: "轻轻把饼干推过去，表现关心"
        bounds: [0.02, 0.02, 0.96, 0.96]
    prompt: "完整竖版漫画，以手与饼干为主视觉；本页分镜决定构图，预留短旁白空间。"
    captions:
      - caption_id: C01
        text: "最后一块，留给妈妈。"
        type: narration
        panel_id: U01
        bounds: [0.06, 0.83, 0.88, 0.13]
        font_size: 40
```

多格页面保存真实有序故事单元，明确文字所属 `panel_id`。文字类型来自原文：`narration` 旁白、`dialogue` 对白、`thought` 心声、`shout` 喊话、`note` 说明、`emphasis` 强调；对话与心声记录 `speaker_id` 或 `owner_id`，不能因模板存在气泡便把旁白改成台词。`bounds` 为归一化 `[x,y,w,h]`，可明确指定或按选中模板的真实区域规划。计划坐标不是实际图片测量。

准备会在创建项目、生图之前，以最终字体、字号和目标尺寸试排每段文字；容量不足先修改区域、分镜或明确改写，不静默删字缩字。字体会复制进项目并绑定哈希。字幕正文不传给生图模型，只传画格、归属和留白要求。参考图继承身份、服装和画风，当前页 SB 决定镜头与构图，避免照搬第一页布局。

```powershell
python <SKILL>/scripts/fast_prepare.py prepare --plan <DRAFT>/fast-draft.yaml --run-root <NEW_RUN>
```

准备会复制原文和参考图，保存独立规划文件、画风、完整逐页提示词与字幕计划，并冻结哈希。配置来自 `config/fast.json`，本次快照为 `fast/config.json`；FAST 状态与 STRICT 独立。新目录必须为空，不覆盖旧项目。已有冻结项目再次运行时只恢复，不重新读取外部原稿。规划改变使用新的项目目录；局部文字修正见后文。

```text
<RUN>/
  source/article.md
  fast/
    config.json
    plan.json
    state.json
    planning/analysis.json
    planning/characters.json
    planning/style.json
    planning/storyboard.json
    references/<sha256>.<ext>
    prompts/P01.txt
    captions/P01.json
    images/P01/attempt-01.png
    final/...
```

## 2. 实际内置工具交接

在领取任务前确认内置 `image_gen` 可用。不可用时停止并报告；已有状态使用 `stop --reason "builtin image_gen unavailable"`，不要改用 API Key、CLI 图片生成程序或其他服务。

```powershell
python <SKILL>/scripts/fast_queue.py claim --run-root <RUN>
```

`claim` 只返回一页完整 `request` 和领取凭据，不调用生图、不代表已经实际发生工具调用。将这份请求直接交给 Codex 内置 `image_gen`，传入其中实际参考图片。不要读完故事再重写请求，不扩展候选数量，也不把一页拆为若干独立请求。

新项目先保存第 1 页并完成当前页的轻量视觉检查，队列才开放后续页；之后每页同样检查再继续。人物卡、已有参考及验证后的第一页跨页复用，不增加参考图生成。文件保存成功只证明文件可读且已入库，不能证明人物、情节和分镜正确。旧冻结任务保持原来的队列行为，不自动改写历史规划。

真实工具返回后使用其**实际本地图片路径和真实调用标识**：

```powershell
python <SKILL>/scripts/fast_queue.py complete --run-root <RUN> --page-id P01 --claim-token <CLAIM_TOKEN> --image <ACTUAL_TOOL_OUTPUT> --tool-call-id <ACTUAL_CALL_ID>
```

脚本将文件原始字节复制到本项目 `fast/images/<PAGE>/`，完整解码、校验哈希后才记录 `succeeded`。图片副本独立于工具临时文件。每页保留一个有效成功结果，已有图片不覆盖。失败/重试文件是过程记录，不是额外交付候选。普通恢复直接跳过有效成功页。

新任务保存后，调用者查看实际底图并写 `review.json`，绑定 `page_id`、`image_sha256` 和 `geometry_observed_from_image: true`。`checks` 包含 `character_consistency`、`story_coverage`、`storyboard_execution`，每项为 `{passed: true|false, reason: "具体看图结论"}`。分镜执行需检查所选SB的镜头、动作和情绪机制，不能只数格子。程序不会自动识别画面，这些声明必须来自真实看图，不能把计划坐标或空泛理由冒充实际检查。登记底图审核：

```powershell
python <SKILL>/scripts/fast_queue.py review --run-root <RUN> --page-id P01 --review <ACTUAL_REVIEW.json>
```

画面失败时另记 `failure_kind: image`、`image_defect_reason`，以及 `image_defects: [{category: character|story|storyboard, reason: ...}]`。保留失败图，不自动重发；明确记录该页重试才使用剩余尝试：

```powershell
python <SKILL>/scripts/fast_queue.py retry-visual --run-root <RUN> --page-id P01 --reason "本次画面缺陷和重试理由"
```

字幕遮挡、位置、字号或溢出只记 `caption_issues`，不能当作重新生图理由。已有下游图片后不重新生成其参考第一页。视觉检查与最终人工验收分别记录，检查通过仍保留人工验收待办。

真实生成失败时只登记该页，最多重试一次：

```powershell
python <SKILL>/scripts/fast_queue.py fail --run-root <RUN> --page-id P01 --claim-token <CLAIM_TOKEN> --reason "实际失败原因" --tool-call-id <ACTUAL_CALL_ID>
```

再次 `claim` 只领取可重试的失败页或未完成页，总派发上限每页 2 次，不重置次数。工具调用标识无法取得时不要编造；`fail` 可不填写 ID，记录为未知。成功返回但文件无法取得/无法保存时保留当前调用，先恢复并保存同一次输出，不重复生图。实际工具结果的来源由调用者如实登记；本地文件和字符串 ID 不能密码学证明它来自 GPT。

## 3. 中断与局部恢复

```powershell
python <SKILL>/scripts/fast_queue.py status --run-root <RUN>
```

简明输出包含每页编号、提示词哈希、实际使用的参考图、输出路径/哈希、派发尝试次数、状态、错误原因、`needs_human_review`。`state.json` 还保留每次尝试与事件，不需要向 Codex 输出整份日志。

运行中的领取记录不会自动超时后重发。恢复时先找回原工具结果并用原凭据 `complete`。只有确认该调用已停止且没有可保存结果时，明确登记恢复原因：

```powershell
python <SKILL>/scripts/fast_queue.py recover --run-root <RUN> --page-id P01 --reason "已确认原调用停止且没有可恢复的输出"
```

恢复不会清零次数，未知工具结果继续标为未知。工具不可用或需要停下检查时 `stop --reason ...`；条件解决后 `resume`，不会因此重发运行中的调用。冻结输入变化会阻塞，先恢复正确文件，不能静默改写冻结计划继续。已成功图片缺失/损坏只影响该页；先恢复原文件，有剩余尝试才可重试该页。

## 4. 本地字幕与检查

画面禁止包含中文、字母、数字、标签、水印和气泡。需要的文字用本地字体后期添加：

```powershell
python <SKILL>/scripts/fast_caption.py --run-root <RUN> --page-id P01 --font C:/Windows/Fonts/msyh.ttc
```

新任务先完成画面检查，再根据实际底图落实文字位置。复制冻结字幕计划到 `fast/caption-revisions/`，添加 `image_review`：当前 `page_id` / `image_sha256`、`geometry_observed_from_image: true`、`caption_placements_verified: true`、实际 `panels`（`panel_id,bounds`）、`protected_regions`（`bounds`）和 `speaker_regions`（`speaker_id,panel_id,bounds`）。所有区域使用归一化 xywh；可把同一次看图的几何记录用于视觉检查与字幕定位，不重新分析故事。没有定位记录时返回待定位状态，不把预设框当成已检查成品。

本地复用原文字容器的绘制能力，保持统一字体、线条与配色；旁白、对白、心声、喊话和说明分别选择适合的形式。根据实际画格、说话者和留白调整，避开脸、手和关键物件。尾巴仅使用已确认的同格人物位置，未知归属不编造。

```powershell
python <SKILL>/scripts/fast_caption.py --run-root <RUN> --page-id P01 --font <FROZEN_FONT> --caption-plan fast/caption-revisions/P01-layout-v1.json
```

独立修订可调整文字区域、字号与同语义的气泡形式，保留文字语义和人物归属；修改原文需明确 `text_revision_reason`。文字对齐沿用原容器规则，不支持的显式对齐会报错，位置调整使用 `bounds`。字号调整必须显式指定并满足可读下限，程序不静默缩字。实际字体容量、边界、相互遮挡与人物保护检查通过后另存成品，不改底图、原字幕计划、冻结生图输入或尝试次数。

成功排字在 `fast/caption-selection.json` 记录本页所选修订、字体、底图和成品哈希。默认再次排字会恢复所选版本；选定文件缺失或改变时明确报错，不退回旧字幕。新底图使旧选择失效。交付每页一个选定成品，旧本地版本保留但不混入交付。

新计划的 `first_final_review_required: true` 表示首张含文字成品须先通过检查。`claim` 返回 `awaiting_final_review` 时，查看当前选定成品，写审核 JSON：`page_id`；从当前选择复制 `output_sha256` 为 `image_sha256`、`caption_plan_sha256`；真实看图后填 `actual_final_viewed: true`；`checks` 包含 `storyboard_expression`、`text_scene_integration`、`reading_order`，各项为 `{passed: true|false, reason: "具体看图结论"}`。分别检查原SB叙事机制是否可见、文字与人物/场景是否共同构图且没有无理由统一底栏、阅读顺序及归属是否清楚。不依据计划直接填通过。

```powershell
python <SKILL>/scripts/fast_queue.py review-final --run-root <RUN> --page-id P01 --review <ACTUAL_FINAL_REVIEW.json>
```

通过后继续原队列；记录失败时返回 `final_review_failed` 及具体原因，优先本地重排并复查，不增加图片尝试、不自动授权重生底图。成品、所选文字版本、排版报告或审核记录改变/丢失会使通过状态失效；相同选定版本恢复时复用已有审核。首张无文字不启用这项门槛，旧冻结计划缺该字段时不补加。不为记录检查调用额外分析模型或生成测试图。

旧冻结计划继续支持原有文字流程，不自动补造文字类型、画格或说话者。旧图试排应另存到独立项目或有明确证据的修订，不覆盖历史底图。无需字幕时也可输出本地成品。

查看完整页面，检查人物连贯、必要情节、分镜机制、图文关系、主体遮挡和文字清晰度；交付前使用已有缩略总览，检查是否多页无理由退化成同一种底栏排版。有问题只修相应页面或后期字幕，不为一页重新执行全篇规划。FAST 自动状态说明文件和已登记审核有效，不能证明审美质量或严格验收通过，`needs_human_review` 默认保留为 true；交付时如实说明检查情况。每页交付一个选定最终 PNG；失败记录、模拟结果和旧版本不混入成品。

恢复后继续调整文字时，若已有 `fast/caption-selection.json`，优先从本页当前选定的字幕计划复制为新修订，保留此前字号、位置和已授权文案调整，仅修改本次要求的内容；没有选定版本时才从冻结字幕计划开始。选定记录缺失或校验失败时先恢复正确文件，不用旧版覆盖。

## 5. 消耗记录与离线验证

`status` 区分已派发尝试、已登记工具调用、内置工具调用、模拟结果和未知中断。真实 Token、额度、费用取不到时记录 `null`，不根据页数估价；模拟测试不能证明真实速度或节省比例。

开发测试显式使用 `prepare --simulation`，模拟导入必须 `complete --provider simulation`。真实项目拒绝模拟 provider，模拟项目也拒绝内置工具结果。Pillow 仅可在离线测试夹具中绘制标明模拟的图片，生产画面必须实际调用内置工具。不要把测试图片当作 GPT 产出。

检查漫画的选择理由、镜头关系、情绪停顿和文字归属；模板 ID、种类数量或 `passed` 元数据不代替真实图片阅读。测试产物及备份置于技能扫描目录之外，避免被发现为同名技能。

只运行本次影响的测试：

```powershell
python -m unittest discover -s <SKILL>/scripts/tests -p "test_fast*.py" -q
```

不要在普通 FAST 创作或只改字幕时运行整库 68 套回归。STRICT 模块未改动时只核对它们与模板库保持不变。
