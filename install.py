"""Registers imap-mcp with Claude Desktop and prepares accounts.json.

Run by setup.ps1 (Windows) or setup.sh (macOS/Linux) using the project's
venv python. Idempotent — safe to run again after updates.
"""

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent
if sys.platform == "win32":
    PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
else:
    PYTHON = ROOT / ".venv" / "bin" / "python"
SERVER = ROOT / "server.py"
ACCOUNTS = ROOT / "accounts.json"
EXAMPLE = ROOT / "accounts.example.json"


def _desktop_config_path() -> Path | None:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Claude" / "claude_desktop_config.json" if appdata else None
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "Claude"
                / "claude_desktop_config.json")
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def main() -> int:
    # 1) accounts.json: create from the template if missing
    if not ACCOUNTS.exists():
        shutil.copy(EXAMPLE, ACCOUNTS)
        if os.name == "posix":
            ACCOUNTS.chmod(0o600)  # credentials file — owner-only
        print(f"Created {ACCOUNTS.name} from the template — REMEMBER to fill "
              "in host/username/password before using the server.")
    else:
        print(f"{ACCOUNTS.name} already exists — leaving it untouched.")

    # 2) Claude Desktop config: add/update the mcpServers entry
    cfg_path = _desktop_config_path()
    if cfg_path is None:
        print("Could not determine the Claude Desktop config path — skipping.")
        return 1
    if cfg_path.exists():
        config = json.loads(cfg_path.read_text(encoding="utf-8"))
    else:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        config = {}
        print("No existing Claude Desktop config — creating one "
              "(is Claude Desktop installed?).")

    entry = {"command": str(PYTHON), "args": [str(SERVER)]}
    servers = config.setdefault("mcpServers", {})
    if servers.get("imap-mail") == entry:
        print("Claude Desktop: 'imap-mail' is already registered correctly.")
    else:
        servers["imap-mail"] = entry
        cfg_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Claude Desktop: registered 'imap-mail' in {cfg_path}.")

    # 3) Config check
    sys.path.insert(0, str(ROOT))
    import server  # noqa: E402

    accounts = server._load_accounts()
    print(f"Config OK: {len(accounts)} account(s): {', '.join(sorted(accounts))}")
    print()
    print("Next steps: fill in accounts.json and restart Claude Desktop.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
