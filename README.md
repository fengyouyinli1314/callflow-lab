# callflow-lab

callflow-lab 是面向复杂指令下多轮对话场景的评测系统，适用于客服、人工外呼、业务助手等场景的自动化评测演示。系统通过任务配置、测试用例、用户模拟器、被测模型模拟器、规则评分、模型评分和可解释报告，完成“任务列表 → 用例选择 → 开始评测 → 多轮对话 → 自动评分 → 查看报告”的闭环。

## 核心功能

- 评测任务管理：维护目标场景、复杂系统指令和评测目标。
- 测试用例管理：配置用户画像、初始问题、最大轮数、期望目标、必须规则和禁止规则。
- 用户模拟器：支持普通用户、情绪激动用户、反复追问用户、信息缺失用户、需求变更用户。
- 自动多轮评测：自动生成用户发言、调用被测模型 mock、保存每轮对话、记录响应时间。
- 双评分机制：规则评分与模型评分接口并行预留，默认使用 mock，保证离线演示稳定。
- 可解释报告：输出总分、五项指标、失败规则、失败案例、证据轮次、对话片段和优化建议。
- 数据大屏：展示评测次数、平均分、平均响应时间、失败规则 TOP5 和最近得分趋势。

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

系统启动时会自动初始化演示数据，默认至少包含 3 个评测任务和 9 个测试用例。

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

## 真实模型接口预留

默认使用 mock 模式，无需外部模型服务即可完成比赛演示。需要接入 OpenAI compatible API 时，在 `backend/.env` 中配置：

```env
LLM_PROVIDER=openai_compatible
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://your-model-endpoint/v1
LLM_MODEL=your-model-name
```

如果未配置 API Key 或接口调用失败，系统会自动回退到 mock 模式。

## 演示流程

1. 打开数据大屏，查看任务、用例、评测次数和质量概览。
2. 进入评测任务，查看外卖退款、酒店订单变更、团购券核销三类任务。
3. 进入测试用例，筛选任务对应的用户画像和规则约束。
4. 进入开始评测，选择任务与用例，点击“开始评测”。
5. 查看多轮对话、轮次评分、规则命中情况和失败规则。
6. 点击“查看报告”，查看总分、雷达图、指标解释、失败案例、证据片段和优化建议。

## 常用示例请求

```bash
curl http://127.0.0.1:8080/api/tasks
curl "http://127.0.0.1:8080/api/cases?task_id=1"
curl -X POST http://127.0.0.1:8080/api/runs/start -H "Content-Type: application/json" -d "{\"task_id\":1,\"case_id\":1}"
curl http://127.0.0.1:8080/api/dashboard/summary
```
