# 活动加分系统 · MVP

一个手机端优先的 Web 应用：学生用 **学号 + 姓名** 免密登录查看个人加分与匿名排名榜，管理员上传 Excel 加分文件经预览审核后入库。

- 后端：Flask 3 + SQLAlchemy + Flask-Login（管理员用）
- 数据库：SQLite（`instance/scoring.db`）
- 前端：Bootstrap 5 + 极少量原生 JS
- 主色：学院紫 `#7C3AED`
- 推荐部署：PythonAnywhere 免费版

---

## 快速开始（本地）

```bash
cd scoring-app

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动
python app.py
# 浏览器打开 http://127.0.0.1:5050
```

首次访问会自动跳到 `/install`，设置主管账号 + 当前学期标识（如 `2026-spring`）。完成后用刚才的账号登录 `/admin/login`。

---

## 功能地图

### 学生端（3 个底部 Tab）

| 路由 | 说明 |
|---|---|
| `/login` | 学号 + 姓名 登录 |
| `/` 首页 | 本学期总分卡片、最近 5 条加分、未读通知红点 |
| `/ranking` | 前 3 名金银铜（匿名）+ 你的排名/百分位 + 全员分数分布 |
| `/me` | 完整加分明细（按学期切换）+ 通知列表 |

### 管理端

| 路由 | 说明 |
|---|---|
| `/install` | 仅首次：设置主管账号 |
| `/admin/login` | 用户名 + 密码登录 |
| `/admin/` | 仪表盘：学生数、本学期记录数、待审核批次 |
| `/admin/students` | 学生名单：Excel 导入 / 单个增删改 |
| `/admin/upload` | 上传加分文件（xlsx / xls / csv） |
| `/admin/batch/<id>` | 批次预览 + 选择性入库 + 重复行覆盖 + 整批回滚 |
| `/admin/records` | 全部加分记录、单条撤销 |
| `/admin/export` | 导出 Excel / 下载 SQLite 备份 |
| `/admin/admins` | 管理员管理（仅主管） |
| `/admin/logs` | 操作日志（永久保留） |
| `/admin/settings` | 切换/新建当前学期 |

---

## 文件格式约定

### 学生名单（导入）

最少两列。表头识别别名：

| 标准字段 | 可识别表头 |
|---|---|
| 学号 | 学号 / 学生号 / 学生学号 / 学生ID / 学生编号 / 账号 |
| 姓名 | 姓名 / 名字 / 学生姓名 |

同学号将更新姓名，不会重复创建。

### 加分文件（上传审核）

四列。表头别名：

| 标准字段 | 可识别表头 |
|---|---|
| 学号 | 学号 / 学生号 / … |
| 姓名 | 姓名 / 名字 / 学生姓名 |
| 活动名称 | 活动 / 活动名称 / 项目 / 事项 / 加分原因 |
| 分值 | 分值 / 分数 / 加分 / 得分 / 分 |

如果完全不识别表头，但前 4 列恰好是这个顺序，会按位置兜底解析（页面会有提示）。

每行预览时会被自动标记为下列状态之一：

- **绿色 / 可入库**：学号在名单且无重复
- **红色 / 已存在**：本学期已有同学+同活动名称的记录，需手动勾选「覆盖」
- **黄色 / 学号不在名单**：跳过该行；管理员可先到名单页加学生再重新上传
- **灰色 / 错误**：分值非法等

---

## 部署到 PythonAnywhere（免费版）

### 1. 注册账号
访问 https://www.pythonanywhere.com 注册 Beginner（免费）账号。

### 2. 上传代码
选其一：

- **Git 拉取**（推荐）：在 PA Console 里
  ```bash
  git clone <你的仓库地址> scoring-app
  ```
- **手动上传**：在 PA "Files" 面板新建 `/home/<你的用户名>/scoring-app/`，把项目文件全部拖进去。

### 3. 创建虚拟环境并安装依赖
在 PA Bash Console 里：

