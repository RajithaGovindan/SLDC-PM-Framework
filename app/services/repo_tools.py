"""Read-only access to a project's source repository, offered to Claude as tools during a revision.

Claude can list folders, search and read text files under the project's target repository, and nothing else:
paths are confined to the repository root, only source-like text files are visible, and secret-bearing files
(.env*, keys, credentials) are refused. In a git repository only tracked files are visible, so untracked dumps
and local config never leave the machine.
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path

TEXT_SUFFIXES = {".py", ".html", ".htm", ".jinja", ".j2", ".js", ".ts", ".tsx", ".jsx", ".css", ".scss", ".sql",
                 ".md", ".txt", ".rst", ".yaml", ".yml", ".toml", ".json", ".ini", ".cfg", ".conf", ".sh", ".ps1",
                 ".go", ".java", ".kt", ".cs", ".rb", ".php", ".vue", ".svelte", ".xml"}
TEXT_NAMES = {"Dockerfile", "Makefile", "Procfile", "requirements.txt", "requirements-dev.txt"}
DENY = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "*pgpass*", "*credentials*", "*.secret",
        "*secrets.*")
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", "dist", "build"}
MAX_FILE_BYTES = 400_000
MAX_SEARCH_HITS = 80
MAX_READ_LINES = 400
MAX_RESULT_CHARS = 24_000


class RepoToolError(ValueError):
    pass


class RepoReader:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise RepoToolError(f"Repository folder not found: {root}")
        self.files_read: list[str] = []
        self._files: list[str] | None = None

    # ------------------------------------------------------------------ visibility
    @staticmethod
    def _visible_name(rel: str) -> bool:
        name = rel.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatch(name.lower(), pat) for pat in DENY):
            return False
        return name in TEXT_NAMES or Path(name).suffix.lower() in TEXT_SUFFIXES

    def files(self) -> list[str]:
        """Relative POSIX paths of every visible file (git-tracked files when the root is a git repo)."""
        if self._files is not None:
            return self._files
        rels: list[str] = []
        if (self.root / ".git").exists():
            try:
                out = subprocess.run(["git", "-C", str(self.root), "ls-files", "-z"], capture_output=True,
                                     timeout=30, check=True).stdout.decode("utf-8", "replace")
                rels = [p for p in out.split("\0") if p]
            except (OSError, subprocess.SubprocessError):
                rels = []
        if not rels:
            for p in self.root.rglob("*"):
                if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(self.root).parts):
                    rels.append(p.relative_to(self.root).as_posix())
        self._files = sorted(r for r in rels if self._visible_name(r)
                             and (self.root / r).is_file() and (self.root / r).stat().st_size <= MAX_FILE_BYTES)
        return self._files

    def _resolve(self, rel: str) -> tuple[str, Path]:
        rel = (rel or "").strip().replace("\\", "/").lstrip("/")
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise RepoToolError("Path is outside the repository.")
        return p.relative_to(self.root).as_posix() if p != self.root else "", p

    # ------------------------------------------------------------------ tools
    def list_dir(self, path: str = "") -> str:
        rel, p = self._resolve(path)
        if not p.is_dir():
            raise RepoToolError(f"Not a folder: {path}")
        prefix = f"{rel}/" if rel else ""
        dirs, files = set(), []
        for f in self.files():
            if not f.startswith(prefix):
                continue
            rest = f[len(prefix):]
            if "/" in rest:
                dirs.add(rest.split("/", 1)[0] + "/")
            else:
                files.append(rest)
        entries = sorted(dirs) + sorted(files)
        if not entries:
            return "(no visible files)"
        shown = entries[:300]
        more = f"\n... {len(entries) - 300} more" if len(entries) > 300 else ""
        return "\n".join(shown) + more

    def read_file(self, path: str, start_line: int = 1, max_lines: int = 250) -> str:
        rel, p = self._resolve(path)
        if rel not in set(self.files()):
            raise RepoToolError(f"Not a readable source file: {path} (use list_dir or search_code to find files)")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line))
        count = max(1, min(int(max_lines), MAX_READ_LINES))
        chunk = lines[start - 1:start - 1 + count]
        if rel not in self.files_read:
            self.files_read.append(rel)
        body = "\n".join(f"{n}\t{line}" for n, line in enumerate(chunk, start))
        tail = f"\n[lines {start}-{start + len(chunk) - 1} of {len(lines)}]"
        return _cap(body + tail)

    def search_code(self, pattern: str, path: str = "", glob: str = "") -> str:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise RepoToolError(f"Invalid regular expression: {exc}") from exc
        rel, _ = self._resolve(path)
        prefix = f"{rel}/" if rel else ""
        hits = []
        for f in self.files():
            if prefix and not (f == rel or f.startswith(prefix)):
                continue
            if glob and not fnmatch.fnmatch(f.rsplit("/", 1)[-1], glob) and not fnmatch.fnmatch(f, glob):
                continue
            try:
                text = (self.root / f).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f}:{n}: {line.strip()[:240]}")
                    if len(hits) >= MAX_SEARCH_HITS:
                        return _cap("\n".join(hits) + f"\n[stopped at {MAX_SEARCH_HITS} matches; narrow the search]")
        return _cap("\n".join(hits)) if hits else "No matches."

    def run(self, name: str, args: dict) -> str:
        """Validate the tool input and run it. Raises RepoToolError on bad input."""
        if not isinstance(args, dict):
            raise RepoToolError("Tool input must be an object.")
        spec = TOOL_ARGS.get(name)
        if spec is None:
            raise RepoToolError(f"Unknown tool: {name}")
        clean = {}
        for key, (typ, required) in spec.items():
            if key not in args:
                if required:
                    raise RepoToolError(f"Missing required field: {key}")
                continue
            if not isinstance(args[key], typ) or isinstance(args[key], bool):
                raise RepoToolError(f"Field {key} must be {typ.__name__}.")
            clean[key] = args[key]
        return getattr(self, name)(**clean)


def _cap(text: str) -> str:
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + "\n[truncated]"


TOOL_ARGS: dict[str, dict[str, tuple[type, bool]]] = {
    "list_dir": {"path": (str, False)},
    "read_file": {"path": (str, True), "start_line": (int, False), "max_lines": (int, False)},
    "search_code": {"pattern": (str, True), "path": (str, False), "glob": (str, False)},
}

TOOL_DEFS = [
    {"name": "list_dir", "eager_input_streaming": True,
     "description": "List the files and sub-folders of a folder in the project's source repository (read-only). "
                    "Use an empty path for the repository root.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "Folder path relative to the repository root, e.g. 'app/routes'."}},
         "additionalProperties": False}},
    {"name": "search_code", "eager_input_streaming": True,
     "description": "Search the repository's source files line by line with a regular expression (Python syntax). "
                    "Returns 'path:line: text' for up to 80 matches. Use it to find functions, routes, columns, "
                    "templates and the code a change concerns.",
     "input_schema": {"type": "object", "properties": {
         "pattern": {"type": "string", "description": "Regular expression, e.g. 'def view\\\\(|fully_received'."},
         "path": {"type": "string", "description": "Optional folder or file to limit the search to."},
         "glob": {"type": "string", "description": "Optional file-name filter, e.g. '*.py' or '*.html'."}},
         "required": ["pattern"], "additionalProperties": False}},
    {"name": "read_file", "eager_input_streaming": True,
     "description": "Read lines of a source file in the repository, numbered. Reads up to 400 lines per call; "
                    "use start_line to page through long files.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string", "description": "File path relative to the repository root."},
         "start_line": {"type": "integer", "description": "First line to read (1-based). Default 1."},
         "max_lines": {"type": "integer", "description": "Number of lines to read, at most 400. Default 250."}},
         "required": ["path"], "additionalProperties": False}},
]
