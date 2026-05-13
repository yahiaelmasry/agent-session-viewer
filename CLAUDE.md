# CLAUDE.md

Guidance for Claude Code in this repo.

## Scope

Export Claude Code and Codex CLI sessions. Reject feature creep.
No conversation analysis, search, or unrelated tools.

## Stack

Python 3.9+, stdlib only by default. New pip deps require justification.
HTML viewer uses CDN libs. Do not vendor.

## Schema

Output is `{source, messages: [{role, text}]}`. Existing fields are fixed.
New optional fields OK in both extractors.

## Code style

No comments unless the why is non-obvious. Short functions, flat logic.
No premature abstractions or compat shims.

## Verification

Add a pytest test for new behavior. Run the suite before commit.
Smoke-test touched scripts on a real session.

## Commits

One purpose per commit. Imperative subject under 70 chars.
Body explains why, not what.
