"""My Music 更新日志数据: 每个版本 = 一批改动的合并, 文案站在使用者视角。

不逐提交记版本 (一个版本可以同时含多个修复和多个功能); 版本号 x.y.z ——
x 大改版 · y 新功能 · z 问题修复, 新批次加在最上面 (新→老)。
听歌应用自己的版本线 (2026-09-14 起与 My Tesla 的更新日志各自独立)。
"""
from typing import Final

from ..schemas import ChangelogItem, ChangelogVersion

VERSIONS: Final[list[ChangelogVersion]] = [
    ChangelogVersion(version="1.3.0", date="2026-09-15", items=[
        ChangelogItem(kind="新增", text="长按任意一首歌弹出菜单: 播放 / 进艺人主页 / 分享 / 添加到播放列表,"
                                       " 主页、资料库、搜索里都能长按 (电脑上是点右键)"),
        ChangelogItem(kind="新增", text="添加到播放列表: 长按菜单里能选任何列表或当场新建一个,"
                                       " 选择单只管加歌; 整张列表的删除在列表页的「删除列表」里,"
                                       " 新建的排主页最上面"),
        ChangelogItem(kind="新增", text="下载管理: 「已下载」栏顶部多了统计行 —— 几首歌、合计多大,"
                                       " 手机存储总占用也看得见; 「全部删除」一键清空 (删前会再问一次)"),
        ChangelogItem(kind="改进", text="「已下载」栏每首歌行尾直接标着这首歌占多大, 哪首占地大一眼看出"),
        ChangelogItem(kind="改进", text="Plex 播放列表同步撤了: 菜单里的同步按钮去掉,"
                                       " 播放列表全在应用里管; 原有的列表原地保留, 删改随意"),
        ChangelogItem(kind="修复", text="播放界面几个控制键的图标有点歪、暂停再切回播放还会左右跳一下 —— 都摆正了"),
        ChangelogItem(kind="修复", text="下载中的歌点「删除」没反应 —— 现在等于取消下载, 行和图标立即清掉"),
    ]),
    ChangelogVersion(version="1.2.1", date="2026-09-14", items=[
        ChangelogItem(kind="新增", text="在家也能离线下载了: 新地址是 HTTPS 加密的, 「下载」按钮和「已下载」栏在家里的 Wi-Fi 下不再隐藏"
                                       " —— 下载好的歌, 人在外面没网也能放"),
        ChangelogItem(kind="改进", text="地址换成固定域名 kinopico.duckdns.org:8500 (家里宽带 IP 变了也照常用);"
                                       " 旧的数字地址停用"),
        ChangelogItem(kind="修复", text="以前账号密码是明文过网的, 现在全程加密; 新地址首次要重新登录、主屏图标删掉重加"),
    ]),
    ChangelogVersion(version="1.2.0", date="2026-09-14", items=[
        ChangelogItem(kind="新增", text="主页: 打开应用先到这一页, 播放列表和最近播放都在这儿, 常听的一眼就看到"),
        ChangelogItem(kind="新增", text="最近播放: 听过的歌自动记下来排在这里 (一家人各记各的, 互不串台), 想循环刚听过的几首很方便"),
        ChangelogItem(kind="新增", text="离线下载: 点曲目行右侧的下载标, 整首歌存进手机, 没网也能放; 资料库新增「已下载」一栏, 能删能整栏连播"
                                       " (需要 HTTPS 环境才能用, 局域网明文访问时此项自动隐藏)"),
        ChangelogItem(kind="新增", text="播放页按 Apple Music 重排: 歌名歌手挪到左上角, 大封面居中更突出, 播放键改成干净的大图标"),
        ChangelogItem(kind="新增", text="歌词页能自由滑动了: 上下滑动快速前后浏览, 唱到哪行哪行照样放大标白;"
                                       " 滑开几秒后自动回到当前句, 也可以点「回到当前句」立刻跳回; 点某一句跳播不变"),
        ChangelogItem(kind="改进", text="资料库收窄成 专辑 / 艺人 / 歌曲 / 已下载 四栏, 播放列表挪去主页, 找东西少翻一层"),
        ChangelogItem(kind="改进", text="下一首提前在后台备好: 一首播完接下一首几乎无缝, 不用等加载转圈"),
        ChangelogItem(kind="改进", text="应用图标换成红色音符标 (Apple Music 同款风格), 重新添加主屏幕图标后生效"),
        ChangelogItem(kind="修复", text="锁屏界面点歌曲封面会跳到别的应用 —— 需把各应用的主屏幕图标删除后重新添加才生效"),
        ChangelogItem(kind="修复", text="页面底部偶尔冒出一排多余的菜单按钮"),
    ]),
    ChangelogVersion(version="1.1.0", date="2026-09-14", items=[
        ChangelogItem(kind="新增", text="搜索会认拼音: 打 liudehua 或 ldh 都能搜到刘德华, 不用切中文输入法;"
                                       " 多打少打空格也不影响"),
        ChangelogItem(kind="新增", text="简繁互搜: 歌名是繁体的 (比如 久石譲), 打简体 (久石让) 也搜得到, 反过来也一样"),
        ChangelogItem(kind="新增", text="Plex 里建的播放列表同步过来了: 资料库多一个「播放列表」分段, 点进去按顺序听整张列表;"
                                       " 顶部菜单里也能手动再同步; Plex 哪天下掉, 已同步的列表照样能听"),
        ChangelogItem(kind="新增", text="每张专辑记下入库时间: 专辑页头多一行入库日期, 「最近添加」也改看这个"),
        ChangelogItem(kind="改进", text="界面做减法: 底部标签栏撤掉, 搜索挪到顶栏右上角的放大镜, 统计收进顶部菜单"),
        ChangelogItem(kind="修复", text="动过文件的专辑 (复制、重新打标签) 不再被当成新添加冒到最前面;"
                                       " 老专辑自动按文件时间补记入库日期, 原来的顺序不变"),
    ]),
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
