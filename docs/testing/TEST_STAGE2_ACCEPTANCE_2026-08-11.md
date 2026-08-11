# DataGuard Stage 2 独立验收记录

- 日期：2026-08-11（Asia/Shanghai）
- 验收对象：Stage 2 implementation acceptance；不接受或替代 V1 evidence
- 候选：`832aed3946d2ffa73a48913900ec2402e6db16e1`
- 分支：`main`
- 起始工作树：clean（`git status --porcelain=v1 --untracked-files=all` 无输出）
- 本地远端跟踪引用：`origin/main=1c540d8d3e17e8429974ac69ff4b546a2a39bfeb`，不等于候选 HEAD；未 fetch、push 或修改远端
- 独立测试结论：**PASS for Stage 2 implementation at local candidate SHA**
- V1 evidence：**NOT ACCEPTED / NOT RUN**

## 1. 结论边界

本地候选在可执行的实现级、静态、单元和离线依赖失败验收中未发现 blocking/high 产品缺陷。完整测试为 711/711 PASS；三份哈希锁在对应离线 wheel cache 上均可解析；真实产品 runtime 在 Ollama 与 PostgreSQL 均不可达时缓存 unhealthy 状态，并由 ASGI 返回权威 503，未启用 simulator 或把 fake 当作集成证据。

Docker、Ollama、PostgreSQL 外部工具/服务均不可用，因此所有需要这些先决条件的真实集成和 evidence-profile 实验均明确记为 `NOT RUN / external prerequisite`。本结论不声称远端已同步：架构文档要求的 `HEAD=origin/main` 推送树条件在本地引用上不成立，属于发布/交付门槛，不改变绑定上述本地 SHA 的 implementation 结论。

## 2. 候选、环境与输入

| 项目 | 独立证据 | 结果 |
|---|---|---|
| Git | `git rev-parse HEAD`；`git branch --show-current`；起始 status | HEAD 为完整 SHA；`main`；clean |
| 远端引用 | `git rev-parse origin/main` | `1c540d8...`，与 HEAD 不同；记录边界 |
| Python | `.venv\Scripts\python.exe --version` | Python 3.12.7 |
| pip | `.venv\Scripts\python.exe -m pip --version` | pip 24.2 |
| 安装一致性 | `pip check` | exit 0，无破损依赖 |
| 项目元数据 | `pyproject.toml` | Python `>=3.12,<3.13`；8 个精确 runtime direct pins、1 个精确 dev pin，build backend 亦精确 pin |
| 适用说明 | `AGENTS.md` 搜索 | 仓库中无适用文件 |
| 已读输入 | Stage 2 scope、README、Stage 2 本地交付记录、全部 machine contracts、资源、产品实现、Docker/Compose/demo/locks | 已读；未采信 DEV/ARCH 的 PASS 表述 |

本验收期间仅刷新本地 editable 安装元数据（`pip install --no-deps --no-build-isolation -e .`），未修改候选文件。刷新前 `.venv` 仅有旧的 `dataguard-validate.exe`；刷新后由当前 `pyproject.toml` 正确生成 `dataguard.exe` 和 `dataguard-server.exe`。这是环境元数据陈旧，不是候选源代码缺陷。

## 3. requirement-by-requirement 矩阵

