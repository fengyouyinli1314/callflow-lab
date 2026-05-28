import json

from app.services.instruction_parser import parse_instruction


def test_parse_instruction_extracts_sections_constraints_and_steps():
    text = """# Role: Customer Support Specialist for Course Publishing Platform

## Task:
告知机构客户，课程发布页面将新增“标准直播”和“低延迟直播”两个独立选项。

# Opening Line:
您好，请问您是贵培训机构/校区的负责人吗？

# Conversation Flow:
## Step 1: 身份确认
若是负责人 -> 进入第2步。

## Step 2: 确认是否知情
询问客户是否知道低延迟直播。

## Step 3: 传达升级内容
说明发布页新增独立低延迟直播选项。
### 3.1 区别
标准直播费用较低，低延迟互动更流畅。

# Knowledge Points:
标准直播延迟 5-10 秒，低延迟直播延迟 1-2 秒。

# Constraints:
- 每次回复极简——最多15-20个字
- 使用简短、自然的口语化表达
"""

    result = parse_instruction(text)

    assert result["role_text"] == "Customer Support Specialist for Course Publishing Platform"
    assert "两个独立选项" in result["task_text"]
    assert result["opening_line"] == "您好，请问您是贵培训机构/校区的负责人吗？"
    assert result["constraints"] == ["每次回复极简——最多15-20个字", "使用简短、自然的口语化表达"]
    assert len(result["steps"]) == 3
    assert result["steps"][0]["step_no"] == "1"
    assert result["steps"][0]["title"] == "身份确认"
    assert result["steps"][2]["sub_steps"][0]["sub_step_no"] == "3.1"
    assert "低延迟互动更流畅" in result["steps"][2]["sub_steps"][0]["content"]


def test_task_detail_returns_conversation_flow_alias_and_steps(client):
    tasks = client.get("/api/tasks").json()
    task = next(item for item in tasks if item["task_type"] == "course_platform_outbound")

    detail = client.get(f"/api/tasks/{task['id']}").json()

    assert "instruction_text" in detail
    assert "conversation_flow" in detail
    assert detail["conversation_flow"] == detail["call_flow"]
    assert "steps" in detail
    parsed_steps = json.loads(detail["steps"] or "[]")
    assert isinstance(parsed_steps, list)
    assert [step.get("step_no") for step in parsed_steps] == ["1", "2", "3", "4", "5", "6", "7"]
    assert json.loads(detail["constraints"] or "[]")
    assert detail["instruction_text"]


def test_parse_instruction_supports_chinese_headings_and_numbered_steps():
    text = """# 角色:
外呼专员

# 任务:
告知骑手飞毛腿合同已生效。

# 约束:
- 约30字以内
- 不强迫恶劣天气配送

# 开场白:
您好，是骑手本人吗？

# 对话流程:
1. 告知骑手今天飞毛腿合同已生效，并询问是否可以开始配送。
2. 说明单日 X 单、多日每天 Y 单。
3. 提醒注意安全。

# 参考知识:
报名按系统排名，不是站长人工干预。
"""

    result = parse_instruction(text)

    assert result["role_text"] == "外呼专员"
    assert "飞毛腿合同已生效" in result["task_text"]
    assert result["opening_line"] == "您好，是骑手本人吗？"
    assert result["constraints"] == ["约30字以内", "不强迫恶劣天气配送"]
    assert "系统排名" in result["knowledge_points"]
    assert [step["step_no"] for step in result["steps"]] == ["1", "2", "3"]
    assert "可以开始配送" in result["steps"][0]["content"]


def test_excel_rider_instruction_gets_numbered_steps_and_policy(client):
    tasks = client.get("/api/tasks").json()
    task = next(item for item in tasks if item["task_type"] == "rider_outbound")

    detail = client.get(f"/api/tasks/{task['id']}").json()

    assert detail["role_text"]
    assert detail["task_text"]
    assert detail["opening_line"]
    assert json.loads(detail["constraints"] or "[]")
    assert json.loads(detail["steps"] or "[]")
    assert json.loads(detail["executable_policy"] or "{}")["reply_rules"]["max_chars_per_reply"] == 30


def test_task_detail_accepts_task_name_for_legacy_frontend_links(client):
    tasks = client.get("/api/tasks").json()
    task = next(item for item in tasks if item["task_type"] == "rider_outbound")

    detail = client.get(f"/api/tasks/{task['name']}").json()

    assert detail["id"] == task["id"]
    assert detail["name"] == task["name"]
    assert detail["role_text"]


def test_task_detail_accepts_legacy_task_name_with_id_suffix(client):
    tasks = client.get("/api/tasks").json()
    task = next(item for item in tasks if item["task_type"] == "course_platform_outbound")

    detail = client.get(f"/api/tasks/{task['name']}id").json()

    assert detail["id"] == task["id"]
    assert detail["name"] == task["name"]
    assert detail["executable_policy"]


def test_task_detail_accepts_short_legacy_course_alias_with_id_suffix(client):
    tasks = client.get("/api/tasks").json()
    task = next(item for item in tasks if item["task_type"] == "course_platform_outbound")

    detail = client.get("/api/tasks/课程直播任务id").json()

    assert detail["id"] == task["id"]
    assert detail["task_type"] == "course_platform_outbound"
    assert detail["steps"]
