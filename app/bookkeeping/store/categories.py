"""类别树: 种子数据 (挖财账本导出) 的播种与读取 (给前端弹层画两级胶囊)。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..default_categories import EXPENSE_CATEGORIES, INCOME_CATEGORIES
from ..schemas import CategoryGroup, CategoryTree
from .engine import session_factory
from .models import Category


def seed_default_categories() -> None:
    """类别表为空时种入默认树 (挖财导出内容); 非空不动 —— 以库为准。"""
    with session_factory()() as session:  # pylint: disable=not-callable
        if session.execute(select(Category.id).limit(1)).scalar() is not None:
            return
        rows: list[Category] = []
        for kind, tree in (("expense", EXPENSE_CATEGORIES),
                           ("income", INCOME_CATEGORIES)):
            for top, children in tree:
                rows.append(Category(name=top, kind=kind, parent="",
                                     sort=len(rows)))
                rows.extend(Category(name=child, kind=kind, parent=top,
                                     sort=len(rows)) for child in children)
        session.add_all(rows)
        session.commit()


def category_tree(session: Session) -> CategoryTree:
    """类别树 → 支出/收入各自的大类 + 子类, 按种子的 sort 保序
    (给前端弹层画两级胶囊用)。"""
    rows = session.execute(select(Category).order_by(Category.sort, Category.id)
                           ).scalars().all()
    children: dict[str, list[str]] = {}
    for row in rows:
        if row.parent:
            children.setdefault(row.parent, []).append(row.name)
    tree = CategoryTree(expense=[], income=[])
    for row in rows:
        if not row.parent:
            group = CategoryGroup(name=row.name,
                                  children=children.get(row.name, []))
            if row.kind == "expense":
                tree.expense.append(group)
            else:
                tree.income.append(group)
    return tree
