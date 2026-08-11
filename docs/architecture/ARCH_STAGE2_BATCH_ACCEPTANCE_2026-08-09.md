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

## 7. Batch A3b — atomic vector-index filesystem store

### 7.1 验收快照与结论

- 产品提交：`c17d16063ab7d621a5792a1fc26d8fda03a1c2ec`
- 提交主题：`feat: add atomic vector index store`
- 覆盖需求：`S2-INDEX` 的路径安全、原子持久化、有界读取和 binding 状态
- 架构结论：**ACCEPTED WITH CORRECTIONS CLOSED**

本批不自动构建/重建索引，不调用 Ollama，也不包含 RAG、数据库、API 或评测逻辑。

### 7.2 接受的实现

- Store 显式接收 absolute existing project root 和 A1 closed settings，唯一目标为
  `runtime_state_dir/vector-index.v1.json`；repr、facts 和错误均不暴露路径。
- 构造仅执行必要只读 root resolve/lstat；import 与构造不创建目录或文件。显式
  `prepare()` 才逐级创建目录，并在每一步复核 lexical/resolved containment、真实目录、
  POSIX symlink 与 Windows reparse/junction 属性。
- 写入先生成并验证 A3a canonical bytes/digest；随后在同目录使用随机 `O_EXCL` temp、
  尽力 `0600`、完整 write/flush/fsync/close、再次校验 identity 与 parent/target，最后
  以 `os.replace` 作为唯一原子提交点。
- 提交点前任何失败保持旧 target exact bytes 不变并只清理本次可证明归属的 temp；
  提交后只声称 target 是完整旧版或完整新版，绝不声称跨进程事务回滚。
- 读取先 lstat/size，再 `os.open` 有界读取最多 `MAX+1`，通过 fstat/lstat identity、
  regular-file 和 size 前后复核阻止换链、增长、短读及 partial read。
- `load_validated` 严格按 safe read → canonical parse → Corpus/model binding 执行，
  成功只返回 validated handle 与 digest/format/count/dimensions 最小事实。
- missing、corrupt、stale、I/O 四种状态和错误码一一对应；错误不含 OS exception、
  path、raw bytes、vector 或 marker。
- 同一 store 实例由 `RLock` 序列化；跨进程只依赖 atomic replace 与读取 identity 检查，
  不宣称 distributed lock。

### 7.3 架构纠偏

初始草案为 replace 后校验失败恢复旧文件，创建了临时 hardlink rollback anchor。该设计
在崩溃时可能留下第二份向量制品，并扩大清理权限面。最终完全删除 hardlink/backup/
rollback，把所有可执行验证移到 replace 前，并将 replace 明确定义为提交点。

独立代码审阅又发现 raw fd 所有权缺口：exclusive temp 创建后若 `fstat` 或 `fdopen`
失败，原始 fd 可能未关闭，Windows 下会阻止安全清理。最终实现显式追踪 raw fd；
`fdopen` 成功后唯一转移给 stream，失败前则先关闭 raw fd，再基于可信 identity 清理。
若 post-create `fstat` 本身失败，没有可信 identity 时宁可留下一个已关闭、随机命名的
temp 并报告固定 I/O 错误，也不按未验证 pathname 删除；后续运维只能精确审计处理，
不能通配清理。该极端残余不含文档或 marker 原文，但仍是本地向量制品。

### 7.4 主架构验收证据

| 检查 | 结果 |
| --- | --- |
| Store 定向测试 | `32 passed`，显式仓库内 basetemp |
| 完整项目测试 | `431 passed`，独立显式 basetemp |
| Stage 1 fixture/catalog CLI | exit 0，6/30/62，0 issue，三个 digest 不变 |
| 路径边界 | absolute root、escape、component file、symlink/reparse、target type/长度均覆盖 |
| 有界读取 | oversize 先验、MAX+1、short/growth、open identity 变化均拒绝 |
| 原子写入 | create/write/flush/fsync/close/revalidate/replace 故障矩阵覆盖 |
| fd 所有权 | fdopen 与 post-create fstat 失败均证明 fd 关闭、旧 target 不变 |
| 四状态 | missing/corrupt/stale/io_error 互斥且内容安全 |
| 并发 | 同实例并发 read/write 未观察到 partial bytes |
| 变更边界 | 仅 vector-index store/export、测试及 Stage 2 开发记录 |
| compile/whitespace | `compileall` 与 `git diff --check` 通过 |

第一次主验收复跑使用系统默认 pytest 临时根，因权限产生 setup errors；同一复合 shell
中后续成功命令曾掩盖 pytest 非零退出。该证据被明确作废。最终定向、全量、CLI、编译
与 diff 均以独立命令/显式退出码重跑；两个验收 basetemp 在确认位于仓库 `.pytest_cache`
且不是 reparse 后精确清理。

### 7.5 残余与下一批门槛

- RAG/runtime orchestrator 必须显式处理 missing/corrupt/stale：可以由明确操作 build 后
  write，但不得在 chat/evaluation 请求中静默 fallback、删除或使用未绑定索引。
- 真实 Ollama 索引构建尚未运行，因此仓库和 runtime_state_dir 中没有真实索引制品；
  Stage 2 集成必须证明实际 model digest/dimension 与持久化 binding 一致。
- 跨进程同时写没有分布式锁；当前支持目标是完整 old-or-new 和读取 identity 检查，
  API 进程拓扑必须保持单 writer，或在未来另立架构决策。
- 后续 RAG 只能消费 `LoadedVectorIndex.validated_index`，不能绕过 store/core binding gate。

### 7.6 Git 交付状态

产品提交 `c17d16063ab7d621a5792a1fc26d8fda03a1c2ec` 已通过核验主机指纹的 SSH
非强制 push 上传；上传后本地 `HEAD` 与 `origin/main` 一致。本节架构验收记录须独立
提交并上传后，才开始 RAG 批次。

## 8. Batch A4a — deterministic RAG planning

### 8.1 验收快照与结论

- 产品提交：`a1da868f9362593cd67416afbd75a48f2cd257d3`
- 提交主题：`feat: add deterministic Stage 2 RAG planning`
- 覆盖需求：`S2-RAG` 的请求解析、成对查询向量、检索前授权、top-4 检索、
  canonical 文档上下文、消息隔离及 `S2-CD05`/`S2-CD06`
- 架构结论：**ACCEPTED WITH CORRECTIONS CLOSED; REMOTE DELIVERY PENDING**

本批只接受从已验证输入到待生成消息的确定性规划。它不调用 generation、detector、
audit/storage、HTTP API 或 evaluation，因此不构成完整 RAG 链、真实模型实验或
Stage 2 总验收。

### 8.2 接受的实现

- `corpus_version`、`subject_id` 和 question 按公共契约顺序验证；有效但不存在的
  corpus/subject 分别使用稳定 404 语义，question 保留全部原始 Unicode 与空白。
