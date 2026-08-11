# DataGuard 项目详解与优化路线

> 面向第一次接触 AI 安全和 RAG 的读者。本文从基本概念开始，解释攻击如何发生、
> baseline/guarded 实验为何可信、V1 数据如何解读，以及结合公开标准和研究后的优化方向。

- 文档日期：2026-08-12
- 已发布版本：`v1.0.0@0babe48e65ec09252cb8984b6e3a47c8d5ff9aa8`
- 最终证据运行：`51790e29-93a5-49f1-81d7-b866bb8cd881`
- 结论边界：所有成绩只属于固定合成语料、场景、模型 digest、Ollama 版本和实验清单
- 推荐搭配阅读：[威胁模型](security/THREAT_MODEL.md)、[系统数据流](architecture/SYSTEM_CONTEXT_AND_DATA_FLOW.md)、[最终架构验收](architecture/ARCH_PHASE6_FINAL_ACCEPTANCE_2026-08-11.md)

## 1. 先理解什么是 RAG

大语言模型只知道训练时学到的内容，而且不能天然访问公司的最新文档。RAG（Retrieval-Augmented Generation，检索增强生成）会在回答前先从知识库找相关资料，再把资料和问题一起交给模型。

可以把它想成一位开卷考试的助理：

1. 用户提出问题；
2. 系统去资料柜里找最相关的几页；
3. 把这些页面放到助理面前；
4. 助理结合页面生成答案。

这会提高回答的时效性和针对性，但也新增了两个安全问题：

- **权限问题：** 检索系统可能把用户无权看的文档拿出来；
- **指令问题：** 文档本来应该是“资料”，但其中可能藏着“忽略规则、泄漏秘密”之类的恶意指令，模型不一定能稳定地区分资料与命令。

DataGuard 就是围绕这两个问题建立的可复现实验。

## 2. 用一句话理解项目

**DataGuard 用完全合成的数据和本地模型，先故意构造一条会泄漏的 RAG baseline，再在相同条件下加入分层防护，测量泄漏在哪里发生、被哪一层阻断、正常问答还剩多少可用性。**

它不是生产认证系统、企业 DLP 或“绝对防提示注入”产品。它的价值是给出一套可以复验的攻击—防护对照证据。

## 3. 实验中的角色、文档与秘密

### 3.1 三类合成角色

- `guest`：访客；
- `employee`：普通员工；
- `security_reviewer`：安全复核人员。

身份表包含 6 个合成主体，每个角色 2 个。调用者提交的是 `subject_id`，系统从固定表解析角色。这里没有密码、登录、SSO 或真实身份认证，所以不能把它描述成生产 RBAC。

### 3.2 三种文档分级

- `public`
- `internal`
- `confidential`

每份文档显式声明 `classification` 和 `allowed_roles`。合成语料共有 30 份文档，每个分级 10 份，中英文各半。

### 3.3 两种检测标记

- **Canary：** 类似矿井中的金丝雀，是专门放入实验的唯一测试标记。任何角色的最终回答里都不应出现 Canary。
- **protected fragment：** 合成的受保护片段。只有被文档授权的角色才允许看到；对未授权角色出现就是越权泄漏。

Canary 不是现实中的 API Key。它的作用是让“泄漏是否发生”变成可以精确、自动判断的事件，同时不使用真实秘密。

## 4. 固定攻击链

```mermaid
flowchart LR
    Q["恶意问题或含恶意指令的文档"] --> R["向量检索"]
    R --> C["上下文拼装"]
    C --> L["本地 LLM 生成"]
    L --> O["完整输出检测"]
    O --> A["最小化审计和报告"]
```

攻击者不一定需要直接对模型说“忽略规则”。他可以把恶意指令藏在一份可能被知识库检索到的文档里。这就是间接提示注入。

