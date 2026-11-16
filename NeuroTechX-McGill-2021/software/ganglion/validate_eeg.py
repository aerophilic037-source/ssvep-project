"""Offline EEG diagnostics; original recordings are never edited."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np

from validation import analyze, dumps
from validation_io import analyze_recording, write_report


def audit(paths, dest, channels):
    files = []
    for input_path in paths:
        path = Path(input_path).expanduser()
        if path.is_dir():
            files.extend(path.rglob("OpenBCI-RAW*.txt"))
            files.extend(path.rglob("*.npz"))
        else:
            files.append(path)
    files = sorted(set(files))
    if not files:
        raise ValueError("입력 파일을 찾지 못했습니다.")
    dest.mkdir(parents=True, exist_ok=True)
    results = []
    for i, path in enumerate(files):
        try:
            result = analyze_recording(path, channels)
            a = result["analysis"]
            rate = a["timing"].get("timestamp_rate_hz")
            print(f"{path.name}: {a['timing']['count']} samples, {rate:.2f} Hz, {'검토 가능' if a['eligible'] else '확인 필요'}" if rate else f"{path.name}: 데이터 부족")
            result['report_file'] = f"{i+1:03d}_{path.stem}.html"
            write_report(dest / result['report_file'], result, path.name)
            # Summary report omits bulky traces, individual HTML retains them.
            result["analysis"].pop("plot", None)
            results.append(result)
        except (ValueError, OSError, KeyError) as exc:
            results.append({"file": str(path), "error": str(exc)})
            print(f"{path.name}: ERROR {exc}")
    payload = {"created_local": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(), "files": results}
    (dest / "audit.json").write_text(dumps(payload), encoding="utf-8")
    write_report(dest / "index.html", payload, "기존 EEG 기록 감사 — 시간축·전극·잡음")
    print(f"보고서: {(dest / 'index.html').resolve()}")


def demo(dest):
    """Known signals exercise success AND failure paths, never a hardware test."""
    dest.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20261114)
    t = np.arange(4000) / 200
    x = rng.normal(0, 4, (len(t), 4))
    cases = {"SYNTHETIC_clean_12Hz": (x + 12*np.sin(2*np.pi*12*t[:, None]), t),
             "SYNTHETIC_flat": (np.zeros_like(x), t),
             "SYNTHETIC_line_60Hz": (x + 300*np.sin(2*np.pi*60*t[:, None]), t),
             "SYNTHETIC_wrong_rate_83Hz": (x, t*2.4),
             "SYNTHETIC_saturation": (np.clip(x*5000, -15686, 15686), t)}
    bad_t = t.copy(); bad_t[1000] = bad_t[999] - .01
    cases["SYNTHETIC_timestamp_reversal"] = (x, bad_t)
    outputs = []
    for name, (samples, stamps) in cases.items():
        meta = {"sampling_rate": 200, "synthetic": True, "note": "소프트웨어 데모: 실제 EEG/보드 검증 아님"}
        np.savez_compressed(dest / (name+'.npz'), samples=samples, timestamps=stamps, metadata=dumps(meta))
        report = {"file": name, "metadata": meta, "analysis": analyze(samples, stamps, channels=[0])}
        report['report_file'] = name+'.html'
        write_report(dest/(name+'.html'), report, name)
        report["analysis"].pop("plot", None)
        outputs.append(report)
    write_report(dest / "index.html", {"files": outputs}, "SYNTHETIC — 소프트웨어 검사 예제 (실제 EEG 아님)")
    print(f"합성 데모: {(dest/'index.html').resolve()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("audit", help="GUI RAW 파일/폴더 또는 앱 NPZ 읽기")
    p.add_argument("paths", nargs="+")
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent/"validation_reports/audit")
    p.add_argument("--channels", nargs="+", type=int, default=[1], help="실제 채널 번호 1~4; 기본 CH1")
    p = sub.add_parser("demo", help="정상/실패 합성 신호 보고서 만들기")
    p.add_argument("--out", type=Path, default=Path(__file__).resolve().parent/"validation_reports/demo")
    args = parser.parse_args()
    if args.command == "audit":
        if any(c not in range(1,5) for c in args.channels):
            parser.error("--channels는 1~4입니다.")
        audit(args.paths, args.out, [c-1 for c in args.channels])
    else:
        demo(args.out)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        sys.exit(1)
