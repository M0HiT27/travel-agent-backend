from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """What the client sends to POST /chat.

    `conversation_id` is omitted to start a new conversation; passing one continues
    it, with the model seeing the full prior history.
    """

    conversation_id: int | None = None
    message: str = Field(min_length=1, max_length=4000)


class ChatMessageOut(BaseModel):
    role: str
    content: str
