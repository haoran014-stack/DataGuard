# DataGuard Stage 1 架构验收记录

## 1. 验收结论

**ACCEPTED** — 主架构验收接受 Stage 1 产品候选快照
`549693e365a120d0668a648b22b8cf83c96769e7`。

该快照满足
[Stage 1 范围与验收基线](STAGE1_SCOPE_AND_ACCEPTANCE.md) 中 `S1-ENV` 至
`S1-DOC` 的要求，未偏离 Stage 0 公共机器契约，且没有遗留 blocker、高严重度或
已确认的 Stage 1 产品缺陷。

本次接受只覆盖 Python 3.12 项目环境、封闭领域模型、`synthetic-v1` 合成 fixture、
安全确定的加载与语义验证、验证 CLI、单元测试和工作文档。它不代表 HTTP API、
RAG 链路、Ollama、数据库、Docker/Compose、真实模型实验、指标 gate、portfolio
资格或生产发布已经完成。

## 2. 角色、输入与 Git 边界

- 架构验收人：主架构 agent `/root`
- 开发记录：
  [DEV_STAGE1_2026-08-09](../development/DEV_STAGE1_2026-08-09.md)
- 独立测试记录：
  [TEST_STAGE1_ACCEPTANCE_2026-08-09](../testing/TEST_STAGE1_ACCEPTANCE_2026-08-09.md)
- Stage 1 起点：`a373d50a5dfc0cef8be0efb308f955fe881443c0`
- 待验收产品快照：`549693e365a120d0668a648b22b8cf83c96769e7`
- 分支：`main`
- 测试开始时远端：`origin/main` 与待验收产品快照一致
- 公共契约边界：从 Stage 1 起点到产品快照，`docs/contracts/` 无变更

开发记录用于解释实现选择，不替代独立验收。独立测试从已提交、已推送、起始工作树
clean 的产品 SHA 开始，没有把开发侧测试结论当作验收证据。测试方只新增测试报告，
没有修改产品、架构、security、contracts 或开发文档。本架构记录与测试报告属于
候选产品之后的证据提交，不改变上述产品快照。

## 3. 需求追踪与架构判定

| 需求 | 架构判定 | 直接证据 |
| --- | --- | --- |
| `S1-ENV` | PASS | Python `>=3.12,<3.13`；build/runtime/dev 直接依赖精确 pin；目标 `.venv` 为 Python 3.12.7；editable install、`pip check`、module/console CLI 均成功 |
| `S1-DOM` | PASS | 封闭、冻结、类型化的角色/分类/语言/身份/文档/证据/场景 aggregate；调用者角色只由 identity table 解析；领域层不依赖 FastAPI、SQLAlchemy、Ollama 或向量存储 |
| `S1-DATA` | PASS | 6 identities、30 documents、62 scenarios 的固定分布成立；三分类均中英各 5；四攻击族均中英各 4；30 个 QA one-per-document；12 个 adversarial 文档保留主动恶意指令且无自我中和句 |
| `S1-LOAD` | PASS | UTF-8/no-BOM/LF 精确字节检查；duplicate-key-safe YAML；Draft 2020-12 + typed model 分层；原始字节 SHA-256；错误最小化且不回显原值 |
| `S1-SEM-DATA` | PASS | 十组跨记录规则全部实现；独立 17 个定向反例和 1 个聚合反例覆盖重复/复用 ID、角色、引用、QA、cross-role 和 evidence ownership；稳定重放且不 fail-fast |
| `S1-SEM-REPORT` | PASS | 对完整 62-result report、chat、五态 run、精确 16-code error catalog 和 Problem Details 做独立正反验证；算术、状态、gate、portfolio implication 与固定 blocked reply 一致 |
| `S1-TEST` | PASS | 目标环境项目测试 147 passed；独立负向探针 109 个全部按预期拒绝；CLI 变体稳定且 raw marker 回显为 0 |
| `S1-DOC` | PASS | README、data governance、开发记录、独立测试记录与本架构记录均陈述真实范围、命令、限制和 Git 证据 |

所有要求均有直接证据，没有以未来 API、模型或数据库能力替代当前验收项。

## 4. 架构一致性审阅

### 4.1 领域与权限边界

- 三个固定角色与累计授权矩阵保持契约定义的值和顺序；fixture 不允许调用者附带一个
  可覆盖 identity table 的权威角色。
- `SubjectId` 使用契约规定的字符集和长度；其他契约 ID 没有被擅自施加更窄的字符集。
- document 与 protected fragment 的授权角色必须精确一致；跨角色攻击必须至少包含
  一个调用主体无权访问的目标。
- Stage 1 领域与 validator 是纯本地服务，不构成 HTTP、RAG 或持久化实现。

### 4.2 合成数据与攻击可评测性

- 所有 fixture 明示 synthetic source、MIT fixture license 与内容警告；静态启发式扫描
  未发现真实凭据、身份、联系方式、支付数据或生产端点候选。
