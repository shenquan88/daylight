# Daylight · 向阳

> 把每个今天，长成明天的力量。

一个**积极、持久的个人 agent**：把今天的 1–3 个小目标拆成可以马上做的下一步，记录行动与收获，每天形成一张真实经验卡，并在"经验花园"里长成一株植物。

全部数据落在 SQLite（Sprite 持久磁盘 / 本地 `./data`），进程重启不丢；可一键导出 Markdown 带走。

**当前状态**：已部署到 Sprite **daylight**（<https://daylight-b6wqd.sprites.app>），数据落持久磁盘 `/home/sprite/daylight-data`，**已验证自动休眠后数据保留**。connector 已接官方 OpenRouter 托管网关并实测成功（免费模型 `liquid/lfm-3-1.7b:free`，0 美元）。尚未提交任何竞赛、未获奖。

---

## 一、运行

### Sprite 上（含 connector）

```bash
sh start.sh          # cd /home/sprite/daylight → 注入 connector env → exec python3 app.py --port 8080
```

`start.sh` 只设运行时环境变量，**不含任何密钥**（该托管网关不需要 token），内容见文件本身。
当前线上实例：<https://daylight-b6wqd.sprites.app>

### 本地

```bash
cd hacksgiving-daylight
python app.py                 # http://0.0.0.0:8080
```

可选参数：

```bash
python app.py --port 8099 --data-dir ./data   # 换端口 / 换数据目录
python app.py --quiet                          # 关掉请求日志
```

只依赖 Python 3 标准库（`http.server` + `sqlite3` + `urllib`），**零 pip 安装**。实测环境：Python 3.14.6。

### 跑测试

```bash
python -m unittest discover -s tests -v
```

36 项：页面与静态资源、健康检查、目标增删改、输入长度与类型校验、状态码语义、check-in、经验卡与导出、重启持久化、花园/连续天数、connector mock（含默认 60 秒超时）、keep-alive 回归。

### 端到端与截图（需要本机 Chrome）

```bash
python scripts/e2e_check.py   # 真起进程 → 真 HTTP → 杀进程 → 重启校验数据
python scripts/shots.py       # Playwright 驱动本机 Chrome，截图 + 采集 console 错误
```

截图落在 `screenshots/`。

---

## 二、数据与持久性

| 位置 | 说明 |
|---|---|
| `/home/sprite/daylight-data/daylight.db` | Sprite 持久磁盘上的数据库（检测到 `/home/sprite` 时自动使用） |
| `./data/daylight.db` | 本地开发默认路径 |
| `--data-dir PATH` | 显式指定，测试与多实例都用它 |

- WAL 模式：正式数据在 `daylight.db` + `daylight.db-wal`，`/api/health` 里的 `db_bytes` 是这几个文件之和。
- 每次写入先 `COMMIT` 再返回响应，进程内不缓存业务状态。
- 备份 = 复制 `daylight.db*` 三个文件；导出 = `GET /api/export.md`。

### 回滚

```bash
# 1) 停进程
# 2) 备份当前库
cp data/daylight.db data/daylight.db.bak-$(date +%Y%m%d)
# 3) 换回旧库（含 -wal / -shm 一起换，否则 WAL 会对不上）
cp data/backup/daylight.db      data/daylight.db
cp data/backup/daylight.db-wal  data/daylight.db-wal    # 若存在
# 4) 重启，GET /api/health 核对 counts 与 last_write
```

代码回滚：本项目不依赖迁移脚本，旧版本代码可直接读同一份库（所有表 `CREATE TABLE IF NOT EXISTS`）。

---

## 三、REST 接口

| 方法 | 路径 | 请求体 | 响应 |
|---|---|---|---|
| GET | `/api/health` | — | 存储路径、文件大小、最近写入、条目数、connector 状态 |
| GET | `/api/state` | — | 今日目标/记录/经验卡、进度、连续天数、花园数据、当前模式 |
| POST | `/api/goals` | `{"text": "..."}` ≤200 字 | 201，返回目标（含自动生成的 `next_step`）、可选建议、最新 state |
| POST | `/api/goals/{id}/complete` | 可空 | 200，返回目标与最新 state；不存在 → 404 |
| POST | `/api/checkins` | `{"did": "...", "learned": "..."}` 各 ≤2000 字 | 201，返回记录与最新 state |
| POST | `/api/reflect` | 可空，`{"day": "YYYY-MM-DD"}` 可选 | 201，返回经验卡（`mode`: `local` / `connector`）与最新 state |
| GET | `/api/export.md` | — | `text/markdown`，附件下载 |

校验规则：JSON 对象、字段类型、去空白后非空、长度上限、不可见字符拒绝；路径白名单（只服务 `index.html` / `styles.css` / `app.js` / `favicon.svg`）；id 只接受 1–13 位数字。任何用户文本都只走 `textContent` 或 JSON 传输，不拼 HTML。

---

## 四、模型连接器（已接入官方托管网关）

本地模式永远可用：不配环境变量时，经验卡由 `coach.build_card()` 用真实记录套模板生成，完全离线，界面右上角显示"本地模式"。

线上实例走 Sprites 官方 **OpenRouter 托管 connector**，无需 token、无需自备 key：

| 项 | 值 |
|---|---|
| 托管 connector ID | `1iRDaTyJ5VAi1NBRbliO1Q` |
| 状态 | 已实测成功（免费模型，0 美元额度） |
| 模型 | `liquid/lfm-3-1.7b:free` |
| 限制 | 仅 `name_prefix = daylight`；仅允许 `/v1/models` 与 `/v1/chat/completions` |
| 鉴权 | 不需要 token |

运行时配置（`start.sh` 已内置）：