| Requirement | 实现/契约证据 | 独立执行证据 | 结论 |
|---|---|---|---|
| S2-ENV | `pyproject.toml`、`config.py`、`.env.example`、3 locks | 精确 pins；unknown env、HTTPS、userinfo、query、other host、gateway 两侧失配均拒绝；3 个 offline hashed dry-run exit 0 | PASS |
| S2-PROMPT | 5 个 package resource YAML、loader、planner | 全量 pytest；Stage1 validator 三种入口；静态实现审阅 | PASS |
| S2-OLLAMA | Ollama models/errors/client | 完整 pytest；离线真实 startup 得到 `ollama_unavailable`；真实模型/标签探测不可执行 | PASS implementation；真实集成 NOT RUN |
| S2-DETECT | detector engine/models | Unicode NFKC + zero-width 代表探针通过；完整 pytest | PASS |
| S2-INDEX | vector index canonical/models/store/core | 完整 pytest 覆盖 missing/corrupt/stale/reparse/atomic/binding；CLI 验证；无真实 embedding/index 构建 | PASS implementation；真实构建 NOT RUN |
| S2-RAG | planner/execution/models | 代表性 unit product runtime + MockTransport 走通 62 pair/124 mode；完整 pytest | PASS implementation，unit-only |
| S2-STORAGE | storage models/repository/reporting/paths | 完整 pytest 的 SQLite 状态、原子完成、恢复、审计；离线 PostgreSQL 返回 storage unavailable | PASS implementation；真实 PostgreSQL NOT RUN |
| S2-API | OpenAPI、API app/models/errors/reports、production/server | factory 创建无启动 I/O，正好 6 routes 且无 `/metrics`；离线 ASGI health/chat 权威 503；完整 pytest | PASS |
| S2-EVAL | evaluation core/reporting/runner | unit fake 精确 62 scenarios/124 mode results，分布 30 QA + 4×8 attacks；完整 pytest 覆盖 report/run arithmetic | PASS implementation，unit-only |
| S2-METRICS | `metrics.yaml`、`metrics.py` | duplicate YAML、未知/高基数 label 代表反例拒绝；无 metrics route；完整 pytest | PASS implementation，process-local |
| S2-CONTRACT | contracts README/OpenAPI/schemas/error catalog/semantic rules | Stage1 validator；16 个 error code 与运行时 catalog、status/retryable 精确一致；完整 pytest | PASS |
| S2-TEST | `tests/`、support fakes、pytest config | 新 basetemp 全量 711/711 PASS；fake 与 external 结论分离 | PASS |
| S2-DOC | README、Stage2 scope、delivery/demo | 本地 Markdown link 检查；交付/残余边界明确 | PASS |
| CD01 | report schema + report semantic rules/reporting | 完整 pytest 覆盖 canary detail 投影与 arithmetic；独立 summary 篡改被拒绝 | PASS implementation |
| CD02 | evaluation runner/models/report semantics | 完整 pytest 覆盖 mode-local failure、fatal run、五态转换/恢复 | PASS implementation |
| CD03 | guard policy、planner | 静态固定预算及完整 pytest 的 UTF-8 byte budget 边界 | PASS implementation |
| CD04 | canonical index + embedding client | 静态 canonical binding；完整 pytest 的模型/digest/dimension/order 篡改 | PASS implementation；真实 embedding NOT RUN |
| CD05 | RAG models/planner | 静态 canonical context fields/digest；完整 pytest 的 context/pair binding 篡改 | PASS implementation |
| CD06 | OpenAPI + API models/app | OpenAPI `DataVersion` 与 404 可达性、请求闭集；完整 pytest | PASS |

## 4. 命令、exit 与计数

### 4.1 依赖与锁

以下三条均使用 `--dry-run --ignore-installed --require-hashes --no-index --only-binary=:all:`，没有联网或安装：

| Target | lock / cache | Exit | 解析闭包 |
|---|---|---:|---:|
| Linux runtime CPython 3.12 manylinux2014 x86_64 | `runtime-linux.lock` / `E:\ai-security-cache\dataguard-linux-wheels` | 0 | 28 packages |
| Linux dev CPython 3.12 manylinux2014 x86_64 | `dev-linux.lock`（递归包含 runtime lock）/ 同上 | 0 | 33 packages |
| Windows dev CPython 3.12 win_amd64 | `dev-windows.lock` / `E:\ai-security-cache\dataguard-windows-wheels` | 0 | 33 packages |

静态闭包检查：runtime 自有 28；Linux dev 自有 5 + runtime 28；Windows dev 33。所有条目为 exact `==` 且带 SHA-256；无 URL、editable、index URL、extra index URL 或 trusted host。Dockerfile 仅复制 `runtime-linux.lock`，并以 `pip --require-hashes` 安装。

