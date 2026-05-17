# callflow-lab 项目上下文与 AI 助手工作规范

## 一、项目定位

本项目名称为 callflow-lab。

本项目是“复杂外呼任务对话模型自动评测平台”，不是普通客服系统，也不是实际外呼业务系统，也不是训练对话模型的平台。

系统目标是：评测已有对话模型在复杂外呼任务指令下的表现。

核心能力包括：
1. 导入复杂任务指令。
2. 根据任务指令生成或管理多轮测试用例。
3. 构建用户模拟器，模拟不同被外呼对象。
4. 接入被测对话模型。
5. 自动执行多轮对话评测。
6. 使用规则评分和 LLM-as-a-Judge 进行评估。
7. 自动生成可解释、可量化的评测报告。
8. 支持批量评测，按任务、用例、模型 provider 和重复次数生成多份 run/report 并汇总统计。

## 二、比赛核心要求

当前比赛核心要求是：

1. 构建用户模拟器，能够充分有效测试对话模型在特定任务指令下的效果。
2. 自动产出评测报告，要求评测过程可解释、结果可量化。

系统应重点体现：
- 多轮对话测试能力
- 复杂任务指令遵循能力评测
- 用户模拟器能力
- 自动评分能力
- 证据链和可解释报告
- 量化指标统计

## 三、当前官方脱敏任务

当前默认评测数据来自 Excel 脱敏任务指令，主要包含两个任务：

1. 飞毛腿骑手合同生效外呼评测
2. 课程直播产品升级外呼评测

这两个任务是默认评测集，但系统设计不能写死只能评测这两个任务。后续应支持继续导入新的复杂外呼任务指令。

## 四、禁止继续使用的旧业务 mock

当前项目早期曾使用以下旧示例业务：

- 外卖退款
- 酒店变更
- 团购券核销
- 订单号
- 手机号后四位
- 商家出餐时间
- 平台超时规则
- 退款
- 核销

除非这些词来自当前任务 instruction_text，否则不允许出现在当前脱敏任务的模型回复中。

尤其注意：

飞毛腿任务下不能出现：
- 退款
- 订单号
- 手机号后四位
- 商家出餐时间
- 平台超时规则
- 核销
- 酒店
- 标准直播
- 低延迟直播
- 负责人

课程直播任务下不能出现：
- 飞毛腿
- 骑手
- 配送
- 派单
- 合同 X 单 / Y 单
- 退款
- 订单号
- 手机号后四位
- 核销
- 酒店

## 五、任务类型约定

系统中建议使用以下 task_type：

1. rider_outbound
用于飞毛腿骑手合同生效外呼评测。

2. course_platform_outbound
用于课程直播产品升级外呼评测。

3. generic_outbound
用于后续其他通用外呼任务。

如果 task_type 为空，应根据 instruction_text 自动推断：
- 包含“飞毛腿 / 骑手 / 配送 / 派单” → rider_outbound
- 包含“课程 / 直播 / 低延迟 / 机构 / 负责人” → course_platform_outbound
- 其他情况 → generic_outbound

## 五点五、被测模型回复生成硬约束

评测流程中的被测模型回复只能通过：

```python
TargetModelClient.generate_reply(...)
```

生成。

`evaluation_service.py` 不允许绕过 `TargetModelClient` 直接调用旧 mock、`llm_client.py` 的 assistant mock 或其他临时模板。

`target_bot.py` 如果保留，只能作为兼容包装器，内部必须转调 `TargetModelClient`，不能包含任何独立回复模板。

`TargetModelClient.generate_reply(...)` 必须按 task_type 分发到任务类型白名单生成器：

1. `rider_outbound` → 飞毛腿骑手外呼白名单回复生成器。
2. `course_platform_outbound` → 课程直播外呼白名单回复生成器。
3. `generic_outbound` → 通用外呼白名单回复生成器。

任何 provider，包括 `mock_fallback`、OpenAI compatible 和 custom endpoint，在返回前都必须经过 `validate_reply_by_task_type(...)`。

如果飞毛腿任务回复出现旧客服或课程直播串场词，必须替换为飞毛腿安全 fallback：

```text
单日需完成 X 单，否则合同和派单可能受影响。
```

如果课程直播任务回复出现飞毛腿或旧客服串场词，必须替换为课程直播安全 fallback：

```text
麻烦您帮忙转达负责人，直播发布页升级了。
```

不允许任何任务继续走外卖退款、酒店变更、团购券核销等旧客服默认模板。

