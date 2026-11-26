"""Native BLE receiver. Raw BrainFlow timestamps are retained separately."""
import time
import threading
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)
from acquisition import Receiver


class NativeReceiver(Receiver):
    def __init__(self):
        super().__init__()
        self.board = None

    def discover(self):
        # Discovery/connection is performed by BrainFlow when Connect is pressed.
        return [{'uid': 'native', 'name': 'Ganglion · Mac Bluetooth',
                 'channels': 4, 'sampling_rate': 200, 'type': 'EEG'}]

    def connect(self, uid):
        if uid != 'native':
            raise ValueError('내장 Bluetooth 연결을 선택하세요.')
        from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds
        self.disconnect()
        log_dir = Path(__file__).resolve().parent / 'native_recordings' / 'connection_logs'
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.log')
        BoardShim.enable_dev_board_logger()
        BoardShim.set_log_file(str(log_path))
        params = BrainFlowInputParams()
        params.other_info = 'fw:3'
        params.timeout = 15
        board = BoardShim(BoardIds.GANGLION_NATIVE_BOARD.value, params)
        stage = 'prepare_session'
        try:
            logger.warning('Ganglion connecting; BrainFlow log: %s', log_path)
            board.prepare_session()
            stage = 'is_prepared after prepare_session'
            if not board.is_prepared():
                raise RuntimeError('prepare_session 반환 후 세션이 준비되지 않았습니다.')
            stage = 'start_stream'
            board.start_stream(100000)
        except Exception as exc:
            self.error = f'{stage} 실패: {exc}. 상세 로그: {log_path}'
            logger.exception(self.error)
            try:
                if board.is_prepared():
                    board.release_session()
            except Exception:
                logger.exception('실패한 Ganglion 세션 정리 오류')
            raise ValueError(self.error) from exc
        self.board = board
        self.inlet = True
        self.info = dict(self.discover()[0], source_id='brainflow-native',
                         acquisition_source='brainflow-native', firmware=3,
                         timestamp_clock='monotonic offset from Unix; raw Unix retained')
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._read_native, daemon=True)
        self.thread.start()
        return self.status()

    def _read_native(self):
        from brainflow.board_shim import BoardShim, BoardIds
        bid = BoardIds.GANGLION_NATIVE_BOARD.value
        eeg = BoardShim.get_eeg_channels(bid)[:4]
        stamp = BoardShim.get_timestamp_channel(bid)
        offset = time.monotonic() - time.time()
        try:
            while not self.stop_event.wait(.02):
                data = self.board.get_board_data()
                received = time.monotonic()
                with self.lock:
                    for i in range(data.shape[1]):
                        raw = float(data[stamp, i]); ts = raw + offset
                        row = data[eeg, i].tolist()
                        self.sequence += 1
                        self.records.append((self.sequence, ts, received, raw, row))
                        self.rows.append((ts, row))
                    if data.shape[1]:
                        self.last_received = received
        except Exception as exc:
            self.error = str(exc)

    def disconnect(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
            if self.thread.is_alive():
                raise ValueError('수집 스레드 종료 대기 중입니다. 다시 시도하세요.')
        if self.board:
            try:
                self.board.stop_stream()
            finally:
                self.board.release_session()
                self.board = None
        self.inlet = self.info = self.thread = None
        with self.lock:
            self.rows.clear(); self.records.clear(); self.sequence = 0
        self.error = None
        self.last_received = 0
