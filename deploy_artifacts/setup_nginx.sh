#!/usr/bin/env bash
# Audit 2026-09-03 C2 / M5: 在 CVM 上安装 Nginx + TLS + acme.sh
# 运行前: 需要 sudo 权限 + 域名已解析到本机 IP
#
# 用法: sudo bash deploy_artifacts/setup_nginx.sh <域名,例如 ma.example.com>

set -euo pipefail

DOMAIN="${1:?用法: $0 <域名>}"
echo ">>> 配置 Nginx + TLS for $DOMAIN"

# ---- 1. 安装 Nginx (假设 Ubuntu) ----
if ! command -v nginx >/dev/null; then
  apt-get update
  apt-get install -y nginx
fi

# ---- 2. 安装 acme.sh (Let's Encrypt 客户端) ----
if [ ! -d ~/.acme.sh ]; then
  curl https://get.acme.sh | sh -s email=admin@${DOMAIN#*.}
  source ~/.acme.sh/acme.sh.env
fi

# ---- 3. 申请证书 ----
mkdir -p /etc/nginx/ssl
~/.acme.sh/acme.sh --issue -d "$DOMAIN" --nginx
~/.acme.sh/acme.sh --install-cert -d "$DOMAIN" \
  --key-file       /etc/nginx/ssl/privkey.pem \
  --fullchain-file /etc/nginx/ssl/fullchain.pem \
  --reloadcmd      "systemctl reload nginx"

# ---- 4. 创建 medicalaudit 用户 ----
if ! id medicalaudit >/dev/null 2>&1; then
  useradd --system --shell /usr/sbin/nologin --home /opt/medical-audit medicalaudit
fi

# ---- 5. 复制 Nginx 配置 ----
install -m 644 deploy_artifacts/nginx.conf /etc/nginx/sites-available/medical-audit
ln -sf /etc/nginx/sites-available/medical-audit /etc/nginx/sites-enabled/medical-audit
unlink /etc/nginx/sites-enabled/default 2>/dev/null || true

# ---- 6. 验证配置 ----
nginx -t

# ---- 7. 启动 ----
systemctl enable --now nginx
systemctl reload nginx

echo ""
echo "✓ Nginx 已配置并启动"
echo "  HTTP  → 80  (301 重定向到 HTTPS)"
echo "  HTTPS → 443 (TLS 1.2/1.3)"
echo "  后端  → 127.0.0.1:5000 (gunicorn)"
echo ""
echo "记得:"
echo "  1. 在 /etc/medical-audit/env 里设 MA_SECRET_KEY (32 字节 hex)"
echo "  2. 设置 MA_ADMIN_USER / MA_ADMIN_PASS (Basic Auth 凭据)"
echo "  3. 设置 MA_ADMIN_ALLOW_CIDR (允许的 IP 段)"
