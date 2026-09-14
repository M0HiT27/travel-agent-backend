"""Keep the cost of a long conversation flat.

Every request sends the whole conversation back to Gemini, so without trimming a chat
gets steadily more expensive with each turn. The bulk of that weight is not the user's
questions — it is the retrieved policy chunks and flight listings sitting in old tool
results, which are useless once their turn is answered.

So: keep the last few turns, and throw away the tool traffic from all but the newest.
Trimming only affects what is *sent* to the model. The database still holds every
message, so the UI can display the full conversation.
"""

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

# A "turn" is one user message plus everything the agent did in response to it.
KEEP_TURNS = 4


def group_into_turns(messages: list[AnyMessage]) -> list[list[AnyMessage]]:
    """Split a flat message list into turns, each starting with a user message."""
    turns: list[list[AnyMessage]] = []
    current: list[AnyMessage] = []

    for message in messages:
        if isinstance(message, HumanMessage) and current:
            turns.append(current)
            current = []
        current.append(message)

    if current:
        turns.append(current)
    return turns


def _is_tool_traffic(message: AnyMessage) -> bool:
    """True for a tool result, or for the assistant message that requested one.

    These two always travel together: dropping a tool result while keeping the message
    that asked for it leaves an unanswered tool call, which the model rejects.
    """
    if isinstance(message, ToolMessage):
        return True
    return isinstance(message, AIMessage) and bool(message.tool_calls)


def trim_history(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Return the messages worth sending to the model.

    The newest turn is kept whole — it holds the tool call currently in flight. Older
    turns keep only their conversational text, which is what a follow-up question like
    "what about 20 hours?" actually needs.
    """
    turns = group_into_turns(messages)
    recent_turns = turns[-KEEP_TURNS:]

    trimmed: list[AnyMessage] = []
    for index, turn in enumerate(recent_turns):
        is_newest = index == len(recent_turns) - 1
        if is_newest:
            trimmed.extend(turn)
        else:
            trimmed.extend(m for m in turn if not _is_tool_traffic(m))

    return trimmed
