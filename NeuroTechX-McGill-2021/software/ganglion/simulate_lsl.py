"""Explicitly synthetic LSL source for testing the complete software path."""
import argparse
import time
from uuid import uuid4

import numpy as np

from acquisition import lsl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frequency", type=float, default=12)
    parser.add_argument("--mode", choices=["clean", "flat", "line", "reversal", "slow"], default="clean")
    parser.add_argument("--seconds", type=float, default=300)
    args = parser.parse_args()
    if not 1 <= args.frequency <= 40 or not 1 <= args.seconds <= 3600:
        parser.error("frequency 1~40 Hz, seconds 1~3600")
    lib = lsl()
    name = "GANGLION-SYNTHETIC-TEST-"+args.mode
    info = lib.StreamInfo(name, "EEG", 4, 200, "float32", uuid4().hex)
    info.desc().append_child_value("synthetic", "true")
    for i in range(4):
        ch = info.desc().append_child("channel")
        ch.append_child_value("label", f"SIM{i+1}")
        ch.append_child_value("unit", "uV")
    outlet = lib.StreamOutlet(info)
    rng = np.random.default_rng(42)
    start, index = lib.local_clock(), 0
    actual = 83.333333 if args.mode == "slow" else 200
    print(f"{name} — 합성 신호입니다. 실제 보드/전극 검증이 아닙니다. Ctrl+C 종료.", flush=True)
    try:
        while lib.local_clock()-start < args.seconds:
            stamp = start+index/actual
            if stamp > lib.local_clock():
                time.sleep(.001)
                continue
            t = index/200
            row = rng.normal(0, 3, 4)+12*np.sin(2*np.pi*args.frequency*t+np.arange(4)*.3)
            if args.mode == "flat":
                row *= 0
            if args.mode == "line":
                row += 400*np.sin(2*np.pi*60*t)
            if args.mode == "reversal" and index%100 == 0:
                stamp -= .02
            outlet.push_sample(row.tolist(), timestamp=stamp)
            index += 1
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