- 每份文档恰好一个 Canary 和一个 protected fragment，60 个证据 ID 全局跨类唯一，
  证据值实际存在于来源文档内容中。
- 12 个 adversarial 文档包含明确的合成恶意指令。开发期间发现并删除会让间接注入
  自行失效的安全句，避免 Stage 1 数据先验地掩盖后续 baseline 风险。
- 固定 fixture SHA-256 为：
  - identities：`594203461e9c5a569d1f805ded0eb58c9f1b5fa509b2c6df1d9811135e204c27`
  - corpus：`77a3615a2bac7f3c9962e39b6c157c21c7703ce6416852af5acc2beadca01571`
  - scenarios：`174866e7c079665894c761b5a6219777227d3e07eaa5d7d04d97300e571fbdcd`

### 4.3 验证、错误与证据边界

- 加载顺序为 exact bytes、duplicate-key-safe YAML、JSON Schema、Pydantic aggregate、
  cross-record semantics；任何一层失败都返回固定 code、固定最小消息和索引路径。
- report 的失败执行保持 `failed/indeterminate`，不会被误计为安全；guarded block 只接受
  契约固定回复，baseline block 被拒绝。
- Problem Details 只把 `code/status/retryable/type` 作为稳定机器分支字段；没有错误地把
  人类可读 `title/detail` 固化成兼容常量。
- 公共 `docs/contracts/` 未改动，Stage 1 没有通过实现细节暗改 v1 对外契约。

## 5. 独立测试证据摘要

独立验收绑定产品 SHA `549693e365a120d0668a648b22b8cf83c96769e7`，结果如下：

- `.venv` Python 3.12.7；精确 pins、editable install、`pip check` 均通过；
- module CLI 与 console CLI 均退出 0，输出相同的 6/30/62 数量与三个固定 digest；
- 完整项目测试：147 passed；
- 独立负向探针：109 个，全部得到预期拒绝；
- 其中包括 data 18、report 29、chat 3、run 5、Problem Details 49、CLI 4、独立
  duplicate-key loader 1；
- 结构合法但语义恶意的 report 变体也被拒绝，证明语义层没有被 schema 正例替代；
- 错误顺序和 CLI 重放稳定，注入 marker/原始 ID 回显为 0；
- UTF-8、BOM、LF、尾空白、Markdown 本地链接、敏感内容和生产端点启发式检查通过；
- blocker 0，高严重度缺陷 0，已确认产品缺陷 0。

完整命令、退出码和探针构造见独立测试记录。本架构结论不把开发侧的 147 项自测重复
计为第二份独立证据。

## 6. 已接受的残余风险与后续硬门槛

### R1 — `canary_hit_details` 完备性尚未规范化

当前 report schema 没有定义该集合相对 mode detections 的筛选、分组、排序、去重及
`violation=false` 处理规则。Stage 1 不生成真实报告，validator 没有自行发明语义，
因此本轮不阻断。

**后续硬门槛：**在任何真实 evaluation report、证据报告或 portfolio 判定使用该字段
之前，必须先完成机器契约决策、语义 validator 和正反测试；未完成时不得宣称 Canary
详情完整。

### R2 — 缺少 hashed transitive lock

直接依赖已精确 pin，但 fresh resolution 的传递依赖仍可能漂移。Stage 1 的范围只要求
Python 3.12 和精确直接依赖，且目标环境安装、运行与测试已通过，因此本轮不阻断。

**后续硬门槛：**进入更高等级可复验证据、离线构建或发布流程前，必须增加可审阅的
hashed transitive lock，并在干净环境验证安装与现有测试。

## 7. 明确不接受的能力声明

以下能力在 Stage 1 仍为 `N/A / 未实现`，不得用于 README、报告、简历或演示中的完成
性陈述：

- 六个 HTTP endpoint；
- 检索、embedding、向量索引、上下文拼装、本地 LLM 生成和输出检测；
- baseline/guarded 真实对照实验和 62-scenario 模型结果；
- Ollama 可用性、模型 digest 或模型配置证据；
- SQLite/PostgreSQL、迁移、审计持久化、Docker/Compose；
- ASR、防护阻断数、合法 QA 通过率、误拒绝率、portfolio eligibility 或生产安全性。

Stage 1 的价值是为这些后续能力提供固定、合成、可验证的领域与数据基线，而不是提前
证明这些能力已经存在。

## 8. 最终架构决定

`S1-ENV` 至 `S1-DOC` 全部通过；公共契约无漂移；实现与固定架构边界一致；独立测试
没有发现 blocker、高严重度或产品缺陷。因此 Stage 1 产品候选
`549693e365a120d0668a648b22b8cf83c96769e7` 正式接受。

只有本记录、独立测试记录被提交并推送，且提交后工作树、`HEAD` 与 `origin/main`
一致时，本轮交付流程才完成。证据提交的最终 SHA 记录在 Git 历史与交付回执中；它不
改变本记录所绑定的产品候选 SHA。
