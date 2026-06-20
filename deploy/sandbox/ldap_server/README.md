# P1b 真 LDAP 端到端实证 VM runbook

> 范围：仅用于麒麟 V11 + LoongArch VM 上 OpenLDAP/slapd 沙箱部署。
> 非生产配置；非生产数据。

## 0. 前提

- 麒麟 V11（aarch64/loongarch64 均可）
- 已 clone 仓库到 VM，分支与 dev 同步
- 仓库位置假定为 `~/kylin-safeops-agent`（按实际路径替换）

## 1. 安装 OpenLDAP

```bash
sudo dnf install -y openldap-servers openldap-clients
```

> 不走 docker。`osixia/openldap` 等公共镜像无 LoongArch 构建，且 D 域不引入 docker 依赖。
> 直接用麒麟仓库的 `openldap-servers` 即可（slapd 主程序）。

## 2. 设置测试口令（仅 shell export，不进任何文件）

```bash
# S9 铁律：仅 shell export，绝不 commit
export KYLIN_LDAP_ROOTPW='ChangeMe-Root-OnlyForSandbox'
export KYLIN_LDAP_USER_PW='KylinTest123!'
export KYLIN_LDAP_BIND_PASSWORD="$KYLIN_LDAP_ROOTPW"   # 给 backend 用
```

> 这些口令仅用于沙箱实证；与生产任何系统不复用。
> 关闭 shell / VM reboot 后即失效，需要重新 export。

## 3. 生成 SSHA hash 并准备工作副本

仓库里的 `slapd.conf` 和 `init.ldif` **不允许修改**（要保持 git status 干净）。
所有 sed 替换都在 `/tmp` 工作副本上做：

```bash
cd ~/kylin-safeops-agent/deploy/sandbox/ldap_server

# 生成 hash
ROOTPW_SSHA=$(slappasswd -s "$KYLIN_LDAP_ROOTPW")
USERPW_SSHA=$(slappasswd -s "$KYLIN_LDAP_USER_PW")

# 复制到 /tmp 后再替换占位符
cp slapd.conf /tmp/slapd.conf
cp init.ldif  /tmp/init.ldif

# sed 用 | 作分隔符（hash 含 /）
sed -i "s|__ROOTPW_SSHA__|${ROOTPW_SSHA}|" /tmp/slapd.conf
sed -i "s|__USER_PW_HASH__|${USERPW_SSHA}|g" /tmp/init.ldif
```

## 4. 部署 slapd.conf 并准备数据目录

```bash
# 备份系统默认配置（首次部署）
sudo cp -a /etc/openldap/slapd.d /etc/openldap/slapd.d.bak.$(date +%s) 2>/dev/null || true

# 用 /tmp 工作副本替换系统配置
sudo cp /tmp/slapd.conf /etc/openldap/slapd.conf
sudo chown root:ldap /etc/openldap/slapd.conf
sudo chmod 640 /etc/openldap/slapd.conf

# 部分发行版默认走 cn=config（slapd.d 目录），需要切回 slapd.conf 模式：
# 删掉旧 slapd.d，让 slapd 用 slapd.conf 启动
sudo rm -rf /etc/openldap/slapd.d

# 准备数据目录
sudo mkdir -p /var/lib/ldap
sudo chown -R ldap:ldap /var/lib/ldap
sudo mkdir -p /var/run/openldap
sudo chown -R ldap:ldap /var/run/openldap
```

## 5. 灌入初始数据

```bash
# slapadd 离线灌库（slapd 必须未运行）
sudo systemctl stop slapd 2>/dev/null || true
sudo -u ldap slapadd -f /etc/openldap/slapd.conf -l /tmp/init.ldif
```

> 若提示 `objectClass: groupOfNames` schema 缺失，确认 `nis.schema` 已 include
> （仓库 slapd.conf 已 include 4 个标准 schema）。

## 6. 启动 slapd

```bash
sudo systemctl enable slapd
sudo systemctl start slapd
sudo systemctl status slapd --no-pager
```

## 7. 烟测：4 用户 + memberOf 都能查到

