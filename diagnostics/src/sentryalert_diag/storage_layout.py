from __future__ import annotations

import re
from typing import Any

from .state import utc_now
from .system import read_text, run_command


def _command(arguments: list[str], timeout: int) -> dict[str, Any]:
    return run_command(arguments, timeout)


def _command_text(result: dict[str, Any]) -> str:
    return str(result.get("output") or "") + str(result.get("error") or "")


def collect_storage_layout(timeout: int = 3) -> dict[str, Any]:
    commands: dict[str, dict[str, Any]] = {
        "lsblk_filesystems": _command(["lsblk", "-f"], timeout),
        "fdisk_mmcblk1": _command(["fdisk", "-l", "/dev/mmcblk1"], timeout),
        "find_teslacam": _command(
            ["find", "/mnt/cam", "-maxdepth", "3", "-type", "d", "-name", "TeslaCam", "-print"],
            timeout,
        ),
        "list_cam_root": _command(["ls", "-la", "/mnt/cam"], timeout),
    }
    for index in range(1, 5):
        commands[f"parted_align_{index}"] = _command(
            ["parted", "/dev/mmcblk1", "align-check", "optimal", str(index)],
            timeout,
        )

    gadget_root = "/sys/kernel/config/usb_gadget/sentryalert"
    udc = (read_text(f"{gadget_root}/UDC", 4096) or "").strip()
    gadget = {
        "present": bool(read_text(f"{gadget_root}/bcdUSB", 4096) is not None),
        "udc": udc,
        "current_speed": read_text(f"/sys/class/udc/{udc}/current_speed", 4096) if udc else None,
        "maximum_speed": read_text(f"/sys/class/udc/{udc}/maximum_speed", 4096) if udc else None,
        "state": read_text(f"/sys/class/udc/{udc}/state", 4096) if udc else None,
        "bcdUSB": read_text(f"{gadget_root}/bcdUSB", 4096),
        "product": read_text(f"{gadget_root}/strings/0x409/product", 4096),
        "manufacturer": read_text(f"{gadget_root}/strings/0x409/manufacturer", 4096),
        "serialnumber": read_text(f"{gadget_root}/strings/0x409/serialnumber", 4096),
        "idVendor": read_text(f"{gadget_root}/idVendor", 4096),
        "idProduct": read_text(f"{gadget_root}/idProduct", 4096),
        "MaxPower": read_text(f"{gadget_root}/configs/c.1/MaxPower", 4096),
    }

    fdisk_text = _command_text(commands["fdisk_mmcblk1"])
    lsblk_text = _command_text(commands["lsblk_filesystems"])
    partition1 = re.search(r"^/dev/mmcblk1p1\s+(\d+)\s+", fdisk_text, re.MULTILINE)
    alignments: dict[str, str] = {}
    for index in range(1, 5):
        text = _command_text(commands[f"parted_align_{index}"]).strip()
        alignments[str(index)] = text or "unavailable"

    checks = {
        "disklabel_gpt": "Disklabel type: gpt" in fdisk_text,
        "partition1_starts_at_2048": bool(partition1 and partition1.group(1) == "2048"),
        "partitions_1_to_4_aligned": all(
            alignments[str(index)].strip() == f"{index} aligned" for index in range(1, 5)
        ),
        "cam_partition_exfat": bool(re.search(r"mmcblk1p4\s+exfat\b.*\bCAM\b", lsblk_text)),
        "teslacam_folder_present": bool(commands["find_teslacam"].get("output", "").strip()),
        "gadget_is_usb2_high_speed": "high-speed" in str(gadget.get("current_speed") or ""),
    }
    checks["overall_storage_layout_ok"] = all(
        checks[name]
        for name in (
            "disklabel_gpt",
            "partition1_starts_at_2048",
            "partitions_1_to_4_aligned",
            "cam_partition_exfat",
            "teslacam_folder_present",
        )
    )

    return {
        "collected_at": utc_now(),
        "target_disk": "/dev/mmcblk1",
        "commands": commands,
        "gadget": gadget,
        "parsed": {
            "partition1_start_sector": partition1.group(1) if partition1 else None,
            "alignments": alignments,
            "checks": checks,
        },
    }


def render_storage_layout_report(layout: dict[str, Any]) -> str:
    parsed = layout.get("parsed", {})
    checks = parsed.get("checks", {})
    alignments = parsed.get("alignments", {})
    gadget = layout.get("gadget", {})
    commands = layout.get("commands", {})

    def yes(value: Any) -> str:
        return "YES" if value else "NO"

    lines = [
        "SentryAlert Storage Layout Check",
        "===============================",
        "",
        f"Collected: {layout.get('collected_at', 'unknown')}",
        f"Target disk: {layout.get('target_disk', '/dev/mmcblk1')}",
        "",
        "Quick verdict",
        "-------------",
        f"Storage layout looks OK: {yes(checks.get('overall_storage_layout_ok'))}",
        f"GPT partition table: {yes(checks.get('disklabel_gpt'))}",
        f"Partition 1 starts at sector 2048: {yes(checks.get('partition1_starts_at_2048'))}",
        f"Partitions 1-4 optimally aligned: {yes(checks.get('partitions_1_to_4_aligned'))}",
        f"CAM partition is exFAT: {yes(checks.get('cam_partition_exfat'))}",
        f"TeslaCam folder present: {yes(checks.get('teslacam_folder_present'))}",
        "",
        "Alignment results",
        "-----------------",
    ]
    for index in range(1, 5):
        lines.append(f"Partition {index}: {alignments.get(str(index), 'unavailable')}")

    lines.extend([
        "",
        "USB gadget facts",
        "----------------",
        f"Product: {str(gadget.get('product') or '').strip() or 'unavailable'}",
        f"Manufacturer: {str(gadget.get('manufacturer') or '').strip() or 'unavailable'}",
        f"Serial: {str(gadget.get('serialnumber') or '').strip() or 'unavailable'}",
        f"bcdUSB: {str(gadget.get('bcdUSB') or '').strip() or 'unavailable'}",
        f"UDC: {str(gadget.get('udc') or '').strip() or 'unavailable'}",
        f"Current speed: {str(gadget.get('current_speed') or '').strip() or 'unavailable'}",
        f"Maximum speed: {str(gadget.get('maximum_speed') or '').strip() or 'unavailable'}",
        f"State: {str(gadget.get('state') or '').strip() or 'unavailable'}",
        f"MaxPower: {str(gadget.get('MaxPower') or '').strip() or 'unavailable'}",
        "",
        "Interpretation",
        "--------------",
    ])
    if checks.get("overall_storage_layout_ok"):
        lines.append(
            "The partition alignment, filesystem, and TeslaCam folder checks passed. "
            "If UI_a111 still appears, this points away from basic storage formatting "
            "and back toward USB gadget presentation, enumeration timing, or Tesla "
            "model/firmware tolerance."
        )
    else:
        lines.append(
            "One or more storage layout checks failed or could not be verified. "
            "Review the raw command output below before changing USB gadget experiments."
        )

    lines.extend(["", "Raw command output", "------------------"])
    for name, result in commands.items():
        lines.extend([
            "",
            f"$ {' '.join(result.get('command', [name]))}",
            f"exit_code: {result.get('exit_code')}",
        ])
        output = str(result.get("output") or "").strip()
        error = str(result.get("error") or "").strip()
        if output:
            lines.append(output)
        if error:
            lines.append("stderr:")
            lines.append(error)

    return "\n".join(lines) + "\n"
