审查证据

基线 fa32438 的提交消息记录了 compileall、scene map、shot contract、prompt fidelity、reference、workflow、graph 和 UI 检查通过；当前 HEAD f595046 的提交消息又记录了 compileall、analysis session、scene map、parser merge、prompt fidelity、reference、shot contract、WebUI、workflow、check_graphs 和 ui_e2e（63/63）通过。GPU 与真实 ComfyUI 仍按提交记录未验证，本审查未重新运行测试套件。

实现核对

- AFE_ScriptFullParser 的每次调用固定为有界 batch；WebUI 从 AnalysisSessionStore 的持久化 claim 构造 batch_start/end 和上下文，不再要求一次调用输出整部剧本。
- session.json 持久化原始剧本、script_signature、目标镜头数、批次范围、完成/失败状态、parsed_shots、scene_map、source_manifest 和失败原因；批次结果按签名写入 batches/<signature>/，claim token、prompt id、锁、恢复、幂等提交和定向取消路径均已核对。
- commit 前检查批次数量、shot id 顺序、source manifest 的覆盖/顺序/重复、shot source_unit_ids 覆盖和 source-validation 错误；不完整或 Phase 2 失败不会成功发布。完成会话才发布 analysis.json，AFE_AnalysisLoader 和 stage 2 gate 继续拒绝 partial/orphan 结果。
- Phase 2 的 null/冲突事实合并保留已验证的 Phase 1/source 事实；场景顺序、重复位置、环境、表情、微动作、business、道具互动、对白、动作三阶段和运镜字段的调用链已核对。无角色/无道具路径、普通中英文标题、36 镜头恢复/幂等/失败重试/源校验均有 CPU/mock 覆盖。
- /afe/ 页面显示批次与镜头进度，提供继续、定向重试和取消；五步流程、参考图可选、素材/首帧/Wan/成片和 show_text_party 兼容路径保留。脚本解析完成前不会进入 Krea、Qwen Image、Wan 或成片。工作流、部署文档和 RunPod 验收步骤已同步，旧 now-02/now-03 仅被文档明确禁止直接排队。

结论

在已记录的 CPU/mock 证据和代码路径审查范围内，未发现满足批准任务所需修正的可达正确性、安全性或数据完整性阻塞项。GPU、真实 ComfyUI 和视觉质量仍是部署验收项，不构成此次代码 gate 的 blocker。