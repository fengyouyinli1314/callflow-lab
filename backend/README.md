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

应用启动时会执行 `app/seed/sample_data.py`。优先导入脱敏 Excel 指令；如果 Excel 不可用，则自动创建外呼评测 fallback：

- 飞毛腿骑手合同生效外呼评测
- 课程直播产品升级外呼评测
- 通用复杂外呼任务评测

默认 fallback 只用于外呼评测演示，不再包含旧示例业务。
