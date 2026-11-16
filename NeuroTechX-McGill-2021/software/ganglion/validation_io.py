"""Read-only import of GUI exports and self-contained offline HTML reports."""
import csv
import html
import json
from pathlib import Path
import re

import numpy as np

from validation import analyze, dumps

ROOT = Path(__file__).resolve().parent


def load_recording(path):
    path = Path(path)
    if path.suffix == ".npz":
        with np.load(path, allow_pickle=False) as z:
            meta = json.loads(str(z["metadata"])) if "metadata" in z else {}
            fs = meta.get("stream", {}).get("sampling_rate", meta.get("sampling_rate", 200))
            return {"samples": z["samples"].copy(), "timestamps": z["timestamps"].copy(),
                    "arrivals": z["arrival_timestamps"].copy() if "arrival_timestamps" in z else None,
                    "fs": fs, "source": "gui" if meta.get("acquisition_source") == "brainflow" else "lsl",
                    "metadata": meta, "parse_issues": [], "path": str(path)}
    if not path.name.startswith(("OpenBCI-RAW", "BrainFlow-RAW")):
        raise ValueError("지원 입력: OpenBCI-RAW*.txt, BrainFlow-RAW*.csv, 앱 .npz. 일반 CSV의 열은 추측하지 않습니다.")
    samples, stamps, indices, parse_issues, markers = [], [], [], [], []
    fs, board, header, expected_width = None, None, None, None
    brainflow = path.name.startswith("BrainFlow-RAW")
    # Only the documented 15-column Ganglion BrainFlow export is supported.
    # Never silently reinterpret Cyton or a transposed data file as Ganglion.
    with path.open(encoding="utf-8-sig", errors="replace") as f:
        for line_no, line in enumerate(f, 1):
            if line.startswith("%"):
                m = re.search(r"Sample Rate\s*=\s*([\d.]+)", line)
                if m:
                    fs = float(m.group(1))
                if "Board =" in line:
                    board = line.split("=", 1)[1].strip()
                if "Number of channels" in line and not re.search(r"=\s*4\s*$", line):
                    raise ValueError("Ganglion 4채널 파일만 지원합니다.")
                continue
            if not line.strip():
                continue
            row = next(csv.reader([line], delimiter="\t" if "\t" in line else ","))
            row = [c.strip() for c in row]
            if row[0] == "Sample Index":
                header = row
                expected_width = len(row)
                if row[1:5] != [f"EXG Channel {i}" for i in range(4)] or "Timestamp" not in row:
                    raise ValueError("지원하지 않는 OpenBCI 헤더입니다.")
                continue
            try:
                if brainflow:
                    if len(row) != 15:
                        raise ValueError("Ganglion BrainFlow 열은 15개여야 함")
                    stamp_index = 13
                else:
                    if not header:
                        raise ValueError("헤더가 없음")
                    if len(row) != expected_width:
                        raise ValueError("헤더와 열 수가 다름")
                    stamp_index = header.index("Timestamp")
                values = [float(row[c]) for c in (1, 2, 3, 4)]
                stamp, index = float(row[stamp_index]), float(row[0])
                marker = float(row[14])
            except (ValueError, IndexError) as exc:
                parse_issues.append({"line": line_no, "reason": str(exc)})
                continue
            samples.append(values)
            stamps.append(stamp)
            indices.append(index)
            markers.append(marker)
    if not brainflow and (fs is None or not board or "Ganglion" not in board):
        raise ValueError("Ganglion 보드/샘플링 주파수 헤더를 확인할 수 없습니다.")
    return {"samples": np.asarray(samples, float).reshape(-1, 4), "timestamps": np.asarray(stamps),
            "arrivals": None, "fs": fs or 200., "source": "gui", "path": str(path),
            "metadata": {"board": board, "units": "uV", "brainflow_assumed_ganglion": brainflow},
            "sample_indices": np.asarray(indices), "markers": np.asarray(markers), "parse_issues": parse_issues}


def analyze_recording(path, channels=None, include_plot=True):
    data = load_recording(path)
    meta = data["metadata"]
    units = meta.get("setup", {}).get("units", "uV")
    result = analyze(data["samples"], data["timestamps"], data["fs"],
                     channels=channels, arrivals=data["arrivals"], source=data["source"],
                     units=units, include_plot=include_plot)
    result["parse_issues"] = data["parse_issues"]
    if data["parse_issues"]:
        result.update(eligible=False, spectral_valid=False)
        result["warnings"].append(f"읽을 수 없는 행 {len(data['parse_issues'])}개: 제거 후 시간축/주파수 판정은 유효하지 않습니다.")
    if "sample_indices" in data and len(data["sample_indices"]) > 1:
        ids = data["sample_indices"]
        steps, counts = np.unique(np.diff(ids), return_counts=True)
        result["packet_index"] = {"min": float(ids.min()), "max": float(ids.max()),
            "step_histogram": dict(zip(map(str, steps.tolist()), counts.tolist())),
            "note": "Ganglion은 두 샘플이 같은 패킷 번호를 공유할 수 있습니다. 펌웨어/범위를 확인하기 전 손실률로 환산하지 않습니다."}
    return {"file": str(Path(path).resolve()), "metadata": meta, "analysis": result}


def write_report(path, payload, title="Ganglion EEG 검증 보고서"):
    """Standalone report: no CDNs, network requests, or external assets."""
    js = (ROOT / "validation_static/report.js").read_text()
    css = (ROOT / "validation_static/style.css").read_text()
    data = dumps(payload).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    Path(path).write_text(f'<!doctype html><html lang="ko"><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>'
        f'<style>{css}</style><main><h1>{html.escape(title)}</h1><p>원시 자료는 보존하고, 문제 단계부터 다시 검사하세요. '
        f'자동 지표는 EEG의 신경성 기원이나 의료적 정상 여부를 판정하지 않습니다.</p><div id="report"></div></main>'
        f'<script id="report-data" type="application/json">{data}</script><script>{js}</script>'
        '<script>renderReport(document.getElementById("report"),JSON.parse(document.getElementById("report-data").textContent));</script></html>', encoding="utf-8")
