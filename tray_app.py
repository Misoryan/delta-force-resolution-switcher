#!/usr/bin/env python3
"""三角洲行动分辨率监视器 - pystray 托盘 + tkinter 设置窗口。"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

import pystray
from PIL import Image, ImageDraw

from delta_resolution_switcher import (
    CONFIG_FILE,
    STATE_DIR,
    ResolutionSwitcher,
    devmode_to_dict,
    get_app_dir,
    get_current_devmode,
    is_any_process_running,
    load_config,
    read_state,
    setup_logging,
)

APP_DIR = get_app_dir()
ASSETS_DIR = APP_DIR / "assets"
STARTUP_DIR = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup"
STARTUP_LNK = STARTUP_DIR / "DeltaForceResolutionSwitcher.lnk"
LOG_FILE = STATE_DIR / "switcher.log"
UI_FONT = "Microsoft YaHei UI"
BASE_DPI = 96.0
BASE_FONT_PX = 14


def _load_asset(name: str) -> Image.Image:
    """加载资源文件（兼容开发模式和 PyInstaller 打包模式）。"""
    path = ASSETS_DIR / name
    if path.exists():
        return Image.open(path)
    # PyInstaller 打包后，资源由 spec 的 datas 复制到 exe 同目录
    fallback = APP_DIR / name
    if fallback.exists():
        return Image.open(fallback)
    raise FileNotFoundError(f"找不到资源文件: {name}")


def get_system_dpi() -> float:
    if sys.platform != "win32":
        return BASE_DPI
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = float(ctypes.windll.gdi32.GetDeviceCaps(hdc, 88))
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi if dpi > 0 else BASE_DPI
    except (AttributeError, OSError):
        return BASE_DPI


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


DEFAULT_CONFIG = {
    "target_width": 1920,
    "target_height": 1080,
    "poll_interval_seconds": 2,
    "process_names": [
        "DeltaForceClient-Win64-Shipping.exe",
        "DeltaForce.exe",
    ],
    "startup_delay_seconds": 3,
    "active_poll_interval_seconds": 0.3,
    "enable_notifications": True,
}


def configure_ui_scaling(root: tk.Tk) -> tuple[float, tuple[str, int]]:
    dpi = get_system_dpi()
    scale = max(dpi / BASE_DPI, 1.0)

    target_scaling = dpi / 72.0
    try:
        current_scaling = float(root.tk.call("tk", "scaling"))
        if abs(current_scaling - target_scaling) > 0.05:
            root.tk.call("tk", "scaling", target_scaling)
    except tk.TclError:
        root.tk.call("tk", "scaling", target_scaling)

    font_px = max(BASE_FONT_PX, round(BASE_FONT_PX * scale))
    font: tuple[str, int] = (UI_FONT, -font_px)

    root.option_add("*Font", font)
    style = ttk.Style(root)
    if sys.platform == "win32":
        for theme in ("vista", "xpnative", "clam"):
            try:
                style.theme_use(theme)
                break
            except tk.TclError:
                continue

    pad_y = max(4, round(4 * scale))
    for widget in (".", "TLabel", "TEntry", "TLabelframe", "TLabelframe.Label"):
        style.configure(widget, font=font)
    style.configure("TButton", font=font, padding=(12, pad_y))
    return scale, font


def scaled_size(base_width: int, base_height: int, scale: float) -> tuple[int, int]:
    return int(base_width * scale), int(base_height * scale)


@dataclass
class AppStatus:
    monitor_running: bool = False
    startup_enabled: bool = False
    game_running: bool = False
    session_active: bool = False
    current_resolution: str = "-"
    target_resolution: str = "-"
    restore_resolution: str = "-"


class MonitorService:
    def __init__(self, notify_queue: queue.Queue | None = None) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._notify_queue = notify_queue

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event = threading.Event()
            self._thread = threading.Thread(target=self._run, name="ResolutionMonitor", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            if self._thread is None:
                return
            self._stop_event.set()
            thread = self._thread
        thread.join(timeout=15)
        with self._lock:
            self._thread = None

    def _make_notify_callback(self) -> Callable[[str, str], None] | None:
        q = self._notify_queue
        if q is None:
            return None

        def _on_notify(title: str, message: str) -> None:
            try:
                q.put_nowait((title, message))
            except queue.Full:
                pass

        return _on_notify

    def _run(self) -> None:
        setup_logging(console=False)
        try:
            config = load_config()
        except FileNotFoundError:
            import logging

            logging.error("找不到配置文件: %s", CONFIG_FILE)
            return
        ResolutionSwitcher(
            config,
            stop_event=self._stop_event,
            on_notify=self._make_notify_callback(),
        ).run()


def save_config(config: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_config() -> None:
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)


def startup_enabled() -> bool:
    return STARTUP_LNK.exists()


def _resolve_pythonw() -> Path:
    pythonw = Path(sys.executable)
    if pythonw.stem.lower() == "python":
        candidate = pythonw.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return pythonw


def _startup_target() -> tuple[Path, str]:
    if getattr(sys, "frozen", False):
        return Path(sys.executable), ""
    script = APP_DIR / "tray_app.py"
    if not script.exists():
        raise FileNotFoundError(f"找不到启动脚本: {script}")
    return _resolve_pythonw(), f'"{script}"'


def install_startup() -> None:
    target, arguments = _startup_target()
    STARTUP_DIR.mkdir(parents=True, exist_ok=True)
    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{STARTUP_LNK}');"
        f"$s.TargetPath = '{target}';"
        f"$s.Arguments = '{arguments}';"
        f"$s.WorkingDirectory = '{APP_DIR}';"
        f"$s.WindowStyle = 7;"
        f"$s.Description = 'Delta Force resolution switcher';"
        f"$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def uninstall_startup() -> None:
    if STARTUP_LNK.exists():
        STARTUP_LNK.unlink()
    subprocess.run(
        ["schtasks", "/Delete", "/TN", "DeltaForceResolutionSwitcher", "/F"],
        creationflags=subprocess.CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def collect_status(monitor: MonitorService) -> AppStatus:
    status = AppStatus()
    status.monitor_running = monitor.is_running()
    status.startup_enabled = startup_enabled()
    try:
        config = load_config()
        status.target_resolution = f"{config['target_width']}x{config['target_height']}"
        status.game_running = is_any_process_running(config.get("process_names", []))
    except (FileNotFoundError, KeyError, TypeError):
        status.target_resolution = "-"

    state = read_state()
    if state and state.get("active"):
        status.session_active = True
        saved = state.get("saved") or {}
        if saved:
            status.restore_resolution = f"{saved.get('width', '?')}x{saved.get('height', '?')}"

    current = get_current_devmode()
    if current:
        info = devmode_to_dict(current)
        status.current_resolution = f"{info['width']}x{info['height']}"
    return status


def load_tray_icons() -> dict[str, Image.Image]:
    """加载三种状态的托盘图标。"""
    return {
        "idle": _load_asset("tray_idle.png"),
        "active": _load_asset("tray_active.png"),
        "stopped": _load_asset("tray_stopped.png"),
    }


class SettingsWindow:
    def __init__(self, app: TrayApplication) -> None:
        self.app = app
        self.window: tk.Toplevel | None = None
        self.status_labels: dict[str, ttk.Label] = {}
        self.fields: dict[str, tk.Variable] = {}
        self.enable_notifications_var = tk.BooleanVar()

    def show(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
            self.refresh_status()
            return

        self.window = tk.Toplevel(self.app.root)
        self.window.title("三角洲行动分辨率监视器")
        width, height = scaled_size(720, 700, self.app.ui_scale)
        min_w, min_h = scaled_size(660, 580, self.app.ui_scale)
        self.window.geometry(f"{width}x{height}")
        self.window.minsize(min_w, min_h)
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self._build()
        self.refresh_status()

    def hide(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.withdraw()

    def _build(self) -> None:
        assert self.window is not None
        pad = {"padx": 12, "pady": 4}
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        status_frame = ttk.LabelFrame(outer, text="运行状态", padding=10)
        status_frame.pack(fill=tk.X, **pad)
        for key, label in [
            ("monitor", "监视器"),
            ("startup", "开机启动"),
            ("game", "游戏进程"),
            ("session", "分辨率会话"),
            ("current", "当前分辨率"),
            ("target", "目标分辨率"),
            ("restore", "待恢复分辨率"),
        ]:
            row = ttk.Frame(status_frame)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=f"{label}:", width=18).pack(side=tk.LEFT)
            value = ttk.Label(row, text="-")
            value.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.status_labels[key] = value

        config_frame = ttk.LabelFrame(outer, text="配置", padding=10)
        config_frame.pack(fill=tk.BOTH, expand=True, **pad)

        self.fields["target_width"] = tk.StringVar()
        self.fields["target_height"] = tk.StringVar()
        self.fields["startup_delay_seconds"] = tk.StringVar()
        self.fields["active_poll_interval_seconds"] = tk.StringVar()
        self.fields["poll_interval_seconds"] = tk.StringVar()
        self._load_fields()

        grid = ttk.Frame(config_frame)
        grid.pack(fill=tk.X)
        ttk.Label(grid, text="目标宽度").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(grid, textvariable=self.fields["target_width"], width=10).grid(row=0, column=1, sticky=tk.W)
        ttk.Label(grid, text="目标高度").grid(row=0, column=2, sticky=tk.W, padx=(16, 0))
        ttk.Entry(grid, textvariable=self.fields["target_height"], width=10).grid(row=0, column=3, sticky=tk.W)
        ttk.Label(grid, text="启动延迟(秒)").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(grid, textvariable=self.fields["startup_delay_seconds"], width=10).grid(row=1, column=1, sticky=tk.W)
        ttk.Label(grid, text="游戏中检测(秒)").grid(row=1, column=2, sticky=tk.W, padx=(16, 0))
        ttk.Entry(grid, textvariable=self.fields["active_poll_interval_seconds"], width=10).grid(row=1, column=3, sticky=tk.W)
        ttk.Label(grid, text="空闲检测(秒)").grid(row=2, column=0, sticky=tk.W, pady=4)
        ttk.Entry(grid, textvariable=self.fields["poll_interval_seconds"], width=10).grid(row=2, column=1, sticky=tk.W)
        ttk.Checkbutton(
            grid,
            text="分辨率切换时发送系统通知",
            variable=self.enable_notifications_var,
        ).grid(row=3, column=0, columnspan=4, sticky=tk.W, pady=(8, 4))

        ttk.Label(config_frame, text="监视进程名（每行一个）").pack(anchor=tk.W, pady=(10, 4))
        process_box = scrolledtext.ScrolledText(config_frame, height=5, wrap=tk.WORD, font=self.app.ui_font)
        process_box.pack(fill=tk.BOTH, expand=True)
        try:
            names = load_config().get("process_names", [])
        except FileNotFoundError:
            names = DEFAULT_CONFIG["process_names"]
        process_box.insert("1.0", "\n".join(names))
        self.process_box = process_box

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_row, text="保存配置", command=self.save_config).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="刷新状态", command=self.refresh_status).pack(side=tk.LEFT, padx=8)

        ctrl_row = ttk.Frame(outer)
        ctrl_row.pack(fill=tk.X, pady=(8, 0))
        self.btn_start = ttk.Button(ctrl_row, text="启动监视", command=self.app.start_monitor)
        self.btn_stop = ttk.Button(ctrl_row, text="关闭监视器", command=self.app.stop_monitor)
        self.btn_install = ttk.Button(ctrl_row, text="安装开机启动", command=self.app.install_startup)
        self.btn_uninstall = ttk.Button(ctrl_row, text="卸载开机启动", command=self.app.uninstall_startup)
        self.btn_start.grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=(0, 6))
        self.btn_stop.grid(row=0, column=1, sticky=tk.W, pady=(0, 6))
        self.btn_install.grid(row=1, column=0, sticky=tk.W, padx=(0, 8))
        self.btn_uninstall.grid(row=1, column=1, sticky=tk.W)

        extra_row = ttk.Frame(outer)
        extra_row.pack(fill=tk.X, pady=(8, 0))
        extra_row.columnconfigure(0, weight=1)
        extra_row.columnconfigure(1, weight=1)
        ttk.Button(extra_row, text="打开日志", command=self.app.open_log).grid(row=0, column=0, sticky=tk.W)
        ttk.Button(extra_row, text="隐藏到托盘", command=self.hide).grid(row=0, column=1, sticky=tk.E)

    def _load_fields(self) -> None:
        try:
            config = load_config()
        except FileNotFoundError:
            config = DEFAULT_CONFIG.copy()
        self.fields["target_width"].set(str(config.get("target_width", 1920)))
        self.fields["target_height"].set(str(config.get("target_height", 1080)))
        self.fields["startup_delay_seconds"].set(str(config.get("startup_delay_seconds", 3)))
        self.fields["active_poll_interval_seconds"].set(str(config.get("active_poll_interval_seconds", 0.3)))
        self.fields["poll_interval_seconds"].set(str(config.get("poll_interval_seconds", 2)))
        self.enable_notifications_var.set(config.get("enable_notifications", True))

    def refresh_status(self) -> None:
        status = collect_status(self.app.monitor)
        mapping = {
            "monitor": "运行中" if status.monitor_running else "未运行",
            "startup": "已启用" if status.startup_enabled else "未启用",
            "game": "已检测到" if status.game_running else "未检测到",
            "session": "游戏中（已切换）" if status.session_active else "空闲",
            "current": status.current_resolution,
            "target": status.target_resolution,
            "restore": status.restore_resolution if status.session_active else "-",
        }
        for key, text in mapping.items():
            if key in self.status_labels:
                self.status_labels[key]["text"] = text
        self.update_controls()

    def update_controls(self) -> None:
        if self.window is None or not self.window.winfo_exists():
            return
        status = collect_status(self.app.monitor)
        if status.monitor_running:
            self.btn_start.grid_remove()
            self.btn_stop.grid()
        else:
            self.btn_stop.grid_remove()
            self.btn_start.grid()
        if status.startup_enabled:
            self.btn_install.grid_remove()
            self.btn_uninstall.grid()
        else:
            self.btn_uninstall.grid_remove()
            self.btn_install.grid()

    def save_config(self) -> None:
        try:
            config = {
                "target_width": int(self.fields["target_width"].get().strip()),
                "target_height": int(self.fields["target_height"].get().strip()),
                "startup_delay_seconds": float(self.fields["startup_delay_seconds"].get().strip()),
                "active_poll_interval_seconds": float(self.fields["active_poll_interval_seconds"].get().strip()),
                "poll_interval_seconds": float(self.fields["poll_interval_seconds"].get().strip()),
                "enable_notifications": self.enable_notifications_var.get(),
                "process_names": [
                    line.strip()
                    for line in self.process_box.get("1.0", tk.END).splitlines()
                    if line.strip()
                ],
            }
        except ValueError:
            messagebox.showerror("错误", "请检查数值配置是否正确。", parent=self.window)
            return
        if not config["process_names"]:
            messagebox.showerror("错误", "至少填写一个进程名。", parent=self.window)
            return
        save_config(config)
        if self.app.monitor.is_running():
            if messagebox.askyesno("配置已保存", "监视器正在运行，是否立即重启以应用新配置？", parent=self.window):
                self.app.restart_monitor()
        else:
            messagebox.showinfo("成功", "配置已保存。", parent=self.window)
        self.refresh_status()
        self.app.update_tray()


class TrayApplication:
    def __init__(self) -> None:
        ensure_config()
        self.root = tk.Tk()
        self.ui_scale, self.ui_font = configure_ui_scaling(self.root)
        self.root.withdraw()
        self.root.title("三角洲行动分辨率监视器")

        self._notify_queue: queue.Queue = queue.Queue(maxsize=16)
        self.monitor = MonitorService(notify_queue=self._notify_queue)
        self.settings = SettingsWindow(self)
        self.icons = load_tray_icons()
        self.icon: pystray.Icon | None = None
        self._build_tray()
        self._schedule_poll()
        self._schedule_notify_check()

    def _create_tray_menu(self) -> pystray.Menu:
        items: list[pystray.MenuItem | pystray.Menu] = [
            pystray.MenuItem("打开设置", self.show_settings, default=True),
        ]
        if self.monitor.is_running():
            items.append(pystray.MenuItem("关闭监视器", self.stop_monitor))
        else:
            items.append(pystray.MenuItem("启动监视", self.start_monitor))
        items.append(pystray.Menu.SEPARATOR)
        if startup_enabled():
            items.append(pystray.MenuItem("卸载开机启动", self.uninstall_startup))
        else:
            items.append(pystray.MenuItem("安装开机启动", self.install_startup))
        items.extend(
            [
                pystray.MenuItem("打开日志", self.open_log),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出程序", self.quit_app),
            ]
        )
        return pystray.Menu(*items)

    def _build_tray(self) -> None:
        self.icon = pystray.Icon(
            "delta_resolution_switcher",
            self.icons["stopped"],
            "三角洲分辨率监视器 - 未运行",
            self._create_tray_menu(),
        )

    def _schedule_poll(self) -> None:
        self.update_tray()
        self.root.after(1500, self._schedule_poll)

    def _schedule_notify_check(self) -> None:
        self._check_notifications()
        self.root.after(500, self._schedule_notify_check)

    def _check_notifications(self) -> None:
        try:
            while True:
                title, message = self._notify_queue.get_nowait()
                if self.icon is not None:
                    self.icon.notify(message, title)
        except queue.Empty:
            pass

    def update_tray(self) -> None:
        status = collect_status(self.monitor)
        if not status.monitor_running:
            icon, title = self.icons["stopped"], "三角洲分辨率监视器 - 未运行"
        elif status.session_active:
            icon, title = self.icons["active"], "三角洲分辨率监视器 - 游戏中"
        else:
            icon, title = self.icons["idle"], "三角洲分辨率监视器 - 监视中"
        if self.icon is not None:
            self.icon.icon = icon
            self.icon.title = title
            self.icon.menu = self._create_tray_menu()
        if self.settings.window is not None and self.settings.window.winfo_exists():
            if self.settings.window.state() != "withdrawn":
                self.settings.refresh_status()
            else:
                self.settings.update_controls()

    def _run_on_ui(self, func) -> None:
        self.root.after(0, func)

    def show_settings(self, icon=None, item=None) -> None:
        self._run_on_ui(self.settings.show)

    def start_monitor(self, icon=None, item=None) -> None:
        def action() -> None:
            if not self.monitor.is_running():
                self.monitor.start()
            self.update_tray()

        self._run_on_ui(action)

    def stop_monitor(self, icon=None, item=None) -> None:
        def action() -> None:
            if self.monitor.is_running():
                self.monitor.stop()
            self.update_tray()

        self._run_on_ui(action)

    def restart_monitor(self) -> None:
        if self.monitor.is_running():
            self.monitor.stop()
        self.monitor.start()
        self.update_tray()
        self.settings.refresh_status()

    def install_startup(self, icon=None, item=None) -> None:
        def action() -> None:
            try:
                install_startup()
                messagebox.showinfo("成功", "已添加到开机启动。")
            except (FileNotFoundError, subprocess.CalledProcessError) as exc:
                messagebox.showerror("错误", f"安装失败：{exc}")
            self.update_tray()

        self._run_on_ui(action)

    def uninstall_startup(self, icon=None, item=None) -> None:
        def action() -> None:
            try:
                uninstall_startup()
                messagebox.showinfo("成功", "已卸载开机启动。")
            except OSError as exc:
                messagebox.showerror("错误", f"卸载失败：{exc}")
            self.update_tray()

        self._run_on_ui(action)

    def open_log(self, icon=None, item=None) -> None:
        def action() -> None:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            if not LOG_FILE.exists():
                LOG_FILE.write_text("", encoding="utf-8")
            os.startfile(LOG_FILE)

        self._run_on_ui(action)

    def quit_app(self, icon=None, item=None) -> None:
        def action() -> None:
            if self.monitor.is_running():
                if not messagebox.askyesno("退出程序", "退出后将停止监视并关闭本程序。是否继续？"):
                    return
                self.monitor.stop()
            if self.icon is not None:
                self.icon.stop()
            self.root.quit()

        self._run_on_ui(action)

    def run(self) -> None:
        tray_thread = threading.Thread(target=self.icon.run, daemon=True)
        tray_thread.start()
        self.root.after(0, self.start_monitor)
        self.root.mainloop()


def main() -> None:
    enable_windows_dpi_awareness()
    TrayApplication().run()


if __name__ == "__main__":
    main()