### 4.2 测试、CLI 与编译

| 命令 | Exit / 结果 |
|---|---|
| `.venv\Scripts\python.exe -m pytest --basetemp E:\ai-security-cache\dataguard-stage2-independent-20260811-run2` | exit 0；711 collected，711 passed，117.92 s |
| 首次 pytest（1 秒工具超时） | 工具终止，非产品结果；随后使用全新 basetemp 完整复跑 |
| `python -m dataguard.validation --project-root .` | exit 0；6 identities、30 documents、62 scenarios、0 issues |
| `dataguard-validate.exe --project-root .` | exit 0；同上 |
| `python -m dataguard.cli --project-root . validate` | exit 0；同上 |
| `dataguard.exe --project-root . validate` | exit 0；同上（刷新 editable metadata 后） |
| `PYTHONPYCACHEPREFIX=E:\ai-security-cache\dataguard-stage2-compile-20260811 python -m compileall -q src tests` | exit 0 |

一次误将 `dataguard-server.exe --help` 当作 argparse 命令调用；该入口按实现直接启动服务器，在本机 127.0.0.1:8000 bind 被系统拒绝并 exit 1。它不属于 server factory/import I/O 判定；factory 的无启动 I/O 与六路由由产品对象直接构造和完整 pytest 验证。

### 4.3 独立代表性边界探针

临时探针位于 `E:\ai-security-cache`，不在仓库中：

- 11 个代表性负例全部拒绝：unknown env；6 个 Ollama URL/gateway 组合；duplicate metrics YAML；metrics 高基数/unknown label；report summary arithmetic 篡改。
- Unicode 探针 `Ａ + zero-width + B + whitespace + C` 规范化为 `ab c`。
- factory 直接构造得到精确 6 routes，无 `/metrics`，runtime 未 startup。
- product unit flow（真实产品 planner/executor/detector，HTTP `MockTransport`）得到 62 scenarios、124 mode results；固定分布为 QA 30、四攻击族各 8。此项仅为 **unit implementation probe**，不是 Ollama/PostgreSQL integration。
- `src/` 无 `simulator` literal；未发现产品 simulator/fallback 路径。

完整 pytest 另外覆盖了 duplicate JSON/YAML/env、manifest/index missing/corrupt/stale/reparse、question/plan/pair/result/context/evidence 跨绑定、Canary/protected fragment Unicode、raw 泄漏、CD01/report arithmetic、run illegal transitions/recovery/atomic completion、scheduler reservation/capacity/cancel、metrics drift、API media/body/query/error allowlist、Docker/demo 静态边界。上述是全量套件证据，不伪装成额外独立反例计数。

## 5. 离线 dependency runtime / ASGI

独立脚本以真实产品 `create_runtime` + `create_production_app` 启动，未注入 `MockTransport`；配置本机 PostgreSQL 与 Ollama loopback，二者均真实不可达：

```text
startup_s=4.047
GET /health => 503
second GET /health => 503, 0.0 s cached response
reasons=[experiment_manifest_mismatch, storage_unavailable, ollama_unavailable]
POST /v1/chat => 503, code=storage_unavailable
raw question leakage=false
```

这证明依赖探测发生在 startup，并由缓存 health/ready error 服务请求；请求时没有 simulator，也没有以 request-time 探测替代缓存状态。错误优先级在 Ollama 与 DB 同时不可用时返回 `storage_unavailable`，符合实现的权威 ready error 顺序。

## 6. 外部先决条件与 NOT RUN

| 探测 | 事实 | 受影响验收 |
|---|---|---|
| `docker` | CLI 不存在 | Docker build、Compose config/up、容器非 root/read-only 的动态验证：NOT RUN |
| `ollama` | CLI 不存在；127.0.0.1:11434 TCP/HTTP 不可达 | 版本/tags/digest/dimension、真实 chat/embed、30-doc index：NOT RUN |
| PostgreSQL | `psql`/`pg_isready` 不存在；127.0.0.1:5432 不可达 | PostgreSQL schema、真实 audit/run/report/recovery：NOT RUN |

