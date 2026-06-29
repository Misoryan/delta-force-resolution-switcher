# 三角洲行动分辨率监视器

Windows 托盘工具：游戏启动时自动切换至 1920×1080，关闭游戏后恢复原分辨率。

## 功能

- 系统托盘常驻，支持高 DPI 显示
- 图形化设置窗口：配置分辨率、检测间隔、监视进程名
- 启动后自动开始监视，可手动关闭/重启监视器
- 可选开机自启动
- 崩溃恢复：异常退出后下次启动尝试还原分辨率

## 快速开始

### 使用 Release（推荐）

1. 从 [Releases](https://github.com/Misoryan/delta-force-resolution-switcher/releases) 下载 `DeltaResolutionSwitcher-v1.0.0.zip`
2. 解压到任意目录
3. 双击 `DeltaResolutionSwitcher.exe`
4. 在托盘图标上右键打开设置，按需修改 `config.json` 中的配置

> `config.json` 需与 exe 放在同一目录。

### 从源码运行

```bash
pip install -r requirements.txt
python tray_app.py
```

### 自行打包 exe

```bash
build.bat
```

输出位于 `dist\DeltaResolutionSwitcher.exe`。

## 配置说明

`config.json` 示例：

```json
{
  "target_width": 1920,
  "target_height": 1080,
  "poll_interval_seconds": 2,
  "process_names": [
    "DeltaForceClient-Win64-Shipping.exe",
    "DeltaForce.exe"
  ],
  "startup_delay_seconds": 3,
  "active_poll_interval_seconds": 0.3
}
```

| 字段 | 说明 |
|------|------|
| `target_width` / `target_height` | 游戏运行时切换到的分辨率 |
| `process_names` | 监视的进程名（每行一个，含 `.exe`） |
| `startup_delay_seconds` | 检测到游戏后延迟切换的秒数 |
| `active_poll_interval_seconds` | 游戏运行中的检测间隔 |
| `poll_interval_seconds` | 空闲时的检测间隔 |

## 日志与状态

- 日志：`%LOCALAPPDATA%\DeltaResolutionSwitcher\switcher.log`
- 运行状态：`%LOCALAPPDATA%\DeltaResolutionSwitcher\state.json`

## 项目结构

```
delta_resolution_switcher.py   # 分辨率切换核心逻辑
tray_app.py                  # 托盘与设置界面
config.json                  # 默认配置
build.bat                      # 打包脚本
DeltaResolutionSwitcher.spec   # PyInstaller 配置
```

## 说明

- 托盘程序与分辨率监视逻辑在**同一进程**内：关闭监视器仅停止后台线程，退出程序才会完全结束
- 移动文件夹后请重新在设置中「安装开机启动」
- 仅支持 Windows

## 许可证

MIT
