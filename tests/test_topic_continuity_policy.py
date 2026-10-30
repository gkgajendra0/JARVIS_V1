import pytest

from jarvis.conversation import ConversationRole, ConversationTurn


@pytest.mark.parametrize(
    "text, allowed",
    [
        ("I am thinking to go on a Nepal trip.", True),
        ("My vehicle is a Jimny.", True),
        ("Budget ka issue nahi hai", True),
        ("My passport number is AB1234567", False),
        ("My medical diagnosis is diabetes", False),
        ("My bank account number is 123456789", False),
        ("My friend's private travel address is somewhere", False),
        ("My password is hunter2", False),
        ("Do not remember my Nepal trip", False),
        ("Don't save my vehicle", False),
        ("Forget Nepal trip", True),
    ],
)
def test_continuity_source_has_no_exact_script_gate_but_rejects_restricted_data(
    text, allowed
):
    from jarvis.memory.topic_continuity_policy import standard_plan_source

    assert (
        standard_plan_source(ConversationTurn(ConversationRole.USER, text)) is allowed
    )
