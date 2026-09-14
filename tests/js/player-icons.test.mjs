/* 播放器控制图标对齐的单元测试 (2026-09-14 用户反馈「歪七扭八」后立规矩):
   图标画在 24×24 视框里, 视觉包围盒的中心必须落在正中 (12,12) ——
   图标光心 = 按钮中心, 播放↔暂停切换不左右跳位, 上一首/下一首镜像对称。
   从源文件文本里提 SVG 路径 (music-common.js 无导出尾巴, 不为测试改产品文件),
   用迷你路径解析器算包围盒 —— 只需覆盖图标用到的 M/L/m/l/H/h/V/v/z。 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dir = path.join(path.dirname(fileURLToPath(import.meta.url)),
  "../../app/music/static");
const common = fs.readFileSync(path.join(dir, "music-common.js"), "utf8");
const page = fs.readFileSync(path.join(dir, "music.html"), "utf8");

/** 算 SVG 路径的几何包围盒 (只认图标用到的命令; M 后隐式 L 同样取点)。 */
function pathBBox(d) {
  const tokens = d.match(/[A-Za-z]|-?\d*\.?\d+/g) || [];
  let x = 0, y = 0;               // 当前点 (绝对坐标)
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  const mark = () => {
    minX = Math.min(minX, x); maxX = Math.max(maxX, x);
    minY = Math.min(minY, y); maxY = Math.max(maxY, y);
  };
  let i = 0;
  let command = "";
  while (i < tokens.length) {
    if (/[A-Za-z]/.test(tokens[i])) { command = tokens[i]; i += 1; continue; }
    const num = () => Number(tokens[i++]);
    switch (command) {
      case "M": case "L": x = num(); y = num(); mark(); break;
      case "m": case "l": x += num(); y += num(); mark(); break;
      case "H": x = num(); mark(); break;
      case "h": x += num(); mark(); break;
      case "V": y = num(); mark(); break;
      case "v": y += num(); mark(); break;
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
  // 同宽同高 (镜像形状), 区间一致 —— 一对跳转键看起来才对称
  assert.equal(prev.maxX - prev.minX, next.maxX - next.minX);
  assert.equal(prev.maxY - prev.minY, next.maxY - next.minY);
  assert.deepEqual([prev.minX, prev.maxX], [next.minX, next.maxX]);
  // 迷你条与全屏页的下一首是同一个字形
  assert.equal(pick("mini-next"), pick("fp-next"));
});