```bash
cd ~/scoring-app
mkvirtualenv scoring-env --python=python3.10
pip install -r requirements.txt
```

### 4. 配置 Web App
PA Dashboard → **Web** → **Add a new web app**：
- 选 **Manual configuration** → Python 3.10
- 进入 Web 面板，依次设置：
  - **Source code**：`/home/<你的用户名>/scoring-app`
  - **Working directory**：`/home/<你的用户名>/scoring-app`
  - **Virtualenv**：`/home/<你的用户名>/.virtualenvs/scoring-env`
  - **WSGI configuration file**：编辑成下面的内容
    ```python
    import sys
    path = '/home/<你的用户名>/scoring-app'
    if path not in sys.path:
        sys.path.insert(0, path)

    import os
    os.environ['SCORING_ENV'] = 'prod'
    os.environ['SCORING_SECRET_KEY'] = '把这里换成一段随机字符串'

    from wsgi import application
    ```

### 5. 启动 + 初始化
点击 Web 面板顶部的绿色 **Reload** 按钮。打开 `https://<你的用户名>.pythonanywhere.com/install` 设置主管账号 + 当前学期。

### 6. 后续更新
每次改代码后：

```bash
cd ~/scoring-app
git pull              # 如果用的是 git
```

回到 Web 面板点 **Reload**。

### PythonAnywhere 免费版说明

- 1 个 Web App、512MB 磁盘、100,000 次/天访问 → 150 人完全够
- **无休眠**，24×7 在线
- SQLite 文件 `instance/scoring.db` 持久化
- 强烈建议每周登录后台「导出 / 备份」→「下载 DB 文件」备份

---

## 安全 / 隐私设计要点

- **学生免密登录**（学号 + 姓名）：方便、零门槛；学号姓名属于校内已知信息。
- **排名榜全员匿名**：不显示其他人姓名/学号，仅显示前 3 名分数 + 你的排名 + 整体分布，避免横向比较。
- **管理员必须密码**：8 位以上密码，bcrypt 哈希；管理员 Session 2 小时。
- **学生 Session**：仅当前浏览器会话，关闭即失效。
- **审计日志永久保留**：登录、上传、审核、撤销、邀请、切换学期等关键动作均有记录。

---

## 常见问题

**Q: 学生在哪打开？**
A: 直接发链接 `https://<你的用户名>.pythonanywhere.com`。学生输入学号 + 姓名即可。

**Q: 想中途加学生怎么办？**
A: 管理后台 → 学生名单 → 单个添加；或重新导入一份新名单（同学号会更新，不会重复）。

**Q: 上传文件出错（学号不在名单）怎么办？**
A: 预览页会标黄。先回到「学生名单」补全这些学号，再到批次页面刷新（或重新上传）。

**Q: 加错了分怎么办？**
A: 「加分记录」页搜索 → 点「撤销」（学生会收到通知）。或在批次页面点「整批回滚」撤销整批。

**Q: 学期结束怎么开新学期？**
A: 「设置」→ 修改当前学期标识（如 `2026-fall`）。历史学期数据自动归档，学生在「我的」可以下拉切换查看。

---

## 目录结构

```
scoring-app/
├── app.py                 应用工厂
├── wsgi.py                PythonAnywhere 入口
├── config.py
├── extensions.py
├── models.py              7 张数据表
├── requirements.txt
├── README.md
├── instance/scoring.db    （运行时生成）
├── blueprints/
│   ├── install.py
│   ├── student.py
│   └── admin.py
├── services/
│   ├── parser.py          模糊表头解析
│   ├── ranking.py         匿名排名 + 百分位 + 直方图
│   ├── exporter.py        Excel 导出
│   └── audit.py           审计日志
├── static/
│   ├── css/app.css
│   └── js/{toast,notifications}.js
└── templates/
    ├── base.html / install.html
    ├── student/{_layout,login,home,me,ranking}.html
    └── admin/{base,login,dashboard,students,upload,batch_review,
                records,export,admins,logs,settings}.html
```
