# 学生综合素质加分管理系统

一个面向年级学生、管理员和主管的综合素质加分网站，用于维护学生名单、录入和审核加分、公开加分明细、发送站内通知，以及按学期导出和备份数据。

系统按学院综合素质测评规则划分六类分数：

1. 行为规范
2. 成才意识
3. 科技创新与学科竞赛
4. 社会工作
5. 文体活动
6. 荣誉称号

当前版本使用 Flask + SQLite，界面同时适配电脑和手机。项目仓库只保存程序代码，不保存正式学生名单、加分数据、申报图片或账号密码。

## 当前功能

### 学生端

- 使用学号和姓名登录，无需单独设置学生密码。
- 首页显示学生姓名、学号、当前学期、六类分数和总加分。
- 首页显示最近活动公示和最新通知。
- 公示页不设置名次，按学号展示所有学生的六类公开分数及总分。
- 点击某位学生的某个类别，可以查看该类别下已公示的活动和对应分值。
- 可查看按活动汇总的公开加分名单。
- 可申报除“行为规范”外的另外五类加分。
- 申报时填写项目名称并上传 JPG、PNG 或 WEBP 证明图片。
- 可查看自己的申报进度、审核结果和所得分值。
- 加分、撤销、申报通过或驳回、新学期开启等事件可通过站内通知告知学生。

### 管理员端

- 主页显示当前学期的学生人数、活动次数和最近活动。
- 管理学生名单，支持搜索、单个增删改、Excel/CSV 导入和 Excel 导出。
- “行为规范”支持按活动批量加分，同一活动可给不同学生填写不同分值。
- 录入行为规范分时可选择是否覆盖已有记录、是否通知学生、是否公开，公开默认开启。
- 在其负责的五类申报中查看证明图片，并选择通过或驳回。
- 通过申报时填写分值，可选择是否公开；通过后自动生成对应类别的加分记录并通知学生。
- 加分记录按活动名称分组，支持按学号、姓名或活动名称搜索。
- 支持单人手动加分、撤销、恢复和批量永久删除记录。
- 支持按学期导出 Excel、下载数据库备份以及查看操作日志。

### 主管端

主管拥有普通管理员的全部权限，另外可以：

- 添加和删除后台管理员。
- 设置管理员或主管身份，并保证系统至少保留一名主管。
- 按学号起止范围把学生申报分配给指定管理员审核。
- 开启新学期；历史学期数据继续保留，新产生的加分和申报进入新学期。
- 开启新学期时向学生发送站内通知。

## 暂未完成

- 通用加分文件的自动识别与入库功能目前只保留了入口。
- 当前请在“加分管理 → 行为规范”中完成行为规范批量录入。
- Word、PDF、截图等文件的智能识别尚未接入。

## 技术栈

- 后端：Python、Flask 3
- 数据访问：Flask-SQLAlchemy
- 登录管理：Flask-Login
- 数据库：SQLite
- 表格处理：pandas、openpyxl
- 前端：Bootstrap 5、Bootstrap Icons、原生 JavaScript
- 默认端口：`5050`

## 本地运行

推荐使用 Python 3.10 或更高版本。

```bash
git clone https://github.com/lianboy123/scoring-app.git
cd scoring-app

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python app.py
```

浏览器访问：

- 学生端：<http://127.0.0.1:5050/>
- 管理后台：<http://127.0.0.1:5050/admin/login>

第一次运行且数据库中没有管理员时，网站会自动跳转至 `/install`。请在该页面创建主管账号并填写当前学期，例如 `2026-spring`。

主管账号只能在首次初始化时创建。系统初始化完成后，`/install` 将自动禁用，其他管理员应由主管在后台“设置”中添加。

## 运行测试

```bash
source .venv/bin/activate
python -m unittest discover -s tests
```

测试使用临时数据库，不会修改 `instance/scoring.db` 中的正式数据。

## 数据文件与隐私

以下运行数据位于 `instance/`，并已通过 `.gitignore` 排除，不会随正常的 Git 提交上传：

- `instance/scoring.db`：学生、管理员、加分、申报、通知和日志等数据。
- `instance/claim_images/`：学生上传的申报证明图片。

`.env`、虚拟环境、缓存文件和编辑器配置同样不会上传。请勿把真实数据库、证明材料、密码、密钥或包含个人信息的表格手动提交到公开仓库。

