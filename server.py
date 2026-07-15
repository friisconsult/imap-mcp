"""IMAP MCP server — mail access for Claude (Desktop/Cowork/Code).

Multi-account IMAP via accounts.json. Read operations (search, read,
attachment download) work on every account. Write operations (move mail,
create folders, move to trash) require "allow_writes": true on the account
in accounts.json — without it every write tool refuses. There is no
permanent-delete and no send capability at all; "delete" means move to the
account's trash folder.
"""

import fnmatch
import json
import re
import smtplib
import sys
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

from imap_tools import AND, MailBox, MailBoxStartTls
from mcp.server.fastmcp import FastMCP

CONFIG_PATH = Path(__file__).parent / "accounts.json"
SCAN_LIMIT_HEADERS = 300   # max messages scanned per search (headers only)
SCAN_LIMIT_FULL = 75       # max messages scanned when body text must be read
BODY_PREVIEW_CHARS = 8000

mcp = FastMCP("imap-mail")


def _load_accounts() -> dict:
    if not CONFIG_PATH.exists():
        raise RuntimeError(
            f"Config file not found: {CONFIG_PATH}. "
            "Copy accounts.example.json to accounts.json and fill in credentials."
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    accounts = data.get("accounts", {})
    if not accounts:
        raise RuntimeError(f"No accounts defined in {CONFIG_PATH}")
    return accounts


def _get_account(name: str) -> dict:
    accounts = _load_accounts()
    if name not in accounts:
        raise ValueError(
            f"Unknown account '{name}'. Available: {', '.join(sorted(accounts))}"
        )
    return accounts[name]


def _connect(name: str, folder: str | None = "INBOX", readonly: bool = True):
    acc = _get_account(name)
    encryption = acc.get("encryption", "ssl")
    port = acc.get("port", 993 if encryption == "ssl" else 143)
    box_cls = MailBoxStartTls if encryption == "starttls" else MailBox
    mailbox = box_cls(acc["host"], port=port, timeout=30)
    mailbox.login(acc["username"], acc["password"])
    if folder is not None:
        mailbox.folder.set(folder, readonly=readonly)
    return mailbox


def _require_send(name: str, to: str) -> dict:
    acc = _get_account(name)
    patterns = acc.get("allow_send_to", [])
    if not patterns:
        raise PermissionError(
            f"Sending is disabled for account '{name}'. Add \"allow_send_to\": "
            f"[\"someone@example.com\", \"*@example.org\", ...] to the account in "
            f"accounts.json to allow forwarding to those addresses."
        )
    if not any(fnmatch.fnmatch(to.lower(), p.lower()) for p in patterns):
        raise PermissionError(
            f"Recipient {to!r} is not on the allow_send_to list for account "
            f"'{name}' ({patterns}). This list is a hard config-level limit — "
            f"the user must edit accounts.json to send elsewhere."
        )
    if "smtp" not in acc:
        raise RuntimeError(
            f"Account '{name}' has no \"smtp\" config. Add e.g. "
            f'{{"host": "smtp.migadu.com", "port": 465}} to enable forwarding.'
        )
    return acc


def _require_writes(name: str) -> dict:
    acc = _get_account(name)
    if not acc.get("allow_writes", False):
        raise PermissionError(
            f"Account '{name}' is read-only. Set \"allow_writes\": true on the "
            f"account in accounts.json to enable move/folder operations."
        )
    return acc


def _is_ascii(s: str) -> bool:
    return s.isascii()


def _parse_date(value: str, param: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"{param} must be YYYY-MM-DD, got: {value!r}")


def _msg_summary(msg) -> dict:
    return {
        "uid": msg.uid,
        "date": msg.date.isoformat() if msg.date else None,
        "from": msg.from_,
        "subject": msg.subject,
        "attachments": [
            {"filename": a.filename, "size": a.size} for a in msg.attachments
        ],
    }


def _matches(msg, from_: str | None, subject: str | None, text: str | None,
             include_body: bool) -> bool:
    if from_:
        haystack = msg.from_ or ""
        if msg.from_values:
            haystack += f" {msg.from_values.name} {msg.from_values.email}"
        if from_.lower() not in haystack.lower():
            return False
    if subject and subject.lower() not in (msg.subject or "").lower():
        return False
    if text:
        body = (msg.subject or "")
        if include_body:
            body += " " + (msg.text or "") + " " + (msg.html or "")
        if text.lower() not in body.lower():
            return False
    return True


@mcp.tool()
def list_accounts() -> str:
    """List the configured IMAP account names (use these as the 'account'
    parameter in the other tools). Does not connect to any server."""
    accounts = _load_accounts()
    result = [
        {"name": name, "host": acc["host"], "username": acc["username"]}
        for name, acc in sorted(accounts.items())
    ]
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def list_folders(account: str) -> str:
    """List folder names for an account (e.g. INBOX, Sent, Archive)."""
    with _connect(account) as mailbox:
        names = [f.name for f in mailbox.folder.list()]
    return json.dumps(names, ensure_ascii=False, indent=2)


@mcp.tool()
def search_messages(
    account: str,
    folder: str = "INBOX",
    from_: str | None = None,
    subject: str | None = None,
    text: str | None = None,
    since: str | None = None,
    before: str | None = None,
    with_attachments_only: bool = False,
    all_folders: bool = False,
    limit: int = 25,
) -> str:
    """Search messages, newest first. Read-only.

    Searches one folder (default INBOX), or every folder on the account
    when all_folders=true — each result then includes which folder it is
    in. from_/subject: case-insensitive substring match on sender/subject.
    text: substring match on subject and body. since/before: dates as
    YYYY-MM-DD (since inclusive, before exclusive). Always constrain with
    since/before when possible — only the newest ~300 messages in range
    are scanned (shared across folders when all_folders), and the result
    says whether the scan was truncated.
    """
    criteria = []
    if since:
        criteria.append(AND(date_gte=_parse_date(since, "since")))
    if before:
        criteria.append(AND(date_lt=_parse_date(before, "before")))
    # IMAP text search criteria only go server-side when pure ASCII; many
    # servers reject UTF-8 SEARCH. Non-ASCII terms are filtered locally.
    if from_ and _is_ascii(from_):
        criteria.append(AND(from_=from_))
    if subject and _is_ascii(subject):
        criteria.append(AND(subject=subject))
    if text and _is_ascii(text):
        criteria.append(AND(text=text))

    needs_body = bool(text and not _is_ascii(text))
    scan_budget = SCAN_LIMIT_FULL if needs_body else SCAN_LIMIT_HEADERS
    server_criteria = AND(*criteria) if criteria else "ALL"
    want = max(limit * 3, limit) if with_attachments_only else limit

    with _connect(account, None) as mailbox:
        if all_folders:
            folder_names = [f.name for f in mailbox.folder.list()]
        else:
            folder_names = [folder]

        scanned = 0
        skipped_folders = []
        matched: dict[str, list[str]] = {}
        n_matched = 0
        for fname in folder_names:
            if scanned >= scan_budget or n_matched >= want:
                break
            try:
                mailbox.folder.set(fname, readonly=True)
            except Exception:
                skipped_folders.append(fname)  # non-selectable (namespace etc.)
                continue
            for msg in mailbox.fetch(
                server_criteria,
                reverse=True,
                limit=scan_budget - scanned,
                mark_seen=False,
                headers_only=not needs_body,
            ):
                scanned += 1
                if not _matches(msg, from_, subject, text, include_body=needs_body):
                    continue
                matched.setdefault(fname, []).append(msg.uid)
                n_matched += 1
                if n_matched >= want:
                    break

        results = []
        for fname, uids in matched.items():
            if len(results) >= limit:
                break
            mailbox.folder.set(fname, readonly=True)
            for msg in mailbox.fetch(AND(uid=uids), mark_seen=False, reverse=True):
                if with_attachments_only and not msg.attachments:
                    continue
                summary = _msg_summary(msg)
                summary["folder"] = fname
                results.append(summary)
                if len(results) >= limit:
                    break

    truncated = scanned >= scan_budget
    return json.dumps(
        {
            "results": results,
            "scanned": scanned,
            "scan_truncated": truncated,
            "skipped_folders": skipped_folders,
            "note": (
                "Scan hit the limit — narrow the date range to search older mail."
                if truncated else "Full date range scanned."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def get_message(account: str, uid: str, folder: str = "INBOX") -> str:
    """Fetch one message by uid: headers, text body (truncated) and
    attachment list. Read-only, does not mark the message as read."""
    with _connect(account, folder) as mailbox:
        msgs = list(mailbox.fetch(AND(uid=uid), mark_seen=False, limit=1))
    if not msgs:
        raise ValueError(f"No message with uid {uid} in {folder}")
    msg = msgs[0]
    body = msg.text or re.sub(r"<[^>]+>", " ", msg.html or "")
    body = re.sub(r"[ \t]+", " ", body).strip()
    info = _msg_summary(msg)
    info["to"] = msg.to
    info["body"] = body[:BODY_PREVIEW_CHARS]
    info["body_truncated"] = len(body) > BODY_PREVIEW_CHARS
    return json.dumps(info, ensure_ascii=False, indent=2)


@mcp.tool()
def download_attachment(
    account: str, uid: str, filename: str, save_dir: str, folder: str = "INBOX"
) -> str:
    """Download one attachment from a message to save_dir (absolute path,
    created if missing). Returns the saved file path. Never overwrites an
    existing file — a numeric suffix is added instead."""
    target_dir = Path(save_dir)
    if not target_dir.is_absolute():
        raise ValueError("save_dir must be an absolute path")
    target_dir.mkdir(parents=True, exist_ok=True)

    with _connect(account, folder) as mailbox:
        msgs = list(mailbox.fetch(AND(uid=uid), mark_seen=False, limit=1))
    if not msgs:
        raise ValueError(f"No message with uid {uid} in {folder}")
    msg = msgs[0]

    att = next((a for a in msg.attachments if a.filename == filename), None)
    if att is None:
        available = [a.filename for a in msg.attachments]
        raise ValueError(
            f"No attachment named {filename!r} on uid {uid}. Available: {available}"
        )

    safe_name = re.sub(r"[\\/:*?\"<>|]", "_", filename) or "attachment.bin"
    target = target_dir / safe_name
    stem, suffix = target.stem, target.suffix
    counter = 1
    while target.exists():
        target = target_dir / f"{stem}-{counter}{suffix}"
        counter += 1
    target.write_bytes(att.payload)
    return json.dumps(
        {"saved_to": str(target), "size": len(att.payload)}, ensure_ascii=False
    )


@mcp.tool()
def create_folder(account: str, folder: str) -> str:
    """Create a new folder on the account (requires allow_writes on the
    account). Use '/' or the server's own separator for nesting, e.g.
    'Arkiv/Bilag'. Fails if the folder already exists."""
    _require_writes(account)
    with _connect(account, readonly=True) as mailbox:
        mailbox.folder.create(folder)
        names = [f.name for f in mailbox.folder.list()]
    return json.dumps(
        {"created": folder, "folders": names}, ensure_ascii=False, indent=2
    )


@mcp.tool()
def move_messages(
    account: str, uids: list[str], from_folder: str, to_folder: str
) -> str:
    """Move messages (by uid) from one folder to another (requires
    allow_writes on the account). The target folder must already exist —
    use create_folder first if needed. Returns how many were moved."""
    _require_writes(account)
    if not uids:
        raise ValueError("uids must not be empty")
    with _connect(account, from_folder, readonly=False) as mailbox:
        existing = {f.name for f in mailbox.folder.list()}
        if to_folder not in existing:
            raise ValueError(
                f"Target folder {to_folder!r} does not exist. "
                f"Available: {sorted(existing)}"
            )
        mailbox.move(uids, to_folder)
    return json.dumps(
        {"moved": len(uids), "from": from_folder, "to": to_folder},
        ensure_ascii=False,
    )


@mcp.tool()
def trash_messages(account: str, uids: list[str], folder: str = "INBOX") -> str:
    """Move messages to the account's trash folder (requires allow_writes).
    This is the ONLY deletion this server offers — nothing is expunged, so
    everything can be restored from the trash until the server's own
    retention empties it. The trash folder name comes from the account's
    "trash_folder" config (default: "Trash")."""
    acc = _require_writes(account)
    if not uids:
        raise ValueError("uids must not be empty")
    trash = acc.get("trash_folder", "Trash")
    with _connect(account, folder, readonly=False) as mailbox:
        existing = {f.name for f in mailbox.folder.list()}
        if trash not in existing:
            raise ValueError(
                f"Trash folder {trash!r} not found on server. Set "
                f"\"trash_folder\" on the account in accounts.json to one of: "
                f"{sorted(existing)}"
            )
        mailbox.move(uids, trash)
    return json.dumps(
        {"trashed": len(uids), "moved_to": trash}, ensure_ascii=False
    )


@mcp.tool()
def forward_message(
    account: str,
    uid: str,
    to: str,
    folder: str = "INBOX",
    comment: str | None = None,
    include_body: bool = True,
) -> str:
    """Forward a message with all its attachments via the account's SMTP.

    Only works if the recipient matches the account's "allow_send_to"
    whitelist in accounts.json — that list is a hard limit that cannot be
    overridden from here. The forward is sent from the account's own
    address with subject "Fwd: <original>"; an optional comment is
    prepended above the original text."""
    acc = _require_send(account, to)

    with _connect(account, folder) as mailbox:
        msgs = list(mailbox.fetch(AND(uid=uid), mark_seen=False, limit=1))
    if not msgs:
        raise ValueError(f"No message with uid {uid} in {folder}")
    src = msgs[0]

    fwd = EmailMessage()
    sender = acc.get("smtp", {}).get("from", acc["username"])
    fwd["From"] = sender
    fwd["To"] = to
    subject = src.subject or "(no subject)"
    fwd["Subject"] = subject if subject.lower().startswith("fwd:") else f"Fwd: {subject}"

    parts = []
    if comment:
        parts.append(comment)
    if include_body:
        parts.append(
            f"---------- Forwarded message ----------\n"
            f"From: {src.from_}\nDate: {src.date}\nSubject: {src.subject}\n\n"
            f"{src.text or ''}"
        )
    fwd.set_content("\n\n".join(parts) or f"Forwarded: {subject}")

    for att in src.attachments:
        maintype, _, subtype = (att.content_type or "application/octet-stream").partition("/")
        fwd.add_attachment(
            att.payload,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=att.filename or "attachment.bin",
        )

    smtp_cfg = acc["smtp"]
    smtp_host = smtp_cfg["host"]
    smtp_enc = smtp_cfg.get("encryption", "ssl")
    smtp_port = smtp_cfg.get("port", 465 if smtp_enc == "ssl" else 587)
    smtp_user = smtp_cfg.get("username", acc["username"])
    smtp_pass = smtp_cfg.get("password", acc["password"])

    if smtp_enc == "ssl":
        smtp = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
    else:
        smtp = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
        smtp.starttls()
    try:
        smtp.login(smtp_user, smtp_pass)
        smtp.send_message(fwd)
    finally:
        smtp.quit()

    return json.dumps(
        {
            "forwarded_uid": uid,
            "to": to,
            "subject": fwd["Subject"],
            "attachments": [a.filename for a in src.attachments],
        },
        ensure_ascii=False,
        indent=2,
    )


if __name__ == "__main__":
    if "--check" in sys.argv:
        accounts = _load_accounts()
        print(f"Config OK: {len(accounts)} account(s): {', '.join(sorted(accounts))}")
        sys.exit(0)
    mcp.run()
