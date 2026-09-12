#!/usr/bin/env python3
"""Improv Wi-Fi (Serial) プロトコルでESPHomeデバイスにWiFi資格情報を送るCLI。

ブラウザ(https://www.improv-wifi.com/serial/, Web Serial API)を使わずに、
`improv_serial:` を有効にしたESPHomeデバイスへ直接WiFi SSID/パスワードを
送信する。プロトコル仕様はImprov WiFiの公式サイト、及びESPHomeが依存する
Improvライブラリ(esphome/.esphome/.../Improv/src/improv.cpp)のchecksum実装
を参照して実装(単純な加算チェックサム、mod 256)。

パケット構造:
    "IMPROV"(6B) + version(1B=0x01) + type(1B) + data_len(1B) + payload + checksum(1B)
    checksum = sum(先頭からchecksum直前まで全バイト) mod 256

使い方:
    bin/improv_wifi.py                          # 自動検出ポート、対話入力
    bin/improv_wifi.py --device /dev/ttyACM0
    bin/improv_wifi.py --ssid MyWiFi --password mypassword
    bin/improv_wifi.py --info                   # 現在の状態/デバイス情報だけ取得
"""
from __future__ import annotations

import argparse
import getpass
import glob
import sys
import time

import serial

MAGIC = b"IMPROV"
VERSION = 0x01

TYPE_CURRENT_STATE = 0x01
TYPE_ERROR_STATE = 0x02
TYPE_RPC_COMMAND = 0x03
TYPE_RPC_RESULT = 0x04

CMD_SEND_WIFI_SETTINGS = 0x01
CMD_REQUEST_CURRENT_STATE = 0x02
CMD_REQUEST_DEVICE_INFO = 0x03

STATE_NAMES = {
    0x00: "Stopped(未起動)",
    0x02: "Ready/Authorized(未設定・待機中)",
    0x03: "Provisioning(設定中)",
    0x04: "Provisioned(設定完了)",
}
ERROR_NAMES = {
    0x00: "エラーなし",
    0x01: "Invalid RPC packet",
    0x02: "Unknown RPC command",
    0x03: "Unable to connect(接続できず。SSID/パスワード再確認)",
    0x05: "Bad Hostname",
    0xFF: "Unknown Error",
}


def find_port() -> str | None:
    candidates = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    return candidates[0] if candidates else None


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def build_packet(packet_type: int, payload: bytes) -> bytes:
    header = MAGIC + bytes([VERSION, packet_type, len(payload)]) + payload
    return header + bytes([checksum(header)])


def build_rpc(command: int, data: bytes) -> bytes:
    payload = bytes([command, len(data)]) + data
    return build_packet(TYPE_RPC_COMMAND, payload)


def build_wifi_settings(ssid: str, password: str) -> bytes:
    ssid_b = ssid.encode("utf-8")
    pass_b = password.encode("utf-8")
    data = bytes([len(ssid_b)]) + ssid_b + bytes([len(pass_b)]) + pass_b
    return build_rpc(CMD_SEND_WIFI_SETTINGS, data)


def build_request_info() -> bytes:
    return build_rpc(CMD_REQUEST_DEVICE_INFO, b"")


def build_request_state() -> bytes:
    return build_rpc(CMD_REQUEST_CURRENT_STATE, b"")


class PacketReader:
    """シリアルの生バイト列(平文ログと混在)からImprovパケットだけを拾う。"""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> list[tuple[int, bytes]]:
        self._buf += chunk
        packets = []
        while True:
            idx = self._buf.find(MAGIC)
            if idx == -1:
                # マジックが見つからない場合、末尾5byteだけ残して捨てる
                # (次のfeedでマジックが跨る可能性に備える)
                if len(self._buf) > 5:
                    del self._buf[: len(self._buf) - 5]
                return packets
            if idx > 0:
                del self._buf[:idx]
            # ここで self._buf は MAGIC から始まる
            if len(self._buf) < 9:
                return packets  # ヘッダすら揃っていない、続きを待つ
            version = self._buf[6]
            ptype = self._buf[7]
            dlen = self._buf[8]
            total_len = 9 + dlen + 1  # +checksum
            if len(self._buf) < total_len:
                return packets  # まだ全部届いていない
            packet = bytes(self._buf[:total_len])
            del self._buf[:total_len]
            payload = packet[9 : 9 + dlen]
            recv_checksum = packet[-1]
            calc = checksum(packet[:-1])
            if version == VERSION and calc == recv_checksum:
                packets.append((ptype, payload))
            # チェックサム不一致 or version違いは静かに捨てて続行


def describe_packet(ptype: int, payload: bytes) -> str | None:
    if ptype == TYPE_CURRENT_STATE and payload:
        state = payload[0]
        return f"[state] {STATE_NAMES.get(state, hex(state))}"
    if ptype == TYPE_ERROR_STATE and payload:
        err = payload[0]
        return f"[error] {ERROR_NAMES.get(err, hex(err))}"
    if ptype == TYPE_RPC_RESULT and len(payload) >= 2:
        cmd = payload[0]
        strs = []
        i = 2
        while i < len(payload):
            slen = payload[i]
            i += 1
            strs.append(payload[i : i + slen].decode("utf-8", "replace"))
            i += slen
        return f"[rpc result] command=0x{cmd:02x} -> {strs}"
    return None


def run(args: argparse.Namespace) -> int:
    port = args.device or find_port()
    if port is None:
        print("error: シリアルポートが見つかりません。--deviceで指定してください。", file=sys.stderr)
        return 1

    print(f"[improv_wifi] port={port} baud={args.baud}", file=sys.stderr)
    reader = PacketReader()

    with serial.Serial(port, args.baud, timeout=0.1) as ser:
        def drain(duration: float) -> None:
            end = time.time() + duration
            while time.time() < end:
                chunk = ser.read(ser.in_waiting or 1)
                if chunk:
                    for ptype, payload in reader.feed(chunk):
                        desc = describe_packet(ptype, payload)
                        if desc:
                            print(desc)

        if args.info:
            ser.write(build_request_info())
            drain(2.0)
            ser.write(build_request_state())
            drain(2.0)
            return 0

        ssid = args.ssid or input("SSID: ")
        password = args.password
        if password is None:
            password = getpass.getpass("Password (非表示入力): ")

        print(f"[improv_wifi] SSID '{ssid}' を送信します...", file=sys.stderr)
        ser.write(build_wifi_settings(ssid, password))

        # Provisioned(0x04)かエラーが出るまで最大15秒待つ
        end = time.time() + 15
        provisioned = False
        while time.time() < end:
            chunk = ser.read(ser.in_waiting or 1)
            if not chunk:
                continue
            for ptype, payload in reader.feed(chunk):
                desc = describe_packet(ptype, payload)
                if desc:
                    print(desc)
                if ptype == TYPE_CURRENT_STATE and payload and payload[0] == 0x04:
                    provisioned = True
                    end = time.time()  # ループを抜ける
                if ptype == TYPE_ERROR_STATE and payload and payload[0] != 0x00:
                    end = time.time()

        if provisioned:
            print("[improv_wifi] Provisioned: WiFi設定が完了しました。")
            return 0
        print(
            "[improv_wifi] 完了通知が届きませんでした(タイムアウト)。"
            " 上のログにerror/stateが出ていないか確認してください。"
            " デバイスが再起動してWiFi接続を試みている可能性もあります。",
            file=sys.stderr,
        )
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", default=None, help="シリアルポート(省略時は自動検出)")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--ssid", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--info", action="store_true", help="WiFi設定はせず、デバイス情報/状態だけ取得して終了")
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
