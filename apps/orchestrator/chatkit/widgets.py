from __future__ import annotations

from pathlib import Path
from typing import List

from chatkit.widgets import WidgetTemplate

from apps.orchestrator.runtime.models import Interrupt


APPROVE_ACTION = "interrupt.approve"
REJECT_ACTION = "interrupt.reject"
SUBMIT_ACTION = "interrupt.submit"
CANCEL_ACTION = "interrupt.cancel"

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
APPROVAL_TEMPLATE = WidgetTemplate.from_file(str(TEMPLATE_DIR / "approval.widget"))
INTERACTION_TEMPLATE = WidgetTemplate.from_file(str(TEMPLATE_DIR / "interaction.widget"))


def approval_widget(interrupt: Interrupt, run_id: str):
    return APPROVAL_TEMPLATE.build(
        {
            "prompt": interrupt.prompt or "Approval required.",
            "run_id": run_id,
            "interrupt_id": interrupt.id,
        }
    )


def interaction_widget(interrupt: Interrupt, run_id: str):
    schema = interrupt.input_schema or {}
    properties = schema.get("properties") if isinstance(schema, dict) else None
    fields: List[str] = list(properties.keys()) if isinstance(properties, dict) and properties else ["response"]

    instructions = interrupt.prompt or "Provide the requested input."
    if interrupt.allow_file_upload:
        instructions += "\nYou can attach files using the chat upload control before submitting."

    return INTERACTION_TEMPLATE.build(
        {
            "instructions": instructions,
            "run_id": run_id,
            "interrupt_id": interrupt.id,
            "fields": fields,
        }
    )
