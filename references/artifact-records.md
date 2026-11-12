# 数据结构与检查命令

## 项目记录

按规模保存源文件/哈希、覆盖表、论文和图源台账、逐页讲稿 JSON、逐页 QA、可编辑 PPTX。小汇报可合表。DOCX/PDF 按要求提供。稳定 slide/figure/paper ID，重排后更新页码。隐藏页脚不删除图源记录，不打包机构凭据或会话。

图源记录至少包括 paper_id/title/year/DOI/URL/version、species/tissue/model、figure_id/figure_number/visible_panels、figure_kind、local_original/local_placed、sha256/crop_bounds、caption、direct_observation、supported_claim、unsupported_claim、verified_against_primary_source。

figure_kind 区分原文整图、完整子面板、作者示意、教学重绘。资料说明真实值与核对状态，未读原文不能标 verified。图注与原文按许可和任务需要简洁引用/转述。

## 讲稿格式

```json
{
  "slides": [
    {
      "page": 1,
      "slide_id": "s001",
      "title": "当前实际标题",
      "question": "当前生物学问题",
      "visual_kind": "paper_data",
      "source": "Actual paper title and DOI",
      "source_url": "primary-source-url",
      "target_minutes": 5,
      "segments": [
        {
          "purpose": "研究问题与场景",
          "spoken_text": "能直接讲的正文与参考答案",
          "teacher_cue": "指图/停顿，不计入口播",
          "figure_ids": ["p01_f2b"]
        }
      ],
      "figures": [
        {
          "id": "p01_f2b",
          "panels": ["b"],
          "spoken_explanation": "具体图解释和边界",
          "explained_in_segments": true
        }
      ],
      "planned_interaction_seconds": 30,
      "blue_comment": "蓝色教师批注"
    }
  ]
}
```

上述只是结构示例，不是完成内容。spoken_explanation 是覆盖索引，不重复计入口播。封面/转场用 visual_kind=cover/transition，不虚构数据。脚本兼容数组、spoken_script、talk、字符串 segments，但提示旧格式可能混入指令。

## 命令

以下 python3 表示明确 Python 3；Windows 可用 py -3、工作区 Python 3 绝对路径或配置的 uv run。只有标准库依赖。

```text
python3 scripts/ppt_workflow.py inventory source.pptx --output audit/slide_inventory.json
python3 scripts/ppt_workflow.py audit-script narration.json --expected-slides 40 --min-minutes 5 --require-blue --output audit/narration_audit.json
python3 scripts/ppt_workflow.py compare-decks original.pptx annotated.pptx --output audit/visual_parts_comparison.json
```

inventory 读取所有页，无静默 limit。导出实际页序、全文/备注、图片关系/哈希/裁切、简单边界、重复候选与读取告警。母版/布局图片不混入科学图重复统计；直接放在 slide 的标志可能被提示，人工登记允许复用。

audit-script 的 expected-slides 必填。min-minutes 默认 0，只在任务有下限时设置；每页亦可有 target_minutes，取两者较严格的要求。默认中文 180 汉字/分钟、英文 130 词/分钟，可用 cjk-rate/word-rate 调整。计划互动不计正文下限。检查页码缺漏/重复、无正文、估计时长不足、缺蓝批注、已声明图缺解释、指令混入口播和长片段重复。要求蓝色教师批注时加 require-blue，让缺失成为必要项失败。

时长估计不等于试讲；不足须扩写当前图特有内容。重复是人工复查线索。未声明完整图列表不能靠此脚本认证所有图已覆盖。

compare-decks 核对实际页序/尺寸及 slide/media/layout/master/theme/chart/embedding 等可视相关部件。visual_parts_identical 只表示这些部件逐字节一致。正常改图/版面会有差异，应渲染检查而非强行消除。

所有命令写 JSON，stdout 仅短状态。退出 0 表示检查完成，退出 1 表示读写/格式错误、讲稿必要项不足或可视部件比较有差异。inventory 裁切/重复不自动失败；所有告警在最终 QA 登记通过、修复或未解决。