- 同一 `QueryEmbedding` 受控、冻结并绑定 embedding model tag、digest 和 dimensions；
  paired baseline/guarded 复用同一 handle，不执行第二次 embedding。
- baseline 将全部 30 个文档 ID 交给同一 A3a 检索器；guarded 按来源文档
  `allowed_roles` 在相似度计算前生成 10/20/30 候选集，禁止检索后过滤。
- 检索结果必须恰好为四个已知、唯一且 eligible 的文档。授权拒绝只包含 opaque
  document ID 与固定 `role_not_allowed` 原因，并保持 Corpus 顺序。
- 两种模式共享同一四字段 canonical 文档 JSON，严格保留 retrieval order；baseline
  仅生成一个弱 user payload，guarded 仅生成 system/user/user 三条隔离消息。
- 上下文预算按 ordered `{role,content}` 消息数组的 compact、sorted-key UTF-8 JSON
  精确计数；只接受 `message_bytes + 512 <= 8192`，不截断、不删除、不重排。
- `RagPlan` repr 不暴露 question、document content、system prompt、marker、vector 或
  model digest；本批无日志、数据库、audit 或 report 写入。

### 8.3 架构纠偏

主架构预审关闭了四类边界偏差：

1. `AuthorizationDenial.doc_id` 从无界字符串收紧为 strict 1..128 contract ID，且
   Pydantic 错误隐藏输入原值。
2. 公共 canonical-document helper 从 duck typing 收紧为恰好四个唯一 `Document`，
   并对 `model_construct`/unchecked-copy 对象重新执行完整模型校验。
3. 公共 message-budget helper 对每条 `OllamaMessage` 重新校验，缺字段、非法 role、
   超长或非字符串 content 统一映射为内容安全的 manifest mismatch。
4. Planner factory 不再直接信任普通 dataclass 资源字段；五个 `ResourceArtifact`、
   SHA 形状与对应资源模型均重新校验，并重新执行 system marker 跨资源隔离检查。

另关闭 A2b 与公共契约的兼容缺口：长度非零的 whitespace-only question 现在原样进入
本地 embedding request，不 trim/normalize。`ValidatedVectorIndex` 只增加 planner
所需的只读 binding facts，默认 repr 仍隐藏 digest、ordered IDs 和 vectors。

### 8.4 主架构验收证据

| 检查 | 结果 |
| --- | --- |
| A4a/A2b/A3a 独立定向回归 | `199 passed in 3.57s`，全新仓库内 basetemp |
| 完整项目独立回归 | `473 passed in 19.29s`，全新仓库内 basetemp |
| Stage 1 fixture/catalog CLI | exit 0，6/30/62，0 issue，三份 fixture digest 不变 |
| Request 与角色矩阵 | malformed/not-found 顺序、三角色 10/20/30 guarded 候选均覆盖 |
| Paired 检索 | 同一 query handle；baseline 30 候选；guarded 检索前授权；同一 retrieve |
| 上下文隔离 | 真实 JSON escaping、四字段/order、baseline 1 message、guarded 3 messages |
| 预算边界 | exact pass、one-byte-over reject、multibyte UTF-8、无截断均覆盖 |
| 范围隔离 | fail-fast spy 证明无 chat、detector 或 VectorIndexStore 调用 |
| 内容安全 | forged Document/message/resource、raw sentinel、repr/error 不回显均覆盖 |
| 编译与格式 | validation、`compileall`、`git diff --check` 均 exit 0 |
| 文本与链接 | 10/10 UTF-8/no-BOM/LF/final-LF/no trailing whitespace；48 local links，0 missing |
| 凭据与契约边界 | 变更文件 credential heuristic 0 命中；`docs/contracts/` 与 Stage 2 scope 未改 |

开发侧第一次完整回归因系统 pytest 临时目录不可访问而产生 setup errors；该证据未被
采信。开发侧和主架构验收均改用不同的、全新仓库内 basetemp 独立重跑并显式检查
退出码，所有产品断言通过。

### 8.5 残余与下一批门槛

- A4b 必须只消费本批 `RagPlan.messages`，使用同一已验证 question/query handle 完成
  paired generation，并把完整输出交给唯一 A2c detector；不得重新 embedding、重新
  拼装上下文或引入 fallback。
- Guarded violation 必须在任何 audit/storage/report 写入前丢弃 raw output；baseline
  必须保留成功原输出且只记录 observe-only evidence。
- 当前仍无真实 Ollama generation、真实 index build、数据库/API/evaluation 证据；
  任何攻击成功率或防护效果声明继续禁止。
- Hashed transitive lock 仍是 Stage 2 产品候选前的 `S2-ENV` 硬门槛。

### 8.6 Git 交付状态

产品提交已在本地创建且工作树产品部分干净。SSH 远端在本批开始前已通过只读
`ls-remote` 验证，并确认 `origin/main` 为 `1c540d8d3e17e8429974ac69ff4b546a2a39bfeb`。
本次 push 被 Codex 外部执行额度限制拒绝，未向远端发送数据；这不是 GitHub SSH
认证失败。产品提交与本节独立架构记录提交必须由用户终端执行一次
`git push origin main` 上传并核对远端 SHA 后，才能开始 A4b。

## 9. Batch A4b — guarded RAG execution

### 9.1 验收快照与结论

- 产品提交：`7b408772d3016cef79d511fd27e25dad58823135`
- 提交主题：`feat: add guarded RAG execution`
- 覆盖需求：`S2-OLLAMA` generation 子集、`S2-RAG` 输出路径及 `S2-DETECT` gate 组合
- 架构结论：**ACCEPTED WITH CORRECTIONS CLOSED; LOCAL-ONLY DELIVERY**

本批只接受已验证 `RagPlan` 到最终内存回复的 generation/detector 编排，不包含
audit/storage、HTTP API、evaluation、report 或 metrics。

### 9.2 接受的实现

- 受控、冻结的 executor 只消费 A4a 已生成的 messages；每次执行精确调用一次
  `OllamaClient.chat`，随后将完整 raw output 原样交给同一个 A2c detector 一次。
- mode 只能从 `RagPlan.mode` 映射，role 只能来自 `RagPlan.resolved_role`；调用方不能
  另传 role、mode、messages、detector action 或输出结论。
- baseline 对所有成功模型输出保持 `answered` 和原文 reply，命中 evidence 只能
  `observed`；guarded 无 violation 时原样回答，有任一 violation 时结果只保留固定
  双语 reply、`blocked` outcome 和最小 evidence。
- Ollama unavailable、timeout 和 protocol errors 不被 executor 捕获或替换；async
  cancellation 原样传播且 detector 不运行。内部 plan/result 漂移统一为固定
  `internal_error` 与公共目录文案，不包含 raw output 或依赖异常文本。
- 最终 result 可显式读取 reply 供后续 API 返回，但无 `model_dump`，默认 repr 不包含
  reply/raw/messages；中间 `DetectorResult.reply` 同样从 repr 隐藏。
