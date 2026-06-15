import os

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql://sandbox:sandbox123@localhost:5432/agent_sandbox",
)

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://10.0.0.224:11434/v1")

OPENCODE_IMAGE: str = os.getenv("OPENCODE_IMAGE", "opencode-sandbox:latest")

# Timeout (seconds) waiting for pod Running + OpenCode /global/health
POD_READY_TIMEOUT: int = int(os.getenv("POD_READY_TIMEOUT", "120"))
HEALTH_CHECK_TIMEOUT: int = int(os.getenv("HEALTH_CHECK_TIMEOUT", "60"))

# opencode.json config template injected into each session ConfigMap.
# The OLLAMA_BASE_URL is substituted at session creation time.
OPENCODE_CONFIG_TEMPLATE = """\
{{
  "$schema": "https://opencode.ai/config.json",
  "model": "ollama/qwen2.5:1.5b",
  "provider": {{
    "ollama": {{
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama",
      "options": {{ "baseURL": "{ollama_base_url}" }},
      "models": {{ "qwen2.5:1.5b": {{ "name": "Qwen 3 8B" }} }}
    }}
  }},
  "agent": {{
    "storyteller": {{
      "description": "Expert storytelling AI",
      "model": "ollama/qwen2.5:1.5b",
      "system": "You are a master storyteller. Craft vivid, engaging narratives with compelling characters, rich world-building, and satisfying story arcs. Adapt your style to match the user request — epic fantasy, dark thriller, sci-fi, children's tale — and always write in flowing prose, never bullet points."
    }}
  }}
}}"""


def get_opencode_config() -> str:
    return OPENCODE_CONFIG_TEMPLATE.format(ollama_base_url=OLLAMA_BASE_URL)
