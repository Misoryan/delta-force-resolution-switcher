#!/usr/bin/env python3
"""三角洲行动分辨率自动切换：游戏启动时改为 1920x1080，关闭后恢复原分辨率。"""

import ctypes
import json
import logging
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32

ENUM_CURRENT_SETTINGS = -1
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000
DM_BITSPERPEL = 0x00040000

DISP_CHANGE_SUCCESSFUL = 0
DISP_CHANGE_RESTART = 1

STATE_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "DeltaResolutionSwitcher"
STATE_FILE = STATE_DIR / "state.json"


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


CONFIG_FILE = get_app_dir() / "config.json"


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmOrientation", wintypes.SHORT),
        ("dmPaperSize", wintypes.SHORT),
        ("dmPaperLength", wintypes.SHORT),
        ("dmPaperWidth", wintypes.WORD),
        ("dmScale", wintypes.SHORT),
        ("dmCopies", wintypes.SHORT),
        ("dmDefaultSource", wintypes.SHORT),
        ("dmPrintQuality", wintypes.SHORT),
        ("dmColor", wintypes.SHORT),
        ("dmDuplex", wintypes.SHORT),
        ("dmYResolution", wintypes.SHORT),
        ("dmTTOption", wintypes.SHORT),
        ("dmCollate", wintypes.SHORT),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


def setup_logging(console: bool = True) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_file = STATE_DIR / "switcher.log"
    handlers: list[logging.Handler] = [
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    if console:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
        force=True,
    )


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"找不到配置文件: {CONFIG_FILE}")
    with CONFIG_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def get_current_devmode() -> DEVMODEW | None:
    devmode = DEVMODEW()
    devmode.dmSize = ctypes.sizeof(DEVMODEW)
    if user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode)):
        return devmode
    return None


def devmode_to_dict(devmode: DEVMODEW) -> dict:
    return {
        "width": devmode.dmPelsWidth,
        "height": devmode.dmPelsHeight,
        "frequency": devmode.dmDisplayFrequency,
        "bits": devmode.dmBitsPerPel,
    }


def apply_resolution(
    width: int,
    height: int,
    frequency: int,
    bits: int,
    allow_fallback: bool = True,
) -> int:
    devmode = DEVMODEW()
    devmode.dmSize = ctypes.sizeof(DEVMODEW)
    user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(devmode))
    devmode.dmPelsWidth = width
    devmode.dmPelsHeight = height
    devmode.dmBitsPerPel = bits
    devmode.dmDisplayFrequency = frequency
    devmode.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_BITSPERPEL | DM_DISPLAYFREQUENCY
    result = user32.ChangeDisplaySettingsW(ctypes.byref(devmode), 0)
    if result == DISP_CHANGE_SUCCESSFUL or not allow_fallback:
        return result

    # 部分显示器在特定分辨率下不支持当前刷新率，依次尝试常见值
    fallback_rates = [frequency, 144, 165, 120, 60]
    seen = set()
    for rate in fallback_rates:
        if rate in seen:
            continue
        seen.add(rate)
        devmode.dmDisplayFrequency = rate
        result = user32.ChangeDisplaySettingsW(ctypes.byref(devmode), 0)
        if result == DISP_CHANGE_SUCCESSFUL:
            logging.info("使用刷新率 %d Hz 切换成功。", rate)
            return result
    return result


def restore_from_saved(saved: dict) -> int:
    return apply_resolution(
        saved["width"],
        saved["height"],
        saved["frequency"],
        saved["bits"],
        allow_fallback=False,
    )


def write_state(active: bool, saved: dict | None = None) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"active": active, "saved": saved}
    STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def clear_state() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def is_any_process_running(process_names: list[str]) -> bool:
    normalized = {name.lower() for name in process_names}
    try:
        output = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=True,
            encoding="oem",
            errors="replace",
        )
    except subprocess.CalledProcessError:
        return False

    for line in output.splitlines():
        if not line.strip():
            continue
        # CSV 第一列为进程名，可能带引号
        proc = line.split(",")[0].strip().strip('"').lower()
        if proc in normalized:
            return True
    return False


def recover_from_crash(process_names: list[str]) -> None:
    state = read_state()
    if not state or not state.get("active") or not state.get("saved"):
        return
    if is_any_process_running(process_names):
        logging.info("检测到上次异常退出，游戏仍在运行，继续监视。")
        return
    saved = state["saved"]
    logging.warning(
        "检测到上次未恢复分辨率 (%dx%d)，正在还原…",
        saved["width"],
        saved["height"],
    )
    result = restore_from_saved(saved)
    if result == DISP_CHANGE_SUCCESSFUL:
        logging.info("分辨率已恢复。")
        clear_state()
    else:
        logging.error("恢复分辨率失败，错误码: %d", result)