- 执行路径不调用 embedding、retrieval、index store、audit 或数据库，也不重新拼装、
  normalize、截断或降级模型输出。

### 9.3 架构纠偏

主架构预审要求内部错误文案直接复用公共 `internal_error` detail，避免重复语义漂移；
要求 result/executor 冻结性有直接反例，并证明 cancellation 不被安全错误包装。

另增加真实组合用例：从同一 accepted fixture、资源、index 和 QueryEmbedding 生成
baseline/guarded A4a plans，再通过同一个 A4b executor 执行；执行前后 embedding 和
retrieve 调用计数不变。该用例证明 A4b 与真实 A4a 输出闭合，而不是只接受测试伪造
plan。

### 9.4 主架构验收证据

| 检查 | 结果 |
| --- | --- |
| A4b/A4a/A2b/A2c 独立定向 | `199 passed in 4.03s`，全新仓库内 basetemp |
| 完整项目独立回归 | `490 passed in 19.89s`，全新仓库内 basetemp |
| Stage 1 fixture/catalog CLI | exit 0，6/30/62，0 issue，三份 digest 不变 |
| 调用顺序 | exact messages → chat once → complete raw → detector once |
| Baseline/guarded gate | 三类命中、授权/越权 fragment、空输出、Unicode/zero-width 均覆盖 |
| 失败与取消 | Ollama error/cancellation 原样传播且 detector 零调用；内部漂移固定 500 语义 |
| 真实 A4a 组合 | paired plans 共用 query embedding；A4b 不增加 embed/retrieve 调用 |
| 内容安全 | blocked result、result/intermediate repr、错误均不保留或回显 raw sentinel |
| 范围隔离 | embed/retrieve/index store 禁止调用；无 audit/storage/API/eval 代码 |
| 编译与格式 | validation、`compileall`、`git diff --check` 均 exit 0 |
| 文本与凭据 | 5/5 UTF-8/no-BOM/LF/final-LF/no trailing whitespace；credential 0 命中 |
| 契约边界 | `docs/contracts/` 与 Stage 2 scope 未修改 |

### 9.5 残余与下一批门槛

- Executor 尚无 planner/detector 的跨组件 Corpus/资源 binding fingerprint。后续
  application composition factory 必须从同一 accepted fixture/resource bundle 构造
  planner、detector、index 和 executor，并将不一致映射为启动失败；在该门关闭前不得
  声称任意外部组装均安全。
- Guarded raw output 只在 generation→detector 的当前栈帧中瞬时存在；后续 storage/
  audit 必须只接收最终 result 和最小 plan evidence，禁止接收 raw output、messages、
  question、document content 或 marker literal。
- 当前仍无真实 Ollama/PostgreSQL/API/evaluation 证据，不产生任何实验指标。

### 9.6 Git 交付状态

用户已在 A4b 开始前明确修改交付策略：后续批次只创建本地独立提交，Stage 2 全部
实现、独立测试和总架构验收完成后再统一 push。因此第 8.6 节的逐批远端交付门已被
此新指令取代。产品提交和本节架构提交均只保存在本地；本批不得执行 push。

## 10. Batch A5a — minimized audit evidence storage

### 10.1 验收快照与结论

- 产品提交：`1950a64`
- 提交主题：`feat: add minimized audit evidence storage`
- 覆盖需求：`S2-STORAGE` 的最小化 audit evidence、SQLite 实体存储、共享
  SQLite/PostgreSQL repository contract 和确定性分页子集
- 架构结论：**ACCEPTED WITH CORRECTIONS CLOSED; LOCAL-ONLY DELIVERY**

本批只接受 audit evidence 基础设施，不包含 run/report persistence、启动恢复、API、
评测执行、指标、Compose 或真实 PostgreSQL 连接证据。

### 10.2 接受的实现

- Audit event、retrieval、authorization denial、detection、filter 和 page 均为
  closed/frozen 模型；UUID 使用 canonical 小写形式，任意 aware 时间统一归一到 UTC。
- retrieved/denial/detection children 是 count 与 aggregate detector action 的唯一事实源；
  显式汇总漂移、数据库子项漂移、重复或非确定性顺序均被拒绝。
- 四张规范化表只保存 allowlisted scalar evidence；不存在 raw question、document body、
  context、prompt、reply、model output、Canary literal 或 protected-fragment literal 列。
- Append 以一个事务写入主记录和全部 children；任一失败回滚整个事件。读取时重新构造并
  验证公共模型，不返回损坏或漂移记录。
- Listing 实现 OpenAPI 全部 filter、inclusive time interval、`limit+1`、稳定
  `(occurred_at,event_id)` 升序和 exclusive cursor，保证翻页无重复和无跳项。
- Cursor 是有界、canonical base64url JSON，含版本与 SHA-256 完整性字段；解析还独立验证
  canonical UUID 和 UTC-Z timestamp。无效输入仅映射固定 `invalid_request`。
- SQLite 路径在显式 `prepare_schema` 时逐组件创建和校验；普通 append/list/health 只做
  read-only 校验，目录消失时失败关闭，绝不静默重建。
- Repository 构造无连接和文件副作用；PostgreSQL engine 保持 lazy 且隐藏参数。具体
  SQLAlchemy repository 受私有 factory token 控制且不从 package 导出。
- Storage/query 错误固定、不可注入修改，且不携带 SQL、DSN、路径、driver text、原始内容
  或依赖异常字符串。

### 10.3 架构纠偏

主架构预审与开发闭环关闭了以下偏差：detector child 与 aggregate action 的 `none` 枚举
污染、frozen exception traceback 不可写、非零时区 aware date-time 过度拒绝、WindowsPath
类型假设、cursor timestamp/checksum 非 canonical、health/schema 漂移未拒绝、运行期路径
校验会重建目录、具体 repository 可绕过 factory 构造、普通异常内容回显，以及测试中
credential-like `user:password@...` DSN 与卫生证据不一致。最终 PostgreSQL lazy/no-connect
测试使用无 userinfo 的 localhost DSN，测试强度未降低。

### 10.4 主架构独立验收证据

| 检查 | 结果 |
| --- | --- |
| A5a 独立定向回归 | `35 passed in 6.42s`，仓库内独立 basetemp |
| 完整项目独立回归 | `525 passed in 26.40s` |
| Stage 1 fixture/catalog CLI | exit 0；6/30/62；0 issue；三份 digest 不变 |
| 事务与恢复 | main/children 故障回滚、duplicate、driver fault、read drift 均覆盖 |
| 分页与 filter | 同时间 tie、exclusive cursor、tamper/noncanonical、closed interval 全覆盖 |
| 路径与 schema | escape、symlink/reparse、hardlink、missing parent、额外 table/column 均拒绝 |
| 依赖边界 | import/constructor 无 I/O；PostgreSQL lazy/no-connect；SQLite prepare 显式 |
| 内容安全 | fixed error/repr、raw-field absence、credential-bearing DSN 扫描均通过 |
| 编译与文本 | compileall、`git diff --check`、8 文件 UTF-8/no-BOM/LF 均通过 |
| 契约边界 | `docs/contracts/`、Stage 2 scope 与依赖文件未修改 |

