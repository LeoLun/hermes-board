"""示例数据脚本：采集 1 分钟平均负载。把这里换成你自己的取数逻辑。"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "_sdk"))
from hermes_board_sdk import Card  # noqa: E402

card = Card()

try:
    load1, _, _ = os.getloadavg()
except (AttributeError, OSError):
    card.fail("当前系统不支持读取平均负载")

cpus = os.cpu_count() or 1
value = round(load1, 2)
card.data.set("current", {"value": value, "unit": f"/ {cpus} 核", "label": "1 分钟平均负载"})
card.series.append("history", value)
card.result({"value": value, "cpus": cpus})