## 五点六、用户模拟器 Agent 硬约束

评测流程中的被外呼对象发言应通过：

```python
UserSimulatorAgent.generate_message(...)
```

生成。

`user_simulator.py` 可以保留为兼容入口，但应转调 `backend/app/services/agents/user_simulator_agent.py`，不要继续使用固定轮次模板作为主链路。

`UserSimulatorAgent.generate_message(...)` 必须基于以下上下文生成下一轮用户发言：
- `task.instruction_text`
- `task.task_type`
- `case.user_profile`
- `case.initial_message`
- `case.expected_goals`
- `case.required_rules`
- `case.forbidden_rules`
- `messages`
- `turn_index`

Agent 输出必须包含：
- `content`
- `intent`
- `user_state`
- `should_continue`

`user_state` 至少包含：
- `persona`
- `emotion_level`
- `patience`
- `info_completeness`
- `goal_progress`
- `interruption_count`
- `current_intent`

用户模拟器必须根据上一轮被测模型回复动态推进：
- 模型未回答时继续追问。
- 模型回复过长时打断并要求说重点。
- 模型违反任务约束时表达不满或结束通话。
- 模型说明清楚时逐步接受。
- 模型机械重复时降低耐心。
- 开车场景下模型继续推销时用户应结束通话。
- 骑手恶劣天气场景下模型强迫配送时用户应情绪升级。

## 五点七、混合评测体系约束

评分体系应围绕“被测对话模型在复杂任务指令下的表现”，不要评价本系统代码质量。

评测报告必须由硬规则评分和 LLM-as-a-Judge 评估共同构成：

1. `backend/app/services/rule_judge.py`
   负责硬规则检查，包括必达流程覆盖、禁止规则触发、字数限制、业务串场、忽略用户打断、安全结束、回答用户问题和机械重复。

2. `backend/app/services/agents/evaluator_agent.py`
   负责 LLM-as-a-Judge 评估，读取任务指令、用例目标、规则、完整消息和 rule_judge_result，输出六个指标分、总体原因、证据、建议。

Evaluator 默认 provider 为 `mock`，可通过以下配置切换 openai compatible：

```env
EVALUATOR_PROVIDER=mock
EVALUATOR_API_KEY=
EVALUATOR_BASE_URL=
EVALUATOR_MODEL=
```

未配置 API Key 或 base_url 时，必须自动回退 mock evaluator。

总分公式固定为：

```text
total_score =
task_completion * 0.25
+ instruction_following * 0.20
+ call_flow_coverage * 0.20
+ constraint_compliance * 0.15
+ context_consistency * 0.10
+ response_quality * 0.10
```

报告 API 必须保留可解释字段：
- `total_score`
- `task_completion`
- `instruction_following`
- `call_flow_coverage`
- `constraint_compliance`
- `context_consistency`
- `response_quality`
- `avg_latency_ms`
- `matched_rules`
- `failed_rules`
- `active_rules`
- `pending_rules`
- `not_applicable_rules`
- `current_stage`
- `active_rules_explanation`
- `llm_judge_result`
- `metric_explanations`
- `failure_cases`
- `evidence_messages`
- `suggestions`
- `score_formula`

规则评分不得把任务级全量流程规则机械套到每个用例或每一轮。`rule_judge.py` 必须按当前用例和对话上下文计算 active rules：

1. `global_rules`：每轮都检查的硬约束，如简短自然、禁止机械重复、禁止业务串场、禁止编造职责外信息。
2. `case_rules`：当前 case.required_rules / case.forbidden_rules 中与当前用例或用户意图相关的规则。
3. `stage_rules`：课程直播等流程型任务中当前流程阶段应该完成的规则。
4. `triggered_rules`：用户明确问到退出、天气、排名、费用、配置、开车等问题后才激活的规则。
5. `pending_rules`：后续流程节点规则，只展示为待完成，不进入当前轮失败规则。
6. `not_applicable_rules`：当前用例未触发规则，不参与扣分。

课程直播任务 `course_platform_outbound` 的评分应支持流程阶段：
- `identity_check`
- `upgrade_intro`
- `awareness_check`
- `publish_method_check`
- `configuration_guidance`
- `fee_check`
- `enterprise_wechat`
- `closing`

