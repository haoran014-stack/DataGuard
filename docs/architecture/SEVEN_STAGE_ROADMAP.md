# DataGuard 七阶段项目进度权威路线

本文是 DataGuard 项目阶段划分、阶段进度和进入下一阶段条件的权威口径。
阶段实现范围仍须同时满足对应机器契约和阶段验收文档；如其他历史文档使用
不同的阶段编号或合并范围，以本文的七阶段编号报告项目进度。

以下为批准的七阶段路线原文，仅将换行规范化为仓库 LF：

---

# DataGuard 分阶段开发路线

## 总体节奏

项目划分为 7 个阶段。每个阶段都是一个独立开发轮次，必须依次经过：

1. 架构师下发本阶段契约和验收标准。
2. 开发 Agent 实现并生成开发工作文档。
3. 测试 Agent 独立验证并生成测试证据。
4. 架构师审阅代码、测试结果和架构偏差。
5. 验收通过后合并到 `main` 并推送 GitHub。
6. 验收失败则退回开发，不将该轮标记为可交付版本。

前一阶段未通过，不进入后一阶段。除最终阶段外不创建正式版本标签，只保留可追踪提交；全部验收通过后创建 `v1.0.0`。

## 阶段 0：项目与架构基线

目标是先冻结规则和接口，不开发业务功能。

交付内容：

- 初始化 DataGuard Git 仓库和 `main` 分支。
- MIT LICENSE、`.gitignore`、README 骨架和项目 charter。
- 威胁模型、风险 taxonomy、数据治理和安全边界。
- baseline/guarded 数据流和信任边界架构图。
- API、YAML、错误码、指标和报告 schema 契约。
- 开发、测试、架构验收工作文档模板。
- 明确不使用真实数据、真实认证、云模型、文档上传和生产凭据。

阶段验收：

- 所有公共接口和枚举没有未决项。
- 四类攻击及成功判定定义清楚。
- baseline 的故意不安全行为被明确限定在合成、本地实验环境。
- guarded 的过滤、隔离、检测、阻断和审计顺序固定。
- 本阶段不应出现业务实现代码。

Git 检查点：`chore: establish DataGuard architecture baseline`

## 阶段 1：合成数据与领域模型

目标是建立不依赖 Ollama 和数据库的确定性数据基础。

交付内容：

- 6 个合成身份，每种角色 2 个。
- 30 份原子文档：
  - public、internal、confidential 各 10 份；
  - 每级中文、英文各 5 份；
  - 每份显式声明 `classification` 和 `allowed_roles`。
- 每文档唯一 Canary、受保护片段和内容警告。
- 62 个 YAML 场景：
  - 合法授权问答 30 个；
  - 四类攻击各 8 个。
- Pydantic 数据模型和 YAML 校验器。
- 语料、身份、场景的规范化 SHA-256。
- 角色—文档授权矩阵和版本化事实断言评分器。
- Unicode NFKC、大小写、零宽字符和空白规范化组件。

阶段测试：

- 3×30 的角色—文档授权矩阵全部验证。
- 重复 ID、非法角色、缺失 Canary、非法 allowlist 和语料版本不一致必须拒绝加载。
- 每份文档恰好有一个合法问答场景。
- 四类攻击分别为 8 个，中英各 4 个。
- 规范化与输入哈希在固定 fixture 上稳定。
- 不得出现真实 PII、凭据或企业数据模式。

阶段验收：

- 数据矩阵、数量、语言和角色分布符合契约。
- 所有测试只依赖确定性代码，不需要 Ollama。
- 合成数据来源和 MIT 许可可从 manifest 追踪。

Git 检查点：`feat: add versioned synthetic corpus and scenario contracts`

## 阶段 2：Ollama、向量检索与 Baseline RAG

目标是先完成可运行、故意不设权限防护的基线链路。

交付内容：

- Ollama HTTP 适配器：
  - `/api/version`
  - `/api/tags`
  - `/api/embed`
  - `/api/chat`
