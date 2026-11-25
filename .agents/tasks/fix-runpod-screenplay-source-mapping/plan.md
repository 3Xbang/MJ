# Implementation Plan

根因已由当前代码链路确定：`AnalysisSessionStore.create()` 在 `script_analysis_session.py:37-252` 根据 `screenplay_source_units.source_units_with_offsets()` 把每个显式“镜头标题 + 正文”保存为一个不可拆分 unit，并按 `(source_block_id, unit_id)` 为 9 个批次建立精确范围；`webui/server.py:665-735` 又把该范围作为 `batch_units`、`batch_unit_ids` 和批次 prompt source context 传入 ComfyUI。也就是说，批次规划和恢复状态本身已经保留了正确的 36 个 source unit。

错误发生在 `script_full_parser_node.py:1589-1667`：Phase 1 返回的 `source_block_id`、`source_unit_ids`、`source_start/end` 和 `source_shot_text` 仍被当作来源真相。Qwen 返回 4 个 shot 并不保证这些字段逐字对应批次 catalog；`_validated_source_fragment()` 在没有精确证据时返回 `missing verified source_unit_ids, source offsets, or verbatim source_shot_text`，随后 `sd` 为空而抛出用户看到的 `分镜 shot_001 缺少可验证的原文描述`。当前 Phase 2 还把整个 source block 作为“environment only”上下文发送，里面含有同批其他镜头，进一步使模型映射与批次范围脱节。

选择的最小修复是：显式镜头模式下由已持久化、按剧本顺序排列的 batch source catalog 绑定 Phase 1 的第 N 个返回项，而不是让模型决定来源；覆盖到输出的 `source_block_id`、`scene_occurrence_id`、`source_unit_ids`、`source_start/end`、`source_shot_text` 和 `source_text` 全部来自同一个原文 unit。Phase 1/Phase 2 的事实仍必须通过该 canonical fragment 验证，模型生成的错误事实仍阻止批次。Phase 2 的附加 source context 改为当前 block 的 context unit，不能再把同一 block 的兄弟镜头当作场景上下文；地点环境分析继续使用既有的 place-only `environment_source_text` 路径。普通无显式镜头标题、片头/闪切、A/B/A、无角色/无道具路径继续走现有通用分支，不放宽其严格验证。

- [ ] 1. 在 `script_full_parser_node.py` 增加显式批次 source catalog，并在 Phase 1 结果进入覆盖校验前按 canonical 顺序绑定当前批次的镜头。
      对显式 source units 要求当前 batch 的数量、顺序和 `(scene, source_block, unit)` 一一对应；覆盖 Phase 1 模型可能缺失或错误的来源元数据，但保留并验证其动作、角色、对白、道具、表情、光线等事实。生成 full shot 时写入 canonical offsets/fragment/source unit IDs，并让 Phase 2 只收到当前 source context 和该 shot 的 exact fragment，避免把兄弟镜头当作可用事实。
      文件：`E:\MJ\ai_film_editor_nodes\nodes\director\script_full_parser_node.py`
      验证：`python3 tests/test_parser_merge.py`、`python3 tests/test_explicit_shot_batch_boundaries.py`；现有 strict source-validation、A/B/A、相机来源和 Phase 2 失败测试继续通过，新的 canonical mapping 测试通过。

- [ ] 2. 增加完整 36 镜头 CPU 回归，覆盖真实剧本文本、批次 parser、session commit 和最终发布门禁。
      在 `tests/test_full_script_batch_regression.py` 直接读取 `test_scripts/san_yan_liang_yu_ep01_fidelity_test.md`，使用 stub LLM 模拟 Phase 1 不提供可靠 source IDs/offsets、Phase 2 只返回可接受结构，并为 9 个批次逐一生成与生产路径等价的 batch context。断言 9 批、每批 4 个显式不可拆分 unit，`shot_001` 的 fragment/IDs/offsets/scene occurrence 一致，Phase 2 不看到兄弟 shot，shot IDs 从 001 到 036 连续；把每批提交到 `AnalysisSessionStore`，重启/恢复语义不丢失，最后用 `Api._assembled_analysis()` 和 `_validate_analysis_payload()` 验证完整结果可发布。不要改变网页协议、继续/重试/取消、重启恢复、完整 session gate、参考图可选、`show_text_party` 或后续五步流程。
      文件：`E:\MJ\ai_film_editor_nodes\tests\test_full_script_batch_regression.py`
      验证：`python3 tests/test_full_script_batch_regression.py`；随后执行完整 CPU/UI/图回归（见 Digest），确认第一批不再因缺少可验证原文失败，且 session 仍只按顺序 claim 下一批。

## Digest