### 10.5 残余与下一批门槛

- Portable Python/SQLite 无法把完整路径 walk 与 SQLite open 合成跨进程不可分割操作；当前
  通过重复校验和 fail-closed 缩小 TOCTOU 面，但不宣称抵御拥有同机写权限的持续竞态攻击。
- Cursor checksum 只提供确定性完整性/损坏检测，不是调用者认证或授权机制；当前接口仍是
  本地合成实验边界。
- 运行时 schema 校验闭合表名和列名，行数据通过公共模型二次验证；它不是完整迁移系统，
  不替代后续 Docker/PostgreSQL 真实 DDL 与故障复验。
- PostgreSQL 本批只有 lazy construction 与 dialect compile 证据，没有真实连接、事务或
  startup recovery 证据，因此 evidence profile 尚不可验收。
- A5b 必须单独实现 run lifecycle、原子 startup recovery 和完整 immutable report
  persistence；不得混入 API 或 evaluation executor。只有 completed 运行可以拥有报告，
  queued/running/failed/interrupted 均不得持久化 partial report。

### 10.6 Git 交付状态

产品提交 `1950a64` 仅保存在本地。按照用户当前交付策略，本节架构验收也创建独立本地提交，
Stage 2 总实现、独立测试与总架构验收完成前不执行任何 push。

## 11. Batch A5b — run lifecycle and immutable complete reports

### 11.1 验收快照与结论

- 产品提交：`2c16921`
- 提交主题：`feat: persist evaluation runs and complete reports`
- 覆盖需求：`S2-STORAGE` 的 run lifecycle、startup recovery 与 complete report
  persistence，以及 `S2-EVAL` 的“只允许完整报告一次性持久化”边界
- 架构结论：**ACCEPTED WITH CONTRACT CLARIFICATION AND CORRECTIONS CLOSED;
  LOCAL-ONLY DELIVERY**

本批不包含 HTTP API、evaluation executor、HTML renderer、metrics、Compose 或真实 PostgreSQL
运行证据。

### 11.2 接受的实现

- `EvaluationRun` 与 `StoredReport` 为 closed/frozen 模型；运行状态严格限制为 queued、
  running、completed、failed、interrupted，且所有时间统一归一到 UTC。
- 每次 create 生成新的 queued run；queued 只能 start 为 running。Running progress 每次只增加
  一个完成 pair，最多持久化到 61；62 只能与完整报告在同一完成事务中出现。
- Terminal 状态不可重复转换。Failed 必须有 failure code 且无 completed time/report；completed
  必须为 62、`completed_at == updated_at`、无 failure code 且恰有一份 report。
- Startup recovery 在一个事务中锁定全部 running runs，先验证它们均无 report，再统一转为
  interrupted；queued 和 terminal runs 保持不变。任一漂移或写故障使整批回滚。
- Report 在写入前依次通过 Draft 2020-12 + FormatChecker、完整 semantic validator、run/profile/
  scenario-set/storage binding，以及 `generated_at == completed_at` 的 UTC 时刻绑定。
- 唯一持久化事实源是 canonical UTF-8 JSON：sorted keys、compact separators、finite JSON、
  no BOM/CR、一个 final LF 和 exact-byte SHA-256。Schema/semantic/binding/time 任一失败均零写入。
- Complete 将 report insert 与 run 的 completed/62 transition 放在同一数据库事务；任一语句
  故障均回滚到 running/61 且无 report。
- Report 读取重新验证 canonical bytes、digest、report/run binding 与完整 report 语义；queued/
  running 返回 `report_not_ready`，failed/interrupted 返回 `report_unavailable`，missing 返回
  `run_not_found`，从不返回 partial report。
- Report schema 仅在首次显式 `prepare_schema` 前加载和编译，数据库准备成功后才缓存；constructor
  与 import 无 I/O，complete/get 不重复读取可变 contract 文件。

### 11.3 契约澄清与架构纠偏

公共契约要求 interrupted 必须带非空 failure code，但闭合的 16 码目录没有专用 process-restart
代码。主架构将 startup recovery 固定映射为 `internal_error`：它不虚构输入、模型、存储或报告
原因，也不新增公共枚举。该澄清只锁定本项目 producer 语义，不改变 OpenAPI shape。

主架构预审还关闭了三项证据完整性缺口：早于运行创建的 report `generated_at` 曾可被接受；
损坏数据库中的 running+report 曾可能在恢复后留下 interrupted+report；report validator 的说明
称只在显式准备时加载，但实现曾在 complete/get 请求路径重复读取文件。最终实现采用更严格的
`generated_at == completed_at` UTC 绑定、恢复前全量 no-report 检查，以及 prepare-time 私有缓存；
相同 UTC 时刻的非零 offset 表示仍被正确接受。

### 11.4 主架构独立验收证据

| 检查 | 结果 |
| --- | --- |
| A5b + A5a 独立定向回归 | `57 passed in 36.61s`，仓库内独立 basetemp |
| 完整项目独立回归 | `547 passed in 57.26s` |
| Stage 1 fixture/catalog CLI | exit 0；6/30/62；0 issue；三份 digest 不变 |
| 状态转换 | 非法转换矩阵、terminal immutability、时间倒退、progress 0..61 均覆盖 |
| 并发与恢复 | 同实例并发 progress 串行；多 running 原子恢复与故障整批回滚均覆盖 |
| 完成事务 | report insert/run update 两处故障均恢复为 running/61 且零 report |
| Report gates | schema、semantic、binding、backend、NaN、早/晚时间均零写入拒绝 |
| Contract 生命周期 | 坏 contract 不建 artifacts；prepare 后删除 contract 不影响当前缓存实例 |
| 四态读取与漂移 | completed/not-ready/unavailable/missing、run/report DB drift 均覆盖 |
| 编译与文本 | compileall、`git diff --check`、10 文件 UTF-8/no-BOM/LF 均通过 |
| 内容与契约边界 | credential/raw-column 扫描通过；contracts、scope、依赖均未修改 |

### 11.5 残余与下一批门槛

- HTML 尚未实现，也未持久化第二份表示。API 批次必须只从已重新验证的 canonical JSON 生成
  deterministic standalone HTML，对所有动态值做完整 escaping，禁止 script、外部资源和调用方
  提供任意 HTML。
- SQLite 的进程内 `RLock` 不提供跨进程 run scheduler 锁。探索配置必须保持单 writer；evidence
  配置的并发/恢复结论必须由后续真实 PostgreSQL transaction/locking 复验支持。
