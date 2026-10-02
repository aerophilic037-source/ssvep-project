"""Local Ganglion SSVEP runner. Run this file, not the legacy dcp Flask app."""
import argparse
import atexit
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

from flask import Flask, jsonify, request
import numpy as np

from acquisition import Receiver, lsl
from decoder import decode

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text())


def create_app(receiver=None, output_dir=None, clock=None):
    app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 256 * 1024
    receiver = receiver or Receiver()
    output_dir = Path(output_dir or ROOT / "recordings")
    now = clock or (lambda: lsl().local_clock())
    operation_lock = threading.Lock()
    trial = None
    atexit.register(receiver.disconnect)

    @app.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(Exception)
    def failed(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        app.logger.exception("Request failed")
        return jsonify(error=f"작업 실패: {exc}"), 500

    @app.before_request
    def local_requests():
        # A local webpage must not start acquisition through a cross-origin POST.
        if request.method == "POST":
            if request.headers.get("Origin") not in (None, request.host_url.rstrip("/")):
                return jsonify(error="다른 출처의 요청은 허용하지 않습니다."), 403
            if not request.is_json:
                return jsonify(error="JSON 요청이 필요합니다."), 415

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/config")
    def config():
        return jsonify(CONFIG)

    @app.get("/api/status")
    def status():
        return jsonify(receiver.status())

    @app.get("/api/streams")
    def streams():
        return jsonify(streams=receiver.discover())

    @app.post("/api/connect")
    def connect():
        nonlocal trial
        with operation_lock:
            if trial:
                raise ValueError("먼저 진행 중인 측정을 중단하세요.")
            uid = request.get_json().get("uid")
            if not isinstance(uid, str) or not uid:
                raise ValueError("스트림을 선택하세요.")
            return jsonify(receiver.connect(uid))

    @app.post("/api/disconnect")
    def disconnect():
        nonlocal trial
        with operation_lock:
            trial = None
            receiver.disconnect()
            return jsonify(ok=True)

    @app.post("/api/trial/start")
    def start():
        nonlocal trial
        with operation_lock:
            if trial and now() - trial["start_lsl"] < 15:
                raise ValueError("측정이 이미 진행 중입니다.")
            if not receiver.status()["receiving"]:
                raise ValueError("EEG 수신이 없습니다. GUI의 두 Start 버튼과 연결 상태를 확인하세요.")
            body = request.get_json()
            channels = body.get("channels", [])
            if not isinstance(channels, list) or not channels or any(type(c) is not int or c not in range(4) for c in channels) or len(set(channels)) != len(channels):
                raise ValueError("CH1~CH4 중 연결된 채널을 선택하세요.")
            target = body.get("target")
            if target not in [None] + [t["id"] for t in CONFIG["targets"]]:
                raise ValueError("잘못된 정답 자극입니다.")
            trial = {"id": uuid4().hex, "start_lsl": now(), "channels": channels,
                     "target": target, "stream": receiver.info, "config": CONFIG,
                     "created_utc": datetime.now(timezone.utc).isoformat()}
            return jsonify(id=trial["id"], duration_seconds=CONFIG["duration_seconds"])

    @app.post("/api/trial/abort")
    def abort():
        nonlocal trial
        with operation_lock:
            trial = None
            return jsonify(ok=True)

    @app.post("/api/trial/stop")
    def stop():
        nonlocal trial
        with operation_lock:
            body = request.get_json()
            if not trial or body.get("id") != trial["id"]:
                raise ValueError("진행 중인 측정 ID가 일치하지 않습니다.")
            current, trial = trial, None
            end = now()
            elapsed = end - current["start_lsl"]
            # Allow the last network chunk to arrive, but exclude samples after end.
            time.sleep(0.25)
            rows = receiver.window(current["start_lsl"], end)
            ts = np.asarray([r[0] for r in rows], dtype=float)
            samples = np.asarray([r[1] for r in rows], dtype=float).reshape(-1, 4)
            mask = ts >= current["start_lsl"] + CONFIG["settle_seconds"]
            result = decode(samples[mask], ts[mask], current["stream"]["sampling_rate"],
                            current["channels"], CONFIG, CONFIG["duration_seconds"] - CONFIG["settle_seconds"])
            frames = body.get("frame_times_ms", [])
            if not isinstance(frames, list) or not 2 <= len(frames) <= 3000 or any(type(v) not in (int, float) or not np.isfinite(v) for v in frames):
                frames = []
            gaps = np.diff(frames)
            timing_ok = len(gaps) > 0 and np.all(gaps > 0)
            result["display_fps"] = float(1000 / np.median(gaps)) if timing_ok else None
            result["max_frame_gap_ms"] = float(gaps.max()) if timing_ok else None
            if not timing_ok or frames[-1] - frames[0] < 0.95 * CONFIG["duration_seconds"] * 1000 or gaps.max() > 100 or result["display_fps"] < 50:
                result.update(prediction=None, reason="자극 프레임이 부족하거나 지연되었습니다. 활성 탭과 화면 주사율을 확인하세요.")
            if not CONFIG["duration_seconds"] - 0.2 <= elapsed <= CONFIG["duration_seconds"] + 1.5:
                result.update(prediction=None, reason="측정 구간 시간이 설정과 다릅니다. 다시 시도하세요.")
            if not receiver.status()["receiving"]:
                result.update(prediction=None, reason="측정 중 EEG 수신이 중단되었습니다.")
            result["target"] = current["target"]
            result["correct"] = result["prediction"] == current["target"] if current["target"] else None
            current.update(end_lsl=end, elapsed_seconds=elapsed, result=result,
                           synchronization="HTTP start/stop; browser frames are relative; no physical display onset measurement")
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + current["id"] + ".npz"
            # One self-contained file, with no pickle/object arrays required on read.
            np.savez_compressed(output_dir / filename, samples=samples, timestamps=ts,
                                frame_times_ms=np.asarray(frames), metadata=json.dumps(current, ensure_ascii=False))
            return jsonify(**result, recording=filename)

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    create_app().run(host="127.0.0.1", port=args.port, debug=False, threaded=True)
