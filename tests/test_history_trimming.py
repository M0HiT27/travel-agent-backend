"""Tests for the sliding window over conversation history.

The rule being enforced: keep the last few turns, but carry the bulky tool traffic only
for the newest turn — and never leave a tool call without its result, which the model
would reject.
"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.ai.history import KEEP_TURNS, group_into_turns, trim_history


def build_turn(question: str, answer: str, *, with_tool: bool = True) -> list:
    """One complete turn: the question, an optional tool round-trip, then the answer."""
    messages = [HumanMessage(content=question)]
    if with_tool:
        messages.append(
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_travel_policies", "args": {"question": question}, "id": f"call_{question[:5]}"}
                ],
            )
        )
        messages.append(
            ToolMessage(content="A" * 3000, tool_call_id=f"call_{question[:5]}")
        )
    messages.append(AIMessage(content=answer))
    return messages


def build_conversation(turn_count: int) -> list:
    messages = []
    for i in range(turn_count):
        messages.extend(build_turn(f"question {i}", f"answer {i}"))
    return messages


class TestGroupIntoTurns:
    def test_each_turn_starts_with_a_user_message(self):
        turns = group_into_turns(build_conversation(3))

        assert len(turns) == 3
        assert all(isinstance(turn[0], HumanMessage) for turn in turns)

    def test_empty_conversation_has_no_turns(self):
        assert group_into_turns([]) == []

    def test_an_unanswered_question_is_still_a_turn(self):
        messages = [*build_turn("first", "answer"), HumanMessage(content="second")]

        turns = group_into_turns(messages)

        assert len(turns) == 2
        assert turns[1][0].content == "second"


class TestTrimHistory:
    def test_short_conversation_keeps_every_turn(self):
        """Nothing is dropped from a conversation shorter than the window."""
        messages = build_conversation(2)

        questions = [m.content for m in trim_history(messages) if isinstance(m, HumanMessage)]

        assert questions == ["question 0", "question 1"]

    def test_even_a_short_conversation_sheds_stale_tool_results(self):
        """The window is not the only saving: old chunks go as soon as their turn is
        no longer the newest, because they cannot help answer the next question."""
        messages = build_conversation(2)

        trimmed = trim_history(messages)

        assert sum(isinstance(m, ToolMessage) for m in trimmed) == 1

    def test_only_recent_turns_survive(self):
        messages = build_conversation(KEEP_TURNS + 3)

        trimmed = trim_history(messages)

        questions = [m.content for m in trimmed if isinstance(m, HumanMessage)]
        assert len(questions) == KEEP_TURNS
        assert "question 0" not in questions, "oldest turns must be dropped"
        assert f"question {KEEP_TURNS + 2}" in questions, "newest turn must be kept"

    def test_only_the_newest_turn_keeps_its_tool_traffic(self):
        messages = build_conversation(KEEP_TURNS + 1)

        trimmed = trim_history(messages)

        # One tool result survives: the newest. The rest were the bulk of the tokens.
        assert sum(isinstance(m, ToolMessage) for m in trimmed) == 1

    def test_older_turns_keep_their_text_answers(self):
        """Dropping tool traffic must not drop the conversation itself."""
        messages = build_conversation(KEEP_TURNS + 1)

        trimmed = trim_history(messages)
        answers = [
            m.content for m in trimmed if isinstance(m, AIMessage) and m.content
        ]

        assert len(answers) == KEEP_TURNS, "each kept turn should still have its answer"

    def test_no_tool_call_is_left_without_its_result(self):
        """An unanswered tool call is rejected by the model, so the pair must move together."""
        messages = build_conversation(KEEP_TURNS + 2)

        trimmed = trim_history(messages)

        requested_ids = {
            call["id"]
            for m in trimmed
            if isinstance(m, AIMessage)
            for call in (m.tool_calls or [])
        }
        answered_ids = {m.tool_call_id for m in trimmed if isinstance(m, ToolMessage)}
        assert requested_ids == answered_ids

    def test_trimming_actually_reduces_size(self):
        messages = build_conversation(KEEP_TURNS + 4)

        before = sum(len(str(m.content)) for m in messages)
        after = sum(len(str(m.content)) for m in trim_history(messages))

        assert after < before / 2, "the whole point is keeping cost flat"

    def test_turns_without_tools_are_handled(self):
        """Not every question needs a tool — plain chat must survive trimming."""
        messages = []
        for i in range(KEEP_TURNS + 2):
            messages.extend(build_turn(f"hi {i}", f"hello {i}", with_tool=False))

        trimmed = trim_history(messages)

        questions = [m.content for m in trimmed if isinstance(m, HumanMessage)]
        assert len(questions) == KEEP_TURNS