class ResolutionSwitcher:
    def __init__(self, config: dict, stop_event: threading.Event | None = None) -> None:
        self.config = config
        self.game_active = False
        self.saved_resolution: dict | None = None
        self.pending_switch = False
        self.switch_at: float = 0.0
        self.stop_event = stop_event or threading.Event()

    @property
    def process_names(self) -> list[str]:
        return self.config.get("process_names", [])

    def target_resolution(self) -> tuple[int, int]:
        return (
            int(self.config.get("target_width", 1920)),
            int(self.config.get("target_height", 1080)),
        )

    def poll_interval(self) -> float:
        return float(self.config.get("poll_interval_seconds", 2))

    def startup_delay(self) -> float:
        return float(self.config.get("startup_delay_seconds", 3))

    def active_poll_interval(self) -> float:
        return float(self.config.get("active_poll_interval_seconds", 0.3))

    def switch_to_game_resolution(self) -> None:
        current = get_current_devmode()
        if not current:
            logging.error("无法读取当前分辨率。")
            return

        self.saved_resolution = devmode_to_dict(current)
        target_w, target_h = self.target_resolution()

        if self.saved_resolution["width"] == target_w and self.saved_resolution["height"] == target_h:
            logging.info("当前已是 %dx%d，仅记录原状态以便退出时保持一致。", target_w, target_h)
        else:
            logging.info(
                "游戏已启动，切换分辨率: %dx%d -> %dx%d",
                self.saved_resolution["width"],
                self.saved_resolution["height"],
                target_w,
                target_h,
            )
            result = apply_resolution(
                target_w,
                target_h,
                self.saved_resolution["frequency"],
                self.saved_resolution["bits"],
            )
            if result == DISP_CHANGE_SUCCESSFUL:
                logging.info("分辨率切换成功。")
            elif result == DISP_CHANGE_RESTART:
                logging.warning("分辨率切换需要重启系统才能生效。")
            else:
                logging.error("分辨率切换失败，错误码: %d", result)
                self.saved_resolution = None
                return

        write_state(True, self.saved_resolution)
        self.game_active = True

    def restore_original_resolution(self) -> None:
        if not self.saved_resolution:
            clear_state()
            self.game_active = False
            return

        logging.info(
            "游戏已关闭，恢复分辨率: %dx%d",
            self.saved_resolution["width"],
            self.saved_resolution["height"],
        )
        result = restore_from_saved(self.saved_resolution)
        if result == DISP_CHANGE_SUCCESSFUL:
            logging.info("分辨率已恢复。")
        elif result == DISP_CHANGE_RESTART:
            logging.warning("恢复分辨率需要重启系统才能生效。")
        else:
            logging.error("恢复分辨率失败，错误码: %d", result)

        self.saved_resolution = None
        self.game_active = False
        clear_state()

    def on_exit(self) -> None:
        if self.game_active and self.saved_resolution:
            logging.info("监视器退出，正在恢复分辨率…")
            self.restore_original_resolution()

    def _wait(self, seconds: float) -> bool:
        return self.stop_event.wait(timeout=seconds)

    def run(self) -> None:
        recover_from_crash(self.process_names)
        logging.info("三角洲行动分辨率监视器已启动。")
        logging.info("监视进程: %s", ", ".join(self.process_names))
        logging.info("目标分辨率: %dx%d", *self.target_resolution())
        logging.info("按 Ctrl+C 可退出并尝试恢复分辨率。")

        try:
            while not self.stop_event.is_set():
                running = is_any_process_running(self.process_names)

                if running and not self.game_active and not self.pending_switch:
                    self.pending_switch = True
                    self.switch_at = time.time() + self.startup_delay()
                    logging.info("检测到游戏进程，%s 秒后切换分辨率…", self.startup_delay())

                if self.pending_switch and not self.game_active:
                    if not running:
                        self.pending_switch = False
                    elif time.time() >= self.switch_at:
                        self.pending_switch = False
                        self.switch_to_game_resolution()

                if not running and self.game_active:
                    self.restore_original_resolution()
                    continue

                if self.game_active:
                    if self._wait(self.active_poll_interval()):
                        break
                elif self.pending_switch:
                    if self._wait(min(0.5, self.poll_interval())):
                        break
                else:
                    if self._wait(self.poll_interval()):
                        break
        except KeyboardInterrupt:
            logging.info("收到退出信号。")
        finally:
            self.on_exit()


def main() -> None:
    setup_logging()
    config = load_config()
    switcher = ResolutionSwitcher(config)
    switcher.run()


if __name__ == "__main__":
    main()
