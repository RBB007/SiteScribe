"""Claude-backed drafting for site-visit observations."""
from __future__ import annotations

import base64
import json
import os

import requests


SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "observations": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"}, "description": {"type": "string"},
                    "action": {"type": "string"},
                    "severity": {"type": "string", "enum": ["Low", "Med", "High", "Critical"]},
                },
                "required": ["id", "description", "action", "severity"],
            },
        },
    },
    "required": ["summary", "observations"],
}


def draft_report(project, visit, observations, photos, api_key=None, instructions=""):
    key = (api_key or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")
    source = [{
        "id": row["id"], "item": row["number"], "description": row["description"],
        "caption": row.get("caption") or "", "action": row.get("action") or "",
        "severity": row.get("severity") or "Low", "tags": row.get("tags") or [],
        "include_in_report": row.get("include_in_report", True),
    } for row in observations]
    prompt = (
        "You are drafting a structural engineer's construction observation report. "
        "Use only the supplied field evidence. Do not invent dimensions, causes, code "
        "conclusions, responsible parties, or completed work. Preserve observation IDs. "
        "Improve clarity and professional tone. Critical must only be retained when the "
        "field record supports it. Return concise descriptions, practical actions, and a "
        "short visit summary. This is a draft requiring engineer review.\n\n"
        + ("\n\nWorkspace instructions:\n" + instructions if instructions else "")
        + "\n\nVisit data:\n"
        + json.dumps({"project": project, "visit": visit, "observations": source}, default=str)
    )
    content = [{"type": "text", "text": prompt}]
    for observation_id, path, mime_type in photos[:20]:
        if mime_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
            continue
        if path.stat().st_size > 5 * 1024 * 1024:
            continue
        content.append({"type": "text", "text": "Photo evidence for observation " + observation_id})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": mime_type,
            "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        }})
    response = requests.post(
        "https://api.anthropic.com/v1/messages", timeout=180,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={
            "model": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
            "max_tokens": 4096, "messages": [{"role": "user", "content": content}],
            "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
        },
    )
    response.raise_for_status()
    payload = response.json()
    text = next(block["text"] for block in payload["content"] if block.get("type") == "text")
    drafted = json.loads(text)
    allowed = {row["id"] for row in observations}
    drafted["observations"] = [row for row in drafted["observations"] if row["id"] in allowed]
    return drafted
