"""대상 문제 식별 (상세구현명세서 8.3). 벡터 검색 없이 알림과 시트를 직접 조회한다."""
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from src.common.text import norm_text

PLATFORM_LABEL = {"programmers": "프로그래머스", "swea": "SWEA"}


@dataclass
class Target:
    platform: str
    problem_id: str
    title: str
    url: str
    tier: str = ""
    rate: float = 0.0
    sent_date: str = ""
    note: str = ""
    hashcode: str = ""


@dataclass
class Resolution:
    target: Target | None = None
    message: str | None = None          # 되묻기·안내 문구 (target이 없을 때)
    hint_only: bool = False
    candidates: list[Target] = field(default_factory=list)


def detect_hint_only(q: str) -> bool:
    return bool(re.search(r"힌트|답은?\s*말고|답\s*빼고|정답\s*빼고|답\s*없이", q))


def detect_platform(q: str) -> str | None:
    low = q.lower()
    if "프로그래머스" in q or "programmers" in low:
        return "programmers"
    if "swea" in low or "swexpert" in low or "에스웨이" in q:
        return "swea"
    return None


def detect_number(q: str) -> str | None:
    m = re.search(r"(\d{2,})\s*번", q) or re.search(r"\b(\d{4,})\b", q)
    return m[1] if m else None


def _row_to_target(row: dict, notice: dict | None = None, note: str = "") -> Target:
    return Target(
        platform=row["platform"], problem_id=row["problem_id"], title=row["title"], url=row["url"],
        tier=row.get("tier", ""), rate=row.get("rate", 0.0), hashcode=row.get("hashcode", ""),
        sent_date=(notice or {}).get("sent_date", ""), note=note)


def _find_row(index: dict, platform: str, pid: str) -> dict | None:
    return next((r for r in index["problems"].get(platform, []) if r["problem_id"] == pid), None)


def _notice_target(index: dict, n: dict, note: str = "") -> Target:
    row = _find_row(index, n["platform"], n["problem_id"]) or {
        "platform": n["platform"], "problem_id": n["problem_id"], "title": n["title"], "url": n["url"],
        "tier": f"레벨 {n.get('level', '')}", "rate": n.get("rate", 0.0)}
    return _row_to_target(row, n, note)


def _latest_done_row(index: dict, platform: str) -> dict | None:
    done = [r for r in index["problems"].get(platform, []) if r["done"]]
    return done[-1] if done else None


def resolve(question: str, index: dict, today: date) -> Resolution:
    q = norm_text(question)
    res = Resolution(hint_only=detect_hint_only(q))
    platform, number = detect_platform(q), detect_number(q)
    notices = sorted(index.get("notices", []), key=lambda n: n["sent_date"], reverse=True)

    # 1) 번호 지정: 시트 전체 목록에서 조회
    if number:
        found = [r for p in ([platform] if platform else ["programmers", "swea"])
                 for r in index["problems"].get(p, []) if r["problem_id"] == number]
        if not found:
            res.message = f"{number}번 문제를 시트에서 찾지 못했습니다."
        elif len(found) > 1:
            res.candidates = [_row_to_target(r) for r in found]
            res.message = (f"{number}번은 두 플랫폼에 모두 있습니다. 어느 쪽일까요? "
                           + " / ".join(PLATFORM_LABEL[r["platform"]] for r in found))
        else:
            res.target = _row_to_target(found[0])
        return res

    pool = [n for n in notices if not platform or n["platform"] == platform]

    # 2) 날짜 지정
    if "어제" in q or "지난주" in q.replace(" ", ""):
        if "어제" in q:
            lo = hi = today - timedelta(days=1)
            label = "어제"
        else:
            lo = today - timedelta(days=today.weekday() + 7)
            hi = lo + timedelta(days=6)
            label = "지난주"
        hits = [n for n in pool if lo.isoformat() <= n["sent_date"] <= hi.isoformat()]
        if not hits:
            res.message = f"{label} 올라온 문제 알림을 찾지 못했습니다."
        elif len(hits) == 1:
            res.target = _notice_target(index, hits[0])
        else:
            res.candidates = [_notice_target(index, n) for n in hits]
            res.message = (f"{label} 문제가 {len(hits)}건입니다. 번호로 다시 물어봐 주세요.\n"
                           + "\n".join(f"• {PLATFORM_LABEL[n['platform']]} {n['problem_id']}번 {n['title']} ({n['sent_date']})" for n in hits))
        return res

    # 3) 오늘(기본): 오늘 알림, 없으면 가장 최근
    todays = [n for n in pool if n["sent_date"] == today.isoformat()]
    if todays:
        res.target = _notice_target(index, todays[0])
        return res
    if pool:
        n = pool[0]
        res.target = _notice_target(index, n, f"오늘은 알림이 없어 가장 최근({n['sent_date'][5:].replace('-', '/')}) 문제입니다.")
        other = {m["platform"] for m in notices} - {n["platform"]}
        if not platform and other:
            res.target.note += f" ({', '.join(PLATFORM_LABEL[p] for p in other)}에도 문제가 있습니다.)"
        return res
    # 알림 기록이 없으면 시트에서 마지막으로 보낸(완료) 문제
    for p in ([platform] if platform else ["programmers", "swea"]):
        row = _latest_done_row(index, p)
        if row:
            res.target = _row_to_target(row, note="알림 기록을 읽지 못해 시트에서 마지막으로 보낸 문제를 사용합니다.")
            return res
    res.message = "문제 목록을 아직 읽지 못했습니다. 잠시 뒤 다시 시도해 주세요."
    return res
