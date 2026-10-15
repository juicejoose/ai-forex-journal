import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).with_name(".env"))

client = OpenAI(timeout=30.0, max_retries=0)

response = client.responses.create(
    model=os.getenv("OPENAI_MODEL", "gpt-6-luna"),
    input="Reply with exactly: Connection successful",
    reasoning={"effort": "none"},
    max_output_tokens=64,
    store=False,
)

print(response.output_text)
print("Status:", response.status)

if response.usage:
    print("Input tokens:", response.usage.input_tokens)
    print("Output tokens:", response.usage.output_tokens)