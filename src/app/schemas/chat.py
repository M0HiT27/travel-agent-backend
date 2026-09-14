from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=2000,
        examples=["If I cancel 30 hours before departure, what fee do I pay?"],
    )
    conversation_id: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Omit to start a new conversation. Send the id returned by the previous "
            "reply to continue one, so follow-up questions keep their context."
        ),
    )


class ChatResponse(BaseModel):
    answer: str
    conversation_id: str = Field(
        description="Send this back with the next question to continue the conversation."
    )


class StreamEvent(BaseModel):
    """One server-sent event from POST /chat/stream.

    Documentation only — the endpoint writes `text/event-stream`, which FastAPI cannot
    describe with a response_model. Kept here so the contract has one written home.

    | event        | fields                       |
    |--------------|------------------------------|
    | `token`      | `delta`                      |
    | `tool_start` | `tool`, `label`              |
    | `tool_end`   | `tool`, `result` (optional)  |
    | `error`      | `status`, `detail`           |
    | `done`       | `conversation_id`, `answer`  |

    `error` has to be an event rather than an HTTP status: by the time a rate limit or
    upstream failure happens, the 200 response is already streaming.

    `result` is structured data from the tool, for the screen rather than the model:

    - `{"kind": "flights", "total_found": 129, "offers": [...]}` — cards to render
    - `{"kind": "sources", "sources": [{"file": "...pdf", "page": 1}]}` — citations
    """

    event: str
    delta: str | None = None
    tool: str | None = None
    label: str | None = None
    status: int | None = None
    detail: str | None = None
    conversation_id: str | None = None
    answer: str | None = None
    result: dict[str, Any] | None = None


class ConversationOut(BaseModel):
    """One row in a "your conversations" list."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    created_at: datetime
    last_message_at: datetime


class MessageOut(BaseModel):
    """One message, for replaying a conversation in the UI.

    Only what a person said and what the assistant replied — the agent's internal tool
    calls and retrieved chunks are left out. What the tools found is kept in structured
    form, attached to the answer that used it.
    """

    role: str = Field(description='"user" or "assistant"')
    content: str
    attachments: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Structured results shown under an answer — flight cards or cited sources, "
            "in the same shape as a stream event's `result`. Omitted when there are none."
        ),
    )


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]
