import os

DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql://sandbox:sandbox123@localhost:5432/agent_sandbox",
)

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://10.0.0.224:11434/v1")

OPENCODE_IMAGE: str = os.getenv("OPENCODE_IMAGE", "opencode-sandbox:latest")

# Namespace where Sandbox CRs (and their pods/services) live
SANDBOX_NAMESPACE: str = os.getenv("SANDBOX_NAMESPACE", "agent-sandbox")

# Name of the SandboxWarmPool to claim from
SANDBOX_WARM_POOL: str = os.getenv("SANDBOX_WARM_POOL", "opencode-warmpool")

# Seconds to wait for a Sandbox to reach Ready condition
SANDBOX_READY_TIMEOUT: int = int(os.getenv("SANDBOX_READY_TIMEOUT", "120"))

# opencode.json embedded in the shared ConfigMap (SandboxTemplate mounts it)
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "nemotron-3-nano:4b")

OPENCODE_CONFIG_TEMPLATE = """\
{{
  "$schema": "https://opencode.ai/config.json",
  "model": "ollama/{ollama_model}",
  "provider": {{
    "ollama": {{
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ollama",
      "options": {{ "baseURL": "{ollama_base_url}" }},
      "models": {{ "{ollama_model}": {{ "name": "{ollama_model}" }} }}
    }}
  }},
  "agent": {{
    "storyteller": {{
      "description": "Coding and storytelling assistant with filesystem access",
      "model": "ollama/{ollama_model}",
      "tools": {{ "bash": true, "read": true, "write": true, "edit": true }},
      "system": "You are a helpful assistant with full access to the /workspace directory. Rules you must follow without exception:\\n1. NEVER show your reasoning or thought process. Respond only with your final answer.\\n2. NEVER ask for clarification if you can attempt the task with tools first. Try the tool, then report what you found.\\n3. When given a filename, immediately use the read tool to read it. Do not ask what to do with it.\\n4. When asked about directory contents, immediately run bash 'ls -la /workspace' or 'find'. Do not say you lack filesystem access — you have it.\\n5. Keep responses short and direct. No preamble, no narration."
    }}
  }}
}}"""


def get_opencode_config() -> str:
    return OPENCODE_CONFIG_TEMPLATE.format(ollama_base_url=OLLAMA_BASE_URL, ollama_model=OLLAMA_MODEL)