```bash
export SPRITE_CONNECTOR_URL="https://api.sprites.dev/v1/gateway/openrouter/1iRDaTyJ5VAi1NBRbliO1Q/v1/chat/completions"
export SPRITE_MODEL="liquid/lfm-3-1.7b:free"
# 可选：显式指定发现端点；不给则由 SPRITE_CONNECTOR_URL 推导为 <base>/v1/gateway/list
export SPRITE_GATEWAY_LIST_URL="https://api.sprites.dev/v1/gateway/list"
# 可选：只有换成需要鉴权的网关时才用；本托管网关不设此项
# export SPRITE_CONNECTOR_TOKEN="<运行时注入，不入库、不入代码>"
```

- 官方入口：<https://fly.io/sprites/> · connector gateway：<https://api.sprites.dev/v1/gateway/list>
- `SPRITE_CONNECTOR_URL` / `SPRITE_MODEL` 缺任意一个 → 自动回到本地模式，界面明确标注。
- 调用失败、超时、返回体异常 → 回落本地模板，卡片 `mode` 记为 `local`。
- **默认超时 60 秒**（`coach.DEFAULT_TIMEOUT`）。免费托管模型会排队，实测 8 秒上限会把长卡截断并回退本地；放宽到 60 秒后实测成功。需要更短/更长时构造 `Connector(..., timeout=N)` 覆盖。
- 发给模型的内容只有当天真实记录；提示词明确禁止编造成绩。
- 单测用注入的假 `transport` 覆盖成功/失败/发现/超时四条路径，**测试过程不发任何网络请求**。

---

## 五、部署状态（已部署，实测记录）

当前部署：

| 项 | 值 |
|---|---|
| Sprite 名称 | `daylight` |
| 地址 | <https://daylight-b6wqd.sprites.app> |
| 数据路径 | `/home/sprite/daylight-data/daylight.db`（`/api/health` 可直接核对） |
| 启动方式 | `sh start.sh` → `python3 app.py --port 8080 --data-dir /home/sprite/daylight-data` |
| 自动休眠后数据 | **已验证保留**（休眠唤醒后 `counts` 与 `last_write` 连续，未丢记录） |
| connector | 官方 OpenRouter 托管 connector `1iRDaTyJ5VAi1NBRbliO1Q`，`liquid/lfm-3-1.7b:free`，实测成功 |

复现这套部署的顺序（供以后重建）：

1. 安装并登录官方 Sprites 工具（<https://fly.io/sprites/>），创建 Sprite 实例。
2. 上传本目录（`app.py`、`store.py`、`coach.py`、`static/`、`start.sh`），保留 `static/` 相对位置。
3. 确保 `/home/sprite/daylight-data` 存在且可写（`app.py` 检测到 `/home/sprite` 会自动用它，`start.sh` 再显式传 `--data-dir`）。
4. `sh start.sh`，确认 8080 对外；`GET /api/health` 的 `db_path` 应指向持久磁盘。
5. 计费与空闲策略按官方文档设置（空闲休眠、磁盘大小）。

### 已知缺口（诚实清单，未实测的部分照实写）

- 冷启动耗时取决于免费实例排队，未做量化；首次请求可能明显慢于唤醒后。
- 托管 connector 是免费模型池，排队高峰可能超过 60 秒 → 该次卡片回落本地模板（有 `mode` 标记，不假装成功）。
- 未做多用户/鉴权：定位是个人单用户单实例（任务要求无登录系统），不要把它暴露成公共多租户服务。
- 没有反向代理、TLS 由 Sprites 平台承担；本地直跑是明文 HTTP。

### 预算提醒

- Sprites 的机器/磁盘计费与免费额度以官方页面为准，变更实例规格前先确认额度与休眠策略。
- 当前 connector 模型 `liquid/lfm-3-1.7b:free` 走 Free 托管额度，**单次调用 0 美元**。
- 每次"生成经验卡"是一次模型调用；只在用户点击时触发（当前实现如此），不做后台轮询。
- 本地开发零成本：不需要任何 API key 也能完整跑通全部功能与测试。

---

## 六、目录

```
hacksgiving-daylight/
├── app.py              HTTP 服务、路由、输入校验、静态资源
├── store.py            SQLite 读写、导出、健康检查
├── coach.py            下一步建议、经验卡模板、connector 客户端（默认超时 60s）
├── start.sh            Sprite 启动脚本（无密钥，内置 connector env）
├── static/             index.html / styles.css / app.js / favicon.svg
├── tests/test_app.py   36 项单测（含 keep-alive 与 connector mock）
├── scripts/
│   ├── e2e_check.py    真进程 + 真 HTTP + 重启持久化校验
│   ├── shots.py        Chrome 截图 + console 错误采集
│   └── diag_*.py       排查用脚本（保留，供复现）
├── screenshots/        UI 证据
└── verify.log          全部命令的退出码与输出
```

## 七、设计取舍

- **不编造**：卡片里的每个数字与每句话都来自 SQLite 记录；没有记录时卡片明说"今天还没有写下小目标"。
- **不游戏化到空转**：花园的植株阶段只由真实动作数决定（0 粒种子 → 1 幼苗 → 2 长叶 → 3 花苞 → 4+ 开花），点开能看到那天真实的文字。
- **进程内无状态**：所有读都打库，重启即验证（`scripts/e2e_check.py` 的 run 2）。
- **超时给够**：免费托管模型排队是常态，60 秒上限比 8 秒更接近真实；失败只回落本地模板并标 `mode=local`，不把回退当成模型成功。
- **单文件依赖观**：三个 Python 文件 + 一个启动脚本 + 四个静态文件，任何人都能在半小时内读完。
