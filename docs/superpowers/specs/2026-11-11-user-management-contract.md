# 用户体系改造 — 接口契约（P2/P3 共同遵守）

本文件是并行开发的**唯一事实来源**。改动任何签名前必须先更新此文件。

## 已完成的 P1（storage.py 数据层，勿改签名）

`DocumentStore` 新增/变更方法：

- `create_user(*, email, password_hash, display_name, role="user", status="active") -> dict`
  email 自动 lowercase；邮箱重复抛 `StorageError("email already registered")`；返回值**不含** password_hash。
- `get_user(user_id) -> dict | None` / `get_user_by_email(email) -> dict | None`（返回不含 password_hash）
- `list_users() -> list[dict]` / `count_users() -> int`
- `update_user_status(user_id, status) -> bool` / `update_user_role(user_id, role) -> bool`
- `touch_user_login(user_id) -> None`
- `create_session(*, user_id, token_hash, expires_at, user_agent, ip_address) -> None`
- `get_session(token_hash) -> dict | None`（过期/已撤销返回 None）
- `revoke_session(token_hash) -> bool` / `purge_expired_sessions() -> None`
- `link_document_owner(*, document_id, user_id) -> None`
- `user_owns_document(*, document_id, user_id) -> bool`
- `create_api_key(*, user_id, name, scopes, expires_at, pepper) -> tuple[str, dict]`（**user_id 现为关键字参数**）
- `persist(..., user_id: int | None = None)`（写入 fetches.user_id + document_owners）

## P2 负责：auth.py / config.py / main.py / models.py

### config.py
- **移除** `api_admin_key` 字段及相关校验。
- `api_auth_enabled=True` 时只校验 `api_key_pepper >= 32`。
- 新增：
  - `session_ttl_hours: int`（env `SESSION_TTL_HOURS`，默认 168）
  - `session_cookie_name: str`（env `SESSION_COOKIE_NAME`，默认 `"oma_session"`）
  - `bootstrap_admin_email` / `bootstrap_admin_password`（env，可选，空=不引导）

### auth.py
- `Principal` 增加字段 `user_id: int | None = None`（保留 key_id/scopes/is_admin）。
- `authenticate(authorization, settings, store)` 语义变更：
  - `api_auth_enabled=False` → 匿名 admin（user_id=None），保持本地开发可用。
  - Bearer `oma_...` token → 走 API key 路径，`user_id = key["user_id"]`。
  - **移除固定 admin key 比较**（API_ADMIN_KEY 已删）。
- 新增独立函数（main.py 的 session 中间件调用）：
  - `hash_password(password: str) -> str`（argon2）
  - `verify_password(password: str, password_hash: str) -> bool`（失败返回 False，不抛）
  - `new_session_token() -> str`（`secrets.token_urlsafe(32)`）
  - `hash_session_token(token: str) -> str`（sha256 hexdigest）
  - `register_user(*, email, password, display_name, store) -> dict`（校验邮箱格式/密码强度，调用 hash_password + store.create_user）
  - `login_user(*, email, password, store) -> dict | None`（verify_password，成功返回 user dict，失败 None）

### main.py
- 引入 **session 认证**：读 cookie → `store.get_session(hash_session_token(cookie))` → 加载 user → 构造 Principal(user_id, scopes by role, is_admin by role)。
- 中间件顺序：session 认证 + 原 bearer 认证二选一（先 session 后 bearer，或合并到统一 `api_authentication`）。
- `/api/auth/register`、`/api/auth/login` **豁免**鉴权（登录注册开放）。
- `require_scope`/`require_admin` 改为基于 `principal.user_id` + user.role。
- **bootstrap**：lifespan 中若 `store.count_users()==0` 且配置了 bootstrap admin env → 创建首个 admin。
- 路由改动：
  - `POST /api/keys`：`user_id = principal.user_id`，非 admin 只能给自己建 key、scopes 不能含 admin。
  - `GET /api/keys`：非 admin 只看自己的 key（storage 需按 user_id 过滤）。
  - `DELETE /api/keys/{id}`：非 admin 只能删自己的 key。
  - `/api/fetch`、`/api/search`、`/api/documents*`：从 principal 取 `user_id` 传给 service（见下方 service 签名）。
  - 新增路由：`POST /api/auth/register`、`POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me`、`GET /api/admin/users`、`PATCH /api/admin/users/{id}`。

### models.py 新增请求模型
- `RegisterRequest(email, password, display_name)`
- `LoginRequest(email, password)`
- `AdminUserUpdateRequest(role?, status?)`

## P3 负责：service.py / web/ / tests/

### service.py（**只改这些签名**，main.py 由 P2 调用）
- `fetch_page(..., user_id: int | None = None)` → 透传给 `store.persist(user_id=user_id)`
- `search_documents(..., user_id: int | None = None)` → 透传给 store 查询
- `list_documents(..., user_id: int | None = None)` → 透传
- `get_document(document_id, user_id: int | None = None)` → 透传
- 对应 storage 查询方法需支持按 user_id 过滤（P3 在 storage.py 追加过滤参数，**只增不改已有签名**）。

### storage.py（P3 追加，勿破坏 P1 签名）
- `search(..., user_id: int | None = None)`：user_id 非 None 时只返回该用户拥有的 document（JOIN document_owners）。
- `list_documents(..., user_id: int | None = None)`：同上 + 返回的 total 也按归属过滤。
- `get_document(document_id, user_id: int | None = None)`：非 None 时校验归属，不属于则返回 None。
- `delete_document(document_id, user_id: int | None = None)`：非 None 时校验归属。
- `list_api_keys(user_id: int | None = None)`：user_id 非 None 时只返回该用户 key。
- `delete_api_key(key_id, user_id: int | None = None)`：非 admin 场景校验归属。

### web/
- 登录/注册 UI；api-client.js 带 cookie 凭证；"我的 API Keys" 页面。

### tests/
- 新增：注册/登录/登出/me；session 过期撤销；**用户隔离**（A 看不到 B 的文档）；key 归属；admin 路由权限；bootstrap。
- 更新 `tests/test_auth.py`：移除 `api_admin_key` 相关断言（`test_admin_key_is_environment_only` 需重写为 role-based）。
- 兼容既有调用：`store.create_api_key` 旧测试需补 `user_id=`。

## 全局约定
- 密码：argon2（依赖已加 `argon2-cffi`）。
- Session cookie：HttpOnly + Secure(生产) + SameSite=Lax。
- 邮箱统一 lowercase 存储/查询。
- 时间统一 `datetime.now(UTC).isoformat()`。
