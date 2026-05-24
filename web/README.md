# 简历转换工具 Web 版（保姆级说明）

想要的体验就是：上传简历 -> 自动转换 -> 一键下载标准 DOCX。  
下面这份文档按「开箱即用」写，尽量少踩坑，适合直接给用户看。

---

## 这版已经支持什么？

- 前端：React，支持上传、进度刷新、下载、历史列表（会话内）
- 后端：FastAPI，复用现有简历解析和模板填充流程
- 安全：必须先在页面配置用户自己的 `DeepSeek API Key`
- 隐私：Key 只存在浏览器会话（`sessionStorage`），刷新不丢，关会话即清
- 文件：上传/生成文件默认落在 Linux `/tmp/resume-web`，1 小时自动清理
- 命名：生成文件为 `姓名-手机号-TEK.docx`，重名自动加 6 位 hash

---

## 用户端使用说明（可直接贴给用户）

### 1) 先配置 API Key

打开页面后，先填写 `DeepSeek API Key`。  
没填时「开始转换」按钮是灰色不可点，这是正常保护逻辑。

### 2) 上传简历

支持：`.pdf` / `.docx` / `.txt` / `.md`  
选中文件后点击「开始转换」，系统会自动轮询进度。

### 3) 下载与管理

- 当前任务完成后可直接下载
- 下方会展示「当前会话已完成列表」（最多最新 10 条）
- 每条都支持：下载 / 删除

---

## 本地开发启动（前后端分开）

### 1) 启动后端

```bash
cd /Users/01-work/jianli
python3 -m venv .venv-web
source .venv-web/bin/activate
pip install -r web/backend/requirements.txt
uvicorn web.backend.app:app --host 0.0.0.0 --port 8000 --reload
```

### 2) 启动前端

```bash
cd /Users/01-work/jianli/web/frontend
npm install
npm run dev
```

默认访问：`http://localhost:5173`

如需指定后端地址（启动前设置）：

```bash
export VITE_API_BASE_URL="http://127.0.0.1:8000"
```

### Mac 一键启动（推荐本地开发）

已经提供脚本：`deploy/macos/dev.sh`，可一键拉起前后端。

```bash
cd /Users/01-work/jianli
bash deploy/macos/dev.sh start
```

常用命令：

```bash
bash deploy/macos/dev.sh status
bash deploy/macos/dev.sh logs
bash deploy/macos/dev.sh restart
bash deploy/macos/dev.sh stop
```

说明：

- 首次执行会自动创建 `.venv-web` 并安装后端依赖
- 首次执行会自动安装前端依赖
- 默认前端 `http://127.0.0.1:5173`，后端 `http://127.0.0.1:8000`
- 日志在 `.run/macos-dev/logs/`

---

## 生产部署（推荐 Linux 一键）

### 方案 A：服务器从 GitHub 直接安装（推荐）

```bash
curl -fsSL https://raw.githubusercontent.com/lovepaul/resume-fill/main/deploy/linux/install-from-github.sh -o /tmp/install-resume-fill.sh
sudo APP_DOMAIN=your.domain.com bash /tmp/install-resume-fill.sh
```

它会自动处理：

- 拉取代码
- 检查并安装系统依赖（含 `git` / `nginx` / `python` / `node` / `npm`）
- 创建 Python 环境并安装依赖
- 构建前端
- 写入 systemd + nginx 配置并启动

### 方案 B：仓库内手动执行

```bash
sudo bash deploy/linux/bootstrap.sh
```

---

## 关键配置（必看）

- 模板文件必须存在：`muban/简历模板 TEK.docx`
- 生产环境变量文件：`/etc/resume-web.env`
- 服务管理：
  - `sudo bash deploy/linux/manage.sh status`
  - `sudo bash deploy/linux/manage.sh restart`
  - `sudo bash deploy/linux/manage.sh logs`

---

## 运行时与清理策略

- 运行目录默认：`/tmp/resume-web`
  - 上传：`/tmp/resume-web/uploads`
  - 输出：`/tmp/resume-web/outputs`
- 自动清理：
  - 应用内后台线程按 TTL 清理
  - Linux cron 定时兜底清理
- 默认保留时长：1 小时（3600 秒）

可通过环境变量覆盖：

- `WEB_TMP_DIR`
- `WEB_FILE_RETENTION_SECONDS`
- `WEB_CLEANUP_SCAN_INTERVAL_SECONDS`

---

## API 一览

- `POST /api/convert`：上传并创建任务（请求头需 `X-DeepSeek-Api-Key`）
- `GET /api/jobs/{job_id}`：查询状态
- `GET /api/jobs/{job_id}/download`：下载文件
- `DELETE /api/jobs/{job_id}`：删除任务和文件
- `GET /api/favicon.png`：站点图标

---

## 小提醒（高频问题）

- 看不到 favicon：先重启服务，再强刷浏览器缓存
- 按钮灰色不能点：通常是没填 API Key 或没选文件
- 下载 404：文件可能已过保留时间被自动清理
- 转换失败：先看后端日志 `sudo bash deploy/linux/manage.sh logs`