- `E:\MJ\ai_film_editor_nodes\nodes\director\script_full_parser_node.py`：读取过 `_source_units_for_block()`（27-32）、`_validated_source_fragment()`（851-930）、`_phase1_source_coverage_errors()`（943-1049）、`_select_batch_scene_map()`（1144-1209）、`parse_script()` 的批次 context/Phase 1/Phase 2 链路（1349-1667），以及 full shot/source manifest 输出（1730-1742、1870-1905）。计划只改这些 source-binding、Phase 2 context 和输出字段块。覆盖测试为现有 `tests/test_parser_merge.py`（来源验证、事实保护、环境 context、Phase 2 失败）和新增 36-shot 回归；验证命令为 `python3 tests/test_parser_merge.py`、`python3 tests/test_explicit_shot_batch_boundaries.py`。
- `E:\MJ\ai_film_editor_nodes\nodes\director\screenplay_source_units.py`：读取过 `EXPLICIT_SHOT_HEADER_RE`（9-14）、`source_units_with_offsets()`（50-130）和 `explicit_shot_units()`（133-135）。它已经把显式标题与正文保留为同一 unit，计划不改；现有 `tests/test_explicit_shot_batch_boundaries.py` 覆盖标题/正文不可拆分。
- `E:\MJ\ai_film_editor_nodes\nodes\director\script_analysis_session.py`：读取过 `_unit_manifest()`（37-106）、`create()`（147-252）、batch claim/commit 校验（358-610）和 `recover_orphaned_running()`（611-646）。它已经按 block+unit 保存 9×4 范围并严格拒绝重复、遗漏、乱序，计划不改；新增回归覆盖最终 commit/publish，现有 `tests/test_analysis_session.py` 覆盖顺序、A/B/A、失败重试、取消和重启恢复。
- `E:\MJ\ai_film_editor_nodes\webui\server.py`：读取过 `_validate_analysis_payload()`（102-180）及 `/run` 中 source range 到 `batch_units`/prompt context 的构造（665-735），以及 `/collect` 的 commit/publish 门禁（830-940）。生产路径已经传递持久化范围，计划不改网页行为；`tests/test_webui_validation.py`、`tests/ui_e2e.py` 和新的 parser/session 回归验证它仍然接受完整结果、拒绝 partial/orphan 结果。
- `E:\MJ\ai_film_editor_nodes\tests\test_full_script_batch_regression.py`：新建；读取完整 `test_scripts/san_yan_liang_yu_ep01_fidelity_test.md`，stub LLM 不加载 GPU，覆盖 canonical source binding、Phase 2 sibling isolation、9 批连续提交和最终发布。
- `E:\MJ\ai_film_editor_nodes\gen_afe_main_workflow.py`：读取过 batch/full workflow 生成器（1-85）；不改。生成/图验证命令：`python3 gen_afe_main_workflow.py`、`python3 tests/test_workflow_graph.py`、`python3 tests/check_graphs.py`，并确认生成的 `workflow_templates/afe_full_pipeline.json` 与 `workflow_templates/afe_script_pipeline.json` 没有非预期 diff。

完成实现后的仓库验证顺序：

```bash
python3 -m compileall -q nodes webui tests
python3 tests/test_full_script_batch_regression.py
python3 tests/test_analysis_session.py
python3 tests/test_scene_map.py
python3 tests/test_parser_merge.py
python3 tests/test_prompt_fidelity.py
python3 tests/test_reference_dependencies.py
python3 tests/test_shot_contract.py
python3 tests/test_webui_validation.py
python3 tests/test_workflow_graph.py
python3 tests/check_graphs.py
python3 gen_afe_main_workflow.py
python3 tests/ui_e2e.py
```

RunPod 更新命令（在真实 Pod 执行）：

```bash
cd /workspace/runpod-slim/ComfyUI/custom_nodes && { [ -d ai_film_editor_nodes/.git ] && git -C ai_film_editor_nodes pull origin main || git clone https://github.com/3Xbang/MJ.git ai_film_editor_nodes; } && bash ai_film_editor_nodes/deploy_pod.sh
```

真实验收：确认 `/tmp/comfyui.log` 没有 `IMPORT FAILED`；打开 `/afe/` 粘贴同一份 180 秒/36 镜头剧本，确认第 1 批显示 4/36 且 shot_001 成功保存逐字 source fragment；刷新、取消后继续，制造一次失败后只重试失败批次，重启 ComfyUI 后确认 running 批次可恢复且已完成批次不重复；完成 9 批后确认 `analysis.json` 通过完整 session gate，再按素材、首帧、Wan、成片五步顺序验收有参考图和无参考图、`show_text_party` 报告、空角色/空道具路径。CPU 回归不替代真实 GPU 视觉质量判断。