因此以下均未产生真实 evidence：Docker image、Compose API+Postgres 环境、Ollama 双模型锁定、真实 30 文档 embedding/index/strict manifest、真实 62×2 evaluation、真实 audit/report/metrics。不得把 unit fake 或 SQLite 单元覆盖称为这些集成项的 PASS。

## 7. 静态卫生、交付边界与人工分类

- `git ls-files`：138 tracked；其中 137 个文本文件进行 UTF-8、BOM、CR/LF、final LF、trailing whitespace 检查，0 issue。
- `.gitattributes` 对 `*.py/*.toml/*.yaml/*.json/*.md` 均固定 text/LF。
- Markdown 本地链接：0 broken。
- credential/private-key/真实邮箱/电话/身份证/生产 endpoint/raw-content/system-marker 启发式扫描：无凭据或真实 PII。命中均人工分类为字段名/placeholder、localhost、`dataguard.local` schema/problem URI、官方 Ollama README 链接、GitHub 仓库地址、测试 sentinel 或防泄漏规则。
- Docker 静态边界：Python 3.12.7、hashed install、non-root user；Compose 恰含 API + PostgreSQL，无 Ollama service、无 Docker socket，API root filesystem read-only、artifacts ro、drop all capabilities、no-new-privileges。
- `.dockerignore` 为 allowlist，只放行 Dockerfile、src、data、contracts 与 runtime lock。
- demo：有前置命令/模型检查、固定健康与评估 deadline、HTTP timeout；明确不 pull 模型；cleanup 只 `docker compose down`，不删除 volume；覆盖写入需显式 `-OverwriteArtifacts`。
- 相对候选父提交，contracts 变化仅 `README.md`、`openapi.yaml`、新增 `report-semantic-rules.yaml`；相对 Stage1 基线 `549693e` 亦仅这三项，符合 Stage2 授权契约变化。Stage2 scope 本身未在候选父差异中漂移。

## 8. 缺陷与残余风险

### 产品缺陷

| 等级 | 数量 | 说明 |
|---|---:|---|
| Blocking | 0 | 无 |
| High | 0 | 无 |
| Medium | 0 | 无确认产品缺陷 |
| Low | 0 | 无确认产品缺陷 |

### 非产品阻塞/残余

| 项目 | 影响 | Stage2 implementation 是否阻断 |
|---|---|---|
| 外部 Docker/Ollama/PostgreSQL 不可用 | 真实 integration 与 V1 evidence 全部 NOT RUN | 否；阻断 V1 evidence |
| `origin/main` 本地引用不等于候选 HEAD | 无法声称已满足 pushed-tree gate | 否；需发布方同步/复核 |
| `RUN_CREATED` audit best-effort | 创建事务成功但该审计写失败时可缺记录 | 否；已声明残余 |
| scheduler 与 metrics process-local | 多进程不共享容量/指标 | 否；Stage2 原型范围内残余 |
| recovery 不回填 metrics | 重启恢复后的 historical run 不补运行指标 | 否；已声明残余 |
| `canary_hit_details` 完备性 | 由 Stage2 CD01/semantic companion rules 实现；V1 证据仍需真实运行复核 | 否 |

## 9. 最终判定与下一轮上下文

**PASS for Stage2 implementation，严格绑定本地 clean `main@832aed3946d2ffa73a48913900ec2402e6db16e1`。V1 evidence NOT ACCEPTED。**

下一轮只需在外部先决条件可用且远端同步后执行真实集成：确认 `HEAD=origin/main`，依 README 准备锁定的 Ollama 模型与 PostgreSQL，构建/验证 30-doc index 和 strict manifest，启动 Compose，完成两次 chat 与 62×2 evidence run，导出并独立校验 report/audit/metrics。任何 unit fake、MockTransport 或 SQLite 结果均不得替代该轮证据。
