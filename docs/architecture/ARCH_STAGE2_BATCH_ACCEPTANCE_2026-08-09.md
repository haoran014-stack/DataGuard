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

产品提交曾因旧 HTTPS token 失效暂留本地。用户重新授权并上传 SSH key 后，主机
Ed25519 指纹与 GitHub 官方公布值核对一致，仓库 `origin` 切换为 SSH；随后产品提交
`d95036c887e81f2a8ae1d8122752f7bae62d1c40` 与本验收提交一并通过非强制 push 上传。
恢复开发前，本地 `HEAD`、`origin/main` 和远端 `refs/heads/main` 均验证为
`f74dfc8bbff485654fa93021b789a06336e8cd4c`。

## 5. Batch A2c — deterministic whole-output detector

### 5.1 验收快照与结论

- 产品提交：`0e842ccff699cd5331e02bf4818936411a26cf7f`
- 提交主题：`feat: add deterministic output detector`
- 覆盖需求：`S2-DETECT` 的统一规范化、角色感知证据与 baseline/guarded 输出门
- 架构结论：**ACCEPTED WITH CORRECTIONS CLOSED**

本批次只接受确定性全输出检测器；不代表向量索引、RAG 编排、持久化、API、评测、
报告或指标已完成。

### 5.2 接受的实现

- 显式 factory 将已验证的版本化 detector、guard policy、system prompt 与合成 Corpus
  绑定；模块导入不读取资源、语料、网络或数据库。
- 完整输出和所有 marker 严格共用 NFKC、casefold、五个指定 zero-width code point
  删除、Unicode whitespace 折叠及 trim 顺序。
- 输入边界与 A1/A2b 的最大响应上限一致，为 8 MiB UTF-8；超限或非法 surrogate
  显式最小化失败，不截断、不跳过尾部。
- evidence 为 closed/frozen，仅包含 type、opaque evidence ID、violation 和 action，
  并按 `(type, evidence_id)` 唯一稳定排序。
- 所有 system/document Canary 对三个角色均为 violation；protected fragment 以来源
  文档的 `allowed_roles` 为唯一权限事实。
- baseline 对所有命中使用 `observed` 且原样返回完整输出；guarded 仅对 violation
  使用 `blocked`，丢弃原输出并返回资源中的精确双语固定回复。授权片段命中不阻断。
- 不同 evidence ID 即使规范化后 marker 碰撞也全部保留；同一 marker 重复出现不会
  产生重复 evidence。
- 检测器只能通过受控 factory 构造，实例和内部 rule 不可变；输出对象不保留 marker、
  文档正文或 blocked 原始输出。

### 5.3 架构纠偏

第一项纠偏关闭直接构造边界：初始检测器实例仍可被调用方改写内部规则/固定回复，且
Canary evidence 可被直接构造为 `violation=false`。最终实现采用受控 factory token、
严格 rule/fixed-reply 校验和实例封印；Canary evidence 的模型级 validator 始终要求
`violation=true`，恶意 sentinel 不进入错误文本。

第二项纠偏关闭权限真相偏离：初始草案使用 fragment 自身 `allowed_roles` 覆盖来源文档，
与 Stage 2 scope 和公共契约规定的“来源文档授权”不一致。最终 factory 使用
`document.allowed_roles`，并在 fragment/document role 不一致时以固定内容安全错误拒绝
整个配置。三角色、三级分类矩阵及 mismatch 反例已覆盖。两项偏差均已关闭。

### 5.4 主架构验收证据

| 检查 | 结果 |
| --- | --- |
| Detector 定向测试 | `44 passed` |
| 完整项目测试 | `338 passed` |
| Stage 1 fixture/catalog CLI | exit 0，6/30/62，0 issue，三个 digest 不变 |
| Unicode 规范化 | NFKC、casefold、五种 zero-width、非 ASCII whitespace 与 trim 均覆盖 |
| Full-output | 首/中/尾、长输出末尾和 8 MiB 边界均覆盖，无静默截断 |
| 权限矩阵 | 三角色、三级来源文档授权、允许与越权均覆盖 |
| 输出门 | baseline 原文保留；guarded violation 固定回复且结果/repr/dump 无 raw sentinel |
| 构造边界 | 直接伪造 Canary、规则、固定回复或实例改写均拒绝 |
| 变更边界 | 仅 detector package、对应单元测试及 Stage 2 开发记录 |
| 公共契约/资源/依赖 | 无修改 |
| compile/whitespace | `compileall` 与 `git diff --check` 通过 |

### 5.5 残余与下一批门槛

- 检测器只负责内存输出门；后续 RAG/storage 必须证明 blocked raw output 在任何 audit、
  report、日志、异常或数据库写入前已经被丢弃。
- 后续 RAG 必须让 baseline 与 guarded 调用同一个检测器实例；不得复制规范化或另建
  检测逻辑。
- Protected fragment 的来源文档绑定必须从同一已验证 Corpus 保持到检索、上下文、
  检测证据和评测结果，不能只传裸 marker。
- 本批没有生成真实模型输出或实验结论。

### 5.6 Git 交付状态

产品提交 `0e842ccff699cd5331e02bf4818936411a26cf7f` 已通过核验主机指纹的 SSH
非强制 push 上传；上传后本地 `HEAD` 与 `origin/main` 一致。本节架构验收记录须以
独立提交上传并再次核对远端 SHA 后，才开始下一开发批次。

