import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("TARGET_MODEL_API_KEY")
base_url = os.getenv("TARGET_MODEL_BASE_URL")
model_name = os.getenv("TARGET_MODEL_NAME")

print("api_key_configured:", bool(api_key))
print("base_url:", base_url)
print("model_name:", model_name)

client = OpenAI(
    api_key=api_key,
    base_url=base_url,
    timeout=60.0,
)

response = client.chat.completions.create(
    model=model_name,
    messages=[
        {"role": "user", "content": "请只回复 OK"}
    ],
    temperature=0,
)

print(response.choices[0].message.content)