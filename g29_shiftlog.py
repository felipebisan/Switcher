"""Bounded asynchronous local diagnostics; no disk I/O on the HID thread."""
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import queue
import threading

class ShiftLog:
    def __init__(self, path):
        self.path=path;self.queue=queue.Queue(maxsize=512);self.stop=threading.Event();self.thread=None
        if path:
            self.thread=threading.Thread(target=self.run,daemon=True,name='Shift timing log')
            self.thread.start()

    def record(self, **record):
        if self.thread and not self.stop.is_set():
            try:self.queue.put_nowait(record)
            except queue.Full:pass

    def run(self):
        handler=None
        try:
            Path(self.path).parent.mkdir(parents=True,exist_ok=True)
            handler=RotatingFileHandler(self.path,maxBytes=262144,backupCount=2,encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(message)s'))
            while not self.stop.is_set() or not self.queue.empty():
                try:row=self.queue.get(timeout=.1)
                except queue.Empty:continue
                handler.emit(logging.LogRecord('shift',logging.INFO,'',0,json.dumps(row),(),None))
        except OSError:pass
        finally:
            if handler:handler.close()

    def close(self):
        self.stop.set()
        if self.thread:self.thread.join(timeout=1)
