# DataGuard Stage 1 独立验收报告

## 1. 结论

**PASS** — Stage 1 候选快照
`549693e365a120d0668a648b22b8cf83c96769e7` 满足
`S1-ENV` 至 `S1-DOC` 的本轮独立验收范围。

本结论只覆盖 Python 3.12 项目环境、封闭领域模型、`synthetic-v1` fixture、分层
loader、数据/报告/API-error 语义 validator、CLI、单元测试和 Stage 1 文档。它不表示
HTTP API、RAG、Ollama、向量检索、数据库、62-scenario 模型实验、效果 gates、
portfolio 或生产发布已经实现或通过。

- 阻断缺陷：0
- 高严重度缺陷：0
- 已确认产品缺陷：0
- 独立负向探针：109；全部得到预期拒绝或稳定问题
- 开发测试套件独立复跑：147 passed

## 2. 待测快照、独立性与文件边界

- 仓库：`E:\cybersecurity\DataGuard`
- 分支：`main`
- `HEAD`：`549693e365a120d0668a648b22b8cf83c96769e7`
- `origin/main`：`549693e365a120d0668a648b22b8cf83c96769e7`
- 提交主题：`chore: enforce LF for Stage 1 sources`
- 起始状态：`git status --porcelain=v1 --untracked-files=all` 无输出，工作树 clean
- 适用 `AGENTS.md`：仓库及已检查上级目录均未发现
- 独立性：完整读取阶段 0 归并上下文、Stage 1 架构范围、开发记录和所有机器契约；
  开发记录中的 PASS/147 passed 不作为验收证据，所有关键命令和反例均由测试方重跑
- 变更边界：只新增本报告；未修改产品、架构、security、contracts 或开发文档，未
  commit/push

`HEAD^..HEAD` 仅修改 `.gitattributes` 和
`docs/development/DEV_STAGE1_2026-08-09.md`。从架构 Stage 1 起点
`a373d50a5dfc0cef8be0efb308f955fe881443c0` 到待测 `HEAD` 共 29 个预期路径：
项目规则/README、3 个 fixture、Stage 1 架构和开发记录、`pyproject.toml`、`src`
领域/validator/CLI、测试支持和 6 个单元测试文件。以下两个 diff 均为空：

- `git diff --name-status HEAD^ HEAD -- docs/contracts`
- `git diff --name-status a373d50a5dfc0cef8be0efb308f955fe881443c0 HEAD -- docs/contracts`

因此公共机器契约相对直接父提交和 Stage 1 架构起点均未改变。

## 3. 权威输入与范围校正

本轮按以下顺序使用输入：

1. `docs/contracts/` 下 3 个 YAML、5 个 JSON Schema、OpenAPI 和契约索引；
2. `docs/architecture/STAGE1_SCOPE_AND_ACCEPTANCE.md`；
3. `docs/testing/TEST_STAGE0_ACCEPTANCE_2026-08-09.md` 的归并上下文和残余约束；
4. 当前实现与独立执行证据。

`docs/development/DEV_STAGE1_2026-08-09.md` 只用来识别待测面和实现方声明，不用来
替代验收。Stage 1 明确不实现 API、RAG、Ollama、数据库或真实实验，故这些项为
`N/A / 后续阶段`，不是本轮缺陷。

## 4. 环境、安装与版本锁定

| 项目 | 独立实测 |
| --- | --- |
| OS/终端 | Windows x64，PowerShell 5.1 |
| 目标解释器 | `.venv\Scripts\python.exe`，Python 3.12.7 |
| Python 约束 | `>=3.12,<3.13` |
| build direct pin | `setuptools==80.9.0` |
| runtime direct pins | FastAPI 0.135.3；jsonschema 4.26.0；Pydantic 2.13.4；PyYAML 6.0.3；SQLAlchemy 2.0.51 |
| dev direct pin | pytest 9.1.1 |
| 包安装 | `dataguard==0.1.0` editable，位置绑定当前仓库 |
| 依赖一致性 | `python -m pip check` 退出 0：`No broken requirements found.` |

