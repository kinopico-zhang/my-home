"""记账存储测试: 双库隔离, 时间/标签往返, 迁移补列。
拆自 test_bookkeeping.py (结构化重构, 代码逐字节未动)。"""

from tests.bookkeeping_sync_helpers import _entry, _sync, _user


def test_sync_two_databases_separate(usersdb, tmp_path):
    """记账库与账号库是两个独立 SQLite 文件 (用户要求分开)。"""
    _user(usersdb, "记账人甲")
    users_file = tmp_path / "users.db"
    bookkeeping_file = tmp_path / "bookkeeping.db"
    assert users_file.exists() and bookkeeping_file.exists()
    assert users_file.read_bytes() != bookkeeping_file.read_bytes()


def test_sync_time_and_tags_roundtrip(usersdb, bkdb):
    """时刻 + 标签: 上行清洗 (去井号/空白, 去重, 截 12 字, 最多 5 个),
    落库逗号连接, 下行还原列表; 时刻格式错 422; 旧客户端不带字段也兼容。"""
    jia, _ = _user(usersdb, "记账人甲")
    data = _sync(jia, [_entry("aaaa1111", "2026-09-13T08:00:00Z",
                              time="08:15",
                              tags=["#报销", "  固定  ", "报销",
                                    "十三字标签看会不会被截断掉", "x", "第六个"])])
    out = data["entries"][0]
    assert out["time"] == "08:15"
    assert out["tags"] == ["报销", "固定", "十三字标签看会不会被截断", "x", "第六个"]
    from app.bookkeeping.store import Entry  # pylint: disable=import-outside-toplevel
    row = bkdb.get(Entry, "aaaa1111")
    assert row.time == "08:15"
    assert row.tags == "报销,固定,十三字标签看会不会被截断,x,第六个"
    # 旧客户端 (再记功能前) 不带 time/tags: 默认空, 不报错
    data2 = _sync(jia, [_entry("bbbb2222", "2026-09-13T09:00:00Z")])
    plain = [e for e in data2["entries"] if e["id"] == "bbbb2222"][0]
    assert plain["time"] == "" and plain["tags"] == []
    # 时刻格式错: 422
    r = jia.post("/bookkeeping/api/sync", json={"entries": [
        _entry("cccc3333", "2026-09-13T08:00:00Z", time="8:15")]})
    assert r.status_code == 422


def test_migrate_columns_adds_time_and_tags(tmp_path):
    """老库升级: entries 已存在但没有 time/tags 列 → ALTER 补列, 旧行默认空;
    再跑一遍不炸不重复 (幂等)。"""
    from sqlalchemy import create_engine, text  # pylint: disable=import-outside-toplevel
    from app.bookkeeping import store  # pylint: disable=import-outside-toplevel
    eng = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with eng.begin() as conn:          # v2.5 之前的老表 (无 time/tags)
        conn.execute(text(
            "CREATE TABLE entries (id VARCHAR PRIMARY KEY, date VARCHAR, "
            "amount FLOAT, kind VARCHAR, category VARCHAR, note VARCHAR, "
            "created_by VARCHAR, created_at DATETIME, updated_by VARCHAR, "
            "updated_at DATETIME, synced_at DATETIME, deleted BOOLEAN)"))
        conn.execute(text(
            "INSERT INTO entries VALUES ('old1', '2026-09-01', 12.0, "
            "'expense', '餐饮', '', 'u1', '2026-09-01 00:00:00', 'u1', "
            "'2026-09-01 00:00:00', '2026-09-01 00:00:00', 0)"))
    store.migrate_columns(eng)
    with eng.begin() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(entries)")]
        old_row = conn.execute(text(
            "SELECT time, tags FROM entries WHERE id = 'old1'")).one()
    assert "time" in cols and "tags" in cols
    assert old_row == ("", "")
    store.migrate_columns(eng)         # 幂等
    with eng.begin() as conn:
        cols2 = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(entries)")]
    assert cols2.count("time") == 1 and cols2.count("tags") == 1
    eng.dispose()
