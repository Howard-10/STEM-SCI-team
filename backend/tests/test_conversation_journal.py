import pytest

from stem_sci.orchestration import ConversationCommandJournal


def test_command_journal_replays_completed_turn(tmp_path) -> None:
    journal = ConversationCommandJournal(tmp_path / "research-dialogue.db")

    first, created = journal.begin("project-a", "client-1", "owner", "开始检索", "hash-1")
    assert created
    journal.update(
        "project-a",
        first["turn_id"],
        status="completed",
        response={"kind": "orchestration", "message": "已开始"},
    )

    replay, replay_created = journal.begin("project-a", "client-1", "owner", "开始检索", "hash-1")
    assert not replay_created
    assert replay["response"]["message"] == "已开始"


def test_command_journal_rejects_reused_turn_id_with_different_request(tmp_path) -> None:
    journal = ConversationCommandJournal(tmp_path / "research-dialogue.db")
    journal.begin("project-a", "client-1", "owner", "开始检索", "hash-1")

    with pytest.raises(ValueError, match="同一消息编号"):
        journal.begin("project-a", "client-1", "owner", "执行分析", "hash-2")

    assert journal.list("project-b") == []
