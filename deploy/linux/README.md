# Linux 一键部署与服务管理

本目录提供生产可用的 `systemd + nginx` 自动化脚本。

## 文件说明

- `bootstrap.sh`：首次全自动部署（安装依赖、构建前端、写 systemd/nginx 配置并启动）
- `manage.sh`：日常一键管理（启动、暂停、重启、状态、日志）
- `install-from-github.sh`：服务器从 GitHub 拉取代码并一键执行部署（适合首次上机）

## 0) 服务器从 GitHub 一键部署（推荐）

如果服务器还没有本项目代码，可直接执行：

```bash
curl -fsSL https://raw.githubusercontent.com/lovepaul/resume-fill/main/deploy/linux/install-from-github.sh -o /tmp/install-resume-fill.sh
sudo APP_DOMAIN=your.domain.com bash /tmp/install-resume-fill.sh
```

常用可选变量：

- `APP_REPO`：仓库地址，默认 `https://github.com/lovepaul/resume-fill.git`
- `APP_BRANCH`：分支名，默认 `main`
- `APP_DIR`：代码目录，默认 `/opt/resume-fill`
- `APP_NAME`：服务名，默认 `resume-web`
- `APP_PORT`：后端端口，默认 `8000`
- `APP_DOMAIN`：域名，默认 `_`
- `INSTALL_PACKAGES`：是否自动安装系统依赖，默认 `1`

## 1) 首次部署

```bash
cd /your/repo/path
chmod +x deploy/linux/bootstrap.sh deploy/linux/manage.sh
sudo bash deploy/linux/bootstrap.sh
```

可选参数（环境变量）：

```bash
sudo APP_NAME=resume-web APP_PORT=8000 APP_DOMAIN=your.domain.com bash deploy/linux/bootstrap.sh
```

常用变量：

- `APP_NAME`：systemd 服务名，默认 `resume-web`
- `APP_PORT`：后端监听端口，默认 `8000`
- `APP_DOMAIN`：nginx `server_name`，默认 `_`
- `APP_USER` / `APP_GROUP`：服务运行账号，默认 `www-data`
- `INSTALL_PACKAGES`：是否自动安装系统依赖，默认 `1`

## 2) 日常管理

```bash
sudo bash deploy/linux/manage.sh start
sudo bash deploy/linux/manage.sh help
sudo bash deploy/linux/manage.sh pause
sudo bash deploy/linux/manage.sh restart
sudo bash deploy/linux/manage.sh status
sudo bash deploy/linux/manage.sh logs
```

忘记命令时，直接执行：

```bash
sudo bash deploy/linux/manage.sh help
```

会显示完整操作清单与排障建议。

## 3) 关键路径

- systemd: `/etc/systemd/system/<APP_NAME>.service`
- env: `/etc/<APP_NAME>.env`
- nginx:
  - Debian/Ubuntu: `/etc/nginx/sites-available/<APP_NAME>.conf`
  - 其他发行版: `/etc/nginx/conf.d/<APP_NAME>.conf`

## 4) 注意事项

1. 首次部署后请编辑 `/etc/<APP_NAME>.env`，填入真实 `DEEPSEEK_API_KEY`
2. 修改配置后执行：

```bash
sudo systemctl daemon-reload
sudo bash deploy/linux/manage.sh restart
```

3. 前端重建后建议执行：

```bash
cd web/frontend && npm run build
sudo bash deploy/linux/manage.sh reload
```
