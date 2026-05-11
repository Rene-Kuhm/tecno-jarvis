import json
from datetime import datetime
from threading import Lock
from pathlib import Path
import sys


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR = _get_base_dir()
SESSION_PATH = BASE_DIR / "session_state.json"
_lock = Lock()

MAX_TOOL_HISTORY = 20
MAX_TASK_HISTORY = 30
MAX_CONTEXT_CHARS = 1600


def _empty_state() -> dict:
    return {
        "active_tasks": {},
        "task_history": [],
        "tool_history": [],
        "last_conversation": None,
        "started_at": None,
    }


def load() -> dict:
    if not SESSION_PATH.exists():
        return _empty_state()
    with _lock:
        try:
            return json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        except Exception:
            return _empty_state()


def save(state: dict) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        SESSION_PATH.write_text(
            json.dumps(state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def start_session() -> dict:
    state = load()
    state["started_at"] = datetime.now().isoformat()
    save(state)
    return state


def clear_session() -> None:
    state = _empty_state()
    save(state)


def record_task_start(task_id: str, goal: str) -> None:
    state = load()
    state["active_tasks"][task_id] = {
        "goal": goal,
        "status": "running",
        "started_at": datetime.now().isoformat(),
    }
    save(state)


def record_task_complete(task_id: str, result: str) -> None:
    state = load()
    task = state["active_tasks"].pop(task_id, None)
    if task:
        task["status"] = "completed"
        task["result"] = result[:200]
        task["completed_at"] = datetime.now().isoformat()
        state["task_history"].append(task)
        if len(state["task_history"]) > MAX_TASK_HISTORY:
            state["task_history"] = state["task_history"][-MAX_TASK_HISTORY:]
    save(state)


def record_task_fail(task_id: str, error: str) -> None:
    state = load()
    task = state["active_tasks"].pop(task_id, None)
    if task:
        task["status"] = "failed"
        task["error"] = error[:200]
        task["failed_at"] = datetime.now().isoformat()
        state["task_history"].append(task)
        if len(state["task_history"]) > MAX_TASK_HISTORY:
            state["task_history"] = state["task_history"][-MAX_TASK_HISTORY:]
    save(state)


def record_tool_call(tool_name: str, args_summary: str, result_summary: str) -> None:
    state = load()
    state["tool_history"].append({
        "tool": tool_name,
        "args": args_summary[:120],
        "result": result_summary[:200],
        "at": datetime.now().isoformat(),
    })
    if len(state["tool_history"]) > MAX_TOOL_HISTORY:
        state["tool_history"] = state["tool_history"][-MAX_TOOL_HISTORY:]
    save(state)


def record_conversation(user_text: str, jarvis_text: str) -> None:
    if not user_text and not jarvis_text:
        return
    state = load()
    state["last_conversation"] = {
        "user": user_text[:300],
        "jarvis": jarvis_text[:300],
        "at": datetime.now().isoformat(),
    }
    save(state)


def get_session_context() -> str:
    state = load()

    if not state.get("started_at"):
        return ""

    lines = ["[SESSION CONTEXT -- what is happening right now]\n"]

    active = state.get("active_tasks", {})
    if active:
        lines.append("Active tasks:")
        for tid, task in list(active.items())[:5]:
            lines.append(f"  [{tid}] {task.get('goal', '')[:100]}")

    recent_tools = state.get("tool_history", [])[-8:]
    if recent_tools:
        lines.append("")
        lines.append("Recent tool calls:")
        for entry in recent_tools:
            tool = entry.get("tool", "?")
            result = entry.get("result", "")[:80]
            lines.append(f"  {tool} -> {result}")

    last_conv = state.get("last_conversation")
    if last_conv:
        lines.append("")
        lines.append(f"Last thing user said: {last_conv.get('user', '')[:150]}")
        lines.append(f"Last thing Jarvis said: {last_conv.get('jarvis', '')[:150]}")

    result = "\n".join(lines)
    if len(result) > MAX_CONTEXT_CHARS:
        result = result[:MAX_CONTEXT_CHARS - 3] + "…"
    return result + "\n"


def get_active_tasks() -> list[dict]:
    state = load()
    return [
        {"id": tid, **task}
        for tid, task in state.get("active_tasks", {}).items()
    ]


def resume_able() -> bool:
    state = load()
    return bool(state.get("active_tasks") or state.get("last_conversation"))
