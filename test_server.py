"""Offline tests for imap-mcp: tool registration, validation and gating.

Runs without any mail server or real credentials — a temporary config is
written and pointed to via server.CONFIG_PATH.

    .venv/bin/python test_server.py        (macOS/Linux)
    .venv\\Scripts\\python.exe test_server.py  (Windows)
"""

import asyncio
import json
import sys
import tempfile
import types
from pathlib import Path

# Fake keyring so the tests never touch the real OS keychain. Must be in
# sys.modules before server's lazy `import keyring` runs.
_keyring_store: dict[tuple[str, str], str] = {}
_fake_errors = types.ModuleType("keyring.errors")


class KeyringError(Exception):
    pass


_fake_errors.KeyringError = KeyringError
_fake_keyring = types.ModuleType("keyring")
_fake_keyring.errors = _fake_errors
_fake_keyring.get_password = lambda service, user: _keyring_store.get((service, user))
_fake_keyring.set_password = (
    lambda service, user, pw: _keyring_store.__setitem__((service, user), pw)
)
sys.modules["keyring"] = _fake_keyring
sys.modules["keyring.errors"] = _fake_errors

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
            "trash_messages", "forward_message", "mark_messages",
            "create_draft",
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

        # mark gating: no allow_writes -> refused; no-op flags rejected
        try:
            server.mark_messages("readonly", ["1"], flagged=True)
            raise AssertionError("mark on read-only account not refused")
        except PermissionError:
            print("mark gating OK")
        try:
            server.mark_messages("writable", ["1"])
            raise AssertionError("mark without flags not rejected")
        except ValueError:
            print("mark no-op validation OK")

        # draft gating: no allow_writes -> refused before any connection
        try:
            server.create_draft("readonly", subject="Hi", body="text")
            raise AssertionError("draft on read-only account not refused")
        except PermissionError:
            print("draft gating OK")

        # empty draft rejected before any connection
        try:
            server.create_draft("writable")
            raise AssertionError("empty draft not rejected")
        except ValueError:
            print("draft content validation OK")

        # RFC 5322 header unfolding (folded subject observed in real mail)
        folded = "Faktura fra e-conomic vedr. aftalenummer 1027203 | Per Friis\r\n Consult ApS"
        assert server._unfold(folded) == (
            "Faktura fra e-conomic vedr. aftalenummer 1027203 | Per Friis Consult ApS"
        )
        assert server._unfold("<id@x>\r\n\t<id2@x>") == "<id@x> <id2@x>"
        print("header unfolding OK")

        # attachment validation fires before any connection
        try:
            server.create_draft("writable", subject="x", attachments=["rel/path.pdf"])
            raise AssertionError("relative attachment path not rejected")
        except ValueError as e:
            assert "absolute" in str(e)
            print("attachment absolute-path validation OK")
        try:
            server.create_draft(
                "writable", subject="x", attachments=[str(Path(tmp) / "missing.pdf")]
            )
            raise AssertionError("missing attachment not rejected")
        except ValueError as e:
            assert "missing.pdf" in str(e)
            print("attachment missing-file validation OK")

        # total size cap (shrunk for the test)
        big = Path(tmp) / "big.bin"
        big.write_bytes(b"x" * 1024)
        orig_limit = server.ATTACHMENTS_TOTAL_LIMIT
        server.ATTACHMENTS_TOTAL_LIMIT = 512
        try:
            server.create_draft("writable", subject="x", attachments=[str(big)])
            raise AssertionError("oversized attachments not rejected")
        except ValueError as e:
            assert "limit" in str(e)
            print("attachment size-cap validation OK")
        finally:
            server.ATTACHMENTS_TOTAL_LIMIT = orig_limit

        # valid attachment passes validation (then fails at connect)
        try:
            server.create_draft("writable", subject="x", attachments=[str(big)])
            raise AssertionError("should have failed at the connection stage")
        except ValueError:
            raise AssertionError("valid attachment wrongly refused")
        except Exception:
            print("attachment pass-through OK (failed at connect as expected)")

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

        # password resolution: explicit config password wins
        assert server._resolve_password("writable", FIXTURE["accounts"]["writable"]) == "x"
        # keychain fallback when "password" is absent
        _keyring_store[(server.KEYRING_SERVICE, "kc")] = "s3cret"
        assert server._resolve_password("kc", {"username": "c@invalid"}) == "s3cret"
        del _keyring_store[(server.KEYRING_SERVICE, "kc")]
        print("password precedence OK")

        # missing everywhere -> loud error pointing at --set-password
        try:
            server._resolve_password("kc", {"username": "c@invalid"})
            raise AssertionError("missing password not rejected")
        except RuntimeError as e:
            assert "--set-password" in str(e)
            print("missing-password error OK")

        # no keychain backend (headless Linux) -> actionable error
        def _no_backend(service, user):
            raise KeyringError("no backend")

        _fake_keyring.get_password = _no_backend
        try:
            server._resolve_password("kc", {"username": "c@invalid"})
            raise AssertionError("keyring backend error not surfaced")
        except RuntimeError as e:
            assert "keychain backend" in str(e)
            print("no-backend error OK")
        finally:
            _fake_keyring.get_password = (
                lambda service, user: _keyring_store.get((service, user))
            )

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
