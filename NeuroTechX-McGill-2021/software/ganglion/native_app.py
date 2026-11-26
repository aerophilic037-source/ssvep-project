"""Progressive SSVEP UI using direct Ganglion native BLE, no GUI/LSL."""
import argparse
import time
from pathlib import Path
from native_receiver import NativeReceiver
from validation_app import create_app

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8004)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    app = create_app(receiver=NativeReceiver(), clock=time.monotonic,
                     output_dir=root/'native_recordings', native=True)
    app.run(host='127.0.0.1', port=args.port, threaded=True, debug=False)