`pyproject.toml` 的 build/runtime/dev 直接依赖均使用精确 `==` pin。build-system
依赖由 PEP 517 隔离构建环境提供，未要求它作为 runtime distribution 常驻目标 venv；
editable 包、全部 runtime/dev pins、两种 CLI 和测试均在目标 venv 中实际可用。

`.gitattributes` 对 `*.py`、`*.toml`、`*.yaml`/`*.yml`、`*.json`、`*.md`
全部声明 `text eol=lf`。逐文件 `git check-attr text eol` 均返回 `text: set`、
`eol: lf`，`git ls-files --eol` 对相关 tracked 文件均为 `i/lf w/lf`。

## 5. 命令与退出码证据

| ID | 命令/批次 | 退出码 | 结果 |
| --- | --- | ---: | --- |
| C01 | Git SHA、branch、status、commit boundary | 0 | `HEAD=origin/main=549693e...96769e7`，`main`，起始 clean |
| C02 | 目标 venv Python、pyproject pins、安装 inventory | 0 | Python 3.12.7；editable 包和全部 runtime/dev pin 精确匹配 |
| C03 | `.venv\Scripts\python.exe -m pip check` | 0 | 无破损依赖 |
| C04 | 全 tracked py/toml/yaml/yml/json/md 的 `git check-attr` 与 `git ls-files --eol` | 0 | 全部 `text eol=lf`、`i/lf w/lf` |
| C05 | `.venv\Scripts\python.exe -m dataguard.validation` | 0 | `status=ok`、0 issue、6/30/62 和三个固定 digest |
| C06 | `.venv\Scripts\dataguard-validate.exe` | 0 | 与 module CLI JSON 完全一致 |
| C07 | `.venv\Scripts\python.exe -m pytest` | 0 | 147 passed in 11.43s |
| C08 | 独立重复键 loader + 3 YAML + Draft 2020-12/FormatChecker | 0 | 3/3 schema 正例；独立内存 duplicate-key 探针拒绝 |
| C09 | S1-SEM-DATA 独立负例批 | 0 | 17 定向 + 1 聚合；聚合产生 27 issues/8 codes；稳定、0 raw 回显 |
| C10 | 完整 report/chat/run 独立批 | 0 | 62-result schema+semantic 正例；29 report、3 chat、5 run 负例通过 |
| C11 | error catalog/ProblemDetails 独立批 | 0 | 精确 16 码；16 可变人类文本正例；49 机器字段负例通过 |
| C12 | CLI 临时复制与恶意变体批 | 0 | 4 变体各重放两次；均 nonzero、JSON 稳定、0 raw 回显 |
| C13 | UTF-8/BOM/LF/尾空白、Markdown links、敏感/生产端点启发式 | 0 | 全通过；详见第 10 节 |
| C14 | `docs/contracts` 相对两个基线 diff | 0 | 均无输出 |

Module/console CLI 的成功证据一致：

- identities：6，SHA-256
  `594203461e9c5a569d1f805ded0eb58c9f1b5fa509b2c6df1d9811135e204c27`
- documents：30，SHA-256
  `77a3615a2bac7f3c9962e39b6c157c21c7703ce6416852af5acc2beadca01571`
- scenarios：62，SHA-256
  `174866e7c079665894c761b5a6219777227d3e07eaa5d7d04d97300e571fbdcd`

## 6. Fixture、Schema 与固定分布

测试方实现了独立 `yaml.SafeLoader` 子类，在 `flatten_mapping` 后拒绝重复键；该
loader 独立解析三份 YAML。随后对对应 schema 执行
`Draft202012Validator.check_schema`，并使用 `FormatChecker` 校验实例。

| 验收项 | 独立结果 |
| --- | --- |
| identities | 6；`guest`、`employee`、`security_reviewer` 各 2 |
| documents | 30；每 classification 10；每 classification 内 `en=5`、`zh=5` |
| cumulative roles | public 3 roles；internal 2 roles；confidential 1 role，顺序和值精确 |
| document evidence | 每文档恰好 1 Canary、1 protected fragment；30 Canary ID 和 30 fragment ID 全局跨类唯一；60 个 value 全部真实出现于来源 `content` |
| scenarios | 62；authorized QA 30；四攻击族各 8 |
| attack language | 每攻击族 `en=4`、`zh=4` |
| QA coverage | 30 个目标文档严格 one-per-document |
| adversarial documents | 恰好 12；保留语言相应的主动恶意指令；两条中/英文自我中和句均不存在 |

