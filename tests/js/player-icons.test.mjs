/* 播放器控制图标对齐的单元测试 (2026-09-14 用户反馈「歪七扭八」后立规矩):
   图标画在 24×24 视框里, 视觉包围盒的中心必须落在正中 (12,12) ——
   图标光心 = 按钮中心, 播放↔暂停切换不左右跳位, 上一首/下一首镜像对称。
   从源文件文本里提 SVG 路径 (music-common.js 无导出尾巴, 不为测试改产品文件),
   用迷你路径解析器算包围盒 —— M/L/m/l/H/h/V/v/z + 素材库图标带的 q/Q/t/T。 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.join(path.dirname(fileURLToPath(import.meta.url)),
  "../../app/music/static");
const common = fs.readFileSync(path.join(dir, "music-common.js"), "utf8");
const page = fs.readFileSync(path.join(dir, "music.html"), "utf8");

/** 算 SVG 路径的几何包围盒 (图标用到的命令都认; M 后隐式 L 同样取点)。
    素材库图标 (2026-09-15 起) 是 q/t 二次曲线: 曲线必落在控制多边形凸包内,
    所以控制点 + 终点都标记; t 的反射控制点 = 2×当前点 − 上一控制点。
    烘焙脚本 (bake-icons.py) 用同一套标记算居中, 两边必须一致。 */
function pathBBox(d) {
  const tokens = d.match(/[A-Za-z]|-?\d*\.?\d+/g) || [];
  let x = 0, y = 0;               // 当前点 (绝对坐标)
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  let lastControl = null;         // 上一条 q/t 的控制点 (t 反射用)
  const markAt = (px, py) => {
    minX = Math.min(minX, px); maxX = Math.max(maxX, px);
    minY = Math.min(minY, py); maxY = Math.max(maxY, py);
  };
  const mark = () => markAt(x, y);
  let i = 0;
  let command = "";
  while (i < tokens.length) {
    if (/[A-Za-z]/.test(tokens[i])) { command = tokens[i]; i += 1; continue; }
    const num = () => Number(tokens[i++]);
    switch (command) {
      case "M": case "L": x = num(); y = num(); mark(); lastControl = null; break;
      case "m": case "l": x += num(); y += num(); mark(); lastControl = null; break;
      case "H": x = num(); mark(); lastControl = null; break;
      case "h": x += num(); mark(); lastControl = null; break;
      case "V": y = num(); mark(); lastControl = null; break;
      case "v": y += num(); mark(); lastControl = null; break;
      case "Q": {
        const cx = num(), cy = num();
        x = num(); y = num();
        markAt(cx, cy); mark();
        lastControl = [cx, cy];
        break;
      }
      case "q": {
        const cx = x + num(), cy = y + num();
        x += num(); y += num();
        markAt(cx, cy); mark();
        lastControl = [cx, cy];
        break;
      }
      case "T": {
        let cx = x, cy = y;
        if (lastControl) { cx = 2 * x - lastControl[0]; cy = 2 * y - lastControl[1]; }
        x = num(); y = num();
        markAt(cx, cy); mark();
        lastControl = [cx, cy];
        break;
      }
      case "t": {
        let cx = x, cy = y;
        if (lastControl) { cx = 2 * x - lastControl[0]; cy = 2 * y - lastControl[1]; }
        x += num(); y += num();
        markAt(cx, cy); mark();
        lastControl = [cx, cy];
        break;
      }
      case "z": case "Z": break;
      default: throw new Error(`路径命令没支持: ${command}`);
    }
  }
  return { minX, maxX, minY, maxY };
}

function iconPath(name) {
  const match = common.match(new RegExp(`const ${name} = '[^']*d="([^"]+)"`));
  assert.ok(match, `music-common.js 里找不到 ${name}`);
  return match[1];
}

function centered(name, d, tolerance = 0.01) {
  const b = pathBBox(d);
  const cx = (b.minX + b.maxX) / 2, cy = (b.minY + b.maxY) / 2;
  assert.ok(Math.abs(cx - 12) <= tolerance, `${name} 横向光心 ${cx} ≠ 12`);
  assert.ok(Math.abs(cy - 12) <= tolerance, `${name} 纵向光心 ${cy} ≠ 12`);
  return b;
}

test("播放/暂停图标: 包围盒中心在正中 (切换不跳位)", () => {
  centered("ICON_PLAY (小)", iconPath("ICON_PLAY"));
  centered("ICON_PAUSE (小)", iconPath("ICON_PAUSE"));
  centered("ICON_PLAY_BIG", iconPath("ICON_PLAY_BIG"));
  centered("ICON_PAUSE_BIG", iconPath("ICON_PAUSE_BIG"));
  centered("ICON_ACTION_PLAY (行内播放角标)", iconPath("ICON_ACTION_PLAY"));
  centered("ICON_ACTION_TRASH (列表删除)", iconPath("ICON_ACTION_TRASH"));
});

test("上一首/下一首 (全屏 + 迷你条): 居中且彼此镜像", () => {
  const pick = (id) => {
    const match = page.match(new RegExp(`id="${id}".*?d="([^"]+)"`, "s"));
    assert.ok(match, `music.html 里找不到 ${id} 的图标路径`);
    return match[1];
  };
  const prev = centered("fp-prev", pick("fp-prev"));
  const next = centered("fp-next", pick("fp-next"));
  centered("mini-next", pick("mini-next"));
  // 同宽同高 (镜像形状), 区间一致 —— 一对跳转键看起来才对称。
  // 镜像是 24−x 烘出来的, 浮点尾差 1e-15 级, 用容差不卡 bit 级相等
  const nearly = (a, b) => Math.abs(a - b) <= 1e-6;
  assert.ok(nearly(prev.maxX - prev.minX, next.maxX - next.minX),
    `上一首宽 ${prev.maxX - prev.minX} ≠ 下一首宽 ${next.maxX - next.minX}`);
  assert.ok(nearly(prev.maxY - prev.minY, next.maxY - next.minY),
    `上一首高 ${prev.maxY - prev.minY} ≠ 下一首高 ${next.maxY - next.minY}`);
  assert.ok(nearly(prev.minX, next.minX) && nearly(prev.maxX, next.maxX),
    `区间不对称: prev [${prev.minX}, ${prev.maxX}] vs next [${next.minX}, ${next.maxX}]`);
  // 迷你条与全屏页的下一首是同一个字形
  assert.equal(pick("mini-next"), pick("fp-next"));
});
