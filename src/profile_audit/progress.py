from __future__ import annotations

import shutil
import sys
import time


class ProgressTracker:
    def __init__(self, total: int = 0, *, stream=None) -> None:
        self.total = max(total, 0)
        self.completed = 0
        self.current = "Starting"
        self.stream = stream if stream is not None else sys.stderr
        self._interactive = bool(getattr(self.stream, "isatty", lambda: False)())
        self._started_at = time.monotonic()
        self._last_rendered_len = 0

    def add_total(self, amount: int) -> None:
        if amount <= 0:
            return
        self.total += amount
        self.render()

    def update(self, message: str) -> None:
        self.current = message
        self.render()

    def advance(self, message: str | None = None, step: int = 1) -> None:
        if message:
            self.current = message
        self.completed = min(self.completed + step, self.total) if self.total else self.completed + step
        self.render()

    def finish(self, message: str = "Done") -> None:
        if self.total:
            self.completed = self.total
        self.current = message
        self.render(final=True)

    def render(self, *, final: bool = False) -> None:
        elapsed = time.monotonic() - self._started_at
        prefix = self._format_prefix(elapsed)
        line = f"{prefix} {self.current}"
        if self._interactive:
            width = shutil.get_terminal_size(fallback=(100, 20)).columns
            rendered = line[: max(width - 1, 1)]
            padding = max(self._last_rendered_len - len(rendered), 0)
            end = "\n" if final else "\r"
            self.stream.write(rendered + (" " * padding) + end)
            self.stream.flush()
            self._last_rendered_len = 0 if final else len(rendered)
            return
        self.stream.write(line + "\n")
        self.stream.flush()

    def _format_prefix(self, elapsed: float) -> str:
        if self.total > 0:
            ratio = min(max(self.completed / self.total, 0.0), 1.0)
            width = 20
            filled = int(ratio * width)
            bar = "#" * filled + "-" * (width - filled)
            percent = int(ratio * 100)
            return f"[{bar}] {self.completed}/{self.total} {percent:3d}% {self._format_elapsed(elapsed)}"
        return f"[{'-' * 20}] {self.completed} steps {self._format_elapsed(elapsed)}"

    @staticmethod
    def _format_elapsed(elapsed: float) -> str:
        total_seconds = int(elapsed)
        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
