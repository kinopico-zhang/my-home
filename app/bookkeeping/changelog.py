"""My Money 更新日志数据: 每个版本 = 一批改动的合并, 文案站在使用者视角。

不逐提交记版本 (一个版本可以同时含多个修复和多个功能); 版本号 x.y.z ——
x 大改版 · y 新功能 · z 问题修复, 新批次加在最上面 (新→老)。
记账应用自己的版本线 (2026-09-14 起与 My Tesla 的更新日志各自独立)。
"""
from typing import Final

from ..schemas import ChangelogItem, ChangelogVersion

VERSIONS: Final[list[ChangelogVersion]] = [
    ChangelogVersion(version="1.0.1", date="2026-09-14", items=[
        ChangelogItem(kind="新增", text="加密访问: 网站有了带锁的新地址 kinopico.duckdns.org:8500, 记的账和密码全程加密,"
                                       " 在家、在外都能用"),
        ChangelogItem(kind="改进", text="地址换成固定域名 —— 家里宽带 IP 以后再变也照常用, 不用改收藏; 旧的数字地址停用"),
        ChangelogItem(kind="修复", text="以前记账密码是明文过网的 —— 现在加密; 新地址首次要重新登录, 主屏图标删掉重加一次"),
    ]),
    ChangelogVersion(version="1.0.0", date="2026-09-13", items=[
        ChangelogItem(kind="新增", text="My Money (记账): 独立小应用, 可单独加到主屏幕; 记一笔支出或收入, 按月看汇总, 每笔都记着是谁记的;"
                                       " 断网也能记, 联网自动同步"),
        ChangelogItem(kind="新增", text="记账的金额输入换成自带计算器键盘: 0-9 加加减乘除顺手就能算 (买菜 3.5×2 这种), 边打边出结果;"
                                       " 「完成」和 ⌫ 排在键盘右边, 长按 ⌫ 一键清空; 系统键盘不再弹出来"),
        ChangelogItem(kind="新增", text="记账类别直接铺子类: 一格就是一个子类 (早餐 / 午餐 / 充电 / 地铁…), 点一下就选好, 不用先点大类;"
                                       " 类别是从挖财账本导过来的 160 多个, 收入支出各一套"),
        ChangelogItem(kind="新增", text="记一笔可以改记账时刻, 还能给账目贴标签; 用过的标签会记着, 下次点一下就能选上"),
        ChangelogItem(kind="新增", text="更新日志页 (本页): 记账应用的版本变化在这里看, 不再混在别的应用日志里"),
        ChangelogItem(kind="改进", text="记一笔弹层顶部的把手可以拽下来关闭 (和充电详情一个手势), 点一下把手也能关; 类别图标改成单色, 跟深色界面更搭"),
        ChangelogItem(kind="改进", text="应用图标换成 Tesla 红的钱袋标, 主屏幕上三个应用一眼就能分清"),
        ChangelogItem(kind="修复", text="主屏幕点图标可能打开别的应用 —— 修好了; 新图标也要把主屏幕图标删除后重新添加一次才看得到"),
        ChangelogItem(kind="修复", text="记一笔弹层能被左右拖动 (日期备注一行比屏幕宽了一点)"),
    ]),
]


def entries() -> list[ChangelogVersion]:
    """全部版本, 新→老。"""
    return VERSIONS
