#!/usr/bin/env python3
"""生成应用图标：exe 的 .ico 文件 + 三种状态的托盘图标。"""

from PIL import Image, ImageDraw, ImageFont
import math
import os


def draw_monitor_switch(draw: ImageDraw.ImageDraw, size: int, color: str, bg_color: str):
    """绘制「显示器 + 分辨率切换箭头」图标。

    整体为一个圆角矩形显示器外框，内部是屏幕区域，
    屏幕中央有上下双向箭头，示意分辨率切换。
    """
    # 背景圆角方形（显示器外壳）
    margin = size * 0.08
    radius = size * 0.16
    bezel_rect = [
        margin,
        margin,
        size - margin,
        size - margin * 0.55,
    ]
    # 底座
    stand_width = size * 0.2
    stand_height = size * 0.08
    stand_left = size / 2 - stand_width / 2
    stand_top = bezel_rect[3] + 1
    # 支架
    neck_width = size * 0.06
    neck_height = size * 0.06
    neck_left = size / 2 - neck_width / 2
    neck_top = bezel_rect[3] - 1

    # 绘制显示器外框
    draw.rounded_rectangle(bezel_rect, radius=radius, fill=color, outline=None)
    # 屏幕区域（内凹）
    screen_margin = size * 0.04
    screen_rect = [
        bezel_rect[0] + screen_margin,
        bezel_rect[1] + screen_margin * 1.5,
        bezel_rect[2] - screen_margin,
        bezel_rect[3] - screen_margin,
    ]
    draw.rounded_rectangle(screen_rect, radius=radius * 0.7, fill=bg_color, outline=None)

    # 绘制底座
    draw.rounded_rectangle(
        [stand_left, stand_top, stand_left + stand_width, stand_top + stand_height],
        radius=size * 0.03,
        fill=color,
    )
    # 支架
    draw.rectangle(
        [neck_left, neck_top, neck_left + neck_width, stand_top],
        fill=color,
    )

    # 屏幕中央：双向箭头（分辨率切换）
    arrow_color = color
    cx = size / 2
    cy = (bezel_rect[1] + bezel_rect[3]) / 2
    arrow_w = size * 0.1
    arrow_h = size * 0.08
    arrow_gap = size * 0.01
    line_w = max(2, int(size * 0.04))

    # 下箭头
    draw.polygon(
        [
            (cx, cy + arrow_h / 2 + arrow_gap),
            (cx - arrow_w, cy - arrow_h / 2 + arrow_gap),
            (cx - arrow_w * 0.4, cy - arrow_h / 2 + arrow_gap),
            (cx - arrow_w * 0.4, cy + arrow_gap),
            (cx + arrow_w * 0.4, cy + arrow_gap),
            (cx + arrow_w * 0.4, cy - arrow_h / 2 + arrow_gap),
            (cx + arrow_w, cy - arrow_h / 2 + arrow_gap),
        ],
        fill=arrow_color,
    )
    # 上箭头（稍上）
    draw.polygon(
        [
            (cx, cy - arrow_h / 2 - arrow_gap),
            (cx - arrow_w, cy + arrow_h / 2 - arrow_gap),
            (cx - arrow_w * 0.4, cy + arrow_h / 2 - arrow_gap),
            (cx - arrow_w * 0.4, cy - arrow_gap),
            (cx + arrow_w * 0.4, cy - arrow_gap),
            (cx + arrow_w * 0.4, cy + arrow_h / 2 - arrow_gap),
            (cx + arrow_w, cy + arrow_h / 2 - arrow_gap),
        ],
        fill=arrow_color,
    )


def draw_monitor_switch_simple(
    draw: ImageDraw.ImageDraw, size: int, color: str, bg_color: str
):
    """小尺寸版本：更简洁的设计，适合 16x16 / 32x32。"""
    margin = 1 if size <= 16 else 2
    radius = 2 if size <= 16 else 3
    bezel = [margin, margin, size - margin, size - margin - 1]
    draw.rounded_rectangle(bezel, radius=radius, fill=color)

    # 屏幕
    inset = 1 if size <= 16 else 2
    screen = [
        bezel[0] + inset,
        bezel[1] + inset,
        bezel[2] - inset,
        bezel[3] - inset,
    ]
    draw.rounded_rectangle(screen, radius=max(1, radius - 1), fill=bg_color)

    # 箭头（简化）
    cx, cy = size / 2, size / 2 - 0.5
    aw = 2 if size <= 16 else 3
    ah = 2 if size <= 16 else 3
    lw = 1

    # 上下两个三角形
    draw.polygon(
        [(cx, cy + ah), (cx - aw, cy), (cx + aw, cy)],
        fill=color,
    )
    draw.polygon(
        [(cx, cy - ah - 1), (cx - aw, cy - 1), (cx + aw, cy - 1)],
        fill=color,
    )


def make_icon(color: str, bg_color: str, size: int = 64) -> Image.Image:
    """生成单个图标图像。"""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if size <= 32:
        draw_monitor_switch_simple(draw, size, color, bg_color)
    else:
        draw_monitor_switch(draw, size, color, bg_color)
    return image


def generate_ico(output_path: str) -> None:
    """生成多分辨率 .ico 文件。"""
    sizes = [16, 32, 48, 64, 128, 256]
    images = []
    for s in sizes:
        img = make_icon("#1a1a2e", "#e94560", s)
        # 转为 RGBA 以确保兼容
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        images.append(img)

    # 以最大尺寸为基准保存
    images[0].save(
        output_path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )


COLOR_IDLE = "#43A047"
COLOR_ACTIVE = "#FB8C00"
COLOR_STOPPED = "#9E9E9E"
BG_DARK = "#1a1a2e"
BG_LIGHT = "#e8e8e8"


def main() -> None:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    assets_dir = os.path.join(base_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)

    # 生成托盘图标
    for name, fg_color in [
        ("tray_idle", COLOR_IDLE),
        ("tray_active", COLOR_ACTIVE),
        ("tray_stopped", COLOR_STOPPED),
    ]:
        img = make_icon(fg_color, BG_LIGHT, 64)
        path = os.path.join(assets_dir, f"{name}.png")
        img.save(path, format="PNG")
        print(f"Generated: {path}")

    # 生成 .ico
    ico_path = os.path.join(base_dir, "icon.ico")
    generate_ico(ico_path)
    print(f"Generated: {ico_path}")


if __name__ == "__main__":
    main()
