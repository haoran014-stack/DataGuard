# DataGuard Stage 2 分批架构验收记录

## 1. 记录边界

- 架构验收人：主架构 agent `/root`
- Stage 2 架构基线：
  [STAGE2_SCOPE_AND_ACCEPTANCE](STAGE2_SCOPE_AND_ACCEPTANCE.md)
- Stage 2 开发记录：
  [DEV_STAGE2_2026-08-09](../development/DEV_STAGE2_2026-08-09.md)
- Stage 2 起点：`78923203816e7ef4478157999f43c1e09153e592`
- 本记录按开发批次追加架构决定；它不替代最终独立测试或 Stage 2 总验收。

## 2. Batch A1 — runtime configuration

### 2.1 验收快照与结论

- 产品提交：`521dd4601ee07a2cf0e0d0fbcbc85bd99747f90f`
- 提交主题：`feat: add Stage 2 runtime configuration`
- 覆盖需求：`S2-ENV` 的配置、直接依赖和秘密最小化子集
- 架构结论：**ACCEPTED WITH CORRECTION CLOSED**

该批次只建立配置与直接依赖基础，不代表 Ollama、RAG、存储、API、评测、报告、
metrics 或 hashed transitive lock 已完成。

### 2.2 接受的实现

- 保持 Python `>=3.12,<3.13` 和原有精确 pins；新增精确直接依赖：
  `httpx==0.28.1`、`uvicorn==0.51.0`、`psycopg[binary]==3.3.4`。
- `RuntimeSettings` 为 frozen、`extra=forbid`、默认值也验证的闭合模型；模块导入不读取
  环境、不访问网络/数据库、不创建文件。
- 默认 profile/backend 为 exploratory/SQLite；evidence profile 强制 PostgreSQL。
- Ollama URL 仅允许 HTTP 和字面 `localhost`、`127.0.0.1`、`[::1]` 根地址；拒绝
  userinfo、query、fragment、远端/模糊 host、非根 path、空/零/越界端口。
- timeout、response bytes、URL/DSN/path 长度和 `artifacts/` 相对运行路径具有固定边界。
- 数据库 DSN 使用 `SecretStr`，不进入 repr、model dump、JSON 或验证错误原值；环境
  变量只在显式 `from_env()` 调用时读取，未知 `DATAGUARD_*` 变量被拒绝。
- `artifacts/` 已在 `.gitignore`，本批没有生成运行数据库或状态文件。

### 2.3 架构纠偏

初始实现的 PostgreSQL DSN 分支没有读取 `urlsplit(...).port`，可能使非数字或超范围端口
绕过配置层并延迟到驱动连接才失败。这会削弱闭合配置和内容安全错误边界。

纠偏后配置层允许无显式端口或 `1..65535`，并统一拒绝非数字、`0`、`65536`，不回显
DSN 或 synthetic credential sentinel。合法 `5432` 和三个反例均有直接测试。该偏差已
关闭，不进入后续批次残余。

### 2.4 主架构验证

| 检查 | 结果 |
| --- | --- |
| 配置定向测试 | `40 passed` |
| 完整项目测试 | `187 passed` |
| Stage 1 fixture/catalog CLI | exit 0；6/30/62；0 issue；三个 digest 不变 |
| 变更边界 | 仅 `pyproject.toml`、配置模块、配置测试、Stage 2 开发记录 |
| 公共契约/Stage 2 scope | 无修改 |
| import side effects | 注入失败 socket/SQLite/file hooks 后导入成功，未产生文件 |
| DSN 最小化 | repr/serialization/validation error 均无原值 |
| whitespace/encoding | diff check、UTF-8、no BOM、LF、尾空白检查通过 |

### 2.5 残余与下一批门槛

- Hashed transitive lock 仍是 `S2-ENV` 未完成项，必须在 Stage 2 产品候选前关闭。
- `database_dsn_value()` 只能由后续 storage factory 在最小作用域调用；后续测试必须证明
  DSN/驱动错误不会进入日志、Problem Details、audit 或 report。
- 后续文件写入方必须把 `artifacts/` 路径解析到可信项目根，并拒绝 symlink/junction/
  reparse-point 逃逸；A1 的纯配置验证不执行文件系统访问。
- 只有版本化 prompt/policy/detector 资源通过下一轮架构审阅后，才允许实现 Ollama/RAG。

### 2.6 Git 交付状态

本记录绑定产品提交 `521dd4601ee07a2cf0e0d0fbcbc85bd99747f90f`。首次 GitHub
HTTPS 推送发生连接重置，随后 HTTP/1.1 与 schannel 有限重试均在 GitHub 443 超时；
`gh api user` 同期成功并确认账号 `haoran014-stack`，因此判断为 Git 传输层外部故障，
不是产品或认证缺陷。

