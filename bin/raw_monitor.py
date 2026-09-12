#!/usr/bin/env python3
"""低レイテンシ・自動再接続シリアルモニタ。

`esphome logs` は接続が切れると(1) 一切再接続しない、
(2) 仮に外側でループさせても毎回ESPHomeのCLIプロセスを丸ごと
起動し直す(Python/esphomeパッケージのimportコストが乗る)ため、
再起動ループの周期がそれより短いボードでは何も見えない。

これはプロセスを起動しっぱなしにして、シリアルポートのopen/closeだけを
高速にリトライする(プロセス起動コストなし、リトライ間隔は数十ms)。
再起動ループの一部のサイクルだけでも捕まえられれば、rst:行や
Guru Meditationのbacktraceが見られるはず。

使い方:
    raw_monitor.py [device] [--baud 115200] [--log path] [--retry-interval 0.02]

deviceを省略すると /dev/ttyACM* /dev/ttyUSB* を毎回スキャンする。
"""
from __future__ import annotations

import argparse
import glob
import sys
import time

import serial


def find_port() -> str | None:
    candidates = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    return candidates[0] if candidates else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("device", nargs="?", default=None, help="シリアルポート(省略時は自動スキャン)")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--log", default=None, help="生ログの追記先ファイル")
    parser.add_argument(
        "--retry-interval",
        type=float,
        default=0.02,
        help="ポートが開けない/切れた時のリトライ間隔(秒)",
    )
    args = parser.parse_args()

    log_fh = open(args.log, "ab", buffering=0) if args.log else None

    print(
        f"[raw_monitor] baud={args.baud} log={args.log or '(none)'} "
        f"device={args.device or '(auto-scan)'}  Ctrl+Cで終了",
        file=sys.stderr,
    )

    last_port: str | None = None
    try:
        while True:
            port = args.device or find_port()
            if port is None:
                time.sleep(args.retry_interval)
                continue
            try:
                with serial.Serial(port, args.baud, timeout=0.05) as ser:
                    if port != last_port:
                        print(f"[raw_monitor] connected: {port}", file=sys.stderr)
                        last_port = port
                    while True:
                        chunk = ser.read(ser.in_waiting or 1)
                        if chunk:
                            sys.stdout.buffer.write(chunk)
                            sys.stdout.buffer.flush()
                            if log_fh:
                                log_fh.write(chunk)
            except (serial.SerialException, OSError):
                last_port = None
                time.sleep(args.retry_interval)
                continue
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
