"""My Music 更新日志数据: 每个版本 = 一批改动的合并, 文案站在使用者视角。

不逐提交记版本 (一个版本可以同时含多个修复和多个功能); 版本号 x.y.z ——
x 大改版 · y 新功能 · z 问题修复, 新批次加在最上面 (新→老)。
听歌应用自己的版本线 (2026-09-14 起与 My Tesla 的更新日志各自独立)。
"""
from typing import Final

from ..schemas import ChangelogItem, ChangelogVersion

VERSIONS: Final[list[ChangelogVersion]] = [
    ChangelogVersion(version="1.0.0", date="2026-09-14", items=[
        ChangelogItem(kind="新增", text="My Music (听歌): 独立小应用, 可单独加到主屏幕; 扫描 NAS 里的曲库 (5 万首) 建索引,"
                                       " 手机上直接串流播放"),
        ChangelogItem(kind="新增", text="播放器: 迷你条悬浮在页面底部, 点开是全屏播放页, 背景是专辑封面的模糊大图; 锁屏 / 控制中心能看歌名封面,"
                                       " 也能暂停切歌"),
        ChangelogItem(kind="新增", text="歌词: 全屏页点「词」看逐行滚动的歌词, 唱到哪行哪行放大; 点任意一行直接跳到那句"),
        ChangelogItem(kind="新增", text="搜歌词: 搜索框直接搜歌词内容, 想不起歌名只记得一句词也能找到那首歌"),
        ChangelogItem(kind="新增", text="按语种筛歌: 中文 / 日文 / 英文 / 韩文 / 俄文一键筛, 想专门听日文歌不用一张张专辑翻"),
        ChangelogItem(kind="新增", text="资料库四个角度逛曲库: 最近添加 / 专辑 / 艺人 / 歌曲, 专辑艺人页里点「播放」「随机」就开听"),
        ChangelogItem(kind="新增", text="随机播放 / 列表循环 / 单曲循环, 播放队列面板能看接下来放什么、跳着选"),
        ChangelogItem(kind="新增", text="关掉浏览器再打开, 会接着上次听到的那首 (进度也记得)"),
        ChangelogItem(kind="新增", text="统计页: 曲库里有多少艺人、多少专辑、多少首歌, 各格式各多少首, 总共能听多久, 一眼看清"),
        ChangelogItem(kind="新增", text="更新日志页 (本页): 听歌应用的版本变化在这里看, 不再混在别的应用日志里"),
        ChangelogItem(kind="改进", text="My Home 门厅现在是三个应用并排: 听歌和车辆、记账一样, 点卡片就进"),
        ChangelogItem(kind="修复", text="极少数老格式 (TAK / DSD / APE) 浏览器播不了的会置灰标明, 点了会提示而不是没反应"),
        ChangelogItem(kind="修复", text="迷你条上的暂停 / 下一首: 点了不该把全屏播放页弹出来"),
        ChangelogItem(kind="修复", text="专辑页里点艺人名没反应 (跳转丢了艺人编号)"),
    ]),
]


def entries() -> list[ChangelogVersion]:
    """全部版本, 新→老。"""
    return VERSIONS
