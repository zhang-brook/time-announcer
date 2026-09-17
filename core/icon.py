"""应用图标：托盘、窗口标题栏与打包 exe 共用同一份图形。

图形由 :func:`draw` 现场绘制，`assets/app.ico` 是它导出的多尺寸图标文件，
供窗口图标与 PyInstaller 使用。改完绘制代码后运行 `python -m core.icon` 重新生成。
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # Pillow 属可选依赖，仅在实际绘制时才需要导入
    from PIL import Image

ICON_FILE = "app.ico"
# 小尺寸供标题栏与托盘，256 供任务栏、Alt+Tab 与资源管理器大图标
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
FACE = (0, 120, 212, 255)
MARK = (255, 255, 255, 255)


def draw(size: int = 256) -> "Image.Image":
    """绘制蓝底白色时钟图标。"""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    pad = max(1, size // 16)
    pen.ellipse((pad, pad, size - 1 - pad, size - 1 - pad), fill=FACE, outline=MARK,
                width=max(2, size // 21))
    center = size // 2
    hand = max(2, size // 16)
    pen.line((center, center, center, size // 5), fill=MARK, width=hand)
    pen.line((center, center, size * 3 // 4, center), fill=MARK, width=hand)
    return image


def resource_root() -> str:
    """打包后为 _MEIPASS 解包目录，源码运行时为项目根目录。"""
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return bundled
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def icon_path() -> Optional[str]:
    """返回 assets/app.ico 的绝对路径，文件缺失时返回 None。"""
    path = os.path.join(resource_root(), "assets", ICON_FILE)
    return path if os.path.exists(path) else None


def export() -> str:
    """由 draw() 生成多尺寸 assets/app.ico，返回写入路径。"""
    target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "assets", ICON_FILE)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    draw(256).save(target, sizes=[(size, size) for size in ICON_SIZES])
    return target


if __name__ == "__main__":
    print(f"已生成 {export()}")
