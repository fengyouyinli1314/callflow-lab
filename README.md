# callflow-lab

callflow-lab 是“复杂外呼任务对话模型自动评测平台”。它不是实际外呼系统，也不是训练对话模型的平台；系统目标是评测已有对话模型在复杂外呼任务指令下的表现。

当前默认评测数据来自脱敏任务指令，主要包含两个任务：

- 飞毛腿骑手合同生效外呼评测
- 课程直播产品升级外呼评测

系统通过任务导入、测试用例管理、用户模拟器 Agent、被测模型接入、规则评分、LLM-as-a-Judge 和可解释报告，完成“任务列表 -> 用例构建 -> 开始评测 -> 多轮对话 -> 自动评分 -> 查看报告”的闭环。

## 核心功能

- 评测任务管理：维护复杂外呼任务指令、角色要求、流程规则和评测目标。
- 测试用例管理：支持预置用例、手动新增/编辑/删除，以及 AI 生成草稿后人工确认保存。
- 用户模拟器 Agent：根据任务指令、用户画像、对话历史和上一轮回复动态生成被外呼对象发言。
- 混合评分：硬规则评分和 LLM-as-a-Judge 共同生成六项指标分、总分、证据和建议。
- 可解释报告：展示总分、各指标分、规则分、Judge 分、融合分、融合公式、规则追溯、证据轮次、对话片段、扣分原因和优化建议。
- 单条问答检测：在不生成正式报告的情况下，直接输入一条或多条用户发言，快速检查被测模型回答、必要事实命中和规则结果。
- 批量评测：按任务、用例、模型 provider 和重复次数生成多份 run/report 并汇总统计。
- 数据大屏：展示任务、用例、评测次数、平均分、失败规则 TOP5、趋势和 AI 能力模块。

## 技术栈

- 后端：Python 3.10、FastAPI、Uvicorn、SQLModel、SQLite、Pydantic、httpx、python-dotenv
- 前端：Vue 3、Vite、Element Plus、ECharts、Axios
- 测试：pytest、FastAPI TestClient

## 后端启动

```powershell
conda activate callflow-lab
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
```

Swagger 地址：

```text
http://127.0.0.1:8080/docs
```

后端启动时会自动初始化演示数据；如果 Excel 指令文件不存在，会使用当前外呼任务 fallback 数据，不再使用旧客服样例。

## 前端启动

```powershell
cd frontend
npm install
npm run dev
```

前端地址：

```text
http://127.0.0.1:5173
```

前端默认后端地址配置在 `frontend/src/api/request.js`，默认值为 `http://127.0.0.1:8080`。如需调整，可设置 `VITE_API_BASE_URL`。

## 模型与 AI 能力配置

`mock_fallback` 只用于无 API Key 或演示环境不可用时兜底跑通流程，不代表真实 AI 能力。

被测模型 provider：

```env
TARGET_MODEL_PROVIDER=mock_fallback
TARGET_MODEL_API_KEY=
TARGET_MODEL_BASE_URL=
TARGET_MODEL_NAME=
TARGET_MODEL_ENDPOINT=
TARGET_MODEL_ALLOW_FALLBACK=false
```

`openai_compatible` 调用使用 OpenAI SDK，读取 `TARGET_MODEL_API_KEY`、`TARGET_MODEL_BASE_URL`、`TARGET_MODEL_NAME`。真实 API 调试阶段建议保持 `TARGET_MODEL_ALLOW_FALLBACK=false`，失败时直接返回错误，避免静默回退。

用户模拟器 openai-compatible 配置：

```env
LLM_PROVIDER=mock
LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
```

LLM-as-a-Judge 配置：

```env
EVALUATOR_PROVIDER=mock
EVALUATOR_API_KEY=
EVALUATOR_BASE_URL=
EVALUATOR_MODEL=
EVALUATOR_TIMEOUT_SECONDS=120
EVALUATOR_MAX_TOKENS=1800
```

AI 测试用例生成配置：

```env
CASE_GENERATOR_PROVIDER=mock
CASE_GENERATOR_API_KEY=
CASE_GENERATOR_BASE_URL=
CASE_GENERATOR_MODEL=
```

未配置 API Key 或接口失败时，对应模块会自动回退到 mock 兜底。

## 演示流程

1. 打开数据大屏，查看任务、用例、评测次数、质量概览和 AI 能力模块。
2. 进入评测任务，查看飞毛腿骑手合同生效和课程直播产品升级两类脱敏外呼任务。
3. 进入测试用例，手动新增/编辑/删除用例，或选择任务后 AI 生成草稿并确认保存。
4. 进入模型配置，确认只展示 `mock_fallback`、`openai_compatible`、`custom_endpoint`，且 API Key 不明文展示。
5. 进入开始评测，先用“单条问答检测”验证某个用户问题的回答是否命中必要事实；该入口不生成正式报告。
6. 选择任务、用例和模型 provider，点击“开始评测”，查看流式多轮对话、轮次评分、规则命中情况和失败规则。
7. 点击“查看报告”，查看总分、六项指标、规则分/Judge 分/融合分、规则追溯、证据片段和优化建议。


```
