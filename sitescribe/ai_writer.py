"""POST-VISIT: AI drafts the written parts of the report.

Owner: ________
Suggested: Anthropic API (pip install anthropic), model "claude-sonnet-5-5".
Read the API key from the ANTHROPIC_API_KEY environment variable. Never put
the key in code.
"""

from __future__ import annotations

from .models import Observation, Project


def draft_summary(project: Project) -> str:
    """Write the report's summary paragraph(s) from all observations:
    overall condition, count by severity, the most important issues first."""
    raise NotImplementedError


def clean_up_description(obs: Observation) -> str:
    """Turn a rambling voice transcript into a clear, professional photo
    caption. Keep every technical fact; don't invent any."""
    raise NotImplementedError


def suggest_action_item(obs: Observation) -> str:
    """Suggest a short action item for Major/Critical/Safety observations,
    or return "" if none is needed."""
    raise NotImplementedError
