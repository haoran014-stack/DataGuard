# DataGuard Stage 2 总架构验收

- 日期：2026-08-11（Asia/Shanghai）
- 验收角色：主架构师
- 产品候选：`main@832aed3946d2ffa73a48913900ec2402e6db16e1`
- 独立验收提交：`9d2a8f9` (`test: record independent stage2 acceptance`)
- 总架构结论：**ACCEPTED - STAGE 2 IMPLEMENTATION COMPLETE**
- V1 evidence 结论：**NOT ACCEPTED / NOT RUN**

## 1. 决策

Stage 2 实现在本地仓库通过总架构验收。产品候选实现了六个固定 HTTP
操作、baseline/guarded RAG 对照、Ollama 本地适配、全输出检测、版本化索引、审计/运行/
报告存储、62 场景成对评测、有界调度与 metrics、生产组合以及可复现本地交付。

独立测试绑定产品候选 SHA，完整回归为 `711/711 PASS`，确认产品缺陷为
Blocking 0、High 0、Medium 0、Low 0。主架构复核未发现偏离 Stage 2 权威范围、
公共契约或安全边界的实现。

当前主机没有可用的 Docker、Ollama 或 PostgreSQL，因此本决策不接受 V1 evidence，
不产生真实攻击成功率、防护率、portfolio 或简历结论。

## 2. 完成性对照

| 权威要求 | 当前状态 | 直接证据 | 架构判定 |
| --- | --- | --- | --- |
| S2-ENV | Python 3.12 边界、闭集配置、精确直接依赖与三份带哈希锁 | `pyproject.toml`、`config.py`、`requirements/`；三组 offline dry-run exit 0 | PASS |
| S2-PROMPT | 五个受审版本化资源；baseline 与 guarded 语义分离 | `resources/*.yaml`、`resources/loader.py`、planner 测试 | PASS |
| S2-OLLAMA | loopback-only 客户端、严格模型/digest/dimension/protocol 验证、显式失败 | `ollama/`；离线 startup 返回 `ollama_unavailable` | PASS implementation |
| S2-DETECT | 统一 Unicode 规范化、三类证据、整段输出检测和固定阻断回复 | `detector/`；Unicode/Canary/fragment 测试 | PASS |
| S2-INDEX | canonical bytes、精确 corpus/model 绑定、授权预过滤、原子持久化与四态加载 | `vector_index/`；missing/corrupt/stale/reparse 回归 | PASS implementation |
| S2-RAG | 共享 query/index 绑定；baseline 全候选；guarded 先授权过滤、边界标记、指令隔离和输出门 | `rag/`、prompt resources、paired-plan 回归 | PASS implementation |
| S2-STORAGE | SQLite/PostgreSQL 边界、最小化表、审计顺序、运行五态、原子报告完成与启动恢复 | `storage/`；状态/事务/恢复回归 | PASS implementation |
| S2-API | 与 OpenAPI 一致的六路由、有界请求体、固定 Problem Details、报告 JSON/HTML | `api/`、`production.py`、`openapi.yaml`；六路由盘点 | PASS |
| S2-EVAL | 固定 62 场景、124 mode results、baseline 先于 guarded、严格可比性与报告重算 | `evaluation/`；unit-only 62/124 完整流 | PASS implementation |
| S2-METRICS | 闭合 catalog、低基数 labels、有界进程内状态，不新增第七路由 | `metrics.py`、`metrics.yaml`；未知/高基数 label 拒绝 | PASS implementation |
| S2-CONTRACT | OpenAPI、schema、error catalog、semantic companion rules 闭合 | `docs/contracts/`；Stage 1 validator 0 issue；16 码一致 | PASS |
| S2-TEST | 单元、API、存储、评测、失败、交付回归和独立验收 | 711/711 PASS；独立报告 | PASS |
| S2-DOC | README、威胁/安全边界、安装复现、指标、局限、demo 和证据边界 | `README.md`、`docs/`、`demo.ps1` | PASS |

CD01-CD06 也均有直接实现与回归证据：Canary detail 完备性重算、基础设施/运行
失败分类、保守上下文预算、canonical embedding/index bytes、canonical retrieved-document
context/message budget，以及请求版本与 not-found 可达性。详细命令、反例和结果见
[`TEST_STAGE2_ACCEPTANCE_2026-08-11.md`](../testing/TEST_STAGE2_ACCEPTANCE_2026-08-11.md)。

## 3. 主架构独立复核

| 复核 | 结果 |
| --- | --- |
| 候选边界 | 独立测试从 clean `832aed3` 开始；报告是唯一产生文件 |
| 完整回归 | 独立新 basetemp：711 collected，711 passed，117.92 s |
| fixture 与语义契约 | 6 identities、30 documents、62 scenarios、0 issues；三个 SHA-256 稳定 |
| 依赖可复现性 | Linux runtime、Linux dev、Windows dev 哈希锁 offline dry-run 全部 exit 0 |
| 产品离线行为 | 无 MockTransport 的 runtime/ASGI startup；`/health` 与 `/v1/chat` 权威 503，失败缓存且无问题原文泄漏 |
| 成对评测实现 | unit-only product flow 产生 62 scenarios/124 mode results；30 QA + 四族各8 attacks |
| 产品模拟器边界 | simulator/fake 仅在测试支持；`src/` 无 simulator 回退路径 |
| 公共接口 | 正好六路由；无 `/metrics`；error/status/retryable 与 16 码 catalog 一致 |
| 文本与机密卫生 | UTF-8/no BOM/LF、Markdown links、credential/PII 启发式扫描全部通过 |
| 契约变更边界 | Stage 2 授权变更仅 OpenAPI、contract README 与 report semantic companion rules |

## 4. 不构成本轮驳回的已知边界

- `RUN_CREATED` audit 是 best-effort；运行创建与该审计事件不是同一原子事务。
- scheduler 和 metrics 仅进程内，不提供多进程/分布式一致性。
- startup recovery 不回填历史 metrics，因存储契约不提供可靠的原 profile/起始时间。
- SQLite 只是 exploratory profile；V1 evidence 仍强制 PostgreSQL。
- Docker/Compose、真实 Ollama 模型身份、30-document index、strict manifest、真实 62x2 评测、
  audit/report/metrics 仍是 `NOT RUN / external prerequisite`。

这些边界在 Stage 2 原型范围内被显式记录，不会被误表述为真实集成结果。

## 5. Git 与交付决策

Stage 2 权威范围原定义了 pushed clean tree 门槛。用户在本轮总验收期间明确指示
"远程推送先不管"。该最新指示将本轮交付边界改为：

1. 产品、开发记录、独立测试和总架构验收均保存在本地 `main`。
2. 本轮不执行 `git push`，也不将 `HEAD != origin/main` 解释为实现失败。
3. 远程同步是后续发布动作；同步后仍应核对 `HEAD=origin/main` 和 clean worktree。

## 6. 关单后的唯一下一门

Stage 2 implementation 不再有开发项。后续工作属于 V1 evidence 复验，必须在真实外部先决条件可用时：

1. 使用精确 Ollama tags/digests/version 与锁定 settings；
2. 使用 PostgreSQL evidence profile；
3. 生成并复验 30-document canonical index 和 strict manifest；
4. 执行真实 62 场景 x baseline/guarded；
5. 对 report、audit、metrics 做结构与语义独立复核，且所有 evidence gates 通过。

在此之前，禁止声称已获得真实安全效果、V1 evidence、portfolio 资格或简历成果。
