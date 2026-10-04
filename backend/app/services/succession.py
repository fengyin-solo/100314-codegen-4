"""采掘接续业务规则：版本链、进度回写、口径重算与存量回填都收在这里。

约定：
- 一个采煤工作面对应台账里的一行；接续方式、计划月份、衔接关系这些计划类字段只存在
  版本表里，台账行上不另存副本；
- 台账行上的「当前版本号」是版本指针的唯一出处，列表、详情、导出、回写都从这里取
  当前版本，保证各处读到的当前版本同源；
- 已批复的版本整行不再改，计划调整一律另出新版，原版保留；
- 偏差按全局当前口径计算并回写台账；历史版本保留创建时的口径快照，翻旧账时仍按
  当时的进度口径看偏差。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "succession"
VERSION_MODULE = "succession_version"
PROGRESS_MODULE = "succession_progress"
CALIBER_MODULE = "succession_caliber"

REQUIRED_FIELDS = ["工作面编号", "工作面名称", "接续方式", "计划开工月份", "计划完工月份"]
SUCCESSION_METHODS = ["顺序接续", "跳采接续", "延伸接续", "新面接续"]
CALIBERS = ["按开工月份", "按完工月份", "按较大偏差"]
PLAN_FIELDS = ["接续方式", "计划开工月份", "计划完工月份", "前续工作面", "后续工作面"]
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _month_diff(later: str, earlier: str) -> int:
    """两个 YYYY-MM 月份相差的月数，later 更晚时为正，表示滞后。"""
    return (int(later[:4]) - int(earlier[:4])) * 12 + (int(later[5:7]) - int(earlier[5:7]))


def _version_no(tag: Any) -> int:
    match = re.match(r"^V(\d+)$", str(tag or ""))
    return int(match.group(1)) if match else 0


def _next_id(module: str) -> int:
    return max((int(row.get("id", 0)) for row in store.rows(module)), default=0) + 1


class SuccessionService:
    def __init__(self) -> None:
        # 启动即把存量数据按接续月份回填进版本链，保证台账读到的行都有当前版本
        self.backfill()

    # ---------- 接续口径 ----------

    def caliber(self) -> dict[str, Any]:
        rows = store.rows(CALIBER_MODULE)
        if not rows:
            rows.append({"id": 1, "当前口径": CALIBERS[0], "调整人": None, "调整时间": None, "说明": None})
        return {**rows[0], "可选口径": list(CALIBERS)}

    def adjust_caliber(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        new = str(values.get("口径") or "").strip()
        if new not in CALIBERS:
            return None, f"接续口径须为：{'、'.join(CALIBERS)}"
        rows = store.rows(CALIBER_MODULE)
        if not rows:
            rows.append({"id": 1})
        row = rows[0]
        old = row.get("当前口径")
        row["当前口径"] = new
        row["调整人"] = str(values.get("调整人") or "").strip() or "调度室"
        row["调整时间"] = _now()
        row["说明"] = str(values.get("说明") or "").strip() or None
        # 口径调整后按新口径重算台账偏差；历史版本不动，仍按当时的进度口径保留
        recalced = 0
        for plan in store.rows(MODULE):
            version = self._current_version(plan)
            if version is None:
                continue
            plan["偏差月数"] = self._deviation(plan, version, new)
            recalced += 1
        result = {"旧口径": old, "新口径": new, "重算条数": recalced}
        return result, f"接续口径已调整为「{new}」，按新口径重算 {recalced} 条偏差"

    # ---------- 版本链 ----------

    def _versions(self, plan_id: int) -> list[dict[str, Any]]:
        rows = [row for row in store.rows(VERSION_MODULE) if int(row.get("计划ID", 0)) == plan_id]
        return sorted(rows, key=lambda row: _version_no(row.get("版本号")))

    def _current_version(self, plan: dict[str, Any]) -> dict[str, Any] | None:
        """当前版本的唯一出处：台账行上的版本号指针。所有读取都走这里，保证同源。"""
        want = str(plan.get("当前版本号") or "")
        if not want:
            return None
        for row in store.rows(VERSION_MODULE):
            if int(row.get("计划ID", 0)) == int(plan.get("id", 0)) and str(row.get("版本号")) == want:
                return row
        return None

    def _new_version(self, plan: dict[str, Any], values: dict[str, Any], note: str) -> dict[str, Any]:
        plan_id = int(plan.get("id", 0))
        version = {
            "id": _next_id(VERSION_MODULE),
            "计划ID": plan_id,
            "版本号": f"V{max((_version_no(row.get('版本号')) for row in self._versions(plan_id)), default=0) + 1}",
            "版本状态": "草稿",
            "进度口径": self.caliber()["当前口径"],
            "调整说明": note,
            "登记人": str(values.get("登记人") or "").strip() or "调度室",
            "登记时间": _now(),
            "批复人": None,
            "批复时间": None,
        }
        for field in PLAN_FIELDS:
            version[field] = values.get(field)
        store.rows(VERSION_MODULE).append(version)
        plan["当前版本号"] = version["版本号"]
        return version

    def _deviation(self, plan: dict[str, Any], version: dict[str, Any], caliber: str) -> int | None:
        """按口径算偏差（月）：实际晚于计划为正。实际进度没登记到的节点不参与。"""
        parts: list[int] = []
        actual_start = plan.get("实际开工月份")
        actual_end = plan.get("实际完工月份")
        if caliber in ("按开工月份", "按较大偏差") and actual_start and version.get("计划开工月份"):
            parts.append(_month_diff(str(actual_start), str(version["计划开工月份"])))
        if caliber in ("按完工月份", "按较大偏差") and actual_end and version.get("计划完工月份"):
            parts.append(_month_diff(str(actual_end), str(version["计划完工月份"])))
        return max(parts) if parts else None

    def _present(self, plan: dict[str, Any]) -> dict[str, Any]:
        """台账读模型：计划类字段一律从当前版本 join，保证各处读到的当前版本同源。"""
        row = dict(plan)
        version = self._current_version(plan)
        for field in PLAN_FIELDS:
            row[field] = (version or {}).get(field) or plan.get(field)
        row["版本状态"] = (version or {}).get("版本状态") or "未建版"
        row["进度口径"] = self.caliber()["当前口径"]
        return row

    # ---------- 台账读写 ----------

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._present(plan) for plan in store.rows(MODULE)]
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("工作面编号", "")) or keyword in str(row.get("工作面名称", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        # 台账按接续月份（计划开工月份）排序，和调度会上的衔接顺序一致
        rows.sort(key=lambda row: (str(row.get("计划开工月份") or "9999-12"), str(row.get("工作面编号") or "")))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        plan = store.find(MODULE, entry_id)
        if plan is None:
            return None
        detail = self._present(plan)
        detail["当前版本"] = self._current_version(plan)
        detail["进度记录"] = self.progress_of(entry_id)
        return detail

    def versions_of(self, entry_id: int) -> list[dict[str, Any]] | None:
        plan = store.find(MODULE, entry_id)
        if plan is None:
            return None
        result = []
        for version in reversed(self._versions(entry_id)):
            row = dict(version)
            # 历史版本按当时的进度口径保留：偏差用版本自己的口径快照算
            row["偏差月数"] = self._deviation(plan, version, str(version.get("进度口径") or CALIBERS[0]))
            row["是否当前版本"] = str(version.get("版本号")) == str(plan.get("当前版本号"))
            result.append(row)
        return result

    def progress_of(self, entry_id: int) -> list[dict[str, Any]]:
        rows = [row for row in store.rows(PROGRESS_MODULE) if int(row.get("计划ID", 0)) == entry_id]
        return sorted(rows, key=lambda row: str(row.get("登记时间") or ""), reverse=True)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        problems: list[str] = []
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            problems.append(f"缺少必填字段：{'、'.join(missing)}")
        problems.extend(self._check_plan(values))
        code = str(values.get("工作面编号") or "").strip()
        if code and any(str(row.get("工作面编号")) == code for row in store.rows(MODULE)):
            problems.append(f"工作面 {code} 已建立接续计划，计划调整请另出新版")
        if problems:
            return None, problems
        plan = {
            "id": _next_id(MODULE),
            "工作面编号": code,
            "工作面名称": str(values["工作面名称"]).strip(),
            "所在采区": str(values.get("所在采区") or "").strip() or None,
            "当前版本号": None,
            "实际开工月份": None,
            "实际完工月份": None,
            "实际衔接工作面": None,
            "偏差月数": None,
            "衔接冲突": False,
            "status": "未开工",
            "pending": True,
            "abnormal": False,
        }
        store.rows(MODULE).append(plan)
        self._new_version(plan, values, "初始登记")
        return self._present(plan), []

    def approve(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        plan = store.find(MODULE, entry_id)
        if plan is None:
            return None, f"接续计划 {entry_id} 不存在或已归档"
        version = self._current_version(plan)
        if version is None:
            return None, "当前版本缺失，请先执行存量回填"
        if version.get("版本状态") == "已批复":
            return None, f"{version['版本号']} 已批复，已批过的版本不能就地改，调整计划请另出新版"
        version["版本状态"] = "已批复"
        version["批复人"] = str(values.get("批复人") or "").strip() or "调度会"
        version["批复时间"] = _now()
        return self._present(plan), f"{plan['工作面编号']} {version['版本号']} 已批复"

    def revise(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        plan = store.find(MODULE, entry_id)
        if plan is None:
            return None, f"接续计划 {entry_id} 不存在或已归档"
        current = self._current_version(plan)
        if current is None:
            return None, "当前版本缺失，请先执行存量回填"
        # 以当前版本为底另出新版，没提交的字段沿用当前版本，原版整行保留
        merged = {field: values.get(field) or current.get(field) for field in PLAN_FIELDS}
        problems = self._check_plan(merged)
        if problems:
            return None, "；".join(problems)
        merged["登记人"] = values.get("登记人")
        note = str(values.get("调整说明") or "").strip() or "计划调整"
        version = self._new_version(plan, merged, note)
        # 计划月份变了，台账偏差按现行口径重算
        plan["偏差月数"] = self._deviation(plan, version, self.caliber()["当前口径"])
        return self._present(plan), f"已另出新版 {version['版本号']}，原 {current['版本号']} 保留"

    def register_progress(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        plan = store.find(MODULE, entry_id)
        if plan is None:
            return None, f"接续计划 {entry_id} 不存在或已归档"
        version = self._current_version(plan)
        if version is None:
            return None, "当前版本缺失，请先执行存量回填"
        start = str(values.get("实际开工月份") or "").strip() or None
        end = str(values.get("实际完工月份") or "").strip() or None
        if not start and not end:
            return None, "至少要登记实际开工月份或实际完工月份"
        for label, month in (("实际开工月份", start), ("实际完工月份", end)):
            if month and not MONTH_PATTERN.match(month):
                return None, f"{label}须为 YYYY-MM 格式"
        actual_start = start or plan.get("实际开工月份")
        actual_end = end or plan.get("实际完工月份")
        if actual_start and actual_end and _month_diff(str(actual_end), str(actual_start)) < 0:
            return None, "实际完工月份不能早于实际开工月份"
        # 衔接关系以版本里的先后为准：实际衔接和当前版本不一致时只记冲突，不改衔接顺序
        actual_link = str(values.get("实际衔接工作面") or "").strip() or None
        planned_link = str(version.get("后续工作面") or "").strip()
        conflict = bool(actual_link and planned_link and actual_link != planned_link)
        progress = {
            "id": _next_id(PROGRESS_MODULE),
            "计划ID": entry_id,
            "实际开工月份": start,
            "实际完工月份": end,
            "实际衔接工作面": actual_link,
            "衔接冲突": conflict,
            "登记人": str(values.get("登记人") or "").strip() or "生产队组",
            "登记时间": _now(),
            "备注": str(values.get("备注") or "").strip() or None,
        }
        store.rows(PROGRESS_MODULE).append(progress)
        # 实际进度回写接续计划台账
        plan["实际开工月份"] = actual_start
        plan["实际完工月份"] = actual_end
        if actual_link:
            plan["实际衔接工作面"] = actual_link
        plan["衔接冲突"] = conflict
        plan["abnormal"] = conflict
        plan["status"] = "已完工" if actual_end else ("回采中" if actual_start else "未开工")
        plan["pending"] = plan["status"] != "已完工"
        plan["偏差月数"] = self._deviation(plan, version, self.caliber()["当前口径"])
        message = "实际进度已登记并回写接续计划台账"
        if conflict:
            message += f"；实际衔接「{actual_link}」与当前版本后续「{planned_link}」不一致，衔接关系仍以版本里的先后为准"
        return self._present(plan), message

    def backfill(self) -> dict[str, Any]:
        """存量数据按接续月份回填：没有版本链的台账行，按行上的接续月份生成首版并指向它。"""
        filled = 0
        skipped: list[str] = []
        for plan in store.rows(MODULE):
            if plan.get("当前版本号"):
                continue
            start = str(plan.get("计划开工月份") or "").strip()
            if not MONTH_PATTERN.match(start):
                skipped.append(str(plan.get("工作面编号") or plan.get("id")))
                continue
            values = {field: plan.get(field) for field in PLAN_FIELDS}
            values["登记人"] = "存量回填"
            version = self._new_version(plan, values, "存量数据按接续月份回填")
            version["版本状态"] = "已批复"
            version["批复人"] = "存量回填"
            version["批复时间"] = version["登记时间"]
            filled += 1
        return {"回填条数": filled, "跳过": skipped}

    def export_entries(self) -> list[dict[str, Any]]:
        rows, _ = self.list_entries(page=1, size=10000)
        return rows

    def _check_plan(self, values: dict[str, Any]) -> list[str]:
        problems: list[str] = []
        method = str(values.get("接续方式") or "").strip()
        if method and method not in SUCCESSION_METHODS:
            problems.append(f"接续方式须为：{'、'.join(SUCCESSION_METHODS)}")
        start = str(values.get("计划开工月份") or "").strip()
        end = str(values.get("计划完工月份") or "").strip()
        for label, month in (("计划开工月份", start), ("计划完工月份", end)):
            if month and not MONTH_PATTERN.match(month):
                problems.append(f"{label}须为 YYYY-MM 格式")
        if MONTH_PATTERN.match(start) and MONTH_PATTERN.match(end) and _month_diff(end, start) < 0:
            problems.append("计划完工月份不能早于计划开工月份")
        return problems
