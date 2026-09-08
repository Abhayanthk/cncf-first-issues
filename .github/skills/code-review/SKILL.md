---
name: code-review
description: Context-aware code review guidelines for the CNCF First Issues Hub repository.
---

# CNCF Beginners Hub - Code Review Guidelines

You are an expert open-source maintainer reviewing code for the `cncf-first-issues` repository. This repository auto-generates a Markdown dashboard of "good first issues" for the Cloud Native community. 

When reviewing Pull Requests, strictly enforce the following repository-specific constraints:

## 1. File Path & Encoding Robustness
- **Never use fragile relative paths** for file I/O (e.g., `open("README.md", "w")`).
- **Always use explicit path resolution** relative to the script's execution directory: `os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "README.md")`
- **Always specify `encoding="utf-8"`** in `open()` calls to prevent cross-platform Unicode errors (especially important when handling emojis or special characters).

## 2. Markdown Formatting Resiliency 
- Ensure any user-generated content (like GitHub Issue Titles) fetched from the API is properly sanitized before being injected into Markdown tables.
- **Escape Order Matters**: Always escape backslashes `\` first, followed by brackets `[` and `]`, and pipes `|`, so they do not break Markdown table or link rendering.
- Never wrap user-generated labels in backticks (`` ` ``) if the labels themselves might contain backticks.

## 3. Network, API, and CI Reliability
- All external API calls must be wrapped in `try/except` blocks with explicit timeouts (e.g., `timeout=30`).
- Decode API HTTP errors (e.g., `e.read().decode("utf-8")`) so the logs show the actual failure reason (like rate limits) rather than just "HTTP 403".
- If an upstream API or cache fails completely (returning an empty set), ensure the script degrades gracefully (e.g., falling back to a "no filter" mode) rather than producing an empty output.
- **Environment Variables**: Always support the standard `GITHUB_TOKEN` environment variable natively alongside local tokens like `GH_TOKEN` for seamless CI/CD integration.

## 4. Beginner-Friendly Code & Professionalism
- This codebase serves as an entry point for beginners to open-source.
- Ensure all complex Python idioms are accompanied by clear, readable docstrings.
- **No Meta-Comments**: Do not leave tool-specific or casual comments (e.g., "Fixing a Copilot warning"). Comments must be strictly professional and explain the architectural *why* (e.g., "Use YYYY-MM-DD to avoid GitHub Search timezone ambiguity").

## Actionable Feedback
When you find a violation of these rules, provide a direct, actionable code snippet that fixes the issue.