- 生成模型 `qwen2.5:3b-instruct`。
- embedding 模型 `qwen3-embedding:0.6b`。
- 30 个文档的进程内向量索引。
- 固定余弦排序、`retrieval_top_k=4` 和 `doc_id` 同分排序。
- baseline 上下文拼装模板及模板 hash。
- `POST /v1/chat` 的 baseline 模式。
- `GET /health` 的 Ollama、模型和 digest 状态。
- 模型未安装、Ollama 离线、超时和非法响应的显式错误。

阶段测试：

- 单元测试使用确定性模型适配器，只验证排序、模板和错误映射。
- 真实模型集成测试验证 embedding 和 chat 两条链路。
- baseline 检索必须允许未授权文档成为候选并进入上下文。
- 审核代码不得自动执行 `ollama pull`。
- Ollama 不可用时返回 503，不得生成模拟回复。
- 报告级运行参数必须能从实际请求和 Ollama 环境读取。

阶段验收：

- 相同模型、语料、问题和参数产生稳定的检索文档顺序。
- baseline 至少能在受控探索场景中复现一次 Canary 或越权片段输出。
- 不在本阶段为达到指标修改 guarded 逻辑，因为 guarded 尚未实现。

Git 检查点：`feat: implement local Ollama baseline RAG`

## 阶段 3：Guarded 防护链与聊天审计

目标是完成 DataGuard 的核心分层防护。

交付内容：

- `subject_id` 到合成角色的服务端解析。
- guarded 的角色过滤后检索。
- 不可信文档 JSON 边界标记。
- 系统指令、文档和用户问题的独立消息隔离。
- 文档 Canary、系统 Canary 和角色感知 protected fragment 检测。
- baseline 检测观察模式和 guarded 强制阻断模式。
- guarded 命中后完整丢弃原回复，返回固定安全回复。
- `POST /v1/chat` 完整支持：
  - `baseline`
  - `guarded`
  - `answered`
  - `blocked`
- SQLite 下的最小化审计：
  - chat trace
  - 检索记录
  - 授权判定
  - 输出检测
  - audit events
- `GET /v1/audit-events` 过滤和 cursor 分页。

阶段测试：

- guest、employee、security_reviewer 的累进权限矩阵。
- guarded 中未授权文档不得参与向量排序或进入上下文。
- 文档内容无法通过边界字符伪造系统消息。
- Canary 对所有角色永久禁止。
- protected fragment 对授权主体允许、对越权主体阻断。
- baseline 记录检测结果但不修改回复。
- guarded 阻断后数据库和日志中不存在原始模型输出。
- 审计不保存原始问题、上下文、回复、Canary 或敏感片段。
- 数据库异常返回明确 503。

阶段验收：

- 四类攻击各有至少一个代表性集成用例。
- guarded 跨角色代表用例的越权上下文数为 0。
- guarded 输出检测代表用例的最终泄露数为 0。
- security_reviewer 合法读取机密文档不会被统一误拒绝。

Git 检查点：`feat: add guarded RAG controls and minimized audit`

## 阶段 4：评测运行器与对照报告

目标是把单次聊天能力升级为完整的 baseline/guarded 配对实验。

交付内容：

- `POST /v1/evaluation-runs`。
- `GET /v1/evaluation-runs/{run_id}`。
- API 进程内单任务 FIFO 队列。
- `queued/running/completed/failed/interrupted` 状态机。
- 每个场景的 baseline/guarded 配对 trace。
- 62 个场景的完整执行。
- 确定性事实断言和泄露判定。
- 固定指标：
  - baseline/guarded 攻击成功率
  - 攻击到达上下文比例
  - 检索授权违规率
  - 被防护阻断的基线攻击数
  - 合法授权问答通过率
  - 误拒绝率
  - Canary 命中详情
- `GET /v1/reports/{run_id}` 的 JSON 和 HTML。
- 报告 schema version、环境信息和 `comparability_key`。
- 服务重启后 queued 任务恢复、running 任务转为 interrupted。

阶段测试：