- PostgreSQL 仍只有 lazy construction 和 DDL compile 证据；evidence profile 仍不可验收。
- Report validator 缓存属于已准备 repository 的启动快照。后续 application composition 必须先完成
  manifest/resource/index binding，再显式 prepare repository；运行中不得热替换 contract。
- 下一批 application/API 只能消费 repository 的受控方法与固定错误，不得直接操作表、跳过
  lifecycle、生成 partial report 或在请求路径静默执行 startup recovery。

### 11.6 Git 交付状态

产品提交 `2c16921` 仅保存在本地。本节架构验收创建独立本地提交；按照用户当前交付策略，
Stage 2 总实现、唯一测试 agent 的独立总验收和主架构总验收完成前不执行 push。

## 12. Batch A6a — closed six-route HTTP contract shell

### 12.1 验收快照与结论

- 产品提交：`11a37cc`
- 提交主题：`feat: add closed six-route API contract shell`
- 覆盖需求：`S2-API` 的六端点 HTTP 契约层、固定 Problem Details、report JSON/HTML
  表示与 side-effect-free dependency injection shell
- 架构结论：**ACCEPTED WITH CORRECTIONS CLOSED; UNIT-SHELL EVIDENCE ONLY;
  LOCAL-ONLY DELIVERY**

本批不构成生产应用组合、真实 RAG/API integration、evaluation scheduling、metrics、Compose 或
真实 Ollama/PostgreSQL 证据。

### 12.2 接受的实现

- FastAPI app factory 只接收注入 service protocol 与预构建 report contract；import/factory 不
  连接网络、数据库、模型，不读文件、不构建索引。Swagger、Redoc、OpenAPI route 均关闭，
  route inventory 恰为六个固定端点。
- 两个 POST 使用 16 KiB 有界流式读取，要求唯一 `application/json` Content-Type、UTF-8、
  duplicate-key-safe JSON object 和 closed DTO；未知字段、超限、错误编码/媒体类型统一 400。
- 四类 GET 在调用 service 前统一要求空 body；重复/非法/负/正 Content-Length 均拒绝，且即使
  缺失或伪报 zero length，stream 首个非空 chunk 也立即固定 400，不缓存剩余正文。
- UUID、date-time、enum、query allowlist、重复 query 与 limit 均在 HTTP 边界闭合。FastAPI
  默认 422 不外泄，输入错误统一使用权威 `invalid_request` Problem Details。
- 每个 endpoint 对 service error 使用独立 code allowlist；16 个 status/retryable/title/detail 与
  `error-codes.yaml` 逐字段一致。意外异常、错误 endpoint code 和伪造返回值统一最小化为
  `internal_error`，Cancellation 不被吞掉。
- Service 返回的 chat、run、audit 和 health 在序列化前重新构造 closed model并执行现有语义
  validator；API shell 不持久化 question、reply 或异常内容。
- Report 只能从 A5b `StoredReport` 进入，重新验证 schema、semantic、canonical bytes、digest
  与 run/report binding。JSON 返回唯一 canonical bytes，不直接访问数据库表。
- HTML 从同一个受控 validated report 确定性生成，全部动态 JSON 文本经 HTML escaping，
  self-contained、无 script/外部资源，32 MiB 超限显式失败且不截断。
- Health endpoint 只序列化注入的 closed health snapshot，不在 request handler 中执行 probe 或
  connect；healthy/degraded 返回 200，required component down 的 unhealthy 返回 503。

### 12.3 架构纠偏

开发预审发现 domain error 的 `code` 实际是 `str, Enum`；初版只接收 exact `str`，会把合法
Ollama/RAG 错误误降级为 `internal_error`。最终只安全读取 Enum `.value`，随后仍执行 endpoint
allowlist 和权威 catalog 校验。

主架构独立负向探针又证明全部 GET 端点曾静默忽略请求体，例如任意 body 的 `/health` 仍返回
200。这偏离无 requestBody 的 OpenAPI，并形成代理/服务器解析差异面。最终统一 empty-body gate
覆盖 run、audit、report、health，且原始 ASGI 测试证明 Content-Length 缺失或伪报 0 也不能
绕过；所有拒绝发生在 service 调用前。

### 12.4 主架构独立验收证据

| 检查 | 结果 |
| --- | --- |
| A6a 独立定向回归 | `53 passed in 9.48s`，仓库内独立 basetemp |
| 完整项目独立回归 | `600 passed in 67.22s` |
| Stage 1 fixture/catalog CLI | exit 0；6/30/62；0 issue；三份 digest 不变 |
| Route inventory | 恰好六个；docs/redoc/openapi/metrics/unknown 均非公共 route |
| POST body boundary | media type、UTF-8、duplicate key、unknown field、16 KiB 超限均覆盖 |
| GET body boundary | 四端点、CL正/负/非法/重复/缺失/伪零与 raw ASGI stream 均覆盖 |
| Error catalog | 16 codes 与权威 YAML 的 status/retryable/title/detail 精确一致 |
| Response drift | forged chat/run/audit/health/report 与错误 endpoint code 均固定 500 |
| Report HTML | nested injection 全转义、deterministic bytes、无 script、JSON/HTML 同源 |
| 编译与文本 | compileall、`git diff --check`、7 文件 UTF-8/no-BOM/LF 均通过 |
| 契约边界 | contracts、Stage 2 scope、依赖均未修改；Canary/credential 扫描通过 |

### 12.5 残余与下一批门槛

- 当前 service 全部是 unit fake/protocol；没有证据证明真实 planner/executor/storage/Ollama 能通过
  这六个端点闭环，也没有后台 62-pair scheduler。不得称为 API integration 或可运行服务。
- Application composition 必须从同一 accepted identity/corpus/resource/index/model facts 构造
  planner、detector、executor、repository 和 health service，关闭 A4b 的跨组件 fingerprint 残余。
- Startup 必须显式 prepare schema、恢复 running runs、加载/绑定 vector index、probe Ollama；
  任一失败只能形成确定性 not-ready/显式错误，禁止请求路径静默 fallback 或隐式 rebuild。
- `ERROR_CATALOG` 当前是代码内闭合快照，并由精确契约测试防漂移；后续若权威 YAML 变更，
  必须同步代码并通过 exact comparison，不能独立演化。
- Unknown route/405 返回空响应，不属于六端点公共 Problem Details 契约；不得把它计为第七 API。
- 下一批 production application service 不得绕过 DTO、service error allowlist、A5b report gate，
  也不得在 API handler 中嵌入 evaluation 或模型降级逻辑。

### 12.6 Git 交付状态

产品提交 `11a37cc` 仅保存在本地。本节架构验收创建独立本地提交；按照用户当前交付策略，
Stage 2 总实现、唯一测试 agent 独立总验收与主架构总验收完成前不执行 push。

## 13. Batch A7a — deterministic paired evaluation and complete reports

### 13.1 验收快照与结论