```bash
# 7a. 匿名查 base DN（应返回 dc=kylin,dc=test）
ldapsearch -x -H ldap://localhost -b "dc=kylin,dc=test" -s base

# 7b. 用 alice 凭证 bind，查自己的 memberOf
ldapsearch -x -H ldap://localhost \
  -D "uid=alice,ou=users,dc=kylin,dc=test" \
  -w "$KYLIN_LDAP_USER_PW" \
  -b "uid=alice,ou=users,dc=kylin,dc=test" \
  memberOf

# 期望输出包含：
# memberOf: cn=kylin-admins,ou=groups,dc=kylin,dc=test

# 7c. 4 个组都存在
ldapsearch -x -H ldap://localhost \
  -b "ou=groups,dc=kylin,dc=test" "(objectClass=groupOfNames)" cn member
```

7b/7c 若全 PASS → 真 LDAP server 就绪，可进入端到端 20 组实证。

## 8. 清理（重跑前）

```bash
# 重置数据（保留配置）
sudo systemctl stop slapd
sudo rm -rf /var/lib/ldap/*
sudo -u ldap slapadd -f /etc/openldap/slapd.conf -l /tmp/init.ldif
sudo systemctl start slapd

# 完全卸载（VM 收尾）
sudo systemctl stop slapd
sudo systemctl disable slapd
sudo dnf remove -y openldap-servers openldap-clients
sudo rm -rf /var/lib/ldap /etc/openldap/slapd.conf
# 可选：恢复备份
# sudo mv /etc/openldap/slapd.d.bak.* /etc/openldap/slapd.d
```

## 9. 安全检查（每次部署后必做）

```bash
# 9a. 仓库无改动
cd ~/kylin-safeops-agent && git status
# 期望：working tree clean

# 9b. /tmp 工作副本不进任何 commit
ls -la /tmp/slapd.conf /tmp/init.ldif
# 仅 root/当前用户可读；用完即删
shred -u /tmp/slapd.conf /tmp/init.ldif 2>/dev/null || rm -f /tmp/slapd.conf /tmp/init.ldif

# 9c. 环境变量不落 history
unset KYLIN_LDAP_ROOTPW KYLIN_LDAP_USER_PW
# 关闭 shell 即可彻底清除
```

## 后端 backend 接 LDAP 时的环境

> ⚠ 键名必须与 `deploy/sso/ldap_client.py:46-53` 的 `_REQUIRED_REAL_ENV` **完全对齐**，
> 拼错任何一个 → `_real_cfg={}` → 真模式直接软降级到失败，所有 authenticate/get_user 返回 False/None。

```bash
# 6 个必填 env（_REQUIRED_REAL_ENV）
export KYLIN_LDAP_URL='ldap://127.0.0.1:389'
export KYLIN_LDAP_BIND_DN='cn=admin,dc=kylin,dc=test'
export KYLIN_LDAP_BIND_PASSWORD="$KYLIN_LDAP_ROOTPW"
export KYLIN_LDAP_BASE_DN='dc=kylin,dc=test'
export KYLIN_LDAP_USER_FILTER='(uid={})'
export KYLIN_LDAP_GROUP_ATTR='memberOf'

# 角色映射（裸名键，依赖 _normalize_group_name 归一化）
export KYLIN_LDAP_GROUP_ROLE_MAP='{"kylin-admins":"admin","kylin-ops":"operator","kylin-viewers":"viewer","kylin-auditors":"auditor"}'
```

字段释义：

- `KYLIN_LDAP_BASE_DN`：search 根 DN，sub-scope 下搜到 `ou=users` 和 `ou=groups` 都行
- `KYLIN_LDAP_USER_FILTER`：用户搜索过滤模板，`{}` 占位会被 `_escape_ldap_filter(username)` 替换
- `KYLIN_LDAP_GROUP_ATTR`：从用户 entry 上读 group 的属性名，配 slapd.conf 的 memberof overlay → `memberOf`
- `KYLIN_LDAP_GROUP_ROLE_MAP`：裸名键映射 OK——L 已在 `ldap_client.py` 加 `_normalize_group_name()`，
  真 LDAP 返回的全 DN `cn=kylin-admins,ou=...` 会归一化成裸名 `kylin-admins` 查映射（commit a761b8d）。