在 `HEAD` 与 `origin/main` 被重新验证一致之前，A1 仅为本地已验收提交，不开始 A2。

## 3. Batch A2a — versioned security resources

### 3.1 验收快照与结论

- 产品提交：`81b111f1f5da4002500d2cb080094ccc2f7870a9`
- 提交主题：`feat: add versioned Stage 2 security resources`
- 覆盖需求：`S2-DETECT` 的版本化输入、`S2-RAG` 的 prompt declaration 子集
- 架构结论：**ACCEPTED WITH CORRECTION CLOSED**

该批次只接受资源声明、闭合 loader 和 exact-byte digest；不代表 prompt assembly、
detector 执行、Ollama adapter、RAG 或任何 API 路径已经实现。

### 3.2 接受的实现

- 五个 package YAML 分别锁定 system prompt、弱 baseline template、guarded template、
  guard policy 和 detector definition，均为 `synthetic=true`、version `1.0`。
- System Canary literal 只存在于受审 system-prompt 资源和瞬时内存；其 opaque evidence
  ID 不与 corpus 中任何 `canary_id` 或 `fragment_id` 碰撞。
- Guard policy 锁定模型、角色、分类、八个 guarded 阶段、生成/检索配置和固定回复。
- Detector definition 锁定完整未截断输出、NFKC/casefold、五个 zero-width code point、
  whitespace normalization、三种 DetectionType、observe/block action 和禁止原始输出持久化。
- Loader 显式调用 `importlib.resources`，采用 duplicate-key-safe YAML、frozen closed
  Pydantic models、固定常量/跨资源校验及 exact-byte SHA-256；导入 package 不读取资源。
- Loader 错误只包含固定 internal code/message，不含资源内容、marker、路径或底层异常。
- `pyproject.toml` 声明 `dataguard.resources/*.yaml` package data。

最终 exact-byte SHA-256：

| Artifact | SHA-256 |
| --- | --- |
| system prompt | `1010949fa467ba987b3b5822e121829af6566b16f940b33bc16c530c6748f48b` |
| baseline prompt | `dfed1d7473f4d077ccbc83ef7ddd7cb74e69f1b987aaab8f190aacb581e0426e` |
| guarded prompt | `4e61873d747da0c291e786a9a71b3bf0f1359cffa76cb2b7aa7c8234d7d7c566` |
| guard policy | `8084394235aa27ebed03be15e31b5fe52a4ca8ca8e43148406834a912ef10f6f` |
| detector | `3137f394ad8d447db019d430427380f01abbdb7fb3e62854fd5d943be1915553` |

### 3.3 架构纠偏

初始 baseline template 把检索文档标成 `untrusted`。这会在 deliberately weak baseline
中提前加入 guarded 的信任边界提示，可能自我中和 indirect-document attack 并破坏
baseline/guarded 对照有效性。

纠偏后 baseline 只保留中性的 system text、retrieved document text、synthetic question
三段单 payload，不含不可信/忽略/不要服从文档等中英提示；guarded 仍独占 JSON 与
不可信数据边界。固定反例词集防止该偏差回归。另补充 system Canary evidence ID 与
全部 corpus evidence ID 的动态不碰撞测试。两项偏差均已关闭。

### 3.4 主架构验证

| 检查 | 结果 |
| --- | --- |
| Resource 定向测试 | `11 passed` |
| 完整项目测试 | `198 passed` |
| Stage 1 fixture/catalog CLI | exit 0；6/30/62；0 issue；digests 不变 |
| Package resource | 当前目标环境 5/5 可读取并通过 closed loader |
| Canary boundary | marker source occurrence 恰好 1；测试/开发记录无 literal 副本 |
| Resource abuse | duplicate key、BOM、CR、unknown/missing、constant drift 均最小化拒绝 |
| 公共契约/Stage 2 scope | 无修改 |
| whitespace/encoding/links | diff、UTF-8/no-BOM/LF/尾空白及本地链接检查通过 |

### 3.5 残余与下一批门槛

- Fresh editable rebuild 尚无成功证据：目标 venv 不常驻 build-only setuptools，隔离
  build dependency 下载又达到硬超时。现有 installed/source-layout 资源可读不能替代
  最终 clean hashed install；该项继续并入 `S2-ENV` lock/release gate。
- Resource loader 返回可信内部调用者所需的 prompt/marker 内存对象。后续 adapter、
  detector、audit、report 和错误映射必须继续证明这些原文不越过最小化边界。
- A2b 必须只实现 bounded local Ollama adapter；不得把 fake transport 变成运行时
  simulator 或 fallback。

### 3.6 Git 交付状态

产品提交 `81b111f1f5da4002500d2cb080094ccc2f7870a9` 已通过普通非强制
`git push origin main` 上传。提交时本地 `HEAD` 与 `origin/main` 一致，工作树 clean。
