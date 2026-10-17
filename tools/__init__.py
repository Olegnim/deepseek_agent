"""Реестр инструментов агента: схемы для API + маппинг на Python-функции."""

from .filesystem import (
    read_file, read_range, write_file, edit_file, list_dir, grep,
)
from .search import (
    search_code, file_outline, read_symbol, diff_files, find_files, project_map,
)
from .vision import read_image
from .shell import run_shell
from .git import git_status, git_diff, git_log
from .web import fetch_url, web_search
from .vscode import (
    vscode_open, vscode_close, vscode_close_all,
    vscode_reveal, vscode_diff, vscode_status,
)

# Инструменты, которые прячутся от модели, если функция выключена
# или неприменима (см. build_tools_list в agent.py).
WEB_TOOLS = {"fetch_url", "web_search"}
GIT_TOOLS = {"git_status", "git_diff", "git_log"}
# Изображения модели (vision.enabled в конфиге).
VISION_TOOLS = {"read_image"}
# Поиск/навигация по коду (tools/search.py): работают локально и отдают выжимку.
SEARCH_TOOLS = {"search_code", "file_outline", "read_symbol",
                "diff_files", "find_files", "project_map"}
# Визуальная работа в редакторе: доступна, только если запущено расширение
# VS Code (vscode-extension/) и vscode.enabled != false.
VSCODE_TOOLS = {
    "vscode_open", "vscode_close", "vscode_close_all",
    "vscode_reveal", "vscode_diff", "vscode_status",
}
# Инструменты, у которых аргумент path по умолчанию = корень проекта.
PATH_TOOLS = {"read_file", "read_range", "write_file", "edit_file", "list_dir",
              "grep", "read_image", "search_code", "file_outline",
              "read_symbol", "find_files"}


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
                           "(including .txt, .log and unknown types). Returns a flat "
                           "list; for grouped results with context use search_code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern"},
                    "path": {
                        "type": "string",
                        "description": "Root dir or one file, default '.'",
                    },
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
            "name": "read_image",
            "description": "Send an image file (screenshot, mockup, diagram, photo) "
                           "to the model. Use it when the task involves pictures, "
                           "UI screenshots or text inside an image; read_file is "
                           "useless for binary files. Supported: JPEG, PNG, GIF, "
                           "WebP (format detected by content).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "Image path (relative to project root)"},
                    "detail": {
                        "type": "string",
                        "description": "low = downscale to 512x512 (faster, cheaper), "
                                       "high/original/auto = original (default: "
                                       "vision.detail from config)",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_shell",
            "description": "Run a shell command (php -l, node --check, python -m "
                           "pytest, git status, etc.). Working dir = project root. "
                           "For Python use the interpreter reported in the system "
                           "prompt ('python' may be absent on macOS/Linux). "
                           "Timeout is configurable (tools.shell_timeout, default "
                           "60s). Returns exit code + stdout + stderr. Large output "
                           "is compressed to a digest (errors + head/tail); the full "
                           "log is saved in .agent-cache/output and can be read with "
                           "read_range or search_code.",
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
                           "blocked. Long pages are returned as excerpts (pass "
                           "query=<what you are looking for> to get the relevant "
                           "paragraphs); the full text is saved in .agent-cache/output.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "http(s) URL"},
                    "max_chars": {
                        "type": "integer",
                        "description": "Optional output limit in characters",
                    },
                    "query": {
                        "type": "string",
                        "description": "Keywords to extract relevant paragraphs "
                                       "(recommended for long pages and docs)",
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
    {
        "type": "function",
        "function": {
            "name": "vscode_open",
            "description": "Open a file in the VS Code editor in a new tab and put "
                           "the cursor on the given line, so the user can watch the "
                           "agent work. Requires the VS Code bridge extension. "
                           "Use it after creating or reading an important file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "File path (relative to project root)"},
                    "line": {"type": "integer",
                             "description": "Line to jump to (1-based, default 1)"},
                    "column": {"type": "integer",
                               "description": "Column (1-based, default 1)"},
                    "preview": {"type": "boolean",
                                "description": "Open as a temporary preview tab "
                                               "(default false — keeps the tab open)"},
                    "preserve_focus": {
                        "type": "boolean",
                        "description": "Open the tab without stealing focus from the "
                                       "terminal (default false — the editor is revealed)",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vscode_close",
            "description": "Close an editor tab in VS Code. Without path closes the "
                           "last tab opened by the agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "File whose tab to close (optional)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vscode_close_all",
            "description": "Close every editor tab that the agent opened in VS Code.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vscode_reveal",
            "description": "Reveal a file in the VS Code Explorer sidebar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "File path (relative to project root)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vscode_diff",
            "description": "Open a diff in VS Code between the current file and its "
                           "older version (side by side). Without `original` the "
                           "latest snapshot from .agent-cache/backups is used. "
                           "Use it to show the user exactly what changed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "File path (relative to project root)"},
                    "original": {"type": "string",
                                 "description": "Path to the old version "
                                                "(optional, default: latest snapshot)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vscode_status",
            "description": "Check whether the VS Code bridge (extension) is running.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Regex search across project files with optional "
                           "context, grouped by file and capped by max_results. "
                           "Returns a compact digest (how many hits/files, where) "
                           "instead of a dump of every match — prefer it over "
                           "reading whole files. fixed=true searches a literal "
                           "substring; files_only=true returns only file names.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex or literal"},
                    "path": {"type": "string", "description": "Root dir or one file, default '.'"},
                    "include": {"type": "string",
                                "description": "Extension filter ('.py'); '*' = all files"},
                    "context": {"type": "integer",
                                "description": "Context lines around each match"},
                    "max_results": {"type": "integer",
                                    "description": "How many matches to show (default 60)"},
                    "fixed": {"type": "boolean",
                              "description": "Treat pattern as plain substring"},
                    "ignore_case": {"type": "boolean"},
                    "files_only": {"type": "boolean",
                                   "description": "Return only matching file names"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_outline",
            "description": "Map of a file's symbols (classes, functions, methods, "
                           "selectors) with line ranges — read it before deciding "
                           "which lines to open with read_range. For a directory "
                           "returns a short outline of its code files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_symbols": {"type": "integer",
                                    "description": "Cap on listed symbols (default 200)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_symbol",
            "description": "Return the body of one symbol (class/function/method) "
                           "by name instead of the whole file. Finds the definition "
                           "in the given file or across the project.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Symbol name"},
                    "path": {"type": "string",
                             "description": "File or project dir, default '.'"},
                    "max_lines": {"type": "integer",
                                  "description": "Body lines shown (default 250)"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "diff_files",
            "description": "Unified diff of two files (only changed hunks, with "
                           "add/remove stats). Use it to compare a file with a "
                           "snapshot or two versions instead of reading both fully.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path_a": {"type": "string"},
                    "path_b": {"type": "string"},
                    "context": {"type": "integer", "description": "Context lines, default 3"},
                    "max_lines": {"type": "integer", "description": "Diff lines shown, default 400"},
                },
                "required": ["path_a", "path_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Find files by glob mask ('*.py', '**/test_*.py'), "
                           "skipping vendor/node_modules/build dirs. Much cheaper "
                           "than listing the tree.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob mask"},
                    "path": {"type": "string"},
                    "max_results": {"type": "integer", "description": "Default 100"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "project_map",
            "description": "Project tree with depth and entry limits — a compact "
                           "overview of the whole repository.",
            "parameters": {
                "type": "object",
                "properties": {
                    "depth": {"type": "integer", "description": "Default 2"},
                    "max_entries": {"type": "integer", "description": "Default 150"},
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
    "search_code": search_code,
    "file_outline": file_outline,
    "read_symbol": read_symbol,
    "diff_files": diff_files,
    "find_files": find_files,
    "project_map": project_map,
    "read_image": read_image,
    "run_shell": run_shell,
    "fetch_url": fetch_url,
    "web_search": web_search,
    "git_status": git_status,
    "git_diff": git_diff,
    "git_log": git_log,
    "vscode_open": vscode_open,
    "vscode_close": vscode_close,
    "vscode_close_all": vscode_close_all,
    "vscode_reveal": vscode_reveal,
    "vscode_diff": vscode_diff,
    "vscode_status": vscode_status,
}