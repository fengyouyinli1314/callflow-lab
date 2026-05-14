# callflow-lab backend

后端提供评测任务、测试用例、自动评测执行、对话记录、可解释报告和数据大屏接口。默认使用 SQLite 数据库和 mock 模型能力，便于本地快速演示。

## 启动

```powershell
conda activate callflow-lab
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
```

## 接口文档

启动后访问：

```text
http://127.0.0.1:8080/docs
```

## 数据初始化

应用启动时会执行 `app/seed/sample_data.py`，当数据库中没有任务时自动创建：

- 外卖退款客服流程评测
- 酒店预订变更流程评测
- 到店团购券核销流程评测

每个任务包含 3 个可直接演示的测试用例。
