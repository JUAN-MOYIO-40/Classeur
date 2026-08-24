from __future__ import annotations

from pathlib import Path
import queue

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    FileSystemEventHandler = object
    Observer = None

from .filesystem import is_ignored_file


class WatchEventHandler(FileSystemEventHandler):
    def __init__(self, event_queue: queue.Queue):
        super().__init__()
        self.event_queue = event_queue

    def _enqueue(self, path: str | None) -> None:
        if path:
            candidate = Path(path)
            if not is_ignored_file(candidate):
                self.event_queue.put(candidate)

    def on_created(self, event) -> None:
        if not event.is_directory:
            self._enqueue(event.src_path)

    def on_modified(self, event) -> None:
        if not event.is_directory:
            self._enqueue(event.src_path)

    def on_moved(self, event) -> None:
        if not event.is_directory:
            self._enqueue(event.dest_path)
