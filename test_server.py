"""Offline tests for imap-mcp: tool registration, validation and gating.

Runs without any mail server or real credentials — a temporary config is
written and pointed to via server.CONFIG_PATH.

    .venv/bin/python test_server.py        (macOS/Linux)
    .venv\\Scripts\\python.exe test_server.py  (Windows)
"""

import asyncio
import json
import tempfile
from pathlib import Path

import server

FIXTURE = {
    "accounts": {
        "writable": {
            "host": "imap.invalid",
            "port": 993,
            "username": "a@invalid",
            "password": "x",
            "allow_writes": True,
            "smtp": {"host": "smtp.invalid", "port": 465},
            "allow_send_to": ["*@allowed.invalid"],
        },
        "readonly": {
            "host": "imap.invalid",
            "port": 993,
            "username": "b@invalid",
            "password": "x",
        },
    }
}


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "accounts.json"
        cfg.write_text(json.dumps(FIXTURE), encoding="utf-8")
        server.CONFIG_PATH = cfg

        tools = await server.mcp.list_tools()
        names = sorted(t.name for t in tools)
        expected = {
            "list_accounts", "list_folders", "search_messages", "get_message",
            "download_attachment", "create_folder", "move_messages",
            "trash_messages", "forward_message",
        }
        assert expected == set(names), f"tool mismatch: {expected ^ set(names)}"
        print("tool registration OK:", names)

        accounts = json.loads(server.list_accounts())
        assert [a["name"] for a in accounts] == ["readonly", "writable"]
        print("list_accounts OK")

        # unknown account is rejected with the available names listed
        try:
            server.list_folders("nope")
            raise AssertionError("unknown account not rejected")
        except ValueError as e:
            assert "readonly" in str(e) and "writable" in str(e)
            print("unknown-account rejection OK")

        # write gating: no allow_writes -> refused before any connection
        try:
            server.move_messages("readonly", ["1"], "INBOX", "Archive")
            raise AssertionError("write on read-only account not refused")
        except PermissionError:
            print("write gating OK")

        # empty uid list rejected before any connection
        try:
            server.trash_messages("writable", [])
            raise AssertionError("empty uids not rejected")
        except ValueError:
            print("uid validation OK")

        # send gating: account without allow_send_to -> refused
        try:
            server.forward_message("readonly", "1", "x@allowed.invalid")
            raise AssertionError("send on non-send account not refused")
        except PermissionError:
            print("send gating (no whitelist) OK")

        # send gating: recipient outside the whitelist -> refused
        try:
            server.forward_message("writable", "1", "attacker@evil.invalid")
            raise AssertionError("off-whitelist recipient not refused")
        except PermissionError:
            print("send gating (off-whitelist) OK")

        # whitelisted recipient passes gating (then fails at connect —
        # .invalid can never resolve, which is exactly what we want here)
        try:
            server.forward_message("writable", "1", "billing@allowed.invalid")
            raise AssertionError("should have failed at the connection stage")
        except PermissionError:
            raise AssertionError("whitelisted recipient wrongly refused")
        except Exception:
            print("whitelist pass-through OK (failed at connect as expected)")

        # date validation
        try:
            server.search_messages("writable", since="15-07-2026")
            raise AssertionError("bad date not rejected")
        except ValueError:
            print("date validation OK")

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
