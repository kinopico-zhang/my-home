"""My Money (家庭记账) —— 独立小应用 (与 My Tesla 只共享账号体系, 同属 My Home)。

自己的代码 (本包)、自己的静态资源 (static/)、自己的数据库
(data/bookkeeping.db)。账号与会话来自主应用 (account_store +
authentication), 同一枚 cookie (path=/) 两个应用通用。
"""
