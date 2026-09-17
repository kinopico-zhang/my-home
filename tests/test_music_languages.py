"""My Music 语言检测测试: 文字 script 识别与语种分组过滤。"""


from app.music.library_languages import (detect_script, language_for_script,
                                         scripts_for_language)


# ---------------------------------------------------------------- 语言

def test_detect_script_and_language_groups():
    """文字检测: 假名必日文, 谚文韩文, 汉字中文, 拉丁英文, 空白检不出。"""
    assert detect_script("レクイエム") == "Jpan"
    assert detect_script(" 첫사랑") == "Kore"
    assert detect_script("单身情歌") == "Hant"          # 汉字归中文组
    assert detect_script("Hello") == "Latn"
    assert detect_script("Привет") == "Cyrl"
    assert detect_script("!!!", "123") == ""
    # 组名映射 + 未知 script 归其他
    assert language_for_script("Hant") == "中文"
    assert language_for_script("Qaaa") == "其他"
    assert language_for_script("") == "其他"


def test_scripts_for_language_negation():
    """其他 = 已知 script 取反; 全部/未知 → None (不过滤)。"""
    assert scripts_for_language("全部") is None
    assert scripts_for_language("不存在的语种") is None
    japanese = scripts_for_language("日文")
    assert japanese is not None
    assert japanese[0] == frozenset({"Jpan"}) and japanese[1] is False
    others = scripts_for_language("其他")
    assert others is not None
    assert others[1] is True              # 已知集取反
    assert "Jpan" in others[0] and "Hant" in others[0] and "" not in others[0]
