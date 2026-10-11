"""Реестр инструментов агента: схемы для API + маппинг на Python-функции."""

from .filesystem import (
    read_file, read_range, write_file, edit_file, list_dir, grep,
)
from .shell import run_shell
from .git import git_status, git_diff, git_log
from .web import fetch_url, web_search

# Инструменты, которые прячутся от модели, если функция выключена
# или неприменима (см. build_tools_list в agent.py).
WEB_TOOLS = {"fetch_url", "web_search"}
GIT_TOOLS = {"git_status", "git_diff", "git_log"}
# Инструменты, у которых аргумент path по умолчанию = корень проекта.
PATH_TOOLS = {"read_file", "read_range", "write_file", "edit_file", "list_dir", "grep"}


# ---------- Схемы для DeepSeek (формат OpenAI tools) ----------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file's full content. If the file is larger "
                           "than 500KB, returns only the first part; use "
                           "read_range for specific sections.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_range",
            "description": "Read specific line range [start, end] (inclusive, "
                           "1-based) from a file. Use for large files when "
                           "read_file truncates. Max 500 lines per call.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start": {"type": "integer", "description": "Start line, 1-based"},
                    "end": {"type": "integer", "description": "End line, inclusive"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file (creates dirs if needed). "
                           "Overwrites existing content. Use edit_file for small edits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace old_text with new_text in a file. By default "
                           "only the FIRST occurrence is replaced; set "
                           "replace_all=true to replace every occurrence. "
                           "CRLF/LF line endings in the file are preserved. "
                           "Prefer this over write_file for small edits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string", "description": "Exact text to find"},
                    "new_text": {"type": "string", "description": "Replacement text"},
                    "replace_all": {
                        "type": "boolean",
                        "description": "Replace all occurrences (default false)",
                    },
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and folders in a directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search by regex in project files. By default searches "
                           "all code extensions (php, py, js, ts, java, kt, swift, "
                           "html, css, templates, configs). Use include='.php' to filter by "
                           "extension, or include='*' to search EVERYTHING "
                           "(including .txt, .log and unknown types).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern"},
                    "path": {"type": "string", "description": "Root dir, default '.'"},
                    "include": {
                        "type": "string",
                        "description": "Extension filter ('.php', 'php', '.css'). "
                                       "Use '*' for no filter.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command (php -l, node --check, python -m "
                           "pytest, git status, etc.). Working dir = project root. "
                           "Timeout is configurable (tools.shell_timeout, default "
                           "60s). Returns exit code + stdout + stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Full shell command"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Download a web page and return it as plain text "
                           "(HTML is converted). Use for reading docs, changelogs, "
                           "RFCs, error messages. Local/private addresses are "
                           "blocked. Content is truncated to tools.web.max_chars.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "http(s) URL"},
                    "max_chars": {
                        "type": "integer",
                        "description": "Optional output limit in characters",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web (DuckDuckGo, no API key needed) and "
                           "return titles, URLs and snippets. Follow up with "
                           "fetch_url to read a promising page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "num_results": {
                        "type": "integer",
                        "description": "How many results to return (default from config)",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Read-only `git status --short --branch`: current branch, "
                           "modified and untracked files. Use it before/after edits "
                           "to see what changed.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Read-only `git diff`. staged=true shows index changes "
                           "(--cached). Optionally limit to one path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Limit diff to this path"},
                    "staged": {
                        "type": "boolean",
                        "description": "Show staged changes (--cached)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_log",
            "description": "Read-only `git log --oneline` — recent commits "
                           "(last 10 by default).",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "How many commits"},
                },
            },
        },
    },
]


# ---------- Маппинг имён на Python-функции ----------

REGISTRY = {
    "read_file": read_file,
    "read_range": read_range,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_dir": list_dir,
    "grep": grep,
    "run_shell": run_shell,
    "fetch_url": fetch_url,
    "web_search": web_search,
    "git_status": git_status,
    "git_diff": git_diff,
    "git_log": git_log,
}