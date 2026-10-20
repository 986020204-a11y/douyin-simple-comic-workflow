# 0.9.0-rc.1 分镜选择与节奏检查验证

本次修复针对把一次SB选型扩展为整篇固定版式的问题。多页入口按各页内容分别比较真实兼容模板；准备、队列恢复与交付使用同一份整篇审核。正常模式缺失页ID、借用其他页证明、过期决策或目标与审核不一致均阻止继续。

本地验证环境为 Windows / Python 3.12.4，结果如下：

| 检查 | 结果 |
| --- | --- |
| 现有生产准备、队列、运行时、文字和交付回归 | 127项通过 |
| 新增逐页选择、重复检查和生成门槛回归 | 45项通过 |
| 内置模板、字段与索引检查 | 68个模板，0错误 |
| 原生画格几何诊断 | 68个模板通过 |
| 缺格、移格等错误结构反例 | 272个全部被拒绝 |
| Skill格式、双插件清单及版本一致性 | 通过 |

复现命令：

```sh
python -m pip install -r requirements.txt
python -B -m unittest discover -s regression/production -p 'test_*.py' -v
python -B -m unittest discover -s skills/douyin-simple-comic-workflow/scripts/tests -p 'test_storyboard*.py' -v
python -B skills/douyin-simple-comic-workflow/scripts/check_executable_templates.py --root skills/douyin-simple-comic-workflow/references/comic-layouts --output .local-validation/templates.json --check-index
python -B skills/douyin-simple-comic-workflow/scripts/verify_template_library.py --root skills/douyin-simple-comic-workflow/references/comic-layouts --output .local-validation/geometry
```

仓库CI在Ubuntu / Python 3.11执行两组回归及模板检查。队列与交付的普通模式对抗测试补充合法的分镜审核前提，保留原有风险断言，保证失败来自待测风险而非缺失新版前置条件。

这些测试不调用图像服务，生成的纯色证明和几何诊断不是故事插画或人工视觉验收。模板索引仍保留原有观察不确定性，结构通过不代表全部文字效果、源预览像素一致或实际漫画质量通过。合理的叙事重复和用户明确要求统一格式仍可记录；不要求每页不同，也不设置模板种类配额。