## 7. S1-SEM-DATA 独立反例

测试方从合法 typed bundle 独立构造 17 个定向变体。每个变体执行两次并比较完整 issue
tuple，所有期望 code 均出现；问题只包含固定 code/message 和 index/field path。

| 反例域 | 数量 | 期望拒绝 |
| --- | ---: | --- |
| duplicate IDs | 5 | subject、document、scenario、Canary、fragment 分别重复 |
| cross-class evidence reuse | 1 | fragment ID 复用其他文档 Canary ID |
| fragment roles | 1 | fragment roles 与来源 document 不同 |
| unknown refs | 3 | unknown subject、target、forbidden evidence |
| QA coverage/auth/fact | 5 | one-per-document、未授权 subject、无正向 assertion、must-include 未锚定、any-of 未锚定 |
| cross-role authenticity | 1 | subject 对所有目标均已授权 |
| evidence ownership | 1 | evidence owner 不属于任一 target |

另构造 1 个组合变体，一次产生全部 27 个稳定 issues，覆盖 8 个不同 code，证明 validator
不是 fail-fast。17 个定向变体共产生 48 个 issue 实例；组合与所有定向变体重放一致。
注入的 `RAW-INJECTED-S1-SEM-DATA` 不出现在任何序列化 issue 中，raw 回显为 0。

## 8. Report、Chat 与 Run 语义

完整合法 report 含 62 个 scenario result，通过 `report.schema.json` 的 Draft 2020-12 +
FormatChecker 和 `validate_report_semantics`。测试方随后构造 29 个 report 恶意变体，
共产生 87 个 issue；其中 25 个变体仍然结构 schema-valid，证明结构校验不能替代语义层。

覆盖范围：

- rate numerator、denominator、value；总 ASR；family successes/ASR；summary scalar；
  prevention stage；
- mode outcome、failed/nonfailed judgment、error_code、fact assertion、baseline blocked、
  attack/QA judgment；
- 四个 family gate 逐一验证，以及 baseline ASR、guarded final leaks、guarded
  unauthorized context、QA pass、false rejection、no-indeterminate gates；
- comparability、strict-manifest、overall 和 portfolio implications。

Chat 独立正例证明 baseline answered 不 block、guarded blocked 只接受契约固定双语回复。
3 个负例分别拒绝 guarded 错误回复、baseline blocked、answered 复用 fixed blocked reply。

Run 独立正例覆盖 `queued`、`running`、`completed`、`failed`、`interrupted` 五态合法
组合；5 个负例逐态覆盖 progress、completed_at 和 failure_code 不一致，全部拒绝。

## 9. Error Catalog 与 Problem Details

独立 YAML 集合检查和产品 loader 均确认 error catalog 恰好包含 16 个唯一固定 code，
集合与 OpenAPI/ErrorCode 契约一致。

测试方为每个 code 构造一份 Draft 2020-12 + FormatChecker-valid Problem Details，刻意把
`title` 和 `detail` 改为非目录原文但仍合法的非空文本。16/16 均通过结构和语义校验，
证明人类可读字段不是兼容常量。

对全部 16 个 code 分别篡改 `status`、`retryable`、code-specific `type`，得到 48 个
负例；另加 unknown code 1 个，共 49 个，全部产生相应固定 issue。

## 10. CLI 恶意变体与仓库卫生

CLI 测试使用自动清理的临时目录复制 `data/` 与 `docs/contracts/`，未改工作树。四个
变体分别为：

1. identities YAML duplicate key；
2. identities unknown field；
3. scenario unknown subject，值为 `RAW-INJECTED-CLI-MARKER`；
4. error catalog version drift。

每个变体执行两次：进程均以非零退出，stdout 均为可解析的闭合 JSON，重放的 JSON
逐字节一致，每例 issue_count=1，marker 在 stdout/stderr 中回显 0 次。

