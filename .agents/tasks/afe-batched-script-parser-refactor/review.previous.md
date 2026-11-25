审查证据

已读取 fa32438 提交消息中的验证命令和结果、fa32438..HEAD 的完整相关 diff、当前解析器/会话状态/WebUI/工作流/部署文档/测试及先前 review。未重新运行测试套件，也未修改生产代码或仓库内用户未提交的日志、缓存、任务文件。HEAD 提交消息记录 compileall、scene/parser/prompt/reference/workflow tests、check_graphs、ui_e2e 63/63、node --check、工作流生成和 git diff --check 通过；GPU 与真实 ComfyUI 仍未验证。先前 review 的 pending-claim B5 已复核：当前 app.js/server.py 与 ui_e2e.py:325-339 已覆盖无 prompt_id claim 的刷新、取消和恢复路径，未重新提出该 finding。

阻塞项

- B1，批次提示仍会破坏 A/B 交替场景的原文顺序。script_full_parser_node.py:288-327 把重复物理地点按首次出现分组，导致 A/B/A 的 scene_map 顺序成为 A 的所有 source_blocks 后再到 B；server.py:661-678 又按这个分组顺序构造 batch scene_subset；script_full_parser_node.py:372-397 和 1354-1355 按 scene_map 顺序写入 LLM prompt，而不是按 source_order 全局排序。会话却在 script_analysis_session.py:908-1000 按全局 source unit 顺序校验结果。对任务明确要求的 A/B 交替剧本，Qwen 会看到错误的来源顺序，常见结果是批次输出顺序被拒绝并反复失败，或把另一地点的事实放进当前镜头。修正：保留按地点分组的 scene identity，但在每个 batch 的 prompt scene map、source text 和 source manifest 投递前按 source_order/source_block_id 全局排序，并增加 A/B/A 的实际 batch prompt 顺序回归断言。

- B2，首个可识别场景标题之前的剧本文本没有进入 source manifest。script_full_parser_node.py:231-238、288-293 在存在 header 时从第一个候选 header 的 start 开始建 block，丢弃 raw_script[:first_header.start()]；script_analysis_session.py:34-75 只从这些 scene_map source_blocks 生成持久化 units。当前三岩两语剧本的标题/视觉风格前言以及普通客户剧本中首场前的片头事实因此没有精确 source unit，后续 coverage gate 也无法发现遗漏。修正：为首个 header 前的非空原文建立有序 preamble/title source block，保留原文和 offsets，并让批次规划、prompt、coverage 和最终 manifest 都覆盖它；补充前言含镜头事实的回归测试。

- B3，要求的 36 镜头、逐批持久化/重启恢复模拟验证没有实际覆盖全部批次。tests/test_analysis_session.py:74-87 只创建 9 批、提交第 1 批并读取一次状态；tests/ui_e2e.py:102-109 只用 6 镜头并在第 1 批后刷新。现有证据没有证明 36 镜头的每个批次完成后都可持久化、重启恢复且不重复，缺少用户明确要求的 GPU-free 模拟批次测试。修正：增加 CPU/mock 测试，遍历 36 镜头的 9 批，在每批 commit 后重新实例化 store 并校验完成批次、解析镜头和 source manifest，再模拟中断/恢复直至 complete，同时断言已完成批次不再次提交。

- B4，提交尚未推送到要求的 origin/main。仓库证据 `git rev-list --left-right --count origin/main...HEAD` 为 `0 5`，origin/main 仍停在 3042079，而当前实现位于 HEAD 404de3b。RunPod 更新命令从 origin/main 获取不到这 5 个实现提交，客户部署的代码不包含当前批次解析修复。修正：在保留用户未提交文件的前提下，将当前已审查提交推送到 origin/main，并记录推送后的远端 commit。
