# imap-mcp — let your AI manage your mailbox

An MCP server that turns any plain IMAP mailbox into something Claude (or
any MCP client) can work in: search it, clean it up, file things away,
pull out attachments and forward receipts to your accounting system —
while hard, config-level guardrails make sure it can never send to
strangers or delete anything permanently.

Gmail and Microsoft 365 have official connectors. This is for **the rest
of your mail**: self-hosted servers, Migadu, your domain host's IMAP, the
old business account you still have to check. Standard IMAP/SMTP is all
it needs.

## What you can use it for

**Inbox cleanup that respects your judgment.** Most of what lands in an
inbox isn't spam — it's just not important: newsletters you once signed
up for, event marketing, "your webinar starts in 2 hours" for a webinar
that ended last month, renewal warnings for things you already renewed.
Ask your AI to sweep the inbox, trash the noise (recoverable — trash is
the only "delete" that exists), and ask you about anything it isn't sure
of.

**Receipts and invoices to your accounting system.** Have the AI find
invoices and receipts across folders, file them in a `Receipts` folder,
download the PDFs, or forward them directly to your bookkeeper or your
accounting system's inbox address (e-conomic, Billy, Dinero, …) — but
only to addresses you've whitelisted in the config.

**Spend your time on what matters.** Instead of wading through 60 unread
mails, ask: *"go through my inbox, summarize what actually needs me, star
it and mark it unread — archive or trash the rest."* You come back to a
mailbox where the flagged items are the to-do list and everything else is
filed.

**Find that mail you filed away and forgot.** Cross-folder search means
"somewhere in this account there's a confirmation from my Apple developer
enrollment" is a one-line request, not ten minutes of clicking through
folders.

Example prompts that work well in Claude Desktop / Cowork:

> Go through the INBOX on `personal`. Move obvious newsletters and
> marketing to trash, file receipts into a Receipts folder, and give me a
> prioritized summary of what needs my attention. Star what I need to
> handle and mark it unread. Ask before touching anything you're unsure
> about.

> Here's a spreadsheet of missing receipts. Search all folders for each
> one (supplier, amount, date), download the PDFs, and forward the mails
> to my bookkeeping inbox. Show me the list before you send anything.

## Safety model

The guardrails live in **config, not in prompt instructions** — so they
hold no matter what the model is asked to do, including by a malicious
mail trying to prompt-inject it:

- **Reading is always allowed**, and folders are opened read-only, so
  nothing even gets marked as read by accident.
- **Writes require `"allow_writes": true`** per account in
  `accounts.json` — without it every write tool refuses.
- **No permanent deletion.** "Delete" means move to the trash folder
  (`trash_folder`, default `Trash`), so everything is recoverable until
  the server's own retention empties it.
- **Forwarding only to a whitelist.** `forward_message` requires an
  `"smtp"` block and an `"allow_send_to"` list on the account. Recipients
  are matched against the list (wildcards like `*@e-conomic.dk` are
  fine) — anything else is refused hard. There is no compose-new-mail
  tool, only forward.

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
| `mark_messages` | Star/unstar and mark read/unread (requires `allow_writes`) |
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
- Mail content is untrusted input. The config-level guardrails limit the
  blast radius of prompt injection, but it's still wise to tell your AI
  to treat mail text as data, not instructions, and to confirm with you
  before forwarding anything.

## Tests

```
.venv/bin/python test_server.py
```

Runs offline — verifies tool registration, config validation and the
write/send gating without touching any mail server.

## License

MIT — see [LICENSE](LICENSE).
