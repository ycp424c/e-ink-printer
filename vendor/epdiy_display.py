#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Safe host-side tooling for epdiy.cn GR5513 EPD displays."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


APP_SERVICE_UUID = "62750001-d828-918d-fb46-b6c11c675aec"
APP_CHAR_UUID = "62750002-d828-918d-fb46-b6c11c675aec"
VERSION_CHAR_UUID = "62750003-d828-918d-fb46-b6c11c675aec"

GOODIX_OTA_SERVICE_UUID = "a6ed0401-d344-460a-8075-b9e8ec90d71b"
EPDIY_PAGE_DFU_SERVICE_UUID = "67fc0001-83ae-f58c-f84b-ba72efb822f4"

CMD_INIT = 0x01
CMD_REFRESH = 0x05
CMD_SET_TIME = 0x20
CMD_WRITE_IMAGE = 0x30
CMD_SET_SLOT = 0x31

MODE_PICTURE = 0
MODE_CALENDAR = 1
EXPECTED_MODEL_ID = 3
EXPECTED_SIZE = (400, 300)


def _require_bleak():
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError as exc:
        raise SystemExit("缺少 bleak；请在隔离环境运行: python3 -m pip install bleak") from exc
    return BleakClient, BleakScanner


def _require_pillow():
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise SystemExit("缺少 Pillow；请在隔离环境运行: python3 -m pip install pillow") from exc
    return Image, ImageOps


@dataclass
class DeviceState:
    firmware: str | None = None
    model_id: int | None = None
    display_mode: int | None = None
    week_start: int | None = None
    selected_slot: int | None = None
    mtu: int = 20
    rle: bool = False
    slot_count: int = 0
    used_mask: int = 0
    clock_enabled: bool | None = None
    remote_time: int | None = None
    sid_present: bool = False
    notices: list[str] = field(default_factory=list)

    def parse(self, raw: bytes, log: Callable[[str], None] | None = None) -> None:
        if len(raw) >= 12 and not _looks_textual(raw):
            self.model_id = raw[7]
            self.display_mode = raw[11]
            self.week_start = raw[12] if len(raw) > 12 else None
            self.selected_slot = raw[13] if len(raw) > 13 else self.selected_slot
            if log:
                log(
                    "config: "
                    f"model={self.model_id} mode={self.display_mode} "
                    f"week={self.week_start} slot={self.selected_slot}"
                )
            return

        message = raw.rstrip(b"\x00").decode("utf-8", errors="replace")
        if message.startswith("sid="):
            self.sid_present = True
            safe_message = "sid=<redacted>"
        else:
            safe_message = message
            self.notices.append(message)

        if message.startswith("mtu="):
            fields = message.split()
            self.mtu = int(fields[0].split("=", 1)[1])
            self.rle = any(field == "rle=1" for field in fields[1:])
        elif message.startswith("slots="):
            fields = message.split("=", 1)[1].split()
            self.slot_count = int(fields[0])
            self.used_mask = int(fields[1]) if len(fields) > 1 else 0
            self.selected_slot = int(fields[2]) if len(fields) > 2 else self.selected_slot
        elif message.startswith("clock_enable="):
            self.clock_enabled = message.split("=", 1)[1] == "1"
        elif message.startswith("t="):
            self.remote_time = int(message.split("=", 1)[1])

        if log:
            log(safe_message)

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["notices"] = [item for item in self.notices if not item.startswith("sid=")]
        return data


def _looks_textual(raw: bytes) -> bool:
    return bool(raw) and all(byte in (9, 10, 13) or 32 <= byte <= 126 for byte in raw)