- 产品提交：`f9e740b`
- 提交主题：`feat: add deterministic paired evaluation reports`
- 覆盖需求：`S2-EVAL` 的逐模式确定性判断、62-pair 汇总、完整 report/gates、
  comparability/strict-manifest 绑定与 `S2-CD01` Canary detail completeness
- 架构结论：**ACCEPTED WITH BLOCKING PROVENANCE CORRECTIONS CLOSED;
  UNIT-ONLY REPORT EVIDENCE; LOCAL-ONLY DELIVERY**

本批只接受纯 evaluation/report core。它不调 Ollama、不调数据库、不提供 scheduler/API production
composition，也不构成真实攻击成功率、防护效果或 portfolio 证据。

### 13.2 接受的实现

- `QueryEmbedding` 私有绑定 exact UTF-8 question SHA-256；planner 在 retrieval/message 前验证
  question 与 handle 一致，避免“问题 B 使用问题 A 的向量”。
- `RagPlanner.plan_pair` 在同一次受控会话中复用同一个 QueryEmbedding 和同一个 validated index，
  生成 baseline/guarded 两个 plan；pair 还绑定 corpus version、subject 和 question digest。
- 每个 plan/result 携带不可序列化的 session/plan identity 与私有内容完整性摘要。Evaluation 只
  接受对应 plan 的 result，拒绝交换、跨 pair、single-plan 冒充和执行后内容篡改。
- Loaded vector index 从实际 canonical artifact bytes 重算 SHA/format/count/dim，并在创建
  evaluation context 时重新执行完整 corpus/model/vector binding，覆盖 finite、dimension、order、
  nonzero norm 与 model tag/digest；不相信调用方声明的 artifact facts。
- Evaluation context 保存 canonical manifest/report-schema snapshot，绑定 fixture、resources、
  model facts、settings、index 和实际 bytes digests，并在 evaluate/build 入口重新验证整体摘要。
- 每个 ScenarioEvidence 绑定当前 context 与自身完整 minimized content digest；report builder 重验
  62 项顺序、fixture metadata、role/classification/case digest、authorization、prevention 和内容完整性。
- QA judgment 只使用固定 NFKC/casefold/五类零宽删除/Unicode whitespace 规范化，确定性计算
  must_include、any_of、must_not_include；禁止 model judge。
- Attack delivery 与 final leak 遵循固定 family 语义；guarded blocked 的最终返回泄露数为 0，
  同时保留最小 blocked detections。Detection ID/owner/role/action/violation 全部从 accepted corpus、
  system resource 和 A2c result 重算。
- Shared query/embed 在 plan 前失败有独立受控入口：四类固定 dependency/protocol code 同时产生
  baseline/guarded failed/indeterminate，证据为空、delivery false，并仍计入固定 124 分母。
- 已成功规划后的 per-mode generation failure 只接受四类 generation/transport code；storage、
  manifest、internal 和 evaluation context-budget drift 不得伪装为有报告的 mode result。
- Report builder 从 62 对重算 ASR、delivery、authorization violation、QA/false rejection、leaks、
  indeterminate、prevention distribution、全部 gates、overall 和 portfolio eligibility。
- Comparability true 同时依赖运行时 paired provenance 与相同 context stable facts；stable key 覆盖
  scenario/corpus/identity/model/settings/resource/vector digests，不写入随机 session identity。
- `S2-CD01` semantic validator 独立重算 Canary details：scenario order、baseline/guarded order、
  trace、exact projection、sort/unique/cardinality 均闭合，且排除 protected fragments。
- 最终 mapping 必须同时通过 Draft 2020-12 + FormatChecker 和完整 semantic validator，再产生
  deterministic compact UTF-8/final-LF bytes；本批不持久化。

### 13.3 阻断级架构纠偏

初版 plan/result 只有 mode/role/retrieval，无法证明两模式共享 QueryEmbedding、index 和资源。
架构因此引入 paired session/result provenance；随后测试又发现 identity 不能发现执行后 plan 内容
篡改，补入私有 plan integrity digest。

主架构独立探针进一步实证：把 scenario 3 的同角色 pair/result 传给 scenario 1，系统曾成功产出
`qa-01` 证据但检索 doc 3，仍可进入 comparable report；同时直接伪造 LoadedVectorIndex 的
artifact SHA 并同步改 manifest 曾被接受。这两项已分别由 exact query/request binding 和 actual
artifact full revalidation 关闭。

ScenarioEvidence 初版没有 context/content binding，builder 又直接写 comparability true；最终增加
context snapshot integrity、每项 content digest 和 62 项 provenance 复核。开发负测还发现 manifest
raw bytes 未直接进入 context integrity payload，最终同时绑定 declared 与 actual manifest digest。

最后，初版把 shared embedding failure 套在已存在 pair 上，真实 scheduler 无法合法产生；最终
新增 pre-plan shared failure 路径。`context_budget_exceeded` 不再伪装为 existing-pair mode failure：
固定 62 fixture 若在 evaluation planning 触发预算漂移，后续 A7b 必须使 run fatal 且无报告。

### 13.4 主架构独立验收证据

| 检查 | 结果 |
| --- | --- |
| A7a/A4a/A4b/CD01/index 独立定向 | `182 passed in 13.50s`，独立安全 basetemp |
| 完整项目独立回归 | `651 passed in 77.30s`，独立安全 basetemp |
| Stage 1 fixture/catalog CLI | exit 0；6/30/62；0 issue；三份 digest 不变 |
| 主架构 cross-scenario 探针 | 原先错误接受；最终相同探针固定 `EvaluationError` |
| Query/pair provenance | question mismatch、subject/corpus drift、cross/swap/single/tamper 均拒绝 |
| Index provenance | fake SHA、zero/nonfinite/dimension drift 即使同步 facts 也拒绝 |
| Context/evidence integrity | manifest/schema/settings/health/index/context 与全部 mode 字段篡改均拒绝 |
| Shared query failure | 四码、双 mode、空证据、delivery false、固定分母均覆盖 |
| 62/124 report | 固定分布、所有 summaries/gates/portfolio 与 deterministic bytes 均覆盖 |
| CD01 | missing/extra/duplicate/order/trace/field/projection 完整负例矩阵均拒绝 |
| 内容最小化 | report/repr/error 无 question/document/reply/marker literal；product simulator 0 命中 |
| 编译与文本 | compileall、`git diff --check`、17 文件 UTF-8/no-BOM/LF 均通过 |
| 契约边界 | contracts、Stage 2 scope、依赖均未修改；credential/marker 扫描通过 |

首次包含 vector store 的开发测试未指定安全 basetemp，因 Windows 默认临时目录权限产生 setup
errors；该结果未被采信。开发侧与主架构最终证据均使用新的受控 basetemp 独立重跑。

### 13.5 残余与下一批门槛