独立卫生扫描结果：

- 55 个待测快照文本文件均为严格 UTF-8、无 BOM、LF-only、有末尾 LF、无尾空白；
- 39 个 Markdown links 中 37 个是本地目标，全部存在；另 2 个为外链；
- 私钥头、AWS/GitHub/OpenAI token、email、中国手机号、中国证件号启发式均 0；
- 初始宽松北美电话/支付卡 regex 的 9/3 个候选经逐条定位，全部是提交 SHA 子串或
  测试 UUID，不是真实联系方式或支付数据；
- assignment-style password/API key/token/secret 和 endpoint-style 配置扫描均 0；
- URL host 逐项分类后只包含 loopback、`dataguard.local`、JSON Schema、Ollama
  官方模型页、仓库来源和显式 `.invalid` 测试域；生产端点候选为 0。

这些是启发式静态检查，不等同于现实身份/合规认证；fixture 仍是明确标识的合成数据。

## 11. 测试工具事件

以下事件未归因于待测产品：

1. 首版环境 inventory 同时查询 runtime distributions 和 build-only `setuptools`；目标
   venv 不常驻 build isolation distribution，查询抛出 `PackageNotFoundError`。移除错误
   前提后，editable 包、精确 runtime/dev pins 和 `pip check` 均通过。
2. 首版中英 fixture 断言把中文 literal 经 PowerShell 5 管道送入 Python，字符被替换，
   造成断言中止；改为 ASCII Unicode escape 后完整批次退出 0。
3. 首版 ProblemDetails 独立 schema 片段只改写 ErrorCode `$ref`，遗漏 Uuid `$ref`，
   触发 `PointerToNowhere`；补全两个本地 `$defs` 后 16 正例/49 负例退出 0。
4. 首版宽松电话/卡号 regex 命中 SHA/UUID；保留候选定位证据并完成上下文分类，未把
   测试标识符误报为真实数据。

## 12. 缺陷

| ID | 严重度 | 状态 | 说明 |
| --- | --- | --- | --- |
| — | — | — | 本快照未发现 Stage 1 范围内的产品缺陷 |

## 13. 残余限制与阻断判定

### R1：`canary_hit_details` 完备性规则未定义

`report.schema.json` 没有定义 `summary.canary_hit_details` 相对 mode detections 的完整
集合、是否包含 `violation=false`、排序、分组或去重规则。Stage 1 validator 没有自行
发明该语义。

判定：**不阻断本轮 Stage 1**。机器契约本身没有可执行的完备性规则，Stage 1 范围也
不生成真实报告；现有 schema 边界保持有效。但在后续阶段把 canary detail 用作完整
evidence 或 portfolio 证明前，必须先由契约/架构定义规范规则并加入语义负例。

### R2：无 hashed transitive lock

build/runtime/dev 直接依赖均精确 pin，但仓库没有 hashed、跨平台的 transitive lock；
fresh resolution 仍可能随依赖索引变化。

判定：**不阻断本轮 Stage 1**。`S1-ENV` 当前要求 Python 3.12 和精确依赖版本，目标
venv 的实际安装、两种 CLI、`pip check` 和全套测试均通过；范围文档未把 hashed
transitive lock 列为 Stage 1 gate。该项保留为供应链/可重复性风险，进入更高证据等级
或发布前应建立 hashed lock 并验证离线/干净安装。

## 14. 最终判定

Stage 1：**PASS**。

理由：待测 SHA/远端/分支/clean 起点一致；Python 3.12、精确 pins、editable 安装、
LF 属性、module/console CLI 和全 pytest 通过；3 个 fixture 的独立重复键 loader、
Draft 2020-12/FormatChecker、固定分布、evidence/content 和 adversarial 可评估性通过；
数据/report/chat/run/error/CLI 的 109 个独立负向探针全部按固定最小化问题拒绝；
contracts 未变、链接/编码/敏感内容边界通过，且无 blocker/high 缺陷。

本结论只绑定
`549693e365a120d0668a648b22b8cf83c96769e7`。新增本测试报告不改变待测产品快照，
也不代替架构接受、发布批准或后续模型实验效果证据。
