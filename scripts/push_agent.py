#!/usr/bin/env python3
"""Push the allo agent config to ElevenLabs.

Everything is authored in the repo and provisioned idempotently:

    agent/agent.json          the agent config, with {{placeholders}}
    agent/prompts/*.md        the system prompt, kept as markdown on purpose
    agent/tools/*.json        the six webhook tools
    agent/deploy.json         non-secret deployment values (urls, voice ids, numbers)
    agent/state.json          ids returned by ElevenLabs (written by this script)

Placeholders filled here:
    {{WORKER_URL}} {{SECRET_ID}} {{KB_DOCUMENT_ID}} {{KB_DOCUMENT_NAME}}
    {{VOICE_FR}} {{VOICE_EN}} {{TRANSFER_NUMBER}} {{POST_CALL_WEBHOOK_ID}}
    {{TOOL_ID:<name>}} {{SYSTEM_PROMPT}}

The tools shared secret is read from pass and uploaded to ElevenLabs as a stored
workspace secret; it never appears in any repo file. The workspace secret **id** is
resolved by name on every run and deliberately NOT persisted to `state.json` — a
32-character id under a "secret_id" key trips gitleaks' generic-api-key rule.

Usage:
    uv run python scripts/push_agent.py --dry-run
    uv run python scripts/push_agent.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from allo_common import (  # noqa: E402
    ROOT,
    Api,
    api_key,
    load_json,
    pass_insert,
    pass_show,
    save_json,
)

AGENT_DIR = ROOT / "agent"
STATE_PATH = AGENT_DIR / "state.json"


# --------------------------------------------------------------------------- #
# placeholder machinery
# --------------------------------------------------------------------------- #


def substitute(node: Any, values: dict[str, str]) -> Any:
    """Replace {{KEY}} in every string, recursively."""
    if isinstance(node, str):
        out = node
        for key, val in values.items():
            out = out.replace("{{" + key + "}}", val)
        return out
    if isinstance(node, dict):
        return {k: substitute(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [substitute(v, values) for v in node]
    return node


def find_unresolved(node: Any, path: str = "") -> list[str]:
    """Any {{...}} left after substitution is a bug — report it loudly."""
    found: list[str] = []
    if isinstance(node, str):
        i = node.find("{{")
        while i != -1:
            j = node.find("}}", i)
            found.append(f"{path}: {node[i:j + 2]}")
            i = node.find("{{", j)
    elif isinstance(node, dict):
        for k, v in node.items():
            found += find_unresolved(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for n, v in enumerate(node):
            found += find_unresolved(v, f"{path}[{n}]")
    return found


# --------------------------------------------------------------------------- #
# provisioning steps
# --------------------------------------------------------------------------- #


def ensure_workspace_secret(api: Api, name: str, value: str) -> str:
    """Create the stored workspace secret if absent; return its id."""
    existing = api.request("GET", "/v1/convai/secrets") or {}
    secrets = existing.get("secrets") or existing.get("data") or []
    for s in secrets:
        if s.get("name") == name:
            print(f"  workspace secret '{name}' already exists ({s.get('secret_id')})")
            return s["secret_id"]

    if api.dry_run:
        print(f"  [dry-run] would create workspace secret '{name}'")
        return "SECDISABLED"

    resp = api.request(
        "POST",
        "/v1/convai/secrets",
        json={"type": "new", "name": name, "value": value},
        expect=(200, 201),
    )
    print(f"  created workspace secret '{name}' ({resp['secret_id']})")
    return resp["secret_id"]


def ensure_knowledge_base(api: Api, file: Path, doc_name: str) -> str:
    """Upload the FAQ document, or refresh it in place if it already exists."""
    listing = api.request("GET", "/v1/convai/knowledge-base", params={"page_size": 100}) or {}
    docs = listing.get("documents") or []
    existing = next((d for d in docs if d.get("name") == doc_name), None)

    if api.dry_run:
        what = "update" if existing else "upload"
        print(f"  [dry-run] would {what} knowledge base document '{doc_name}'")
        return existing.get("id", "KBDISABLED") if existing else "KBDISABLED"

    if existing:
        doc_id = existing["id"]
        print(f"  reusing knowledge base document '{doc_name}' ({doc_id})")
    else:
        with file.open("rb") as fh:
            resp = api.request(
                "POST",
                "/v1/convai/knowledge-base/file",
                data={"name": doc_name},
                files={"file": (file.name, fh, "text/markdown")},
                expect=(200, 201),
            )
        doc_id = resp["id"]
        print(f"  uploaded knowledge base document '{doc_name}' ({doc_id})")

    # The upload endpoint sometimes keeps the filename instead of the name we
    # asked for, and re-uploading would leave a stale duplicate behind. Setting
    # both name and content explicitly makes the push idempotent and exact.
    api.request(
        "PATCH",
        f"/v1/convai/knowledge-base/{doc_id}",
        json={"name": doc_name, "content": file.read_text(encoding="utf-8")},
        expect=(200, 204),
    )
    print("  name and content set to match the repo")

    # RAG needs an index for the document to be retrievable.
    try:
        api.request(
            "POST",
            f"/v1/convai/knowledge-base/{doc_id}/rag-index",
            json={"model": "e5_mistral_7b_instruct"},
            expect=(200, 201),
        )
        print("  RAG index requested")
    except RuntimeError as e:
        print(f"  RAG index request returned: {e}")

    return doc_id


def ensure_tool(api: Api, tool_dir: Path, secret_id: str, worker_url: str) -> tuple[str, str]:
    """Create or update one webhook tool. Returns (name, tool_id)."""
    cfg = load_json(tool_dir)
    cfg = substitute(cfg, {"SECRET_ID": secret_id, "WORKER_URL": worker_url})
    name = cfg["name"]

    listing = api.request("GET", "/v1/convai/tools", params={"page_size": 100}) or {}
    tools = listing.get("tools") or []
    existing = next(
        (t for t in tools if (t.get("tool_config") or {}).get("name") == name), None
    )

    if api.dry_run:
        print(f"  [dry-run] would {'update' if existing else 'create'} tool '{name}'")
        return name, existing.get("id", "TOOLDISABLED") if existing else "TOOLDISABLED"

    body = {"tool_config": cfg}
    if existing:
        resp = api.request(
            "PATCH", f"/v1/convai/tools/{existing['id']}", json=body, expect=(200,)
        )
        tool_id = existing["id"]
        print(f"  updated tool '{name}' ({tool_id})")
    else:
        resp = api.request("POST", "/v1/convai/tools", json=body, expect=(200, 201))
        tool_id = resp["id"]
        print(f"  created tool '{name}' ({tool_id})")
    return name, tool_id


def ensure_post_call_webhook(api: Api, name: str, url: str) -> tuple[str | None, str | None]:
    """Create the HMAC post-call webhook. Returns (webhook_id, webhook_secret)."""
    listing = api.request("GET", "/v1/workspace/webhooks") or {}
    hooks = listing if isinstance(listing, list) else listing.get("webhooks") or []
    existing = next((h for h in hooks if h.get("name") == name), None)

    if api.dry_run:
        print(f"  [dry-run] would {'reuse' if existing else 'create'} webhook '{name}' -> {url}")
        return (existing or {}).get("webhook_id"), None

    if existing:
        print(f"  post-call webhook '{name}' already exists ({existing['webhook_id']})")
        return existing["webhook_id"], None

    resp = api.request(
        "POST",
        "/v1/workspace/webhooks",
        json={
            "settings": {
                "auth_type": "hmac",
                "name": name,
                "webhook_url": url,
            }
        },
        expect=(200, 201),
    )
    print(f"  created post-call webhook '{name}' ({resp['webhook_id']})")
    return resp["webhook_id"], resp.get("webhook_secret")


def find_agent_by_name(api: Api, name: str) -> dict | None:
    listing = api.request("GET", "/v1/convai/agents", params={"page_size": 100}) or {}
    agents = listing.get("agents") or []
    for a in agents:
        if a.get("name") == name:
            return a
    return None


# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="validate and print, send nothing")
    ap.add_argument(
        "--rotate-tools-secret",
        action="store_true",
        help="generate a new tools secret, store it in pass, and recreate the workspace secret",
    )
    args = ap.parse_args()

    deploy = load_json(AGENT_DIR / "deploy.json")
    worker_url = deploy["worker_url"]
    state = load_json(STATE_PATH) if STATE_PATH.exists() else {}

    # --- the shared tools secret (never printed, never written to the repo) ---
    entry = deploy["secrets"]["tools_pass_entry"]
    if args.rotate_tools_secret:
        import secrets as _s

        value = _s.token_hex(32)
        pass_insert(entry, value)
        print(f"rotated the tools secret in pass ({entry})")
        state.pop("secret_id", None)  # legacy key: the id is never persisted
    else:
        value = pass_show(entry)

    api = Api(api_key(), dry_run=args.dry_run)

    print("1. workspace secret")
    # Resolved by name every run: existing id reused, new one created if absent.
    # Kept in memory only, so no secret id ever lands in a committed file.
    secret_id = ensure_workspace_secret(
        api, deploy["secrets"]["tools_workspace_secret_name"], value
    )

    print("2. knowledge base")
    kb = deploy["kb"]
    kb_id = ensure_knowledge_base(api, ROOT / kb["file"], kb["name"])
    state["kb_document_id"] = kb_id
    state["kb_document_name"] = kb["name"]

    print("3. webhook tools")
    tool_ids: dict[str, str] = {}
    for tool_file in sorted((AGENT_DIR / "tools").glob("*.json")):
        name, tool_id = ensure_tool(api, tool_file, secret_id, worker_url)
        tool_ids[name] = tool_id
    state["tool_ids"] = tool_ids

    print("4. post-call webhook")
    hook = deploy["post_call_webhook"]
    webhook_id, webhook_secret = ensure_post_call_webhook(
        api, hook["name"], worker_url + hook["url_suffix"]
    )
    state["post_call_webhook_id"] = webhook_id
    if webhook_secret:
        pass_insert(deploy["secrets"]["webhook_pass_entry"], webhook_secret)
        print(
            f"  stored the webhook signing secret in pass "
            f"({deploy['secrets']['webhook_pass_entry']}) — "
            f"set it on the Worker with: wrangler secret put ELEVENLABS_WEBHOOK_SECRET"
        )

    print("5. agent")
    values = {
        "WORKER_URL": worker_url,
        "SECRET_ID": secret_id or "",
        "KB_DOCUMENT_ID": state["kb_document_id"],
        "KB_DOCUMENT_NAME": state["kb_document_name"],
        "VOICE_FR": deploy["voices"]["fr"],
        "VOICE_EN": deploy["voices"]["en"],
        "TRANSFER_NUMBER": deploy["transfer_number"],
        "POST_CALL_WEBHOOK_ID": webhook_id or "",
        "SYSTEM_PROMPT": (AGENT_DIR / "prompts" / "system_prompt.md").read_text(
            encoding="utf-8"
        ),
    }
    for name, tool_id in tool_ids.items():
        values[f"TOOL_ID:{name}"] = tool_id

    blueprint = load_json(AGENT_DIR / "agent.json")
    blueprint.pop("_comment", None)
    payload = substitute(blueprint, values)

    unresolved = find_unresolved(payload)
    if unresolved:
        print("\nUNRESOLVED PLACEHOLDERS — refusing to push:")
        for u in unresolved:
            print("   ", u)
        return 2

    existing = find_agent_by_name(api, payload["name"])
    body = {
        "name": payload["name"],
        "tags": payload.get("tags"),
        "conversation_config": payload["conversation_config"],
        "platform_settings": payload.get("platform_settings"),
    }
    if api.dry_run:
        print(f"  [dry-run] would {'update' if existing else 'create'} agent '{payload['name']}'")
        print(f"  payload bytes: {len(json.dumps(body))}")
        return 0

    if existing:
        agent_id = existing["agent_id"]
        api.request("PATCH", f"/v1/convai/agents/{agent_id}", json=body, expect=(200,))
        print(f"  updated agent '{payload['name']}' ({agent_id})")
    else:
        resp = api.request("POST", "/v1/convai/agents/create", json=body, expect=(200, 201))
        agent_id = resp["agent_id"]
        print(f"  created agent '{payload['name']}' ({agent_id})")

    state["agent_id"] = agent_id
    state["agent_name"] = payload["name"]
    state["llm"] = payload["conversation_config"]["agent"]["prompt"]["llm"]
    state["tts_model"] = payload["conversation_config"]["tts"]["model_id"]
    save_json(STATE_PATH, state)
    print(f"\nwrote {STATE_PATH}")
    print(f"agent_id = {agent_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
