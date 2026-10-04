"""采掘接续业务规则：版本管理、进度回写与偏差重算都收在这里。

核心约定：
- 一个采煤工作面挂一条台账记录，计划以版本形式挂在台账下；
- 计划调整必须另出一版，已批准的版本不再就地改；
- 台账上的 current_version 是当前版本的唯一指针，列表、明细、偏差都从这里读，保证同源；
- 实际进度登记后回写台账，衔接关系与原计划冲突时以版本里的先后为准；
- 每个版本各自记住进度口径，历史版本按当时的口径保留，当前版本按新口径实时重算。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "succession"
REQUIRED_FIELDS = ["工作面编号", "工作面名称", "所在采区", "接续方式", "计划开工月份", "计划完工月份"]
VERSION_FIELDS = ["接续方式", "计划开工月份", "计划完工月份", "衔接前工作面", "衔接后工作面", "进度口径"]
CALIBERS = ["开工口径", "完工口径", "开完工口径"]
LEDGER_STATUSES = ["接续正常", "衔接冲突", "已采完"]


def _month_value(text: Any) -> int | None:
    """把「YYYY-MM」折算成可比较的月份序号；格式不对时返回 None。"""
    parts = str(text or "").strip().split("-")
    if len(parts) != 2:
        return None
    try:
        year, month = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not 1 <= month <= 12:
        return None
    return year * 12 + month


def _current_version(row: dict[str, Any]) -> dict[str, Any] | None:
    """当前版本的唯一入口：全系统都按台账上的 current_version 指针取。"""
    versions = row.get("versions") or []
    if not versions:
        return None
    number = row.get("current_version")
    for version in versions:
        if version.get("版本号") == number:
            return version
    return None


def _draft_version(row: dict[str, Any]) -> dict[str, Any] | None:
    for version in row.get("versions") or []:
        if version.get("版本状态") == "草稿":
            return version
    return None


def _deviation_months(version: dict[str, Any], row: dict[str, Any]) -> int | None:
    """按版本自己的进度口径算偏差（月）：实际减计划，正数为滞后。"""
    caliber = str(version.get("进度口径") or "开完工口径")
    diffs: list[int] = []
    if caliber in ("开工口径", "开完工口径"):
        plan = _month_value(version.get("计划开工月份"))
        actual = _month_value(row.get("实际开工月份"))
        if plan is not None and actual is not None:
            diffs.append(actual - plan)
    if caliber in ("完工口径", "开完工口径"):
        plan = _month_value(version.get("计划完工月份"))
        actual = _month_value(row.get("实际完工月份"))
        if plan is not None and actual is not None:
            diffs.append(actual - plan)
    if not diffs:
        return None
    return max(diffs, key=abs)


def _version_view(version: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    """版本视图：当前版本按口径实时重算偏差，历史版本保留批准时的快照。"""
    view = dict(version)
    view["是否当前"] = version.get("版本号") == row.get("current_version")
    if view["是否当前"]:
        view["偏差(月)"] = _deviation_months(version, row)
    else:
        view["偏差(月)"] = version.get("偏差月")
    return view


def _ledger_view(row: dict[str, Any]) -> dict[str, Any]:
    """台账列表行：把当前版本的关键字段摊平到一行，方便表格直接读。"""
    view = {key: value for key, value in row.items() if key not in ("versions", "progress")}
    version = _current_version(row)
    if version:
        view["当前版本"] = f"V{version['版本号']}"
        view["接续方式"] = version.get("接续方式")
        view["计划开工月份"] = version.get("计划开工月份")
        view["计划完工月份"] = version.get("计划完工月份")
        view["进度口径"] = version.get("进度口径")
        deviation = _deviation_months(version, row)
        view["偏差(月)"] = deviation if deviation is not None else "待定"
    else:
        view["当前版本"] = "待批准"
        view["偏差(月)"] = "待定"
    view["待批准"] = _draft_version(row) is not None
    return view


def _check_months(values: dict[str, Any], fields: list[str]) -> str | None:
    for field in fields:
        text = str(values.get(field) or "").strip()
        if text and _month_value(text) is None:
            return f"「{field}」应按 YYYY-MM 填写，当前值：{text}"
    start = _month_value(values.get("计划开工月份"))
    end = _month_value(values.get("计划完工月份"))
    if start is not None and end is not None and end < start:
        return "计划完工月份不能早于计划开工月份"
    return None


class SuccessionService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        mode: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("工作面编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if mode:
            rows = [row for row in rows if (_current_version(row) or {}).get("接续方式") == mode]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [_ledger_view(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        detail = _ledger_view(row)
        detail["versions"] = [_version_view(version, row) for version in row.get("versions") or []]
        detail["progress"] = list(row.get("progress") or [])
        return detail

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        problem = _check_months(values, ["计划开工月份", "计划完工月份"])
        if problem:
            return None, problem
        caliber = str(values.get("进度口径") or "开完工口径").strip()
        if caliber not in CALIBERS:
            return None, f"进度口径「{caliber}」不在允许范围：{'、'.join(CALIBERS)}"
        rows = store.rows(MODULE)
        code = str(values["工作面编号"]).strip()
        if any(str(row.get("工作面编号")) == code for row in rows):
            return None, f"工作面 {code} 已建台账，一个采煤工作面只挂一条记录"
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry["工作面编号"] = code
        entry["工作面名称"] = str(values["工作面名称"]).strip()
        entry["所在采区"] = str(values["所在采区"]).strip()
        entry["实际开工月份"] = ""
        entry["实际完工月份"] = ""
        entry["衔接结论"] = "尚未登记实际进度"
        entry["status"] = "接续正常"
        entry["pending"] = True
        entry["abnormal"] = False
        entry["current_version"] = 0
        entry["versions"] = [{
            "版本号": 1,
            "版本状态": "草稿",
            "进度口径": caliber,
            "偏差月": None,
            "调整说明": str(values.get("调整说明") or "初版接续计划").strip(),
            **{field: str(values.get(field) or "").strip() for field in VERSION_FIELDS if field != "进度口径"},
        }]
        entry["progress"] = []
        rows.append(entry)
        return entry, "接续计划已登记，V1 版为草稿，批准后成为当前版本"

    def create_version(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """计划调整：从当前批准版另出一版草稿，原版原样保留。"""
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"接续台账 {entry_id} 不存在或已归档"
        base = _current_version(row)
        if base is None:
            return None, "当前还没有已批准的版本，请先批准 V1 版再做调整"
        if _draft_version(row) is not None:
            return None, "已存在待批准的草稿版，请先批准或作废后再另出新版"
        merged = {field: str(values.get(field) or base.get(field) or "").strip() for field in VERSION_FIELDS}
        problem = _check_months(merged, ["计划开工月份", "计划完工月份"])
        if problem:
            return None, problem
        if merged["进度口径"] not in CALIBERS:
            return None, f"进度口径「{merged['进度口径']}」不在允许范围：{'、'.join(CALIBERS)}"
        number = max(int(version.get("版本号", 0)) for version in row["versions"]) + 1
        version = {
            "版本号": number,
            "版本状态": "草稿",
            "偏差月": None,
            "调整说明": str(values.get("调整说明") or f"在 V{base['版本号']} 基础上调整").strip(),
            **merged,
        }
        row["versions"].append(version)
        return version, f"已另出 V{number} 版草稿，V{base['版本号']} 版原样保留，批准后生效"

    def approve_version(self, entry_id: int) -> tuple[dict[str, Any] | None, str]:
        """批准草稿版：成为新的当前版本，并按其口径给当时进度留一份偏差快照。"""
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"接续台账 {entry_id} 不存在或已归档"
        draft = _draft_version(row)
        if draft is None:
            return None, "没有待批准的草稿版，计划调整请先另出新版"
        draft["版本状态"] = "已批准"
        draft["偏差月"] = _deviation_months(draft, row)
        row["current_version"] = draft["版本号"]
        return _ledger_view(row), f"V{draft['版本号']} 版已批准，当前版本已切换，各处读取同源"

    def register_progress(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """登记实际进度：回写台账，并按当前版本的衔接关系核对先后。"""
        row = store.find(MODULE, entry_id)
        if row is None:
            return None, f"接续台账 {entry_id} 不存在或已归档"
        actual_start = str(values.get("实际开工月份") or "").strip()
        actual_end = str(values.get("实际完工月份") or "").strip()
        if not actual_start and not actual_end:
            return None, "至少要登记实际开工月份或实际完工月份之一"
        problem = _check_months({"计划开工月份": actual_start, "计划完工月份": actual_end}, ["计划开工月份", "计划完工月份"])
        if problem:
            return None, problem.replace("计划", "实际")
        if actual_start:
            row["实际开工月份"] = actual_start
        if actual_end:
            row["实际完工月份"] = actual_end
        row.setdefault("progress", []).append({
            "登记月份": str(values.get("登记月份") or date.today().strftime("%Y-%m")).strip(),
            "实际开工月份": actual_start or row["实际开工月份"],
            "实际完工月份": actual_end or row["实际完工月份"],
            "进度说明": str(values.get("进度说明") or "").strip(),
        })
        message = self._reconcile(row)
        return _ledger_view(row), message

    def _reconcile(self, row: dict[str, Any]) -> str:
        """衔接核对：实际进度与版本里的衔接关系冲突时，以版本里的先后为准。"""
        version = _current_version(row)
        if version is None:
            row["衔接结论"] = "尚无已批准版本，进度已回写待核对"
            return "实际进度已回写台账，但还没有已批准版本可核对"
        predecessor = str(version.get("衔接前工作面") or "").strip()
        conflict = False
        if predecessor and _month_value(row.get("实际开工月份")) is not None:
            for other in store.rows(MODULE):
                if str(other.get("工作面编号")) != predecessor:
                    continue
                planned_end = _month_value((_current_version(other) or {}).get("计划完工月份"))
                actual_start = _month_value(row.get("实际开工月份"))
                if planned_end is not None and actual_start is not None and actual_start < planned_end:
                    conflict = True
                break
        if conflict:
            row["status"] = "衔接冲突"
            row["abnormal"] = True
            row["衔接结论"] = f"实际开工早于 {predecessor} 计划完工，衔接顺序以 V{version['版本号']} 版先后为准"
        else:
            row["abnormal"] = False
            row["衔接结论"] = f"与 V{version['版本号']} 版衔接关系一致"
            row["status"] = "接续正常"
        if _month_value(row.get("实际完工月份")) is not None:
            row["status"] = "已采完"
            row["pending"] = False
        deviation = _deviation_months(version, row)
        text = "待定" if deviation is None else f"{deviation} 个月"
        return f"实际进度已回写台账，按{version.get('进度口径')}重算偏差：{text}；{row['衔接结论']}"
