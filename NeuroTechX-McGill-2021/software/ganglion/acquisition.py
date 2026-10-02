"""One local LSL inlet, continuously drained by a background thread."""
from collections import deque
import os
from pathlib import Path
import sys
import threading
import time


def lsl():
    framework = Path(sys.prefix) / "lsl.framework/Versions/A/lsl"
    if framework.exists():
        os.environ.setdefault("PYLSL_LIB", str(framework))
    try:
        import pylsl
        return pylsl
    except (ImportError, RuntimeError) as exc:
        raise ValueError("pylsl/liblsl 로딩 실패. software/ganglion/README.md의 설치 안내를 확인하세요.") from exc


def describe(info):
    return {"uid": info.uid(), "name": info.name(), "type": info.type(),
            "channels": info.channel_count(), "sampling_rate": info.nominal_srate(),
            "source_id": info.source_id()}


class Receiver:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.inlet = None
        self.info = None
        self.rows = deque(maxlen=30000)
        self.error = None
        self.last_received = 0.0

    def discover(self):
        return [describe(s) for s in lsl().resolve_streams(wait_time=2) if s.type() == "EEG"]

    def connect(self, uid):
        streams = lsl().resolve_byprop("uid", uid, timeout=3)
        if not streams:
            raise ValueError("선택한 스트림을 찾지 못했습니다. 다시 검색하세요.")
        info = streams[0]
        if info.channel_count() != 4 or info.type() != "EEG":
            raise ValueError("Ganglion의 4채널 EEG TimeSeries 스트림을 선택하세요.")
        if not 80 <= info.nominal_srate() <= 1000:
            raise ValueError("유효한 고정 샘플링 주파수가 필요합니다. TimeSeries 설정을 확인하세요.")
        self.disconnect()
        inlet = lsl().StreamInlet(info, max_buflen=30, recover=False)
        try:
            inlet.open_stream(timeout=3)
            correction = inlet.time_correction(timeout=3)
            xml = inlet.info(timeout=3).as_xml()
        except Exception:
            inlet.close_stream()
            raise
        self.inlet = inlet
        self.info = {**describe(info), "xml": xml, "time_correction": correction}
        self.error = None
        self.last_received = 0.0
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._read, args=(inlet, correction), daemon=True)
        self.thread.start()
        return self.status()

    def _read(self, inlet, correction):
        try:
            while not self.stop_event.is_set():
                samples, timestamps = inlet.pull_chunk(timeout=0.1, max_samples=1024)
                if samples:
                    with self.lock:
                        self.rows.extend((float(ts + correction), row) for ts, row in zip(timestamps, samples))
                        self.last_received = time.monotonic()
        except Exception as exc:
            self.error = str(exc)

    def status(self):
        with self.lock:
            age = time.monotonic() - self.last_received
            recent = [ts for ts, _ in self.rows if self.rows and ts >= self.rows[-1][0] - 2]
            rate = (len(recent) - 1) / (recent[-1] - recent[0]) if len(recent) > 1 and recent[-1] > recent[0] else None
        return {"connected": self.inlet is not None, "receiving": age < 1 and not self.error,
                "stream": self.info, "measured_rate_hz": rate, "error": self.error}

    def window(self, start, end):
        with self.lock:
            return [(ts, row) for ts, row in self.rows if start <= ts <= end]

    def disconnect(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)
            if self.thread.is_alive():
                raise ValueError("수신 스레드가 종료되지 않았습니다. 서버를 다시 시작하세요.")
        if self.inlet:
            self.inlet.close_stream()
        self.inlet = self.info = self.thread = None
        with self.lock:
            self.rows.clear()
        self.error = None
        self.last_received = 0.0
