"""Visual evidence for the Siemens handoff, captured from the live product."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import pathlib
import sys
import time
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.integrations.plant_simulation.adapter import PlantSimulationAdapter  # noqa: E402
from app.integrations.plant_simulation.from_factory import exchange_from_factory  # noqa: E402
from app.models.factory import Factory  # noqa: E402
from app.models.layout import FactoryLayout  # noqa: E402

API = "http://localhost:8000"
REPO = pathlib.Path(__file__).resolve().parents[2]


# screen capture

def capture_plant_simulation(path: pathlib.Path) -> bool:
    """PrintWindow the Plant Simulation main window into `path`."""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32

    target = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _param):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if "Plant Simulation" in buffer.value and user32.IsWindowVisible(hwnd):
                target.append((hwnd, buffer.value))
        return True

    user32.EnumWindows(each, 0)
    if not target:
        return False

    hwnd, title = target[0]
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return False

    window_dc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)
    # 2 = PW_RENDERFULLCONTENT, which is what makes a hardware-composited
    # child pane (the 3D view) appear instead of a black rectangle.
    user32.PrintWindow(hwnd, mem_dc, 2)

    _save_bitmap(bitmap, width, height, path)

    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, window_dc)
    print(f"    captured '{title}' -> {path.name} ({width}x{height})")
    return True


def _save_bitmap(bitmap, width: int, height: int, path: pathlib.Path) -> None:
    """Write a GDI bitmap out as a PNG, via Pillow if present, else BMP."""
    gdi32 = ctypes.windll.gdi32

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    header = BITMAPINFOHEADER()
    header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    header.biWidth = width
    header.biHeight = -height  # top-down
    header.biPlanes = 1
    header.biBitCount = 32
    header.biCompression = 0

    buffer = ctypes.create_string_buffer(width * height * 4)
    dc = ctypes.windll.user32.GetDC(0)
    gdi32.GetDIBits(dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
    ctypes.windll.user32.ReleaseDC(0, dc)

    from PIL import Image  # noqa: PLC0415 - only needed here

    image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
    image.convert("RGB").save(path)



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="bc4f970cd40d4438")
    parser.add_argument("--prefix", default="ps")
    parser.add_argument("--run-seconds", type=float, default=120.0)
    args = parser.parse_args()

    with urllib.request.urlopen(f"{API}/projects/{args.project}") as response:
        state = json.load(response)["project"]["state"]

    concept = state["concept"]
    package = exchange_from_factory(
        Factory.model_validate(concept["factory"]),
        concept["product_id"],
        layout=FactoryLayout.model_validate(concept["layout"]) if concept.get("layout") else None,
        equipment_selections=state.get("equipment", {}).get("selections") or None,
    )

    adapter = PlantSimulationAdapter()
    adapter.connect(visible=True)
    print(f"connected: {adapter.product_version} via {adapter.prog_id}")

    out = pathlib.Path(os.environ.get("TEMP", ".")) / "fm-probe" / "visual-qa.spp"
    out.parent.mkdir(parents=True, exist_ok=True)

    result = adapter.build(package, save_path=str(out))
    print(f"built: ok={result.ok} layout={result.layout_mode} overlaps={result.overlaps or 'none'}")
    for tier in result.tiers():
        print(f"  {tier.tier:10} {tier.status:9} {tier.detail}")

    root = adapter.ids.root if adapter.ids else ".Models.Model"

    def talk(code: str, label: str) -> bool:
        try:
            adapter.app.ExecuteSimTalk(code)
            print(f"  OK   {label}")
            return True
        except Exception as exc:  # noqa: BLE001 - probing what this build supports
            print(f"  fail {label}: {str(exc)[:70]}")
            return False

    print("arranging the view")
    for code, label in (
        (f"{root}.openWindow", "open frame window"),
        (f"{root}.zoomAll", "zoom to fit"),
        (f"{root}.showAll", "show all"),
    ):
        talk(code, label)

    time.sleep(2.5)
    capture_plant_simulation(REPO / f"{args.prefix}-2d-network.png")

    print(f"running the model for {args.run_seconds} simulated seconds")
    talk(f"{root}.EventController.reset", "reset")
    talk(f"{root}.EventController.start", "start")
    time.sleep(4)
    capture_plant_simulation(REPO / f"{args.prefix}-3d-running.png")

    print()
    print("LEFT OPEN. Model at:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