def rle_tokens(data: bytes, literal_limit: int) -> list[bytes]:
    """Encode the PackBits variant used by epdiy.cn."""
    if not 1 <= literal_limit <= 128:
        raise ValueError("literal_limit must be in 1..128")
    tokens: list[bytes] = []
    index = 0
    while index < len(data):
        run = 1
        while index + run < len(data) and run < 130 and data[index + run] == data[index]:
            run += 1
        if run >= 3:
            tokens.append(bytes([0x80 | (run - 3), data[index]]))
            index += run
            continue

        start = index
        literal_length = 0
        while (
            index < len(data)
            and literal_length < literal_limit
            and not (
                index + 2 < len(data)
                and data[index] == data[index + 1]
                and data[index] == data[index + 2]
            )
        ):
            literal_length += 1
            index += 1
        if literal_length == 0:
            tokens.append(bytes([0, data[index]]))
            index += 1
        else:
            tokens.append(bytes([literal_length - 1]) + data[start : start + literal_length])
    return tokens


def rle_chunks(data: bytes, chunk_limit: int) -> list[bytes]:
    if chunk_limit < 2:
        raise ValueError("chunk_limit is too small")
    tokens = rle_tokens(data, min(chunk_limit - 1, 128))
    chunks: list[bytes] = []
    current = bytearray()
    for token in tokens:
        if len(token) > chunk_limit:
            raise AssertionError("RLE token exceeded chunk limit")
        if current and len(current) + len(token) > chunk_limit:
            chunks.append(bytes(current))
            current.clear()
        current.extend(token)
    if current:
        chunks.append(bytes(current))
    return chunks


def rle_decode(data: bytes) -> bytes:
    output = bytearray()
    index = 0
    while index < len(data):
        header = data[index]
        index += 1
        if header & 0x80:
            if index >= len(data):
                raise ValueError("truncated RLE run")
            length = (header & 0x7F) + 3
            output.extend([data[index]] * length)
            index += 1
        else:
            length = header + 1
            if index + length > len(data):
                raise ValueError("truncated RLE literal")
            output.extend(data[index : index + length])
            index += length
    return bytes(output)


def image_flags(layer: str, first: bool, compressed: bool) -> int:
    if layer not in {"black", "red"}:
        raise ValueError("layer must be black or red")
    return (1 if layer == "red" else 0) | (0x02 if first else 0) | (0x04 if compressed else 0)


def pack_msb(image: Any) -> bytes:
    width, height = image.size
    if width % 8:
        raise ValueError("image width must be divisible by 8")
    pixels = image.load()
    output = bytearray()
    for y in range(height):
        for x0 in range(0, width, 8):
            value = 0
            for bit in range(8):
                value |= (1 if pixels[x0 + bit, y] else 0) << (7 - bit)
            output.append(value)
    return bytes(output)


@dataclass
class RenderedImage:
    black_image: Any
    red_image: Any
    preview: Any
    black_data: bytes
    red_data: bytes