- 运行状态合法转换和重复提交处理。
- 单任务串行执行，不并发争用 GPU。
- baseline/guarded 必须使用相同身份、问题、语料和模型参数。
- attack success 只依据最终返回泄露，不把越权入上下文直接当作输出泄露。
- blocked baseline attack 必须能追踪到角色过滤、提示隔离或输出门禁。
- 报告中不得出现原始问题、完整回复、Canary 或 protected fragment。
- JSON 与 HTML 的指标、分母和运行环境一致。

阶段验收：

- 真实 Ollama exploratory 运行能够完成全部 62 个场景。
- 四类攻击均生成独立指标。
- 任一场景失败不能被忽略；运行必须标记 failed 或在报告中明确记录失败。
- 两份不同 `comparability_key` 的报告不得被标记为可直接回归比较。

Git 检查点：`feat: add paired evaluation runs and sanitized reports`

## 阶段 5：Evidence 门禁、PostgreSQL 与 Docker

目标是建立可复验的正式实验环境。

交付内容：

- PostgreSQL 存储适配器。
- Compose 仅包含：
  - DataGuard API
  - PostgreSQL
- PostgreSQL 位于私有 Compose 网络，不发布宿主机端口。
- API 通过 `host.docker.internal:11434` 访问宿主机 Ollama。
- PostgreSQL 密码必须通过被忽略的 `.env` 提供。
- `exploratory/evidence` 两种运行档位。
- 版本化 experiment manifest，固定：
  - 两个模型的完整 digest
  - Ollama 版本
  - 模型参数
  - 模板 hash
  - 语料和场景 hash
  - 防护策略版本
  - PostgreSQL 后端
- evidence 清单不匹配时 fail-closed。
- 显式确认的 manifest 捕获和更新脚本。

阶段测试：

- SQLite 与 PostgreSQL 的领域行为一致。
- evidence 在 SQLite 上必须拒绝。
- PostgreSQL 不可用时返回 503。
- PostgreSQL 中断时运行状态明确变为 failed/interrupted。
- Compose API 和 PostgreSQL 健康检查。
- 容器内 API 能访问宿主机 Ollama。
- API、数据库和 Ollama 任一依赖缺失时不得返回模拟成功。
- 数据库和容器日志不得出现原始敏感测试内容。

阶段验收：

- 全套 PostgreSQL integration 通过。
- evidence preflight 能识别模型、Ollama、语料、模板和配置漂移。
- Docker 环境可以从干净数据库完成一次 exploratory 对照运行。
- Compose 中没有 Ollama 容器或额外 worker 服务。

Git 检查点：`feat: add PostgreSQL delivery and evidence gating`

## 阶段 6：正式证据、文档与 V1 发布

目标是产生可公开验证、但不夸大结论的最终作品集证据。

交付内容：

- 在固定 experiment manifest 和 PostgreSQL 环境中运行真实 evidence。
- 导出：
  - 脱敏 JSON
  - 静态 HTML
  - SHA-256 manifest
- README 完整补齐：
  - 项目问题与非目标
  - 威胁模型
  - 架构图
  - 数据来源、MIT 许可和内容警告
  - 第三方模型许可
  - 安装与运行
  - baseline/guarded 复现实验
  - 指标定义
  - 局限性
  - 安全边界
- 演示脚本覆盖：
  - baseline 越权泄露
  - guarded 角色过滤
  - 间接提示注入
  - 输出 Canary 阻断
  - 合法 reviewer 问答
  - 审计与报告查询
- 发布检查清单和最终测试证据。
- 只有真实报告达到门槛后才撰写 DataGuard 简历表述。

最终验收：

- baseline 四类攻击各至少 1 次成功，总 ASR ≥20%。
- guarded 最终泄露数为 0。
- guarded 跨角色越权文档入上下文数为 0。
- 合法问答通过率 ≥80%。
- 主动误拒绝率 ≤10%。
- 报告 `portfolio_eligible=true`。
- JSON、HTML 和 manifest 哈希一致。
- README 中所有数字能追踪到归档 evidence 报告。
- 全部单元、真实模型集成、PostgreSQL 集成和 manifest 验证通过。
- 架构师完成最终需求追踪和残余风险审阅。

Git 检查点：`release: DataGuard v1.0.0`

最终版本标签：`v1.0.0`
