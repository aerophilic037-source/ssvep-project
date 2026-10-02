"""Read-only LSL discovery/receipt check. No recording or visual stimulation."""
import argparse
import json
import time

from acquisition import Receiver

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--uid", help="Connect to this UID and observe receipt for five seconds")
    args = parser.parse_args()
    receiver = Receiver()
    try:
        if not args.uid:
            streams = receiver.discover()
            print(json.dumps(streams, indent=2, ensure_ascii=False))
            if not streams:
                print("EEG 스트림 없음: GUI에서 LSL / TimeSeries / EEG 및 두 Start 버튼을 확인하세요.")
        else:
            receiver.connect(args.uid)
            time.sleep(5)
            state = receiver.status()
            if state['stream']:
                state['stream'].pop('xml', None)
            print(json.dumps(state, indent=2, ensure_ascii=False))
            if not state['receiving']:
                raise SystemExit("수신 없음")
    finally:
        receiver.disconnect()