例如“我是负责人，你说吧。”首轮只应激活身份识别和升级说明相关规则；费用差异、企业微信添加、结束确认、Web 控制台 / 第三方系统路径等后续流程规则应进入 `pending_rules`，不能直接计入失败规则。只有用户追问“区别、在哪里配置、费用、优惠券、企业微信、开车”等内容时，相关触发规则才参与评分。

## 五点八、批量评测约束

批量评测能力用于把单条对话 Demo 扩展为真实评测平台能力，不等同于强制 A/B 测试。

后端必须保留以下接口：

```text
POST /api/batch-runs/start
GET /api/batch-runs/{batch_id}
GET /api/batch-runs/{batch_id}/summary
```

批量执行必须复用现有单用例评测流程，不得绕过：

```python
EvaluationService.start_evaluation(...)
```

每个批量任务应按以下维度展开：
- task_ids
- case_ids，为空时使用任务下全部用例
- model_providers，默认至少支持单模型 `mock_fallback`
- repeat_times，默认 1

批量 summary 至少包含：
- `batch_id`
- `total_runs`
- `finished_runs`
- `failed_runs`
- `average_score`
- `average_latency_ms`
- `pass_rate`
- `task_score_summary`
- `metric_score_summary`
- `failed_rule_top5`
- `report_list`

当传入多个 `model_providers` 时，可以额外返回 `model_score_summary` 和 `best_model_provider`，但前端不应强行写成“A/B 测试”。

## 五点九、模型 provider 配置约束

模型配置页用于展示和测试被测模型 provider 接入状态，不负责训练模型，也不在前端保存或展示 API Key 明文。

后端应保留以下接口：

```text
GET /api/model-providers
POST /api/model-providers/test
```

默认 provider 包括：
- `mock_fallback`：本地兜底模型，仅用于无 API Key 或演示环境不可用时保证流程跑通，不作为系统 AI 能力亮点。
- `openai_compatible`：真实大模型 API 接入，用于接入 Qwen、DeepSeek、GPT、智谱、Moonshot 等兼容 OpenAI 格式的模型。
- `custom_endpoint`：自定义模型接口，用于接入外部被测模型服务、企业内部模型或其他团队接口。

历史 provider 必须兼容映射：
- `mock_baseline` → `mock_fallback`
- `mock_strong` → `mock_fallback`

系统真正的 AI 能力来自用户模拟器 Agent、LLM-as-a-Judge 评估器、AI 辅助生成测试用例、`openai_compatible` 真实大模型接口、`custom_endpoint` 外部模型接口，以及可解释、可量化评测报告。不要把 `mock_fallback` 写成 AI 能力亮点。

真实模型的 Base URL、Model Name、Endpoint 和 API Key 仍以 `.env` 为配置来源；前端只展示非敏感配置和 API Key 是否已配置。

## 五点十、初始化与测试用例幂等性约束

后端启动初始化、Excel 导入和 sample seed 必须具备幂等性，不允许因为重复启动后端或重复导入指令而重复创建同一个测试用例。

任务判重优先使用：

```text
name + task_type
```

测试用例判重必须使用：

```text
task_id + name + initial_message
```

如果三者相同，应复用已有用例或跳过插入，不得新增重复记录。

`backend/app/services/case_registry.py` 是测试用例判重、去重展示和历史重复清理的统一工具入口。`sample_data.py`、`import_instruction_excel.py`、`cases.py` 和批量评测用例展开不得绕过该规则。

历史重复数据不得在后端启动时自动删除。若需要清理，应使用手动接口：

```text
POST /api/cases/deduplicate
```

清理逻辑保留最早创建的同签名用例，并在删除重复项前把 run/report/batch item 的 `case_id` 引用迁移到保留项。若未来 `EvaluationCase` 增加 `data_source=manual` 字段，清理逻辑不得删除 manual 用例。

## 六、核心后端文件

重点关注以下文件：

- backend/app/services/target_model_client.py
  被测模型接入层。评测流程应统一通过它调用被测模型。

- backend/app/services/target_bot.py
  旧兼容包装器。如果保留，只能转调 TargetModelClient，不能继续自己生成旧客服 mock 回复。

- backend/app/services/evaluation_service.py
  评测执行主流程。负责创建 run、执行多轮对话、调用被测模型、调用评分器、生成报告。

- backend/app/services/batch_evaluation_service.py
  批量评测服务。负责展开任务、用例、模型 provider 和重复次数，并复用单次评测流程生成汇总统计。

- backend/app/services/case_registry.py
  测试用例幂等和历史重复清理工具。负责 `task_id + name + initial_message` 判重、列表去重和手动 deduplicate 迁移引用。

