#!/usr/bin/env python3
"""A small, approval-first terminal agent for Linux environments on Android.

It sends chat messages and approved command output to the OpenAI API. It does
not connect to the Arena chat or control the Android UI.
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4.1-mini"
REQUEST_TIMEOUT_SECONDS = 90
COMMAND_TIMEOUT_SECONDS = 120
MAX_COMMAND_CHARS = 5_000
MAX_OUTPUT_CHARS = 12_000
MAX_TOOL_ROUNDS_PER_TURN = 8

SYSTEM_PROMPT = """You are a cautious terminal assistant running inside the user's Linux environment on Android.
Reply in the user's language, usually Hindi or Hinglish. Help with the user's stated task.
You may propose shell commands using the run_command tool. The client will show the exact
command and ask the user for approval before it runs; never claim a command ran unless a
result is returned. Use the fewest commands possible, prefer read-only checks first, and
explain important risks. Do not ask to inspect or print passwords, API keys, tokens, private
keys, browser data, or other secrets. Do not suggest uploading local files or exposing a
remote shell. Assume commands can affect anything accessible to this Linux environment;
keep work within the user's current directory where possible. Ask before proposing commands
that install, delete, overwrite, or change system configuration. This agent cannot control
Android apps or the Android UI."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Propose one shell command for the user to review. The client always asks "
                "the user before executing it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The exact shell command to propose.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "A short explanation of what the command does.",
                    },
                },
                "required": ["command", "reason"],
                "additionalProperties": False,
            },
        },
    }
]


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return (
        text[:half]
        + "\n\n... output shortened before sending to the assistant ...\n\n"
        + text[-half:]
    )


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_command(command: str, reason: str, workdir: Path) -> str:
    """Show a proposed command and run it only after explicit user approval."""
    command = command.strip()
    if not command:
        return "No command was run: the proposed command was empty."
    if len(command) > MAX_COMMAND_CHARS:
        return f"No command was run: commands are limited to {MAX_COMMAND_CHARS} characters."

    print("\nAgent proposes a terminal command")
    if reason.strip():
        print(f"Why: {reason.strip()}")
    print(f"Working directory: {workdir}")
    print("Command (review it carefully):")
    print(command)
    print("If approved, the command's output will be sent to the OpenAI API.")
    try:
        approval = input("Run this exact command? Type y to approve [y/N]: ")
    except (EOFError, KeyboardInterrupt):
        return "User did not approve the command; nothing was executed."

    if approval.strip().lower() != "y":
        return "User declined the command; nothing was executed."

    try:
        completed = subprocess.run(
            command,
            shell=True,
            executable="/bin/sh",
            cwd=str(workdir),
            text=True,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = _as_text(exc.stdout)
        stderr = _as_text(exc.stderr)
        output = "\n".join(part for part in (stdout, stderr) if part)
        if output:
            output = "\n" + _truncate(output)
        return (
            f"Command timed out after {COMMAND_TIMEOUT_SECONDS} seconds."
            f" Partial output:{output or ' none'}"
        )
    except OSError as exc:
        return f"Command could not be started: {exc}"

    sections = []
    if completed.stdout:
        sections.append("STDOUT:\n" + completed.stdout)
    if completed.stderr:
        sections.append("STDERR:\n" + completed.stderr)
    if not sections:
        sections.append("(no output)")
    result = "\n\n".join(sections)
    result += f"\n\nExit code: {completed.returncode}"
    return _truncate(result)


def _api_error_message(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read(8_192).decode("utf-8", errors="replace")
        parsed = json.loads(body)
        message = parsed.get("error", {}).get("message")
        if message:
            return str(message)
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return f"HTTP {exc.code} {exc.reason}"


def request_assistant(messages: list[dict[str, Any]], api_key: str, model: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OpenAI API error: {_api_error_message(exc)}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach the OpenAI API ({exc.reason}). Check the terminal's internet connection."
        ) from None
    except TimeoutError:
        raise RuntimeError("The OpenAI API request timed out. Try again.") from None
    except json.JSONDecodeError:
        raise RuntimeError("The API returned a response that was not valid JSON.") from None

    try:
        return response_data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("The API response did not contain an assistant message.") from None


def _tool_result(call: dict[str, Any], workdir: Path) -> tuple[dict[str, str], str]:
    call_id = str(call.get("id", "missing_tool_call_id"))
    function = call.get("function") or {}
    name = function.get("name")
    raw_arguments = function.get("arguments", "{}")

    if name != "run_command":
        result = f"Unsupported tool requested ({name!r}); nothing was executed."
    else:
        try:
            arguments = json.loads(raw_arguments)
            command = arguments.get("command", "")
            reason = arguments.get("reason", "")
            if not isinstance(command, str) or not isinstance(reason, str):
                raise ValueError("command and reason must be strings")
            result = run_command(command, reason, workdir)
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            result = f"Invalid command request; nothing was executed: {exc}"

    message = {"role": "tool", "tool_call_id": call_id, "content": result}
    return message, result


def handle_turn(
    messages: list[dict[str, Any]], api_key: str, model: str, workdir: Path
) -> None:
    for _ in range(MAX_TOOL_ROUNDS_PER_TURN):
        assistant_message = request_assistant(messages, api_key, model)
        # Keep only fields accepted in a subsequent Chat Completions request.
        saved_message: dict[str, Any] = {
            "role": "assistant",
            "content": assistant_message.get("content"),
        }
        if assistant_message.get("tool_calls"):
            saved_message["tool_calls"] = assistant_message["tool_calls"]
        messages.append(saved_message)

        content = assistant_message.get("content")
        if content:
            print(f"\nAgent: {content}")

        tool_calls = assistant_message.get("tool_calls") or []
        if not tool_calls:
            return

        for call in tool_calls:
            tool_message, _ = _tool_result(call, workdir)
            messages.append(tool_message)

    print(
        f"\nStopped after {MAX_TOOL_ROUNDS_PER_TURN} command rounds for this request. "
        "You can ask the agent to continue."
    )


def get_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        key = getpass.getpass("OpenAI API key (input is hidden; it will not be saved): ").strip()
    if not key:
        raise RuntimeError("No API key provided. Set OPENAI_API_KEY or start the program again.")
    return key


def main() -> int:
    workdir = Path.cwd().resolve()
    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    print("Android Linux Terminal Agent")
    print(f"Model: {model}")
    print(f"Commands run from: {workdir}")
    print(
        "Privacy and cost: your chat messages and approved command output are sent to the "
        "OpenAI API. API use may be billed separately from a ChatGPT subscription. "
        "This program does not save the API key or chat history to a file."
    )
    print(
        "Safety: every command requires your approval, but this is not a security sandbox. "
        "The agent can only run Linux shell commands here; it cannot control Android apps."
    )
    try:
        consent = input("Continue? Type y to connect [y/N]: ")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        return 0
    if consent.strip().lower() != "y":
        print("Cancelled; no API request was made.")
        return 0

    try:
        api_key = get_api_key()
    except (RuntimeError, KeyboardInterrupt) as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1

    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    print("\nReady. Type /help for commands, /clear to reset the chat, or /exit to quit.")

    while True:
        try:
            user_text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return 0

        if not user_text:
            continue
        if user_text.lower() in {"/exit", "/quit"}:
            print("Goodbye.")
            return 0
        if user_text.lower() == "/help":
            print(
                "Type a request in Hindi or English. The agent may suggest a shell command; "
                "review the exact command and type y to run it, or press Enter to refuse. "
                "Use /clear to forget this session's local conversation history or /exit to quit."
            )
            continue
        if user_text.lower() == "/clear":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            print("Conversation history cleared from this program's memory.")
            continue

        messages.append({"role": "user", "content": user_text})
        try:
            handle_turn(messages, api_key, model, workdir)
        except RuntimeError as exc:
            print(f"\n{exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
