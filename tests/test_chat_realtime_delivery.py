"""Tests for app-wide real-time chat delivery.

Real reported production bug: new messages only reached users who had sent
``{"type": "join", "conversation_id": ...}`` over the chat WebSocket — i.e.
users with that exact conversation open. Everyone else (dashboard, chat list,
another conversation) saw nothing until they re-called the REST API.

The fix delivers ``message:new`` / ``message:read`` USER-targeted via
``manager.send_to_user`` to every conversation participant — any open socket,
anywhere in the app, fanned out across workers via Redis.

Runs under pytest *or* standalone:  python tests/test_chat_realtime_delivery.py
"""
import asyncio
import inspect
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.websocket_chat import broadcast_new_message, broadcast_read_receipt
from app.core.websocket_manager import manager


def _capture_send_to_user():
    """Monkeypatch manager.send_to_user, returning the capture list + restore fn."""
    sent = []

    async def fake_send_to_user(user_id, message):
        sent.append((user_id, message))

    original = manager.send_to_user
    manager.send_to_user = fake_send_to_user
    return sent, lambda: setattr(manager, "send_to_user", original)


def test_new_message_is_user_targeted():
    conv_id = uuid4()
    sender, a, b = uuid4(), uuid4(), uuid4()
    sent, restore = _capture_send_to_user()
    try:
        asyncio.run(broadcast_new_message(
            conversation_id=conv_id,
            message_data={"message_id": "m1", "conversation_id": str(conv_id), "content": "hi"},
            exclude_user_id=sender,
            recipient_user_ids=[sender, a, b],
        ))
    finally:
        restore()
    targets = [uid for uid, _ in sent]
    assert sender not in targets, "sender must not receive their own message echo"
    assert set(targets) == {a, b}, f"both other participants must be targeted, got {targets}"
    for _, event in sent:
        assert event["type"] == "message:new"
        assert event["conversation_id"] == str(conv_id)
        assert event["content"] == "hi"


def test_read_receipt_is_user_targeted():
    conv_id, msg_id = uuid4(), uuid4()
    reader, other = uuid4(), uuid4()
    sent, restore = _capture_send_to_user()
    try:
        asyncio.run(broadcast_read_receipt(
            conversation_id=conv_id,
            message_id=msg_id,
            user_id=reader,
            read_at=datetime(2026, 7, 12, 12, 0, 0),
            recipient_user_ids=[reader, other],
        ))
    finally:
        restore()
    targets = [uid for uid, _ in sent]
    assert reader not in targets
    assert targets == [other]
    assert sent[0][1]["type"] == "message:read"
    assert sent[0][1]["message_id"] == str(msg_id)


def test_rest_send_message_supplies_participants():
    # Source pin: the REST send/read endpoints must pass recipient_user_ids,
    # otherwise delivery silently falls back to join-room-only (the old bug).
    from app.api.v1.chat_conversations import send_message, mark_messages_as_read
    for fn in (send_message, mark_messages_as_read):
        src = inspect.getsource(fn)
        assert "recipient_user_ids" in src, (
            f"{fn.__name__} no longer passes recipient_user_ids - real-time "
            "delivery will regress to users who joined the conversation room"
        )


def test_ws_loop_does_not_swallow_disconnect():
    # A catch-all around receive_json once swallowed WebSocketDisconnect,
    # leaving a coroutine spinning forever per dropped client (event-loop
    # starvation = production real-time outage). The loop must re-raise it.
    import re
    from app.api.v1.websocket_chat import websocket_chat_endpoint
    src = inspect.getsource(websocket_chat_endpoint)
    receive_idx = src.index("receive_json()")
    assert re.search(r"except WebSocketDisconnect:\s*\n\s*raise", src[receive_idx:]), (
        "chat WS loop no longer re-raises WebSocketDisconnect after receive - "
        "dropped clients will spin the event loop again"
    )


def _run_standalone():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run_standalone() else 0)