- backend/app/services/user_simulator.py
  用户模拟器旧入口。如后续新增 Agent 版本，应转调 user_simulator_agent.py。

- backend/app/services/agents/user_simulator_agent.py
  用户模拟器 Agent。根据任务指令、用户画像、对话历史动态生成用户发言。

- backend/app/services/rule_judge.py
  规则评分器。负责硬规则检查。

- backend/app/services/agents/evaluator_agent.py
  LLM-as-a-Judge 评估器。负责语义级评分和证据解释。

- backend/app/services/report_service.py
  评测报告生成模块。

- backend/app/api/batch_runs.py
  批量评测 API。提供启动批量评测、查询批量详情和批量 summary。

- backend/app/api/model_providers.py
  模型 provider 配置 API。提供 provider 列表和连接测试，不返回 API Key 明文。

- backend/app/seed/import_instruction_excel.py
  Excel 脱敏任务导入模块。

## 七、核心前端文件

重点关注以下文件：

- frontend/src/pages/Dashboard.vue
  数据大屏。

- frontend/src/pages/TaskList.vue
  评测任务列表。

- frontend/src/pages/TaskDetail.vue
  任务详情。

- frontend/src/pages/CaseList.vue
  测试用例列表。

- frontend/src/pages/RunConsole.vue
  开始评测页面，是核心演示页面。

- frontend/src/pages/ReportDetail.vue
  完整评测报告页面。

- frontend/src/pages/BatchEvaluation.vue
  批量评测页面。用于选择任务、用例范围、模型 provider 和重复次数，并展示批量 summary 与报告列表。

- frontend/src/pages/ModelConfig.vue
  模型配置页面。展示 provider 名称、类型、启用状态、Base URL、Model Name、Endpoint 和测试连接按钮，不展示 API Key 明文。

## 八、开发优先级

当前开发优先级：

1. 先修复不同任务之间的回复串场问题。
2. 确保 evaluation_service.py 真正统一调用 target_model_client.py。
3. 确保 target_bot.py 不再生成旧客服 mock。
4. 确保飞毛腿任务和课程直播任务回复不串场。
5. 再增强用户模拟器 Agent。
6. 再增强规则评分与 LLM-as-a-Judge。
7. 再增强可解释报告。
8. 批量评测和模型配置完成后，再按需增强更复杂的多模型分析、异步批量任务和报告导出。

不要在底层回复串场未修复前继续堆新功能。

## 九、后端启动命令

后端启动：

```bash
cd backend
uvicorn main:app --reload --port 8080
```

Swagger 地址：

http://127.0.0.1:8080/docs

## 十、前端启动命令

前端启动：

```bash
cd frontend
npm install
npm run dev
```

前端默认访问：

http://127.0.0.1:5173

## 十一、基本验证标准

每次修改后至少验证：

1. 后端可以启动。
2. Swagger 可以访问。
3. 前端可以启动。
4. Dashboard 不白屏。
5. 开始评测页面可以跑通。
6. 报告页可以打开。
7. 飞毛腿任务不出现课程直播和旧退款客服内容。
8. 课程直播任务不出现飞毛腿和旧退款客服内容。
9. 报告中有总分、指标分、失败规则、证据轮次、扣分原因和优化建议。
10. 批量评测接口可以生成多个 run/report，summary 可以返回平均分、通过率、失败规则 TOP5 和报告列表。
11. 模型配置页可以打开，`/api/model-providers` 不返回 API Key 明文，仅展示 `mock_fallback`、`openai_compatible`、`custom_endpoint`，且旧 `mock_baseline` / `mock_strong` 请求可兼容映射到 `mock_fallback`。

## 十二、AI 助手工作规范

每次修改代码前必须先理解当前项目结构，不要盲目重建项目。

除非用户明确要求，否则：
- 不要重建项目。
- 不要大改 UI。
- 不要删除已有功能。
- 不要随意改接口路径。
- 不要引入复杂不可控依赖。
- 不要写空文件。
- 不要只写 TODO。
- 不要在代码中写真实 API Key。
- 不要把项目写成真实外呼系统。
- 不要把项目写成训练对话模型的平台。

每次完成代码修改后，必须同步更新 docs/当前进度.md。

只有当长期规则、核心架构、启动方式、禁止事项或重要验证标准发生变化时，才更新 AGENTS.md。
普通 bug 修复、页面调整、接口小改动，不要修改 AGENTS.md。
