"""Реестр инструментов агента: схемы для API + маппинг на Python-функции."""

from .filesystem import (
    read_file, read_range, write_file, edit_file, list_dir, grep,
)
from .shell import run_shell


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
            "description": "Replace the FIRST occurrence of old_text with "
                           "new_text in a file. Safer than write_file for "
                           "small edits.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string", "description": "Exact text to find"},
                    "new_text": {"type": "string", "description": "Replacement text"},
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
                           "all code extensions (php, py, js, ts, html, css, "
                           "templates, configs). Use include='.php' to filter by "
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
                           "Timeout 60s. Returns exit code + stdout + stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Full shell command"},
                },
                "required": ["command"],
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
}