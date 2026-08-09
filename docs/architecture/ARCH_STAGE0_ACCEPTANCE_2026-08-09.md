# DataGuard 阶段 0 架构验收

## 1. 验收结论

**ACCEPTED — Stage 0 contract-ready。**

不可变开发快照
`9c971e41d6e44f1cd0c8cd7351188314dac3295d` 已通过独立测试和架构复核，
满足本轮“项目骨架、章程、RAG 架构、安全边界、机器可读契约和工作记录模板”
的验收范围。阻断缺陷为 0，高严重度缺陷为 0，没有未关闭的架构偏差。

本结论不表示 API、RAG 管线、合成 fixture、Ollama、数据库、Compose 或任何实验
结果已经实现或运行，也不表示 evidence gate、portfolio、生产安全或合规已经通过。

## 2. 验收元数据

- 日期：2026-08-09（Asia/Shanghai，UTC+08:00）
- 验收角色：系统架构师
- 分支：`main`
- 开发快照：`9c971e41d6e44f1cd0c8cd7351188314dac3295d`
- 开发记录：`docs/development/DEV_STAGE0_2026-08-09.md`
- 独立测试记录：`docs/testing/TEST_STAGE0_ACCEPTANCE_2026-08-09.md`
- 测试结论：`PASS`
- Portfolio eligible：`no`
- 产品发布批准：`no`
- 阶段 0 文档基线发布：`yes`

## 3. 证据链

| 证据 | 结果 | 架构判定 |
| --- | --- | --- |
| 开发交付记录 | 文档、8 个机器契约和 3 类模板完成；未写业务代码 | 职责与范围合规 |
| 不可变待测提交 | 根提交 `9c971e41…`，26 个文件、4,026 行新增，测试开始时工作树 clean | 可追踪、可复测 |
| 独立测试 | 3/3 YAML、5/5 JSON Schema、34 个 Schema 正反例、20 个 OpenAPI 反例通过 | 测试证据充分 |
| 引用完整性 | 80 个 OpenAPI ref、137 个 Schema ref、21 个本地 Markdown link 解析 | 无悬空引用 |
| 架构师复核 | 结构、跨契约、可满足性、反例、许可、敏感信息和换行检查通过 | 无未关闭偏差 |
| GitHub 基线 | 主机凭据验证为 `haoran014-stack`；远端公开且无默认分支/历史 | 初始化 `main` 不覆盖既有历史 |

架构师另行构造了完整的 identity、corpus、scenario、manifest 和 62-result report
内存 witness，并验证合法实例被接受；角色注入、evaluation modes 注入、错误双语
分布、SQLite portfolio、非零 indeterminate 和 protected-fragment 冒充 Canary
明细等反例被拒绝。测试代理没有采信开发记录中的自检结论。

## 4. 需求追踪与判定

| 需求/控制 | 设计与契约证据 | 独立测试 | 判定 |
| --- | --- | --- | --- |
| 阶段 0 仅文档/契约 | README、charter、文件清单 | 无源码、入口、依赖、迁移或 Compose | PASS |
| 六个公共端点 | `openapi.yaml` | 路径、方法、请求/响应反例 | PASS |
| 合成身份与授权矩阵 | identity/corpus schema、governance | 6 身份、2/role、累计 allowed_roles | PASS |
| 固定数据分布 | corpus/scenario/report/manifest schema | 30 文档、62 场景及双语反例 | PASS |
| Baseline 对照路径 | 架构、威胁模型、契约索引 | 全语料、弱隔离、observe-only 一致 | PASS |
| Guarded 八步路径 | 架构时序、README、契约索引 | 三份顺序逐项一致，无可重排旁路 | PASS |
| 输出检测与阻断 | 3 DetectionType、固定回复、whole-output discard | Canary-only 明细和未知类型反例 | PASS |
| 本地模型和参数 | manifest/report/health contract | 模型 tag、digest 字段和参数 const | PASS |
| 运行、错误和报告状态 | OpenAPI、error catalog、report schema | 16 ErrorCode、5 RunStatus、报告状态反例 | PASS |
| 审计和零原文持久化 | 审计 allowlist、governance | 自由文本 reason/message/raw 字段被拒绝 | PASS |
| 指标和 evidence gate | metrics、report gate schema | 阈值、portfolio 组合和分布反例 | PASS |
| 许可证和内容边界 | MIT、README 模型许可说明 | 仓库许可与第三方模型许可分离 | PASS |
| 三角色工作记录 | development/testing/architecture 模板与 dated records | 字段和职责边界检查 | PASS |

