"""Version-pinned report provenance; never infer old records from current settings."""

import json
from typing import Literal, cast

ResearchMode = Literal["synthetic", "live", "unknown"]
MODE_NOTICES = {
    "synthetic": "Synthetic research: invented data. Not real financial evidence or investment advice.",
    "live": "Live-source research: provider observations, not a guarantee of accuracy or investment advice.",
    "unknown": "Unknown research mode: provenance was not recorded. Do not assume this is live or verified data.",
}


def saved_mode(configuration) -> ResearchMode:
    if isinstance(configuration, str):
        try:
            configuration = json.loads(configuration)
        except ValueError:
            return "unknown"
    value = configuration.get("research_mode") if isinstance(configuration, dict) else None
    return (
        cast(ResearchMode, value) if isinstance(value, str) and value in MODE_NOTICES else "unknown"
    )
