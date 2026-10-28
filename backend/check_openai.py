import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).with_name(".env"))

client = OpenAI(timeout=90.0, max_retries=0)
model = os.getenv("OPENAI_MODEL", "gpt-6.1-sol")
print("Requested model:", model)
print("Reasoning effort: medium")

response = client.responses.create(
    model=model,
    input="Reply with exactly: Connection successful",
    reasoning={"effort": "medium"},
    max_output_tokens=2048,
    service_tier="default",
    store=False,
)

print("Returned model:", response.model)
print("Status:", response.status)

if response.usage:
    print("Input tokens:", response.usage.input_tokens)
    print("Output tokens:", response.usage.output_tokens)

if response.status != "completed" or not response.output_text.strip():
    raise SystemExit("The connection check did not return a complete reply. Check the status above.")

print(response.output_text)