## 5. 架构偏差复核

开发过程中识别的偏差均在待测快照前关闭：

1. `blocked_baseline_attack_count` 的防护归因由可重复数组收紧为唯一
   `prevention_stage`。
2. `canary_hit_details` 收紧为仅允许 `document_canary` 和
   `system_canary`，不允许混入 unauthorized protected fragment。
3. 报告 gate 的 operator/threshold、62 场景分布和
   `portfolio_eligible=true` 的 PostgreSQL/strict/comparable/zero-indeterminate
   条件由 Schema 直接约束。
4. AuditEvent 删除自由文本 `reason_codes`，失败原因仅引用稳定 ErrorCode；
   权限拒绝和检测继续使用结构化字段。
5. 架构图补齐 baseline/guarded 共用 versioned vector index，并消除 corpus
   绕过检索进入上下文的歧义。
6. 明确 queued 重启后继续调度，重启前 running 原子转为 interrupted 且不自动重跑。
7. 删除 LLM 位级确定性暗示；确定性 simulator 只准用于单元测试。
8. README 区分仓库 MIT 与第三方模型许可；`.gitattributes` 固定当前文本为 LF，
   防止跨平台 artifact digest 因换行漂移。

最终判定：没有偏离已批准 RAG 架构的开放项。

## 6. 安全与数据边界判定

- 数据、身份、Canary 和 protected fragment 均为合成 fixture；真实身份、业务数据、
  生产日志、凭据和远程模型 token 禁止进入项目。
- 调用方只提交 `subject_id`；角色从版本化合成身份表解析。这是实验授权模型，
  不是现实认证。
- Baseline 的越权候选进入上下文是受控实验变量，只允许本地、纯合成环境。
- Guarded 必须先做角色过滤再检索，随后执行 JSON 不可信边界、消息隔离和完整输出检测。
- 原始 question、document、context、prompt、reply、Canary 和 protected fragment
  不得进入数据库、审计、指标或报告。
- Ollama/模型不可用时必须显式失败；除隔离单元测试外不得用 simulator 静默替代。
- Compose 在后续阶段只包含 API 与 PostgreSQL；宿主机 Ollama 独立管理。

## 7. 残余限制与下一阶段硬门槛

| ID | 残余限制 | 处置要求 | 阻断时点 |
| --- | --- | --- | --- |
| ST0-R01 | 尚无实现、fixture、数据库或真实报告 | 阶段 1/后续阶段按契约实现，不得声称已有指标 | 产品/实验验收前 |
| ST0-R02 | JSON Schema 不能独立证明全部跨记录和算术关系 | 实现 semantic validator，并覆盖测试报告第 9 节全部负向用例 | 阶段 1 合并前 |
| ST0-R03 | 本地 Ollama 版本、完整 digest、embedding dimensions 尚未采集 | 运行时读取并写入 strict manifest/report，失配显式失败 | evidence run 前 |
| ST0-R04 | 第三方模型许可和模型库内容可能变化 | 拉取/分发模型前重新核对当时条款；模型不进入仓库 | 获取模型前 |
| ST0-R05 | 合成角色模型不提供现实认证 | 保持本地实验边界；若未来扩为生产系统必须另做身份架构 | 任何生产化前 |
| ST0-R06 | 历史 baseline 文档描述的是空仓起点 | 以后以 Git SHA 和最新 dated record 为准，不把历史阻塞当当前状态 | 下一轮开始时 |

阶段 1 的 semantic validator 至少必须强制：跨文件 ID 唯一/引用、fragment 与
document 授权一致、一文档一 authorized-QA、rate/gate/summary 算术、outcome/judgment
状态关系、固定 blocked reply，以及 Problem Details code/status/retryable 配对。

## 8. 最终声明

批准把阶段 0 文档与契约基线发布到远端 `main`，并允许在用户确认后进入下一开发
阶段。未批准业务产品发布、真实数据接入、远程模型接入或简历/portfolio 指标声明。

本文件记录被测提交 SHA。包含独立测试报告和本验收文件的最终证据提交在本文件
生成后创建，因此无法无递归地写入自身 SHA；最终提交 SHA 和远端
`refs/heads/main` 一致性由推送后的 Git 证据和本轮交付说明记录。