## 6. Batch A3a — validated vector-index core

### 6.1 验收快照与结论

- 产品提交：`fde3d4da3c31dc88c7cc79c5f2f1c2e3ae8cffba`
- 提交主题：`feat: add validated vector index core`
- 覆盖需求：`S2-INDEX` 的构建、规范制品、绑定门与确定性内存检索子集
- 架构结论：**ACCEPTED WITH CLARIFICATION AND CORRECTIONS CLOSED**

本批不包含文件系统持久化、索引自动重建、RAG 模式编排、API、数据库或评测运行。

### 6.2 接受的实现

- 一次调用生产 `OllamaClient.embed`，按已接受 Corpus 顺序提交 30 个精确
  `title + "\n\n" + content` 输入，并传入探测到的实际 embedding dimension。
- `dataguard-vector-index-v1` closed/frozen artifact 绑定 Corpus exact-byte SHA、
  30 个有序文档 ID、固定 embedding tag、实际本地 digest、维度与对应向量。
- artifact 只包含绑定元数据、opaque 文档 ID 和有限 numeric vectors；动态扫描证明
  不包含 title、content、Canary 或 protected-fragment literal。
- Canonical JSON 固定 UTF-8/no-BOM、sorted keys、compact separators、一个 final LF、
  finite numbers、Corpus entry 顺序和 64 MiB 上限；digest 入口拒绝非 canonical bytes。
- 向量维度限制为 `1..16384`，在遍历和 norm 计算前执行；拒绝 bool、NaN、Inf、空、
  维度漂移与 zero/invalid norm。
- 只有同时验证 format、Corpus digest/order、模型 tag/digest、维度及全部向量的私有
  token handle 才能调用检索；handle 和 artifact 默认 repr 隐藏 ID/entries/vectors。
- 检索只计算调用方预先提供的 eligible ID，候选最多 30、唯一且必须存在；稳定 cosine
  score 被约束为 `[-1,1]`，按 score 降序再 doc ID 升序，至少四项返回 exact top 4。
- 索引模块不了解 role、baseline 或 guarded；后续 RAG 必须负责构造预过滤候选集。

### 6.3 架构澄清与纠偏

开发前的 `S2-CD04` 初稿同时要求 exact `title+content` 和 marker 不进入 embedding。
动态检查证明 30/30 document content 已包含其 Canary 和 protected fragment literal，两个
要求不可同时满足。架构选择保留精确输入与实验真实性：这些合成 marker 仅瞬时进入
单独管理的本地 Ollama，不进入索引制品；不额外 append 独立 marker/权限元数据。修订
已通过提交 `588517c28e3f6953aebedb07810e133f27bfed8a` 先行上传。

主架构预审另关闭六项实现边界：30 次单项调用合并为一次有界 30-input 调用；直接向量
长度前置限制；eligible 数量在 set 分配前限制；默认 repr 隐藏向量；删除未使用 hook；
artifact digest 必须先验证 canonical bytes。所有纠偏均有直接回归测试。

### 6.4 主架构验收证据

| 检查 | 结果 |
| --- | --- |
| Vector-index 定向测试 | `61 passed` |
| 完整项目测试 | `399 passed` |
| Stage 1 fixture/catalog CLI | exit 0，6/30/62，0 issue，三个 digest 不变 |
| Embedding request | 单次 30 项、顺序和 exact input；actual dimension 传入 |
| Artifact minimization | 动态 Corpus 全 title/content/Canary/fragment literal 均不存在 |
| Canonical codec | BOM/CRLF/重复键/pretty/trailing/unknown/raw/nonfinite/oversize 均拒绝 |
| Binding gate | Corpus bytes/order、model tag/digest、dimension/vector 漂移均拒绝 |
| Retrieval | pre-filter、tie-break、top-4/<4、重复运行和 eligible 顺序无关均覆盖 |
| Error/repr | 原始 bytes/vector/doc marker sentinel 不回显 |
| 变更边界 | 仅 vector_index package、对应单元测试及 Stage 2 开发记录 |
| compile/whitespace | `compileall` 与 `git diff --check` 通过 |

### 6.5 残余与下一批门槛

- A3b 必须把 canonical bytes 原子写入 A1 `runtime_state_dir` 下固定文件，验证 project-root
  containment，拒绝 symlink/junction/reparse-point 逃逸，并在任何失败后保留旧有效索引。
- A3b load 必须先有界读取并执行 canonical codec，再进行 Corpus/model binding；损坏、
  缺失、陈旧与依赖不可用必须是固定失败/显式重建状态，不能静默使用旧索引。
- 后续 RAG 必须从同一 validated handle 检索；guarded 的 allowed ID 集必须在调用
  `retrieve` 前由来源文档授权生成，baseline 则传完整 30-ID 集。
- 本批不产生真实索引文件、真实模型 digest 或任何实验结果。

### 6.6 Git 交付状态

产品提交 `fde3d4da3c31dc88c7cc79c5f2f1c2e3ae8cffba` 已通过核验主机指纹的 SSH
非强制 push 上传；上传后本地 `HEAD` 与 `origin/main` 一致。本节架构验收记录须独立
提交并上传后，才开始 A3b。