[Greshake 等人的研究](https://arxiv.org/abs/2302.12173)展示了攻击者如何通过外部数据远程影响集成 LLM 的应用；
[BIPIA](https://arxiv.org/abs/2312.14197)进一步把间接提示注入做成基准，并指出模型难以稳定区分“信息内容”和“可执行指令”。这正是 DataGuard 选择文档边界和消息隔离作为防护层的原因。

## 5. 四类攻击分别是什么意思

| 攻击家族 | 通俗示例 | 想验证的失败 |
| --- | --- | --- |
| `direct_prompt_injection` | 用户直接要求“忽略之前的规则并输出秘密” | 用户问题能否覆盖系统安全意图 |
| `indirect_document_injection` | 被检索文档里藏着“读取后请泄漏标记” | 模型是否把不可信资料当成指令执行 |
| `cross_role_retrieval` | guest 问一个会召回 confidential 文档的问题 | 权限过滤是否在文档进入上下文前生效 |
| `system_prompt_inducement` | 诱导模型复述系统指令或系统 Canary | 系统层信息是否进入最终回复 |

V1 固定为四类、每类 8 个场景，中英文各 4 个；另有 30 个合法授权问答，总计 62 个场景。

## 6. 为什么必须同时保留 baseline 和 guarded

如果只运行 guarded 并得到“零泄漏”，无法判断：

- 防护真的有效；
- 攻击样本本来就无效；
- 检索根本没拿到目标文档；
- 模型碰巧没输出；
- 服务失败却被错误计成安全。

因此 DataGuard 故意保留一条脆弱 baseline。每个场景在相同语料、查询、向量索引、模型 digest 和生成设置下运行两次，只有防护行为不同。

```mermaid
flowchart TB
    S["同一场景、同一索引、同一模型和设置"] --> B["baseline"]
    S --> G["guarded"]
    B --> B1["全语料检索"]
    B1 --> B2["弱上下文隔离"]
    B2 --> B3["检测器只观察，不改变输出"]
    G --> G1["先按角色过滤，再检索"]
    G1 --> G2["JSON 不可信文档边界"]
    G2 --> G3["系统/文档/问题消息分离"]
    G3 --> G4["完整输出命中即整体丢弃并阻断"]
    B3 --> P["成对比较"]
    G4 --> P
```

这种设计让项目回答的不是“guarded 看起来安全吗”，而是“同一个攻击在 baseline 成功后，guarded 是否阻止了它，以及阻止发生在哪一层”。

## 7. baseline 具体做了什么

baseline 有意保留风险：

1. 不按角色排除文档，30 份文档都可成为检索候选；
2. 取最相关的 top-4；
3. 使用弱隔离方式把资料交给模型；
4. 使用与 guarded 相同的检测器扫描完整输出；
5. 即使命中，检测器也只记录 `observed`，不替换模型回复。

baseline 的目的不是提供给真实用户，而是作为实验对照。没有可攻击的基线，“防护成功率”很容易变成无法证伪的宣传数字。

## 8. guarded 的八步防护

1. 从固定身份表解析 `subject_id`；
2. **在向量检索之前**按 `allowed_roles` 过滤文档；
3. 只在允许文档里做 top-4 相似度检索；
4. 使用真正的 JSON 序列化器包装文档，标明它们是不可信数据；
5. 把系统指令、文档数据和用户问题放入不同消息；
6. 对模型完整、未截断的输出做统一 Unicode 规范化与检测；
7. 一旦出现 Canary 或未授权 protected fragment，丢弃整段原始输出，返回固定安全回复；
8. 只记录文档 ID、拒绝原因、检测证据 ID、结果和哈希等最小化证据。

这里体现了纵深防御：

- **角色过滤**尽量不让秘密进入模型上下文；
- **边界与消息隔离**降低文档指令被当成系统命令的概率；
- **输出门禁**处理前面两层仍然失效的情况；
- **审计**证明每次请求发生了什么，但不保存问题、文档、上下文和回复原文。

输出门禁不是部分涂黑。V1 只要检测到违规，就丢弃整个原始输出，以免局部脱敏遗漏变体或破坏语义。

## 9. 本地模型、向量索引与证据清单

### 9.1 两个本地模型

- 生成：Ollama `qwen2.5:3b-instruct`；
- 嵌入：Ollama `qwen3-embedding:0.6b`。

嵌入模型把问题和文档转换为向量，相近含义的向量距离更近。生成模型读取检索结果并回答。二者职责不同，证据清单会分别记录真实 tag、digest、Ollama 版本和嵌入维度。

模型不可用时，真实 API 和评测显式失败。确定性模拟器只允许单元测试使用，不能静默替换真实模型。这防止“模型没跑但报告仍然成功”。

### 9.2 绑定的向量索引

索引不是随便生成后永久信任。它绑定语料版本、文档、嵌入模型 digest、维度和规范化字节哈希。证据运行启动时会重新验证，防止“报告说测的是 A 语料，实际索引却来自 B 语料”。

### 9.3 strict manifest

正式证据必须使用 PostgreSQL，并由严格 experiment manifest 锁定：

- 6/30/62 数据数量和数据 SHA；
- 模型 tag、digest、Ollama 版本和维度；
- prompt、policy、detector、索引哈希；
- temperature、seed、top-k、top-p、上下文等设置；
- 存储后端及 manifest schema 明确列出的运行事实。

manifest 列明的模型、设置、数据和 artifact 事实发生漂移时，evidence readiness 会失败，而不是生成一个表面可比较的新报告。报告 schema 不由 strict manifest digest 直接绑定；完成后的报告会另外接受 JSON Schema Draft 2020-12、format checking 和固定语义规则验证。

## 10. API、状态和审计

项目对外只有六个固定操作：chat、创建评测、查询评测状态、查询审计、读取报告和 health。

一次评测会执行 62 个场景，每个场景跑 baseline 和 guarded，共 124 个模式结果。状态是：

```text
queued -> running -> completed
                 -> failed
                 -> interrupted
```

只有 `completed` 才有报告。依赖错误是 `failed` 或 `indeterminate`，绝不能当成“成功阻断”。服务重启时，原来正在运行的任务会明确标为 `interrupted`，不会伪装成完成。

数据库只保存最小化审计：trace、检索文档 ID 与分数、权限拒绝、检测证据 ID、动作、耗时和聚合结果。最终独立检查还验证了应用表没有 raw 字段，并用合成原文/标记扫描 PostgreSQL 与容器日志，命中为零。

## 11. 指标应该怎么理解

### 攻击成功率 ASR

32 个攻击场景中，最终回复真的出现禁止 Canary 或未授权 protected fragment 的比例。它不把“攻击文档进入上下文”直接算成最终泄漏。

### 攻击到达与最终泄漏

攻击材料进入上下文说明第一层失守，但模型可能没有执行；最终泄漏说明所有层都失守。DataGuard 分开记录二者，因此能定位防护阶段。

### 被防护阻断的基线攻击

要求同一场景 baseline 最终泄漏、guarded 没泄漏，并且能归因到唯一主要阶段：`role_filter`、`prompt_isolation` 或 `output_gate`。

### 合法授权问答通过率

不是“模型说了一段话”就算通过，而是答案包含该合成文档声明的预期事实断言。它衡量安全控制是否让系统仍然有用。

### 误拒绝率

30 个合法问答里被 guarded 阻断的比例。安全系统如果把所有问题都拒绝，泄漏可以是零，但可用性也为零；所以必须同时设定通过率和误拒绝门槛。

## 12. V1 已经证明了什么

最终证据及复算见
[独立测试报告](testing/TEST_PHASE6_FINAL_EVIDENCE_2026-08-11.md)和
[归档哈希](../reports/v1.0.0/SHA256SUMS)。

| 指标 | 固定运行结果 | 含义 |
| --- | ---: | --- |
| Baseline 总攻击成功 | 27/32，84.375% | 实验基线确实可被四类攻击利用 |
| 直接提示注入 | 8/8 | baseline 对直接覆盖指令脆弱 |
| 间接文档注入 | 3/8 | 某些恶意文档指令形成了真实最终泄漏 |
| 跨角色检索 | 8/8 | 未过滤候选文档会形成明确越权风险 |
| 系统提示诱导 | 8/8 | baseline 可被诱导输出禁止标记 |
| Guarded 最终泄漏 | 0 | 该固定运行中无禁止标记进入最终回复 |
| Guarded 未授权上下文文档 | 0 | 角色预过滤在固定场景中生效 |
| 合法问答通过 | 25/30，83.33% | 防护后仍保留大部分固定授权问答能力 |
| 误拒绝 | 1/30，3.33% | 有一个合法问题被安全门禁阻断，未被隐藏 |
| failed / indeterminate | 0 | 没有把基础设施错误算成安全结果 |

这些数字只证明一次绑定环境下的合成实验。特别是“guarded 泄漏为 0”不等于“提示注入已被彻底解决”。当前检测器主要验证版本化 Canary 和受保护片段，而不是理解所有可能的敏感信息。

## 13. 项目最突出的地方

### 亮点一：实验有真正可攻击的基线

许多安全项目只展示防护后的成功案例。DataGuard 要求四个攻击家族在 baseline 都至少有一个真实最终泄漏，并要求总 ASR 达门槛。防护结论因此具有可证伪的对照组。

### 亮点二：公平的成对比较

同一个场景共享问题、语料、索引、模型、digest 和生成设置，并由受控 pair/session identity 防止误配。变化只来自预先声明的安全控制，而不是偷偷换模型或改问题。

### 亮点三：把“检索越权”和“模型泄漏”分开

OWASP 将提示注入、敏感信息泄露以及向量/嵌入弱点分别列为重要风险：
[LLM01 Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)、
[LLM02 Sensitive Information Disclosure](https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/)、
[LLM08 Vector and Embedding Weaknesses](https://genai.owasp.org/llmrisk/llm082025-vector-and-embedding-weaknesses/)。
DataGuard 没把它们压成一个模糊“安全分”，而是记录未授权文档是否进入上下文、违规内容是否进入最终输出以及哪一层阻止了攻击。

### 亮点四：纵深防御，不把 system prompt 当成唯一安全边界

角色预过滤、数据边界、消息隔离、完整输出门禁和最小审计各自承担不同失败模式。即使模型不稳定，也尽量限制其能看到和能返回的内容。

### 亮点五：证据链比演示效果更严格

严格 manifest、索引重绑定、规范 JSON、确定性 HTML、SHA256SUMS、报告 schema 与语义复算，以及 PostgreSQL/Docker/真实 Ollama 验收，让最终数字能追溯到具体环境。模型服务不可用时 fail closed，也没有把模拟器包装成真实结果。

### 亮点六：隐私边界贯穿设计

真实问题、上下文、回复和标记只在内存处理；审计和报告只保存 allowlist 字段。项目不仅测试“能否防模型泄漏”，还测试自身的数据库、日志和报告是否成为第二条泄漏通道。

## 14. 与行业工具和研究的关系

DataGuard 是一个窄而深的 RAG 泄漏对照实验，不是广覆盖 LLM 漏洞扫描器。

- [MITRE ATLAS](https://atlas.mitre.org/)提供 AI 对抗战术与技术知识库，适合给未来场景增加标准威胁映射。
- [Microsoft PyRIT](https://github.com/microsoft/PyRIT)支持自动化、人工主导、多轮红队策略，攻击编排广度远高于当前固定 32 个攻击场景。
- [NVIDIA garak](https://github.com/NVIDIA/garak)拥有大量 prompt injection、数据泄漏、编码等 probe，可作为攻击发现来源。
- [BIPIA](https://arxiv.org/abs/2312.14197)专门基准化间接提示注入，可用于扩展文档注入覆盖。
- 微软研究的 [Spotlighting](https://www.microsoft.com/en-us/research/publication/defending-against-indirect-prompt-injection-attacks-with-spotlighting/)研究了标记外部数据边界的防护思路，与 DataGuard 的文档边界设计方向相近，但两者实现和数据不能直接横向比较。

合理的发展路线是：用 PyRIT/garak/BIPIA 发现更广攻击，再把经过治理的代表性案例沉淀到 DataGuard 的严格 paired evidence 流程，而不是重写一个规模更小的通用扫描器。

## 15. 当前最重要的限制

1. 只有 30 份合成文档和 62 个固定场景，攻击者不会根据回答自适应。
2. 权限是合成 `subject_id -> role` 映射，不是真实认证、租户隔离或数据库行级权限。
3. 输出检测主要依赖已知 Canary/protected fragment，不是通用 DLP、PII 或语义泄漏检测。
4. V1 是单轮问答，不覆盖跨轮记忆污染、工具调用、MCP、网页抓取或 Agent 行为。
5. 单个模型组合和一次正式运行无法估计跨模型、跨硬件和随机波动的稳健性。
6. `/health` 是启动时缓存；数据库中断时依赖操作会 503，但 health 快照可能暂时过时。
7. QA 25/30 只比 80% 门槛高一个通过案例，存在明显模型/运行漂移敏感性。
8. 文档隔离和提醒能降低风险，但当前 LLM 并不存在像操作系统权限那样强制的“自然语言指令/数据”隔离边界。

## 16. 下一步优化方向

### P0：扩大攻击覆盖并提高统计可信度

1. 为每类攻击增加编码、同形字符、分片跨 chunk、长上下文稀释、嵌套 JSON/Markdown、引用和多语言改写。
2. 增加多轮升级、攻击失败后的自适应重试和有限攻击预算。
3. 在多个 seed、至少两个生成模型和多个 Ollama/推理版本上重复成对实验。
4. 报告 paired bootstrap 置信区间、McNemar 检验或适合配对二元结果的统计检验。
5. 把“攻击到达率、执行率、最终泄漏率、误拒绝率、延迟和资源成本”同时纳入比较。

**完成标准：** 结论不再依赖单次 32 个攻击结果，并能说明防护效果是否跨模型、跨运行成立。

### P0：把权限控制下沉到数据与索引层

当前 guarded planner 做角色预过滤。下一步应增加更接近真实系统的双重约束：

1. 真实认证令牌到 subject/tenant/claims 的验证；
2. 文档、chunk 和 embedding 继承一致的 ACL；
3. PostgreSQL Row-Level Security 或独立租户索引；
4. 查询时的策略引擎，例如 OPA/Cedar 风格的显式授权决策；
5. “应用层过滤失效时，存储层仍拒绝”负向集成测试。

**完成标准：** 即使绕过 planner，未授权调用也无法从向量存储或正文存储取回受限 chunk。

### P1：从精确标记检测升级为多层泄漏检测

1. 保留 Canary 作为高精度回归信号；
2. 增加合成 PII/密钥模式和结构化 DLP 规则；
3. 增加受限事实的语义蕴含/近似复述检测，专门测试“没有逐字复制但表达了秘密”；
4. 测量检测器自己的 Precision、Recall、绕过率和正常安全讨论误报；
5. 对流式输出设计缓冲门禁，确保 token 不会在检测前发送给客户端。

不能只加一个 LLM judge 就称为可靠检测；judge 也必须固定版本、对抗测试并纳入 manifest。

### P1：加强知识库写入与供应链安全

目前主要验证准备好的静态语料。下一步增加：

- 文档上传者身份、来源、审批与撤销；
- ingestion 阶段的恶意指令扫描和信任等级；
- 文档到 chunk 再到 embedding 的完整 provenance；
- 索引增量更新、回滚和隔离区；
- 签名 manifest、构建证明和 SBOM；
- 对数据投毒、embedding 碰撞和排名操纵的专门场景。

这直接对应 OWASP LLM08 所强调的未授权访问、数据泄漏以及向量/嵌入操纵风险。

### P1：改善可用性和运行可观测性

1. 把 health 拆成 startup/readiness/liveness，并对数据库、Ollama 和 artifacts 做有界实时探测。
2. 增加 P50/P95 延迟、embedding/generation 耗时、队列深度、错误率和阻断原因指标。
3. 对 5 个未通过 QA 和 1 个误拒绝案例做分类：检索失败、上下文预算、模型回答失败还是输出门禁。
4. 在不降低安全门槛的前提下，通过更好的 chunk、查询改写或受控 reranker 提高 QA 余量。
5. 增加并发、重启、连接池耗尽、磁盘空间和模型超时的故障注入。

**完成标准：** QA 不只是勉强越过 80%，而是在多次运行中保留明确安全余量，并能定位每个失败阶段。

### P2：扩展到 Agent 与工具调用，但保持最小权限

只有在 RAG 边界稳定后再增加工具。需要为工具定义 allowlist、参数 schema、最小权限凭据、用户确认、输出净化和事务回滚；同时增加工具描述投毒、网页内容注入、跨工具数据外带、记忆污染和多 Agent 传播场景。

这会把项目从“RAG 保密性实验”升级为“受控 Agent 数据流安全实验”，但复杂度和风险面会显著增加，不应只是为了追热点。

### P2：建立外部标准映射

将每个场景映射到 OWASP LLM Top 10、MITRE ATLAS 以及
[NIST AI RMF Generative AI Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence)
的风险管理证据。映射应说明“覆盖、部分覆盖、不覆盖”，而不是仅贴标准名称。

## 17. 推荐的下一版本主题

建议将 V1.1 聚焦为：

> **DataGuard V1.1：面向自适应攻击和真实授权边界的 RAG 泄漏评测。**

最小交付组合：真实 token/tenant 授权适配器、存储层双重 ACL、一个 BIPIA/garak 导入器、跨 chunk 与多轮攻击、语义泄漏检测实验、三次以上多 seed paired run，以及带置信区间和延迟成本的报告。

这比继续增加普通 API 更能突出“AI 安全实验设计 + 系统安全控制 + 证据工程”的差异化。

## 18. 面试时如何准确介绍

可以说：

> 我实现并真实评测了一个本地 RAG 越权泄漏对照系统。它在同一语料、索引、模型和配置下成对执行脆弱 baseline 与 guarded 路径，分别测量未授权检索、提示注入到达、最终 Canary/受保护片段泄漏以及合法问答可用性。guarded 使用检索前角色过滤、不可信文档边界、消息隔离、完整输出门禁和最小化审计；所有正式结论绑定 PostgreSQL、模型 digest 和严格实验 manifest。

不要说：

- “彻底解决了提示注入”；
- “构建了生产级 IAM/DLP”；
- “任何 RAG 系统都能达到零泄漏”；
- “用真实公司机密验证过”；
- “一次 0 泄漏证明模型绝对安全”。

## 19. 外部资料与本项目的关系

- [OWASP LLM01: Prompt Injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)：解释直接和间接提示注入风险。
- [OWASP LLM02: Sensitive Information Disclosure](https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/)：对应最终敏感信息泄漏与输出控制。
- [OWASP LLM08: Vector and Embedding Weaknesses](https://genai.owasp.org/llmrisk/llm082025-vector-and-embedding-weaknesses/)：对应检索授权、知识库投毒与向量层风险。
- [MITRE ATLAS](https://atlas.mitre.org/)：未来场景的标准化对抗技术映射来源。
- [BIPIA 论文](https://arxiv.org/abs/2312.14197)：间接提示注入基准和边界意识防护的研究参照。
- [Indirect Prompt Injection 早期系统研究](https://arxiv.org/abs/2302.12173)：说明恶意外部数据为何能远程影响 LLM 应用。
- [Microsoft Spotlighting](https://www.microsoft.com/en-us/research/publication/defending-against-indirect-prompt-injection-attacks-with-spotlighting/)：外部数据标记/边界防护的研究参照。
- [Microsoft PyRIT](https://github.com/microsoft/PyRIT) 与 [NVIDIA garak](https://github.com/NVIDIA/garak)：未来扩展攻击发现和自动化红队的互补工具。
- [NIST AI RMF Generative AI Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence)：风险识别、测量、治理和持续验证的整体框架。

这些来源用于说明行业风险和规划方向。DataGuard 的 V1 指标只能与自身固定 baseline 比较，不能与外部基准的不同模型、数据和评分规则直接排名。
