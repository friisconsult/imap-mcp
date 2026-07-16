# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

`imap-mcp` is a single-file Python MCP server (`server.py`, FastMCP over stdio) that gives Claude Desktop/Cowork/Code access to plain IMAP/SMTP mailboxes — the accounts not covered by the official Gmail/M365 connectors. There is no package structure: `server.py` holds all tools, `test_server.py` the tests, `install.py` the Claude Desktop registration.

## Commands

```bash
bash setup.sh                        # create .venv, install deps, register in Claude Desktop (idempotent)
.venv/bin/python server.py --check   # validate accounts.json without starting the server
.venv/bin/python test_server.py      # run tests (offline — no mail server, no framework, plain asserts)
```

On Windows use `.\setup.ps1` and `.venv\Scripts\python.exe`. There is no pytest/lint setup; the test file is a script that prints per-check status and `ALL CHECKS PASSED`.

Configuration lives in `accounts.json` (gitignored, plain-text credentials — never commit or print it). `accounts.example.json` is the template; `install.py` copies it on first setup and registers the server as `imap-mail` in Claude Desktop's config.

## Architecture: config-level safety gating

The central design decision is that **all guardrails live in `accounts.json`, not in prompts or tool descriptions**, so they hold under prompt injection from mail content. Every tool falls into one of three tiers, and any new tool must be gated the same way:

1. **Read tools** (search, get, list, download) — always allowed, but must connect read-only and fetch with `mark_seen=False` so nothing is even marked read as a side effect.
2. **Write tools** (move, trash, create folder, mark, create draft) — must call `_require_writes(account)` first, which raises `PermissionError` unless the account has `"allow_writes": true`. Deletion does not exist: `trash_messages` only moves to the account's `trash_folder` (default `Trash`); never add expunge/permanent delete. `create_draft` only APPENDs to the `drafts_folder` (default `Drafts`) — it composes but can never send, which is why it is a write tool, not a send tool.
3. **Send** (`forward_message` only) — must call `_require_send(account, to)`, which enforces the `allow_send_to` fnmatch whitelist and requires an `smtp` block. There is deliberately no send-new-mail tool.

Gating checks run **before** any network connection (the tests rely on this — they use `.invalid` hosts that can never resolve).

Other invariants worth knowing:

- **Search scan budgets:** `search_messages` scans at most `SCAN_LIMIT_HEADERS` (300) messages, or `SCAN_LIMIT_FULL` (75) when body text must be fetched. Non-ASCII search terms are never sent as IMAP SEARCH criteria (many servers reject UTF-8 SEARCH) — they're filtered locally via `_matches()`. Responses report `scan_truncated` so the calling model knows to narrow the date range.
- **Connections** go through `_connect()` (SSL default port 993, `"starttls"` → port 143, per-account override). Config is re-read from disk on every call — no caching, so edits to `accounts.json` take effect immediately.
- **Tool output** is always a JSON string (`json.dumps(..., ensure_ascii=False)`); user-facing errors are raised as `ValueError`/`PermissionError`/`RuntimeError` with messages that tell the model (or user) how to fix the problem, including what to change in `accounts.json`.

## Adding or changing a tool

- Update the `expected` tool-name set in `test_server.py` — the tests assert exact tool registration.
- Add offline gating/validation tests there; input validation (empty uids, date format) must fire before any connection attempt.
- Update the tool table in `README.md`.
