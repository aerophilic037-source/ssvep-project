"""Optional 30 s direct Ganglion capture to isolate GUI from hardware/driver.

Close OpenBCI GUI before running. Does not flash firmware or change sample rate.
The default route uses the BLED112 dongle. Native BLE is an explicit alternative.
"""
import argparse
from datetime import datetime, timezone
import importlib.metadata
from pathlib import Path
import time
from uuid import uuid4

import numpy as np

from validation import analyze, dumps
from validation_io import write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=["dongle", "native", "synthetic"], default="dongle")
    parser.add_argument("--serial-port", help="macOS: /dev/cu.usbmodem... (동글 경로 직접 확인)")
    parser.add_argument("--mac", default="", help="GUI 로그에서 확인한 대상 보드 주소")
    parser.add_argument("--firmware", choices=[2,3], type=int, default=3)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent/"validation_reports/direct")
    args = parser.parse_args()
    if not 5 <= args.seconds <= 120:
        parser.error("--seconds는 5~120 범위입니다.")
    if args.transport == "dongle" and not args.serial_port:
        parser.error("동글 모드는 --serial-port가 필요합니다. GUI를 종료하고 /dev/cu.usbmodem* 경로를 확인하세요.")
    try:
        from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds
    except ImportError:
        parser.error("별도 환경에 requirements-brainflow.txt를 설치하세요. docs/MORNING_GUIDE.html 참고.")
    args.out.mkdir(parents=True, exist_ok=True)
    ident = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_")+uuid4().hex[:8]
    stem = args.out / f"{'SYNTHETIC' if args.transport=='synthetic' else 'DIRECT'}_{ident}"
    BoardShim.enable_dev_board_logger()
    BoardShim.set_log_file(str(stem)+".log")
    params=BrainFlowInputParams()
    params.mac_address=args.mac
    if args.transport=="dongle":
        board_id=BoardIds.GANGLION_BOARD.value
        params.serial_port=args.serial_port
    elif args.transport=="native":
        board_id=BoardIds.GANGLION_NATIVE_BOARD.value
        params.other_info=f"fw:{args.firmware}"
    else:
        board_id=BoardIds.SYNTHETIC_BOARD.value
    board=BoardShim(board_id,params)
    blocks,receipts=[],[]
    running=False
    interrupted=False
    started=None
    failure=None
    try:
        board.prepare_session()
        board.start_stream(100000)
        running=True
        started=time.monotonic()
        print(f"{args.transport}: {args.seconds:g}초 수집. GUI는 종료 상태여야 합니다. Ctrl+C는 부분 저장.",flush=True)
        while time.monotonic()-started<args.seconds:
            values=board.get_board_data()
            if values.shape[1]:
                blocks.append(values)
                receipts.extend([time.time()]*values.shape[1])
            time.sleep(.02)
    except KeyboardInterrupt:
        interrupted=True
    except Exception as exc:
        failure=str(exc)
    finally:
        elapsed=time.monotonic()-started if started is not None else 0
        if running:
            try:
                board.stop_stream()
                tail=board.get_board_data()
                if tail.shape[1]:
                    blocks.append(tail);receipts.extend([time.time()]*tail.shape[1])
            except Exception as exc:
                failure=f"{failure or ''} stop/drain: {exc}"
        if board.is_prepared():
            try:
                board.release_session()
            except Exception as exc:
                failure=f"{failure or ''} release: {exc}"
    if not blocks:
        raise SystemExit(f"수집 데이터 없음. 로그: {stem}.log\n{failure or ''}")
    raw=np.concatenate(blocks,axis=1)
    eeg=BoardShim.get_eeg_channels(board_id)[:4]
    fs=BoardShim.get_sampling_rate(board_id)
    x=raw[eeg].T
    timestamps=raw[BoardShim.get_timestamp_channel(board_id)]
    arrivals=np.asarray(receipts)
    meta={"acquisition_source":"brainflow", "sampling_rate":fs, "units":"uV",
          "brainflow_version":importlib.metadata.version('brainflow'), "board_id":board_id,
          "transport":args.transport,"synthetic":args.transport=='synthetic',
          "serial_port":args.serial_port,"mac_address":args.mac,
          "requested_firmware_native":args.firmware if args.transport=='native' else None,
          "requested_seconds":args.seconds,
          "elapsed_seconds":elapsed,"aborted":interrupted,"failure":failure,
          "timestamp_clock":"BrainFlow Unix timestamps; receipt timestamps=time.time; elapsed=monotonic",
          "note":"GUI 없이 직접 수집. EEG 4채널과 보드 전체 행을 함께 저장. firmware/sample-rate 변경 안 함."}
    np.savez_compressed(str(stem)+'.npz',samples=x,timestamps=timestamps,arrival_timestamps=arrivals,
                        board_data=raw,metadata=dumps(meta))
    result=analyze(x,timestamps,fs,channels=[0],arrivals=arrivals,elapsed=elapsed,source="gui")
    if interrupted or failure:
        result["eligible"]=False
        result["warnings"].append("중단/수집 오류가 있는 부분 기록입니다.")
    write_report(str(stem)+'.html',{"file":str(stem)+'.npz',"metadata":meta,"analysis":result},"직접 수집 비교 — "+args.transport)
    print(f"{len(x)}샘플 / {elapsed:.2f}초 = {len(x)/elapsed:.2f} Hz (도착 기준)")
    print(f"보고서: {stem}.html")
    if failure:
        raise SystemExit(f"부분 기록 저장 후 오류 종료: {failure}")


if __name__=='__main__':
    main()