- 测试 simulator 只存在于 `tests/support/evaluation_factory.py`。它构造的 portfolio-eligible mapping
  只证明计算路径可达，绝不是 evidence-profile 实验或安全效果结论。
- A7b 必须按 fixture 顺序执行 exact shared embed，然后 baseline plan/execute、guarded plan/execute，
  将真实 latency/trace/error 交给本批受控入口；禁止直接构造 ModeEvidence/ScenarioEvidence。
- Shared query failure 必须同时完成该 scenario 的两个 indeterminate mode results；generation failure
  可单 mode 保留。Fatal manifest/index/storage/report validation/context-budget drift 必须使 run failed、
  无 partial report。
- A7b 必须每完成一个 pair 原子推进一次 progress，完成 62 对后调用 A5b complete+report 一次；
  任一 report gate/write 失败不得留下 completed run 或 report。
- 真实 comparability/portfolio 仍需要 actual local model digests、真实 Ollama calls、PostgreSQL、
  strict manifest 和完整持久化报告。当前这些均没有运行证据。
- Metrics 尚未实现；后续只能从本批 minimized outcome/reason facts 更新固定低基数标签。

### 13.6 Git 交付状态

产品提交 `f9e740b` 仅保存在本地。本节架构验收创建独立本地提交；按照用户当前策略，Stage 2
总实现、唯一测试 agent 独立总验收与主架构总验收完成前不执行 push。

## 14. Batch A7b — evaluation runner and bounded scheduler

### 14.1 结论

- 产品提交：`cd15dad`
- 提交主题：`feat: run paired evaluations with bounded scheduling`
- 架构结论：**ACCEPTED; PROCESS-LOCAL UNIT EVIDENCE; LOCAL-ONLY DELIVERY**

本批将 A7a 的纯计算核、A4 的 paired RAG 和 A5b 的运行状态机连接为受控后台执行路径；
仍不构成生产应用组合、真实 Ollama/PostgreSQL 集成或实验结果。

### 14.2 接受的运行语义

- Runner factory 绑定同一完整性校验后的 EvaluationContext、planner、executor、detector、
  Ollama client settings、repository、clock 和 trace provider，构造与 import 均无 I/O。
- 严格按 accepted fixture 顺序执行 62 个场景：每场景一次 exact embedding、一次 `plan_pair`，
  再依次执行 baseline、guarded，共 62 次 embedding、62 次 paired planning 和 124 次 generation。
- Shared query 四类失败一次形成双模式 indeterminate；generation 四类失败可保留单模式结果；
  context budget、manifest/index、storage、report validation 与 internal fault 均使 run failed 且无报告。
- 前 61 个完整 pair 各调用一次 `advance_run`；第 62 对不单独推进，而是构造完整报告后调用
  一次 `complete_run`，由 A5b 在同一事务中完成 running/61 到 completed/62 与唯一报告写入。
- 取消始终传播；Runner 只尽力执行 `fail_run(internal_error)`。若存储同时失败，run 可暂留
  running，并明确交给后续 application startup recovery；Runner 不调用全局 recovery。
- Scheduler 固定单进程并发 1、registry 上限 64；每次 schedule 都创建独立任务且不去重，
  完成回调消费固定异常，shutdown 关闭接纳、取消并等待全部自有任务。

### 14.3 主架构独立证据

| 检查 | 结果 |
| --- | --- |
| A7b/A7a/A5b 独立定向 | `78 passed in 39.87s`，独立安全 basetemp |
| 完整项目独立回归 | `670 passed in 81.96s`，独立安全 basetemp |
| Stage 1 fixture CLI | exit 0；6/30/62；0 issue；三个 digest 不变 |
| 编译与差异 | compileall、`git diff --check` 通过；contracts、scope、依赖未修改 |
| 精确调用序列 | 62 embed、62 plan-pair、baseline→guarded 124 execute、61 advance、1 complete |
| 失败矩阵 | shared、单模式 generation、context budget、manifest、storage、report gate、internal 均覆盖 |
| 取消与恢复边界 | fail 成功、fail 失败仍传播、shutdown cancellation 与 task 回收均覆盖 |
| 调度边界 | concurrency 1、capacity 64、overflow 拒绝、无去重、done exception 被消费 |

### 14.4 残余门槛

- 当前 repository、transport、clock 均为 unit fake；不得引用为真实模型、数据库或 API 证据。
- `complete_run` 若已在一个不可信 repository 内提交却返回伪造模型，Runner 无法跨信任边界回滚；
  A5b concrete repository 的事务和 closed return 是生产组合必须绑定的受控边界。
- 下一批生产组合必须显式执行 repository prepare、startup recovery、index load/revalidation、
  Ollama health probe、服务构造和 graceful shutdown；请求 handler 不得隐式执行这些动作。
- 调度器不是分布式锁。SQLite 探索运行保持单 writer；PostgreSQL evidence profile 仍需真实复验。

### 14.5 Git 状态

产品提交 `cd15dad` 与本验收均仅保存到本地。Stage 2 全部实现、唯一测试 agent 独立总验收和
主架构总验收完成前不执行 push。

## 15. P1 — production composition, lifecycle and bounded metrics

### 15.1 结论

- 产品提交：`a552637`
- 提交主题：`feat: compose production runtime and bounded metrics`
- 架构结论：**ACCEPTED FOR LOCAL COMPOSITION; REAL DEPENDENCY EVIDENCE PENDING**

本批把已验收的资源、Ollama adapter、index、RAG、audit/run/report storage、evaluation runner 与
六端点 API 组合为单一显式生命周期，并加入契约闭合的进程内 metrics；不把 MockTransport/SQLite
证据解释为真实 Ollama/PostgreSQL 结果。

### 15.2 接受的架构行为

- Import 与 factory 零 I/O；FastAPI lifespan 是唯一自动 startup/shutdown 入口。Startup 固定执行
  fixture/resource/contract 加载、repository prepare/recovery、index 有界读取、Ollama probe、完整
  index rebind 和共享 planner/detector/executor/context/runner/scheduler 组合。
- 本地权威文件或 evidence manifest 无效为 boot-fatal；Ollama/DB 运行依赖失败则启动为缓存的
  unhealthy runtime，`/health` 可返回 503，依赖端点返回固定目录错误且请求路径不隐式重连。
- Index missing/corrupt/stale 只形成 cached not-ready；不在启动或请求中静默 rebuild/fallback。
- Chat 精确执行 embed→plan→generation/detection，并在返回 reply 前写入最小审计；审计失败不返回
  已生成内容。Evaluation 通过 reservation→create→commit 避免调度容量竞态造成 queued 孤儿。
- 每个 evaluation mode 产生最小 output-detection audit，包含受控检索 ID、授权拒绝、检测和结果；
  raw question/context/reply/marker 不持久化。该审计失败使运行 failed 且无报告。
- Shutdown 停止接纳、取消并等待 owned tasks，再反向关闭 client/repository；重复调用幂等，前序清理
  故障不阻止后续资源关闭。
