# 简历转换工具（Web）

上传简历后自动转换并生成标准 DOCX 文件。  
线上默认域名：`https://lensmanlucas.com/`。

## 导航

- [功能概览](#功能概览)
- [快速开始](#快速开始)
- [部署后 5 分钟验收](#部署后-5-分钟验收)
- [安全基线（必须）](#安全基线必须)
- [环境变量速查](#环境变量速查)
- [运行与运维](#运行与运维)
- [清理与容量策略](#清理与容量策略)
- [常见问题](#常见问题)

## 功能概览

- 支持上传 `PDF / DOCX / TXT / MD`
- 转换任务自动轮询进度，完成后下载 DOCX
- 文件命名：`姓名-手机号-TEK.docx`
- 浏览器会话内保留最近 10 条完成历史
- API Key 仅保存在当前浏览器会话，不落库
- 管理页面：
  - `/stats/`：Nginx 访问统计
  - `/nvwa/`：女娲蒸馏文件管理与任务执行

## 快速开始

### 本地开发

后端：

```bash
cd /Users/01-work/jianli
python3 -m venv .venv-web
source .venv-web/bin/activate
pip install -r web/backend/requirements.txt
uvicorn web.backend.app:app --host 0.0.0.0 --port 8000 --reload
```

前端：

```bash
cd /Users/01-work/jianli/web/frontend
npm install
npm run dev
```

Mac 一键开发：

```bash
cd /Users/01-work/jianli
bash deploy/macos/dev.sh start
```

Mac 一键关停：

```bash
cd /Users/01-work/jianli
bash deploy/macos/stop.sh
```

Mac 常用开发命令：

```bash
cd /Users/01-work/jianli
bash deploy/macos/dev.sh start
bash deploy/macos/dev.sh stop
bash deploy/macos/dev.sh restart
bash deploy/macos/dev.sh status
bash deploy/macos/dev.sh logs
```

### Linux 部署（推荐）

```bash
cd /opt/resume-fill
sudo APP_DOMAIN=lensmanlucas.com bash deploy/linux/install-from-github.sh
```

首次部署建议同时设置强密码（禁止弱口令）：

```bash
cd /opt/resume-fill
sudo APP_DOMAIN=lensmanlucas.com \
  NVWA_USERNAME=lensman \
  NVWA_PASSWORD='replace-with-strong-password' \
  STATS_USERNAME=lensman \
  STATS_PASSWORD='replace-with-strong-password' \
  HERMES_DISTILL_COMMAND='hermes run "distill-docs --input {input_dir} --output {output_json}"' \
  bash deploy/linux/install-from-github.sh
```

首次 HTTPS 建议：

```bash
cd /opt/resume-fill
sudo APP_DOMAIN="lensmanlucas.com www.lensmanlucas.com" bash deploy/linux/install-from-github.sh
```

仅需临时脚本安装时：

```bash
curl -fsSL https://raw.githubusercontent.com/lovepaul/resume-fill/main/deploy/linux/install-from-github.sh -o /tmp/install-resume-fill.sh
sudo APP_DOMAIN=lensmanlucas.com bash /tmp/install-resume-fill.sh
```

## 部署后 5 分钟验收

```bash
cd /opt/resume-fill
sudo bash deploy/linux/manage.sh status
sudo bash deploy/linux/manage.sh logs-all
curl -fsS http://127.0.0.1:8000/api/health
```

浏览器验收建议：

- 打开首页 `/`，上传一个小文件验证转换链路
- 打开 `/stats/` 并登录，确认有统计数据
- 打开 `/nvwa/` 并登录，确认可查看目录与启动任务

## 安全基线（必须）

- 不要使用弱口令（如 `666666`、`123456`、`password`）
- 部署脚本默认开启弱口令检查；仅本地临时调试可显式设置 `ALLOW_WEAK_PASSWORDS=1`
- 环境变量文件：`/etc/resume-web.env`（权限 600）
- 修改配置后执行：

```bash
sudo bash /opt/resume-fill/deploy/linux/manage.sh restart
```

## 环境变量速查

高频变量（写入 `/etc/resume-web.env`）：

- 运行目录与容量
  - `WEB_RUNTIME_DIR`
  - `WEB_UPLOADS_MAX_BYTES`
  - `WEB_OUTPUTS_MAX_BYTES`
  - `WEB_DISTILL_MAX_BYTES`
- 认证与会话
  - `WEB_STATS_USERNAME`
  - `WEB_STATS_PASSWORD`
  - `WEB_NVWA_USERNAME`
  - `WEB_NVWA_PASSWORD`
  - `WEB_STATS_SESSION_TTL_SECONDS`
  - `WEB_NVWA_SESSION_TTL_SECONDS`
- 并发与限流
  - `WEB_LLM_MAX_CONCURRENCY`
  - `WEB_LLM_QUEUE_TIMEOUT_SECONDS`
  - `WEB_CONVERT_MAX_CONCURRENCY`
  - `WEB_CONVERT_QUEUE_TIMEOUT_SECONDS`
  - `WEB_RATE_LIMIT_CONVERT_MAX`
  - `WEB_RATE_LIMIT_STATUS_MAX`
  - `WEB_RATE_LIMIT_DOWNLOAD_MAX`
- 女娲蒸馏
  - `WEB_HERMES_DISTILL_COMMAND`
  - `WEB_HERMES_DISTILL_TIMEOUT_SECONDS`

## 运行与运维

### 常用管理命令

```bash
cd /opt/resume-fill
sudo bash deploy/linux/manage.sh help
sudo bash deploy/linux/manage.sh status
sudo bash deploy/linux/manage.sh restart
```

### 日志与排障

```bash
# 后端日志（systemd journal）
sudo bash /opt/resume-fill/deploy/linux/manage.sh logs

# Nginx 错误日志
sudo bash /opt/resume-fill/deploy/linux/manage.sh logs-nginx

# 聚合日志（后端 + Nginx 错误 + 前端/接口访问）
sudo bash /opt/resume-fill/deploy/linux/manage.sh logs-all

# runtime 清理任务日志
sudo bash /opt/resume-fill/deploy/linux/manage.sh logs-runtime-cleanup
```

### 配置备份与回滚

部署会自动备份配置到 `/var/backups/resume-web/`（env/systemd/nginx/cron）。

```bash
sudo bash /opt/resume-fill/deploy/linux/manage.sh backup-config
sudo bash /opt/resume-fill/deploy/linux/manage.sh rollback-config
```

## 清理与容量策略

### runtime 文件清理

- 清理任务：`/etc/cron.d/resume-web-tmp-cleanup`
- 执行频率：每 10 分钟
- 目录与默认上限：
  - `uploads`：50MB
  - `outputs`：10MB
  - `distill-watch`：200MB
- 日志文件：`/var/log/resume-web-runtime-cleanup.log`

### 日志清理

- 任务文件：`/etc/cron.d/resume-web-log-cleanup`
- 执行频率：每 10 分钟
- 总量控制：`nginx + journal + cleanup-log` 不超过 `20MB`
- 清理脚本：`/opt/resume-fill/deploy/linux/cleanup-logs.sh`

手动执行：

```bash
sudo bash /opt/resume-fill/deploy/linux/manage.sh cleanup-logs
sudo bash /opt/resume-fill/deploy/linux/manage.sh setup-log-maintenance
```

## 常见问题

### 更新后 HTTPS 会不会被覆盖？

不会。检测到现有 Nginx 配置包含 `ssl_certificate` 时，部署会保留 HTTPS 与重定向配置，仅更新 `server_name` 并补齐必要路由。

### 浏览器提示下载文件不存在怎么办？

表示文件已被自动清理（TTL 到期或容量淘汰）。重新上传转换即可。

### 上传和输出目录在哪里？

默认由 `WEB_RUNTIME_DIR` 控制（兼容旧变量 `WEB_TMP_DIR`）。Linux 默认路径：

- `/var/lib/resume-web/runtime/uploads`
- `/var/lib/resume-web/runtime/outputs`
- `/var/lib/resume-web/runtime/distill-watch`

### 页面打不开 / 超时怎么排查？

```bash
sudo bash /opt/resume-fill/deploy/linux/manage.sh status
sudo bash /opt/resume-fill/deploy/linux/manage.sh logs-all
sudo ss -lntp | rg ':80|:443|:8000'
```