def render_image(
    source: Path,
    *,
    fit: str = "cover",
    rotate: int = 0,
    dither: str = "floyd",
    black_threshold: int = 140,
    red_threshold: int = 160,
) -> RenderedImage:
    Image, ImageOps = _require_pillow()
    image = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
    target = EXPECTED_SIZE
    if fit == "cover":
        image = ImageOps.fit(image, target, method=Image.Resampling.LANCZOS)
    elif fit == "contain":
        contained = ImageOps.contain(image, target, method=Image.Resampling.LANCZOS)
        background = Image.new("RGB", target, "white")
        background.paste(contained, ((target[0] - contained.width) // 2, (target[1] - contained.height) // 2))
        image = background
    else:
        raise ValueError("fit must be cover or contain")

    transpose = {
        0: None,
        90: Image.Transpose.ROTATE_90,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_270,
    }[rotate]
    if transpose is not None:
        image = image.transpose(transpose)
        if image.size != target:
            image = ImageOps.fit(image, target, method=Image.Resampling.LANCZOS)

    pixel_data = image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()
    rgb = list(pixel_data)
    red_mask = [r > red_threshold and r > g and r > b for r, g, b in rgb]
    grayscale = [
        255 if is_red else round(0.299 * r + 0.587 * g + 0.114 * b)
        for (r, g, b), is_red in zip(rgb, red_mask)
    ]
    gray_image = Image.new("L", target)
    gray_image.putdata(grayscale)
    if dither == "floyd":
        black_image = gray_image.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    elif dither == "none":
        black_image = gray_image.point(lambda value: 255 if value >= black_threshold else 0, mode="1")
    else:
        raise ValueError("dither must be floyd or none")

    black_pixels = black_image.load()
    red_image = Image.new("1", target, 1)
    red_pixels = red_image.load()
    for index, is_red in enumerate(red_mask):
        x = index % target[0]
        y = index // target[0]
        if is_red:
            black_pixels[x, y] = 255
            red_pixels[x, y] = 0

    preview = Image.new("RGB", target, "white")
    preview.paste((0, 0, 0), mask=ImageOps.invert(black_image.convert("L")))
    preview.paste((200, 0, 0), mask=ImageOps.invert(red_image.convert("L")))
    black_data = pack_msb(black_image)
    red_data = pack_msb(red_image)
    expected_length = target[0] * target[1] // 8
    if len(black_data) != expected_length or len(red_data) != expected_length:
        raise AssertionError("unexpected plane length")
    return RenderedImage(black_image, red_image, preview, black_data, red_data)


def save_rendered(rendered: RenderedImage, source: Path, output_dir: Path, overwrite: bool) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    paths = {
        "preview": output_dir / f"{stem}-epd-preview.png",
        "black_plane": output_dir / f"{stem}-black-plane.png",
        "red_plane": output_dir / f"{stem}-red-plane.png",
        "black_bin": output_dir / f"{stem}-black.bin",
        "red_bin": output_dir / f"{stem}-red.bin",
    }
    existing = [str(path) for path in paths.values() if path.exists()]
    if existing and not overwrite:
        raise FileExistsError("输出已存在；传 --overwrite-output: " + ", ".join(existing))
    rendered.preview.save(paths["preview"])
    rendered.black_image.save(paths["black_plane"])
    rendered.red_image.save(paths["red_plane"])
    paths["black_bin"].write_bytes(rendered.black_data)
    paths["red_bin"].write_bytes(rendered.red_data)
    return {key: str(value.resolve()) for key, value in paths.items()}


async def find_device(name_prefix: str, timeout: float):
    _, BleakScanner = _require_bleak()
    device = await BleakScanner.find_device_by_filter(
        lambda dev, adv: (adv.local_name or dev.name or "").startswith(name_prefix),
        timeout=timeout,
    )
    if device is None:
        raise RuntimeError(f"未发现名称以 {name_prefix!r} 开头的设备")
    return device


async def write_confirmed(client: Any, packet: bytes, timeout: float = 30.0) -> None:
    await asyncio.wait_for(client.write_gatt_char(APP_CHAR_UUID, packet, response=True), timeout=timeout)


async def read_version(client: Any) -> str:
    raw = bytes(await client.read_gatt_char(VERSION_CHAR_UUID))
    return raw.rstrip(b"\x00").decode("utf-8", errors="replace")


def notification_handler(state: DeviceState, verbose: bool) -> Callable[[Any, bytearray], None]:
    def handler(_sender: Any, value: bytearray) -> None:
        state.parse(bytes(value), (lambda text: print(f"notify: {text}", file=sys.stderr)) if verbose else None)

    return handler


async def collect_state(client: Any, state: DeviceState, verbose: bool, initialize: bool = True) -> None:
    await client.start_notify(APP_CHAR_UUID, notification_handler(state, verbose))
    await asyncio.sleep(0.25)
    if initialize:
        await write_confirmed(client, bytes([CMD_INIT]))
        await asyncio.sleep(0.8)


async def command_scan(args: argparse.Namespace) -> dict[str, Any]:
    _, BleakScanner = _require_bleak()
    discovered = await BleakScanner.discover(timeout=args.timeout, return_adv=True)
    devices = []
    for device, advertisement in discovered.values():
        name = advertisement.local_name or device.name or ""
        if name.startswith(args.name_prefix):
            devices.append({"name": name, "address": device.address, "rssi": advertisement.rssi})
    return {"devices": sorted(devices, key=lambda item: item["rssi"], reverse=True)}


async def command_inspect(args: argparse.Namespace) -> dict[str, Any]:
    BleakClient, _ = _require_bleak()
    device = await find_device(args.name_prefix, args.timeout)
    state = DeviceState()
    async with BleakClient(device, timeout=args.timeout) as client:
        state.firmware = await read_version(client)
        await collect_state(client, state, args.verbose)
        services = [service.uuid for service in client.services]
    result = state.public_dict()
    result.update({"device_name": device.name, "services": services})
    return result


async def send_layer(client: Any, data: bytes, layer: str, mtu: int, delay: float, verbose: bool) -> dict[str, Any]:
    chunk_limit = mtu - 2
    encoded_chunks = rle_chunks(data, chunk_limit)
    encoded = b"".join(encoded_chunks)
    if rle_decode(encoded) != data:
        raise AssertionError(f"{layer} RLE round-trip failed")
    compressed = len(encoded) < len(data)
    chunks = encoded_chunks if compressed else [
        data[offset : offset + chunk_limit] for offset in range(0, len(data), chunk_limit)
    ]
    for index, chunk in enumerate(chunks):
        flags = image_flags(layer, index == 0, compressed)
        await write_confirmed(client, bytes([CMD_WRITE_IMAGE, flags]) + chunk)
        if delay:
            await asyncio.sleep(delay)
        if verbose and (index == 0 or (index + 1) % 10 == 0 or index + 1 == len(chunks)):
            print(f"{layer}: {index + 1}/{len(chunks)} flags=0x{flags:02x}", file=sys.stderr)
    return {
        "layer": layer,
        "compressed": compressed,
        "raw_bytes": len(data),
        "encoded_bytes": len(encoded),
        "chunks": len(chunks),
    }


def timezone_hours(explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    offset = datetime.now().astimezone().utcoffset()
    if offset is None:
        raise RuntimeError("无法确定本地时区偏移")
    return round(offset.total_seconds() / 3600)


async def restore_calendar_on_client(client: Any, tz_hours: int) -> None:
    if not -128 <= tz_hours <= 127:
        raise ValueError("timezone hours out of int8 range")
    packet = (
        bytes([CMD_SET_TIME])
        + int(time.time()).to_bytes(4, "big")
        + bytes([tz_hours & 0xFF, MODE_CALENDAR])
    )
    await write_confirmed(client, packet, timeout=60.0)


async def command_upload(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.image).expanduser().resolve()
    rendered = render_image(
        source,
        fit=args.fit,
        rotate=args.rotate,
        dither=args.dither,
        black_threshold=args.black_threshold,
        red_threshold=args.red_threshold,
    )
    outputs = None
    if args.output_dir:
        outputs = save_rendered(rendered, source, Path(args.output_dir).expanduser().resolve(), args.overwrite_output)

    BleakClient, _ = _require_bleak()
    device = await find_device(args.name_prefix, args.timeout)
    state = DeviceState()
    refresh_sent = False
    transfers: list[dict[str, Any]] = []
    async with BleakClient(device, timeout=args.timeout) as client:
        state.firmware = await read_version(client)
        await collect_state(client, state, args.verbose)
        if state.model_id != EXPECTED_MODEL_ID and not args.allow_unknown_model:
            raise RuntimeError(f"拒绝上传：实机 model_id={state.model_id}，预期 {EXPECTED_MODEL_ID}")
        if not state.rle:
            raise RuntimeError("拒绝上传：设备未声明 rle=1，不能使用 GR5513 扩展包头")
        if state.slot_count <= args.slot:
            raise RuntimeError(f"槽位 {args.slot} 不可用；设备槽位数={state.slot_count}")
        if state.used_mask & (1 << args.slot) and not args.overwrite_slot:
            raise RuntimeError(f"槽位 {args.slot} 已占用；确认后传 --overwrite-slot")
        if not 20 <= state.mtu <= 512:
            raise RuntimeError(f"非法 MTU: {state.mtu}")

        await write_confirmed(client, bytes([CMD_SET_SLOT, 0, args.slot]))
        await write_confirmed(client, bytes([CMD_INIT]))
        await asyncio.sleep(0.2)
        try:
            transfers.append(
                await send_layer(client, rendered.black_data, "black", state.mtu, args.write_delay, args.verbose)
            )
            transfers.append(
                await send_layer(client, rendered.red_data, "red", state.mtu, args.write_delay, args.verbose)
            )
            await asyncio.sleep(0.4)
            await write_confirmed(client, bytes([CMD_REFRESH]), timeout=60.0)
            refresh_sent = True
            await asyncio.sleep(args.refresh_wait)
        except Exception:
            if not refresh_sent and not args.no_restore_on_error:
                try:
                    await restore_calendar_on_client(client, timezone_hours(args.timezone_hours))
                    print("上传失败，已请求恢复日历", file=sys.stderr)
                except Exception as restore_error:
                    print(f"上传失败，恢复日历也失败: {restore_error}", file=sys.stderr)
            raise

    slot_persisted = bool(state.used_mask & (1 << args.slot))
    if not slot_persisted:
        raise RuntimeError("刷新已发送，但未收到目标槽位占用通知；保留当前画面并人工检查")
    return {
        "device_name": device.name,
        "firmware": state.firmware,
        "model_id": state.model_id,
        "slot": args.slot,
        "used_mask": state.used_mask,
        "slot_persisted": slot_persisted,
        "refresh_sent": refresh_sent,
        "transfers": transfers,
        "outputs": outputs,
        "visual_confirmation_required": True,
    }


async def command_restore_calendar(args: argparse.Namespace) -> dict[str, Any]:
    BleakClient, _ = _require_bleak()
    device = await find_device(args.name_prefix, args.timeout)
    tz = timezone_hours(args.timezone_hours)
    async with BleakClient(device, timeout=args.timeout) as client:
        await restore_calendar_on_client(client, tz)
        await asyncio.sleep(args.refresh_wait)

    verify = DeviceState()
    async with BleakClient(device, timeout=args.timeout) as client:
        verify.firmware = await read_version(client)
        await collect_state(client, verify, args.verbose)
    if verify.display_mode != MODE_CALENDAR:
        raise RuntimeError(f"日历恢复未持久化；display_mode={verify.display_mode}")
    return {"restored": True, "display_mode": verify.display_mode, "timezone_hours": tz}


async def command_firmware_audit(args: argparse.Namespace) -> dict[str, Any]:
    BleakClient, _ = _require_bleak()
    device = await find_device(args.name_prefix, args.timeout)
    async with BleakClient(device, timeout=args.timeout) as client:
        service_details = []
        for service in client.services:
            service_details.append(
                {
                    "uuid": service.uuid,
                    "characteristics": [
                        {"uuid": char.uuid, "properties": sorted(char.properties)}
                        for char in service.characteristics
                    ],
                }
            )
        firmware = await read_version(client)
    service_uuids = {item["uuid"].lower() for item in service_details}
    return {
        "device_name": device.name,
        "firmware": firmware,
        "services": service_details,
        "goodix_ota_present": GOODIX_OTA_SERVICE_UUID in service_uuids,
        "epdiy_page_dfu_present": EPDIY_PAGE_DFU_SERVICE_UUID in service_uuids,
        "firmware_readback_supported": False,
        "writes_performed": False,
        "assessment": "只读审计；未验证 bootloader 布局、签名、应用地址或恢复镜像，禁止 OTA 写入。",
    }


def command_render(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.image).expanduser().resolve()
    rendered = render_image(
        source,
        fit=args.fit,
        rotate=args.rotate,
        dither=args.dither,
        black_threshold=args.black_threshold,
        red_threshold=args.red_threshold,
    )
    outputs = save_rendered(
        rendered,
        source,
        Path(args.output_dir).expanduser().resolve(),
        args.overwrite_output,
    )
    black_encoded = b"".join(rle_chunks(rendered.black_data, 242))
    red_encoded = b"".join(rle_chunks(rendered.red_data, 242))
    return {
        "size": list(EXPECTED_SIZE),
        "plane_bytes": len(rendered.black_data),
        "black_rle_ratio": round(len(black_encoded) / len(rendered.black_data), 6),
        "red_rle_ratio": round(len(red_encoded) / len(rendered.red_data), 6),
        "outputs": outputs,
    }


def command_self_test() -> dict[str, Any]:
    samples: list[bytes] = [
        b"",
        b"A",
        b"AA",
        b"AAA",
        b"A" * 130,
        b"A" * 131,
        bytes(range(256)) * 3,
        random.Random(0).randbytes(30_000),
        b"\xff" * 15_000,
    ]
    for sample in samples:
        chunks = rle_chunks(sample, 242)
        if chunks and max(map(len, chunks)) > 242:
            raise AssertionError("chunk exceeded limit")
        if rle_decode(b"".join(chunks)) != sample:
            raise AssertionError("RLE round-trip mismatch")
    assert image_flags("black", True, True) == 0x06
    assert image_flags("black", False, True) == 0x04
    assert image_flags("red", True, True) == 0x07
    assert image_flags("red", False, True) == 0x05
    state = DeviceState()
    state.parse(bytes.fromhex("ffffffffffffff03ffffff010000"))
    assert (state.model_id, state.display_mode, state.week_start, state.selected_slot) == (3, 1, 0, 0)
    state.parse(b"slots=7 1 0")
    state.parse(b"mtu=244 rle=1")
    state.parse(b"sid=must-not-leak")
    public = json.dumps(state.public_dict())
    assert "must-not-leak" not in public
    assert (state.slot_count, state.used_mask, state.mtu, state.rle) == (7, 1, 244, True)
    return {"ok": True, "rle_samples": len(samples), "sid_redaction": True}


def add_render_options(parser: argparse.ArgumentParser, output_required: bool) -> None:
    parser.add_argument("image", help="输入图片绝对路径")
    parser.add_argument("--fit", choices=("cover", "contain"), default="cover")
    parser.add_argument("--rotate", type=int, choices=(0, 90, 180, 270), default=0)
    parser.add_argument("--dither", choices=("floyd", "none"), default="floyd")
    parser.add_argument("--black-threshold", type=int, default=140)
    parser.add_argument("--red-threshold", type=int, default=160)
    parser.add_argument("--output-dir", required=output_required)
    parser.add_argument("--overwrite-output", action="store_true")


def add_ble_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name-prefix", default="NRF_EPD_", help="蓝牙名称前缀")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--verbose", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("self-test", help="运行无硬件协议自检")

    scan = subparsers.add_parser("scan", help="扫描 NRF_EPD 设备")
    add_ble_options(scan)

    inspect = subparsers.add_parser("inspect", help="检查应用协议和能力；INIT 不刷新屏幕")
    add_ble_options(inspect)

    render = subparsers.add_parser("render", help="离线生成双图层和预览")
    add_render_options(render, output_required=True)

    upload = subparsers.add_parser("upload", help="按 GR5513 RLE/槽位协议上传")
    add_render_options(upload, output_required=False)
    add_ble_options(upload)
    upload.add_argument("--slot", type=int, default=0)
    upload.add_argument("--overwrite-slot", action="store_true")
    upload.add_argument("--allow-unknown-model", action="store_true")
    upload.add_argument("--write-delay", type=float, default=0.008)
    upload.add_argument("--refresh-wait", type=float, default=25.0)
    upload.add_argument("--timezone-hours", type=int)
    upload.add_argument("--no-restore-on-error", action="store_true")

    restore = subparsers.add_parser("restore-calendar", help="同步时间并恢复日历模式")
    add_ble_options(restore)
    restore.add_argument("--timezone-hours", type=int)
    restore.add_argument("--refresh-wait", type=float, default=20.0)

    firmware = subparsers.add_parser("firmware-audit", help="只读检查 OTA/DFU 服务")
    add_ble_options(firmware)
    return parser


def emit(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "self-test":
        emit(command_self_test())
    elif args.command == "render":
        emit(command_render(args))
    else:
        commands = {
            "scan": command_scan,
            "inspect": command_inspect,
            "upload": command_upload,
            "restore-calendar": command_restore_calendar,
            "firmware-audit": command_firmware_audit,
        }
        emit(asyncio.run(commands[args.command](args)))


if __name__ == "__main__":
    main()