生产环境必须设置随机的 `SCORING_SECRET_KEY`，不要使用代码中的开发默认值。

## 学生名单格式

推荐上传 `.xlsx` 或 `.csv` 文件，表头至少包含：

| 必需字段 | 可识别表头示例 |
|---|---|
| 学号 | 学号、学生号、学生学号、学生ID、学生编号、账号 |
| 姓名 | 姓名、名字、学生姓名 |

同一学号再次导入时会更新姓名，不会创建重复学生。已有加分记录的学生不能直接删除，以免破坏历史数据。

## 部署到 PythonAnywhere

以下路径中的用户名、Python 版本和域名请替换为自己的实际信息。

### 1. 下载代码

在 PythonAnywhere 的 Bash Console 中执行：

```bash
git clone https://github.com/lianboy123/scoring-app.git
cd scoring-app
```

如果仓库是私有仓库，需要先在服务器上配置 GitHub 身份验证，或使用其他安全的代码上传方式。不要把访问令牌写入代码。

### 2. 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 配置 Web App

在 PythonAnywhere 的 Web 页面创建 Manual configuration Web App，并设置：

- Source code：`/home/<用户名>/scoring-app`
- Working directory：`/home/<用户名>/scoring-app`
- Virtualenv：`/home/<用户名>/scoring-app/.venv`

WSGI 配置示例：

```python
import os
import sys

project_path = "/home/<用户名>/scoring-app"
if project_path not in sys.path:
    sys.path.insert(0, project_path)

os.environ["SCORING_ENV"] = "prod"
os.environ["SCORING_SECRET_KEY"] = "请替换为足够长的随机字符串"

from wsgi import application
```

保存后点击 Reload。首次打开网站时按照页面提示创建主管账号和当前学期。

## 保留数据更新网站

代码与数据是分开的。正常执行 `git pull` 只更新受 Git 管理的程序文件，不会覆盖被忽略的 `instance/scoring.db` 和 `instance/claim_images/`。但任何正式环境更新前仍应先备份。

在服务器项目目录中执行：

```bash
cd ~/scoring-app

# 先在管理后台下载数据库备份，再更新代码
git pull origin main

source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests
```

测试通过后回到 PythonAnywhere Web 页面点击 Reload。若未来版本包含较大的数据库结构调整，应先阅读该版本的更新说明，再进行部署。

## GitHub 更新流程

本地修改并测试完成后：

```bash
git status
git add .
git commit -m "说明本次修改内容"
git push origin main
```

推送代码不会自动更新服务器。服务器仍需执行 `git pull origin main`，然后在 Web 控制面板重新加载应用。

## 主要目录

```text
scoring-app/
├── app.py                     Flask 应用工厂与本地启动入口
├── wsgi.py                    生产环境 WSGI 入口
├── config.py                  数据库、会话和上传配置
├── models.py                  数据模型
├── blueprints/
│   ├── student.py             学生登录、首页、公示、通知和申报
│   ├── admin.py               管理员登录与后台主页
│   ├── admin_students.py      学生名单管理
│   ├── admin_scores.py        行为规范加分与加分记录
│   ├── admin_claims.py        五类申报审核
│   ├── admin_system.py        导出、日志、管理员和学期设置
│   └── install.py             首次初始化主管账号
├── services/
│   ├── categories.py          六大类统一定义
│   ├── database.py            建表与轻量兼容迁移
│   ├── parser.py              名单和表格解析
│   ├── exporter.py            Excel 导出
│   ├── announcements.py       活动公示数据整理
│   ├── semesters.py           学期管理
│   └── audit.py               操作日志
├── templates/                 学生端和管理端页面
├── static/                    CSS、JavaScript 和图片资源
├── tests/test_smoke.py        基础流程测试
└── instance/                  本地运行数据，不提交到 Git
```

## 使用建议

- 正式导入学生名单前，先用少量测试数据检查学号格式。
- 每次集中加分后抽查活动人数、分值和是否公开。
- 重要操作完成后及时下载 Excel 或数据库备份。
- 主管账号应使用独立强密码，不要多人共用。
- 学号和姓名免密登录适合校内低风险查询场景；如未来开放到更广范围，建议增加统一身份认证或学生密码/验证码。

## 项目状态

系统正在持续完善。当前版本以稳定完成学生名单、六类加分、公示、申报审核、通知、导出备份和学期管理为主，通用文件自动识别等能力将在后续版本中实现。
