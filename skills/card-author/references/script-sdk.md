# 数据脚本 SDK

数据脚本运行在远程 Hermes 所在的机器上，负责取数和执行操作，把结果写入看板的 SQLite 数据库（`plugin-data/hermes-board/board.sqlite3`）。卡片 HTML 只能读这些数据，不能联网。

## 安装位置与运行方式

- 保存卡片时，脚本被安装到 `$HERMES_HOME/scripts/hermes-board/<卡片 id>/<文件名>`，SDK 被同步到 `$HERMES_HOME/scripts/hermes-board/_sdk/hermes_board_sdk.py`。
- `.py` 脚本用 Hermes 自带的 Python 运行（标准库加 Hermes 环境里已有的包，例如 `psutil`、`httpx`）；`.sh` 脚本用 bash 运行。不要假设能 `pip install`。
- 触发方式：
  - **cron**：清单中写了 `schedule` 的脚本，由 Hermes 原生 cron 以 no-agent 方式定时运行（任务名 `hermes-board:<卡片>:<脚本>`）。cron 运行时 stdout 应保持为空，否则 Hermes 会把输出当作消息投递。
  - **action**：卡片调用 `HermesCard.run`（脚本需 `callable: true`）。
  - **install**：保存后运行 `runOnInstall` 的脚本。
  - **tool**：Agent 调用 `board_manage {action:"run"}`。
- 卡片、工具、安装触发的运行有超时（`timeoutSec`，默认 60，最大 600），超时后整个进程组被终止；全局最多同时运行 4 个，同一脚本同时只运行一个。stdout、stderr 各保留末尾 4 KiB。

## Python 脚本模板

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "_sdk"))
from hermes_board_sdk import Card

card = Card()                      # 从脚本路径推断卡片 id 和 HERMES_HOME
city = card.args.get("city") or card.state.get("city")   # 参数优先，其次是卡片状态
card.progress(0.2, "正在获取数据")
value = {"temp": 21.5, "text": "晴"}
card.data.set("current", value)     # 写数据集（最新快照）
card.series.append("temp", 21.5)    # 追加序列点（ts 默认为当前 UTC 毫秒）
card.result({"ok": True})           # 运行结果，卡片和 Agent 都能看到
```

前两行（把 `_sdk` 加入 `sys.path` 并导入 `Card`）必须保留。

## Card 接口

| 接口 | 说明 |
|---|---|
| `Card()` | 创建运行上下文。也可以 `Card(card_id=..., hermes_home=...)` 显式指定 |
| `card.id` / `card.home` / `card.manifest` | 卡片 id、`HERMES_HOME` 路径、清单内容 |
| `card.args` | 本次运行的参数（dict，cron 运行时为空） |
| `card.trigger` | `cron`、`action`、`install`、`tool` |
| `card.run_id` | 本次运行的 id |
| `card.data.set(key, value)` / `.get(key, default)` / `.list()` | 数据集读写，单值 ≤ 256 KiB |
| `card.series.append(name, value, ts=None)` | 追加序列点，单点 ≤ 4 KiB；按清单的 `retention` 自动清理 |
| `card.series.query(name, since, until, limit, order)` | 查询序列 |
| `card.state.get(key, default)` / `.set(key, value)` / `.delete(key)` | 卡片状态（与卡片 HTML 共享） |
| `card.progress(fraction, message)` | 上报进度（0 到 1）和说明，卡片可显示 |
| `card.result(value)` | 设置运行结果（JSON 可序列化） |
| `card.fail(message)` | 记录失败原因并以退出码 1 结束 |

值必须能被 JSON 序列化。所有写入都会生成变更记录，订阅了对应主题的卡片会自动刷新。

运行状态：脚本正常结束为 `succeeded`；非零退出码、未捕获异常或 `card.fail` 为 `failed`，错误信息会记录到运行记录的 `error`；超时为 `timeout`。cron 运行时 SDK 会自动创建并结束运行记录。

## Shell 脚本

`.sh` 脚本不能使用 SDK 的数据写入接口，适合执行操作（例如切换配置）。需要返回结果时，在最后一行输出：

```bash
echo 'HERMES_BOARD_RESULT {"switched": true, "node": "hk-1"}'
```

需要写数据时，改用 Python 脚本，或在 Python 中用 `subprocess` 调用命令。

## 网络、凭据与权限

- 脚本可以联网（卡片不能）。网络请求要设置超时，失败时用 `card.fail("原因")` 给出可读的错误。
- 凭据（API Key、Token）不要写进脚本或卡片文件。请用户在远程 Hermes 配置的 `terminal.env_passthrough` 中放行对应环境变量，脚本通过 `os.environ.get("NAME")` 读取；缺失时 `card.fail("缺少环境变量 NAME，请在 terminal.env_passthrough 中放行")`。
- 需要特权的操作（例如 `systemctl restart xray`）由用户在远程机器上自行授权（如 sudoers 中只允许特定命令免密），脚本只调用已授权的命令，例如 `sudo -n systemctl restart xray`；`-n` 保证无授权时立即失败而不是等待密码。
- 读取其他程序或插件的数据时只读打开，不要写入：

```python
import sqlite3
conn = sqlite3.connect(f"file:{card.home}/plugin-data/hermes-bill/bills.sqlite3?mode=ro", uri=True)
```

## 自测

保存后用 `board_manage {action:"run", card, script, args}` 运行，检查返回的 `status`、`result`、`error`、`stdoutTail`、`stderrTail`；再用 `board_manage {action:"data", card, kind:"data"}`（或 `series`、`state`、`runs`）确认数据已写入。
