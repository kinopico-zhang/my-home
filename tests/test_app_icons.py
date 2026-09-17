"""应用图标测试: PNG 手工解码验不透明底 (Safari 看不见 SVG),
三应用各自图标, 每页声明 PNG favicon + 触屏图标。
拆自 test_auth.py (拆仓批次改口径: 图标按 HTTP 取 —— 三应用的静态
挂在各自 scope 下, 本仓只存共享层那份)。"""
import struct
import zlib


def _png_idat(data: bytes) -> bytes:
    """拼出 PNG 的全部 IDAT 块。"""
    pos, idat = 8, b""
    while pos < len(data):
        ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
        if typ == b"IDAT":
            idat += data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
    return idat


def _unfilter_png(raw: bytes, w: int, ch: int) -> list[bytearray]:
    """逆 PNG 行滤镜 (8-bit, 滤镜 0-4), 返回每行的 RGB(A) 字节 (不引 Pillow)。"""
    stride = w * ch + 1
    rows: list[bytearray] = []
    for y in range(len(raw) // stride):
        f = raw[y * stride]
        row = bytearray(raw[y*stride+1:(y+1)*stride])
        up = rows[y - 1] if y else None
        for x in range(w * ch):
            a = row[x - ch] if x >= ch else 0
            b = up[x] if up is not None else 0
            c = up[x - ch] if up is not None and x >= ch else 0
            if f == 1:
                row[x] = (row[x] + a) & 255
            elif f == 2:
                row[x] = (row[x] + b) & 255
            elif f == 3:
                row[x] = (row[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                row[x] = (row[x] + (a if pa <= pb and pa <= pc
                                    else b if pb <= pc else c)) & 255
        rows.append(row)
    return rows

def test_apple_touch_icon_opaque_with_padding(auth):
    """iOS 主屏图标: 不透明纯白底 (透明底被 iOS 合成纯黑) + Tesla 红 T 居中留边。
    旧版 T 铺满整个画布还带 Alpha → 添加到主屏幕后 logo 过大且黑底。"""
    d = auth.get("/tesla/static/apple-touch-icon.png").content
    w, h = struct.unpack(">II", d[16:24])
    ctype = d[25]
    assert (w, h) == (180, 180)
    assert ctype in (2, 6), f"应是 RGB/RGBA, 实际类型 {ctype}"

    # 纯 Python 解码 (无 Pillow 依赖): 拼出 IDAT 后逆滤镜
    ch = {2: 3, 6: 4}[ctype]
    rows = _unfilter_png(zlib.decompress(_png_idat(d)), w, ch)

    def px(x, y):
        return tuple(rows[y][x*ch:x*ch+3])

    if ch == 4:   # 带 Alpha 则必须全不透明 (透明像素在主屏上变黑)
        assert all(rows[y][x*4+3] == 255
                   for y in range(h) for x in range(0, w, 9))
    # 满出血白底, 四角纯白 (iOS 自己切圆角, 不能预切)
    for x, y in [(0, 0), (w-1, 0), (0, h-1), (w-1, h-1)]:
        assert px(x, y) == (255, 255, 255)
    # T 标居中, 是 Tesla 红
    assert px(w//2, h//2) == (232, 33, 39)
    # 上下左右各留 ≥18px (10%) 白边: logo 不再铺满画布
    assert px(18, h//2) == (255, 255, 255)
    assert px(w-1-18, h//2) == (255, 255, 255)
    assert px(w//2, 18) == (255, 255, 255)
    assert px(w//2, h-1-18) == (255, 255, 255)


def _fetch_icons(auth, prefix):
    """拉一个应用静态 scope 下的全套图标 (按用户实际拿到的字节验)。"""
    icons = {}
    for fname, size in (("apple-touch-icon.png", 180), ("icon-192.png", 192),
                        ("icon-512.png", 512), ("favicon-32.png", 32)):
        r = auth.get(f"{prefix}/{fname}")
        assert r.status_code == 200, f"{prefix}/{fname}"
        d = r.content
        w, h = struct.unpack(">II", d[16:24])
        assert (w, h) == (size, size), fname
        assert d[25] in (0, 2), f"{fname} 必须不带 Alpha (iOS 透明底变黑)"
        icons[fname] = d
    return icons


def test_mymoney_app_has_own_icons(auth):
    """My Money 是独立应用: 自己的图标 (Tesla 红底白钱袋, 不透明全出血方形 ——
    iOS 自己圆角, 透明底会被合成纯黑), 不借 My Tesla 的红 T。"""
    icons = _fetch_icons(auth, "/bookkeeping/static")
    rows = _unfilter_png(zlib.decompress(_png_idat(icons["apple-touch-icon.png"])),
                         180, 3)
    icon_w = icon_h = 180
    def px(x, y):
        return tuple(rows[y][x*3:x*3+3])
    # 四角 Tesla 红 (#E82127) 满出血; 中心区有白色钱袋笔画
    for x, y in [(1, 1), (icon_w-2, 1), (1, icon_h-2), (icon_w-2, icon_h-2)]:
        assert px(x, y) == (232, 33, 39), f"角({x},{y}) {px(x, y)}"
    whites = sum(1 for yy in range(30, icon_h-30, 3)
                 for xx in range(30, icon_w-30, 3) if min(px(xx, yy)) > 225)
    assert whites > 60, f"白色钱袋笔画太少: {whites}"
    tesla = auth.get("/tesla/static/icon-512.png").content
    assert icons["icon-512.png"] != tesla, "两个应用不该共用图标"


def test_mymusic_app_has_own_icons(auth):
    """My Music 是独立应用: 自己的图标 (Apple 红底白音符, 不透明全出血方形 ——
    iOS 自己圆角, 透明底会被合成纯黑), 不借 My Tesla 的红 T。"""
    icons = _fetch_icons(auth, "/music/static")
    rows = _unfilter_png(zlib.decompress(_png_idat(icons["apple-touch-icon.png"])),
                         180, 3)
    icon_w = icon_h = 180
    def px(x, y):
        return tuple(rows[y][x*3:x*3+3])
    # 四角 Apple 红 (#ff2f56) 满出血; 中心区有白色音符笔画
    for x, y in [(1, 1), (icon_w-2, 1), (1, icon_h-2), (icon_w-2, icon_h-2)]:
        assert px(x, y) == (255, 47, 86), f"角({x},{y}) {px(x, y)}"
    whites = sum(1 for yy in range(30, icon_h-30, 3)
                 for xx in range(30, icon_w-30, 3) if min(px(xx, yy)) > 225)
    assert whites > 60, f"白色音符笔画太少: {whites}"
    tesla = auth.get("/tesla/static/icon-512.png").content
    assert icons["icon-512.png"] != tesla, "两个应用不该共用图标"


def test_myhome_app_has_own_icons(auth):
    """共享层也有自己的图标 (黑底白房子, 不透明全出血方形), 与三个应用
    互不共用 —— 四个主屏图标一眼可分。"""
    icons = _fetch_icons(auth, "/static")
    mine = icons["icon-512.png"]
    assert mine != auth.get("/tesla/static/icon-512.png").content
    assert mine != auth.get("/bookkeeping/static/icon-512.png").content
    assert mine != auth.get("/music/static/icon-512.png").content, \
        "四个入口不该共用图标"


def test_all_pages_declare_png_and_touch_icons(auth):
    """每个页面都要有 PNG favicon + apple-touch-icon (Safari/iOS 看不见 SVG)。"""
    from tests.page_test_helpers import (  # pylint: disable=import-outside-toplevel
        ALL_PAGES, _page_client)
    for path in ALL_PAGES:
        body = _page_client(auth, path).get(path).text
        assert "favicon-32.png" in body, f"{path} 缺 PNG favicon"
        assert "apple-touch-icon.png" in body, f"{path} 缺 apple-touch-icon"