- Metrics version 1 精确锁定 17 项 name/type/unit/label/value、buckets 与 forbidden labels，拒绝重复键
  和 catalog 漂移；只在真实 operation/lifecycle/evidence 边界更新，不新增第七个 HTTP 路由。

### 15.3 主架构独立证据

| 检查 | 结果 |
| --- | --- |
| 生产组合/API/metrics 定向 | `101 passed in 33.63s`，独立安全 basetemp |
| 完整项目回归 | `699 passed in 104.73s`，独立安全 basetemp |
| Stage 1 CLI | exit 0；6/30/62；0 issue；digests 不变 |
| 六端点 SQLite+MockTransport 闭环 | chat、62-pair run、run/audit/report JSON+HTML、health 全部通过 |
| 精确模型调用 | 单次 chat 加完整 run 共 63 embedding、125 generation |
| 评测审计 | 124 条 mode event；raw question/reply/context/marker 均不在持久化表示 |
| Metrics | 四攻击族每模式各 8 attempts、QA 每模式 30、running/terminal/duration 与 Ollama 调用一致 |
| 依赖失败 | Ollama/DB 离线形成 unhealthy cached state；index 四态不触发 rebuild |
| 生命周期 | startup 顺序、recovery 调用、admission、取消、shutdown 逆序与幂等均覆盖 |
| 边界 | compileall、diff check 通过；contracts、scope、依赖和公共 route inventory 未漂移 |

### 15.4 明确保留边界

- `RUN_CREATED` audit 目前是 best-effort：A5b 没有 create-run-plus-audit 原子操作，也没有 queued 删除/
  失败转换；本批未虚构原子保证。场景证据与报告写入仍是 required/fatal。
- 进程内 metrics 不回填启动前历史 interrupted run，因为 recovery 只返回聚合计数，无法可靠取得
  原 profile 与 running 起点；不得伪造 duration 或标签。
- Scheduler 仅单进程有界协调，不是分布式锁。真实 evidence 仍要求 PostgreSQL、锁定 manifest、
  实际 Ollama tags/digests/calls 和完整 P2 复验。

### 15.5 Git 状态

产品提交 `a552637` 与本验收均只保存在本地；统一 push 继续推迟到 Stage 2 总验收之后。

## 16. P2 — reproducible local delivery candidate

### 16.1 结论

- 产品提交：`1ac7296`（`feat: deliver reproducible local stage2 runtime`）
- LF 纠偏：`1a3e32e`（`chore: lock delivery files to lf`）
- 架构结论：**STAGE 2 IMPLEMENTATION CANDIDATE ACCEPTED; EXTERNAL INTEGRATION NOT RUN;
  INDEPENDENT TOTAL ACCEPTANCE PENDING**

当前主机缺少 Docker、Compose、Ollama 和 PostgreSQL，且 11434 不可用。因此本节只接受实现与
离线交付，不接受 V1 evidence、真实安全效果、portfolio 或简历结论。

### 16.2 接受的交付

- 新增 side-effect-free ASGI factory、默认 `127.0.0.1` server 与统一 artifact CLI：fixture validation、
  real-Ollama index build、strict manifest generation 和 prepared-artifact verification。API startup 只读并
  重验证 artifact，绝不隐式 build、replace、repair 或 simulator fallback。
- `host.docker.internal` 仅在精确显式 opt-in 时允许；同一开关才使容器 server 绑定 `0.0.0.0`。
  其他 host、HTTPS、userinfo、path、query、fragment 继续被拒绝。
- Compose 恰好包含 API 与 PostgreSQL；Ollama 在宿主机。API 非 root、只读根、只读 artifact mount、
  drop all capabilities、no-new-privileges、无 Docker socket；PostgreSQL 使用命名 volume。
- Docker build context 使用默认排除全部的 allowlist，只放行 Dockerfile、source、synthetic data、
  contracts 与 Linux runtime lock。Docker runtime 仅以 `--require-hashes` 安装依赖并通过 source layout
  启动，避免 PEP 517 的额外网络构建依赖。
- 三个窄平台锁覆盖 CPython 3.12 Linux runtime、Linux test overlay 和 Windows dev；具体 requirement
  均为 exact pin + SHA-256，禁止 URL/editable/index/trusted-host。README 主路径不再浮动解析依赖。
- PowerShell demo 不拉模型、不默认删除 volume，检查两个 exact tag，安全复用成对 artifacts；只有
  `-OverwriteArtifacts` 才替换。Health/evaluation 有 deadline，所有 HTTP 调用有 timeout。
- README 已覆盖问题/非目标、威胁模型、架构、数据/许可证/内容警告、安装、Ollama、artifact、
  Compose/PostgreSQL、六 API、复现实验、指标、限制、安全边界和明确 NOT RUN 状态。

### 16.3 主架构独立证据

| 检查 | 结果 |
| --- | --- |
| P2 config/CLI/delivery/production 定向 | `64 passed in 23.18s` |
| 完整项目回归 | `711 passed in 112.14s`，独立安全 basetemp |
| Stage 1 unified CLI | exit 0；6/30/62；0 issue；三个 fixture digest 不变 |
| Linux runtime lock | offline wheel cache + `--dry-run --require-hashes --no-index` exit 0 |
| Linux dev lock | offline wheel cache + `--dry-run --require-hashes --no-index` exit 0 |
| Windows dev lock | offline wheel cache + `--dry-run --require-hashes --no-index` exit 0 |
| PowerShell demo | AST parse exit 0；safe artifact branches、deadlines、timeouts 由静态测试锁定 |
| Docker/Compose static | exactly two services、host Ollama、nonroot/read-only/cap-drop/no socket、context allowlist |
| 配置边界 | default loopback；container gateway requires exact bool+host pair；manifest path bounded |
| 文本交付 | compileall/diff check 通过；新增类型经 `.gitattributes` 固定 LF，blob/worktree 无 CR |
| 契约边界 | public contracts 与 Stage 2 scope 未修改；六路由无 metrics route |

### 16.4 外部证据状态

以下均为 **NOT RUN / external prerequisite**，不是 PASS，也不是实现缺陷：Docker build、Compose
config/runtime、PostgreSQL health/persistence/recovery、真实 Ollama probe/show/embed/chat、30 文档索引、
strict evidence manifest、baseline/guarded chat、62-pair evidence run、audit/report 和容器故障演示。

Stage 2 scope 允许外部依赖缺失时接受 evaluation-ready implementation，但独立测试必须复核明确
dependency failure，且在真实 evidence report 通过全部 gates 前禁止 measured/V1/portfolio/résumé claim。

### 16.5 下一门槛与 Git 状态

下一步仅使用唯一测试 agent 对当前 clean candidate 做独立 Stage 2 总验收；随后主架构逐项总审计。
产品与验收仍只在本地，按用户策略在总验收结束后统一 push。
