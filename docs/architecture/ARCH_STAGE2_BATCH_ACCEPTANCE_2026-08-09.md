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

## 4. Batch A2b — bounded local Ollama adapter

### 4.1 验收快照与结论

- 产品提交：`d95036c887e81f2a8ae1d8122752f7bae62d1c40`
- 提交主题：`feat: add bounded local Ollama adapter`
- 覆盖需求：`S2-OLLAMA` 的本地协议适配、健康事实、embedding/chat 与失败边界
- 架构结论：**ACCEPTED WITH CORRECTION CLOSED**

本批次只接受 Ollama 内部适配器，不代表健康 API、向量索引、RAG、检测、存储、
评测或报告已实现；也不构成真实本地模型兼容性证据。

### 4.2 接受的实现

- 异步客户端只使用 A1 已验证的 loopback 根地址、超时和响应大小上限；导入、构造
  和关闭不发起模型请求，并要求调用方显式管理生命周期。
- `probe()` 只调用 `/api/version`、`/api/tags` 和 `/api/show`，返回最小化且不可变的
  Ollama 版本、两个固定模型 tag/digest 与 embedding dimension。
- `embed()` 固定 `qwen3-embedding:0.6b`、`truncate=false`，校验输入数量、总长度、
  输出数量、有限数值及维度一致性。
- `chat()` 固定 `qwen2.5:3b-instruct`、非流式、`think=false`、无 tools，并发送锁定的
  temperature、seed、top-k、top-p、上下文与生成长度。
- 所有响应均先校验状态、长度与唯一 JSON Content-Type，再有界流式读取正文；JSON
  拒绝重复键、非对象、非有限值和未知字段。
- 运行时没有 simulator、fake、重试或远端 fallback；测试 transport 只存在于单元测试。
- 仅暴露五个固定且内容安全的内部错误码；URL、prompt、响应正文及底层异常不进入
  错误对象、字符串或字典。

### 4.3 架构纠偏

初始实现有两个直接构造/协议边界缺口：健康事实模型没有自行锁定 digest/tag，成功
响应也没有在读取正文前验证 JSON 媒体类型。若绕过 HTTP parser 直接构造事实，或
loopback 服务返回 HTML/错误媒体类型，边界可能发生漂移。

纠偏后，digest 必须匹配可选 `sha256:` 加 64 位小写十六进制；健康事实交叉验证固定
generation/embedding tag 且拒绝交换、重复与错误 tag。所有成功响应必须恰有一个
`application/json` Content-Type，仅可附带单一 UTF-8 charset；缺失、重复、非 JSON、
非 UTF-8 或额外参数均在读取正文前被拒绝。404 与其他非 2xx 的既有安全映射保持不变，
并且不读取错误正文。两项偏差均已关闭。

### 4.4 主架构验收证据

| 检查 | 结果 |
| --- | --- |
| Ollama adapter 定向测试 | `96 passed` |
| 完整项目测试 | `294 passed` |
| Stage 1 fixture/catalog CLI | exit 0，6/30/62，0 issue，三个 digest 不变 |
| 直接事实构造 | 非法 digest、交换/相同/错误 tag 均最小化拒绝 |
| HTTP 内容边界 | Content-Length、累计 bytes、唯一 JSON Content-Type 与 UTF-8 参数均闭合 |
| 失败正文边界 | 404、非 2xx 与错误 Content-Type 均在读取正文前失败 |
| 请求契约 | probe/embed/chat 的 method、path、body、模型与生成参数固定 |
| 变更边界 | 仅 Ollama package、对应单元测试及 Stage 2 开发记录 |
| 公共契约/资源/依赖 | 无修改 |
| whitespace | `git diff --check` 通过 |

### 4.5 残余与下一批门槛

- 本批仅使用内存 fake transport；尚未证明宿主机 Ollama 版本、实际模型 digest、
  embedding dimension 或真实响应与适配器兼容。真实集成证据留在 Stage 2 集成门。
- 后续健康服务必须只返回最小化事实，不能暴露 URL、prompt 或 `/api/show` 原始内容。
- 后续 index/RAG 必须复用 probe 得到的维度并显式关闭客户端，不得新增 simulator、
  自动下载模型或远端 fallback。
- Hashed transitive lock 仍属于 `S2-ENV` 未完成项。

### 4.6 Git 交付状态

产品提交已经在本地生成。首次上传时，`gh auth status` 明确报告账号
`haoran014-stack` 的现有 token 已失效；Git 因无可用凭据而停止，未改写提交或远端。
在重新授权并验证 `origin/main` 包含该产品提交和本验收记录之前，不开始下一开发批次。
