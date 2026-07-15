# imap-mcp

An MCP server that gives Claude (Desktop/Cowork, Claude Code, or any MCP
client) access to plain IMAP mailboxes — the accounts that have no official
connector: self-hosted mail servers, Migadu, and any other standard
IMAP/SMTP provider.

Typical uses: digging out missing receipts/invoices from your mail and
forwarding them to your accounting system, cleaning up folders, finding
that mail you filed away years ago and forgot about.

## Safety model

Designed so the guardrails live in *config*, not in prompt instructions —
they cannot be talked around:

- **Reading is always allowed**, and folders are opened read-only, so
  nothing even gets marked as read by accident.
- **Writes require `"allow_writes": true`** per account in
  `accounts.json` — without it every write tool refuses.
- **No permanent deletion.** "Delete" means move to the trash folder
  (`trash_folder`, default `Trash`), so everything is recoverable until
  the server's own retention empties it.
- **Forwarding only to a whitelist.** `forward_message` requires an
  `"smtp"` block and an `"allow_send_to"` list on the account. Recipients
  are matched against the list (wildcards like `*@example.org` are fine) —
  anything else is refused hard, no matter what the model is asked to do.
  There is no compose-new-mail tool, only forward.

## Setup

Requires Python 3.11+ on PATH and Claude Desktop installed.

1. Clone/copy this folder and run the setup script:
   - **Windows** (PowerShell): `.\setup.ps1`
   - **macOS/Linux**: `bash setup.sh`

   The script creates a venv, installs dependencies, creates
   `accounts.json` from the template (if missing) and registers the
   server as `imap-mail` in Claude Desktop's config (Windows:
   `%APPDATA%\Claude\`, macOS: `~/Library/Application Support/Claude/`).
2. Fill in `accounts.json` — host, username and password per account.
   The key (e.g. `personal`) is the name Claude uses as the `account`
   parameter.
   - `encryption`: `"ssl"` (port 993, default) or `"starttls"` (port 143).
   - Use an app password if your provider supports them.
   - `accounts.json` is gitignored — credentials are entered per machine.
3. Test the configuration (Windows: `.venv\Scripts\python.exe`,
   macOS/Linux: `.venv/bin/python`):
   ```
   .venv/bin/python server.py --check
   ```
4. Restart Claude Desktop.

## Tools

| Tool | Does |
|---|---|
| `list_accounts` | List configured accounts |
| `list_folders` | Folders in an account (INBOX, Sent, …) |
| `search_messages` | Search (sender/subject/text/date), newest first — one folder or the whole account (`all_folders`) |
| `get_message` | Read one message incl. its attachment list |
| `download_attachment` | Save one attachment to a directory (never overwrites) |
| `create_folder` | Create a new folder (requires `allow_writes`) |
| `move_messages` | Move messages between folders (requires `allow_writes`) |
| `trash_messages` | Move messages to the trash folder (requires `allow_writes`) |
| `forward_message` | Forward a message incl. attachments (requires `smtp` + `allow_send_to`) |

## Notes and limitations

- Search criteria containing non-ASCII characters are not sent to the
  IMAP server (many servers reject UTF-8 SEARCH) — they are filtered
  locally instead. Always constrain with `since`/`before`; otherwise only
  the newest ~300 messages are scanned, and the response sets
  `scan_truncated: true` so the model knows to narrow the range.
- `accounts.json` stores credentials in plain text. Keep it out of git
  and sync services (it is gitignored here), prefer app passwords, and
  treat the file like you would a password manager export.
- Authentication is plain IMAP/SMTP login — no OAuth. Gmail and
  Microsoft 365 accounts are better served by their official connectors
  anyway; this server is for everything else.

## Tests

```
.venv/bin/python test_server.py
```

Runs offline — verifies tool registration, config validation and the
write/send gating without touching any mail server.

## License

MIT — see [LICENSE](LICENSE).
