#!/usr/bin/env python3
"""Print the live agent config from the API — the "does it actually exist" check.

Reads agent/state.json for the agent id and prints agent_id, language settings,
voice ids, LLM, tool names, knowledge base, language presets, data collection and
evaluation criteria.

Usage: uv run python scripts/show_agent.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from allo_common import ROOT, Api, api_key, load_json  # noqa: E402


def main() -> int:
    state = load_json(ROOT / "agent" / "state.json")
    agent_id = state["agent_id"]
    agent = Api(api_key()).request("GET", f"/v1/convai/agents/{agent_id}")

    cc = agent["conversation_config"]
    prompt = cc["agent"]["prompt"]
    ps = agent.get("platform_settings") or {}
    presets = cc.get("language_presets") or {}
    en = (presets.get("en") or {}).get("overrides") or {}

    print(f"agent_id          : {agent.get('agent_id')}")
    print(f"name              : {agent.get('name')}")
    print(f"tags              : {agent.get('tags')}")
    print()
    print("--- language ---")
    print(f"default language  : {cc['agent'].get('language')}")
    print(f"first message     : {cc['agent'].get('first_message')}")
    print(f"language presets  : {list(presets.keys())}")
    print(f"  preset 'en' llm/lang : {(en.get('agent') or {}).get('language')}")
    print(
        "  language_detection   : "
        f"{json.dumps((prompt.get('built_in_tools') or {}).get('language_detection', {}))}"
    )
    print()
    print("--- voices ---")
    print(f"primary (fr) voice_id : {cc['tts'].get('voice_id')}")
    print(f"preset 'en' voice_id  : {(en.get('tts') or {}).get('voice_id')}")
    print(f"tts model_id          : {cc['tts'].get('model_id')}")
    print()
    print("--- brain ---")
    print(f"llm                   : {prompt.get('llm')}")
    print(f"analysis_llm          : {ps.get('analysis_llm')}")
    print(f"temperature           : {prompt.get('temperature')}")
    print(f"parallel tool calls   : {prompt.get('enable_parallel_tool_calls')}")
    print(f"system prompt chars   : {len(prompt.get('prompt') or '')}")
    print()
    print("--- tools ---")
    webhook_tools = [t.get("name") for t in (prompt.get("tools") or []) if t.get("type") == "webhook"]
    builtins = sorted((prompt.get("built_in_tools") or {}).keys())
    print(f"webhook tools         : {webhook_tools}")
    print(f"built-in tools        : {builtins}")
    print()
    print("--- knowledge base ---")
    for kb in prompt.get("knowledge_base") or []:
        print(f"  {kb.get('name')}  id={kb.get('id')}  usage_mode={kb.get('usage_mode')}")
    print(f"rag enabled           : {(prompt.get('rag') or {}).get('enabled')}")
    print()
    print("--- platform ---")
    print(f"data collection       : {list((ps.get('data_collection') or {}).keys())}")
    print(f"eval criteria         : {[c.get('id') for c in ((ps.get('evaluation') or {}).get('criteria') or [])]}")
    print(
        "post-call webhook     : "
        f"{((ps.get('workspace_overrides') or {}).get('webhooks') or {}).get('post_call_webhook_id')}"
    )
    print(f"prompt-injection guard: {(ps.get('guardrails') or {}).get('prompt_injection', {}).get('is_enabled')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
