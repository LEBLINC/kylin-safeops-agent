@echo off
REM A2.2: Windows 反代启动脚本 (proxy.py, Basic Auth -> 真接 LDAP -> HMAC 签名注入).
REM 用法: 拷贝本文件到部署目录, 填好下列 env 后双击运行 / 或 `start.bat` 命令行运行.
REM 决策⑨硬阻断: KYLIN_LDAP_MOCK 必须是 false (mock 禁止用于生产反代).

setlocal

REM ---- 反代签名密钥 (必设; 未设 app 侧 fail-closed 拒绝一切签名头) ----
set KYLIN_PROXY_AUTH_SECRET=CHANGE_ME_32BYTE_HEX

REM ---- KYLIN_LDAP_* 6 env (真接 LDAP, 不得用 mock) ----
set KYLIN_LDAP_MOCK=false
set KYLIN_LDAP_URL=ldap://ldap.kylin.local:389
set KYLIN_LDAP_BIND_DN=cn=svc,ou=system,dc=kylin,dc=local
set KYLIN_LDAP_BIND_PASSWORD=CHANGE_ME
set KYLIN_LDAP_BASE_DN=ou=users,dc=kylin,dc=local
set KYLIN_LDAP_USER_FILTER=(uid={0})
set KYLIN_LDAP_GROUP_ATTR=memberOf

REM ---- 上游 app 地址 + 监听端口 ----
set KYLIN_UPSTREAM=http://127.0.0.1:8000

uvicorn deploy.proxy.proxy:app --host 0.0.0.0 --port 8080

endlocal
