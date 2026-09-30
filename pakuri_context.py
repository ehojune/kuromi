"""Read-only fortnight trends and a daily profile from the private Pakuri store."""
from collections import defaultdict
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
from urllib.parse import urlsplit

from briefing_links import source_urls
from pakuri_tools import _json, _slack, _text, _time, _validate_item

_UTC = timezone.utc
_KST = timezone(timedelta(hours=9))
_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\Z")
_REPO = re.compile(r"[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}\Z")
_MAX_ROWS = 25_000
_TOPICS = {
    **dict.fromkeys(("genomics", "alignment", "pangenome", "human-genetics", "rare-disease",
                     "variant-calling", "tandem-repeats", "str", "bioinformatics"), "유전체·생물정보학"),
    **dict.fromkeys(("agents", "ai-agents", "agent", "scientific-agents", "multiagent",
                     "multi-agent", "agentic-ai", "coding-agents"), "AI 에이전트"),
    **dict.fromkeys(("single-cell", "singlecell", "spatial-omics"), "단일세포·공간 오믹스"),
    **dict.fromkeys(("protein", "protein-design", "protein-structure", "protein-language-models"), "단백질"),
    **dict.fromkeys(("workflow", "workflows", "orchestration", "pipelines"), "워크플로·오케스트레이션"),
    **dict.fromkeys(("evaluation", "evals", "llm-evaluation", "benchmarking"), "평가·벤치마크"),
    **dict.fromkeys(("llm-tools", "llm", "coding", "mcp"), "LLM 개발 도구"),
    "data-tools": "데이터 도구", "security": "보안", "biology": "생물학",
    "microbial-genomics": "미생물 유전체", "antimicrobial-resistance": "항생제 내성",
    "rna-seq": "RNA-seq", "quantification": "발현 정량", "read-processing": "시퀀싱 전처리",
    "genomic-ai": "유전체 AI", "variant-analysis": "변이 해석", "structural-variation": "구조 변이",
    "homology-search": "상동성 검색", "structure-prediction": "구조 예측", "therapeutics": "치료제 연구",
    "llm-training": "LLM 학습", "open-models": "공개 모델", "education": "AI 교육",
    "retrieval": "검색·RAG", "automation": "자동화", "reproducibility": "재현성",
    "data-infrastructure": "데이터 인프라", "algorithms": "알고리즘", "compression": "압축",
    "data-formats": "데이터 형식", "formats": "데이터 형식", "sequence-tools": "서열 도구",
    "graph-genomics": "그래프 유전체", "ai": "AI",
}


class CollectorBusy(OSError):
    pass


def _path(root, name):
    result = (root / name).resolve()
    if not result.is_relative_to(root):
        raise ValueError("path_outside_project")
    return result


def _source(value):
    if not isinstance(value, str) or len(value) > 1000:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or
            parsed.password or any(ord(c) < 33 for c in value) or
            any(c in value for c in "<>|\\\"'`")):
        return ""
    return value


def _targets(root):
    doc = _json(_path(root, "targets.json"))
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        raise ValueError("invalid_targets")
    people, repo_topics = [], {}
    rows = doc.get("people", [])
    if not isinstance(rows, list) or len(rows) > 500:
        raise ValueError("invalid_people")
    for row in rows:
        if not isinstance(row, dict) or not _LOGIN.fullmatch(str(row.get("login", ""))):
            continue
        verification = row.get("verification", {})
        if (not isinstance(verification, dict) or verification.get("status") != "verified" or
                verification.get("account_type") != "User"):
            continue
        people.append(row)
    repo_rows = doc.get("repositories", [])
    if not isinstance(repo_rows, list) or len(repo_rows) > 500:
        raise ValueError("invalid_repositories")
    for row in repo_rows:
        if not isinstance(row, dict) or not _REPO.fullmatch(str(row.get("full_name", ""))):
            continue
        topics = row.get("topics", [])
        if isinstance(topics, list):
            repo_topics[row["full_name"].casefold()] = [_text(t, 60) for t in topics[:30] if isinstance(t, str)]
    unique = {row["login"].casefold(): row for row in people}
    return list(unique.values()), repo_topics


@contextmanager
def _snapshot(root):
    """Copy DB+WAL under the collector's existing lock; SQLite only opens the copy."""
    path = _path(root, "data/state.sqlite3")
    wal = _path(root, "data/state.sqlite3-wal")
    guard = _path(root, "data/state.sqlite3.lock")
    if not path.is_file():
        raise FileNotFoundError(path)
    with tempfile.TemporaryDirectory(prefix="kuromi-pakuri-") as directory:
        copied = Path(directory) / "snapshot.sqlite3"
        # Never create a lock file or open SQLite on the original. All Pakuri writers
        # hold this exclusive byte/flock lock through their final close/checkpoint.
        with guard.open("rb") as handle:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBRLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError as exc:
                raise CollectorBusy("collector_in_progress") from exc
            try:
                for source, destination in ((path, copied), (wal, copied.with_name(copied.name + "-wal"))):
                    if source.is_file():
                        if source.stat().st_size > 128_000_000:
                            raise ValueError("snapshot_too_large")
                        shutil.copyfile(source, destination)
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        with closing(sqlite3.connect(copied.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
            db.execute("PRAGMA query_only=ON")
            yield db


def _history(root, now):
    """Read the WAL-aware database without checkpoints, migrations or writes."""
    cutoff = now - timedelta(days=14)
    deadline = time.monotonic() + 2
    with _snapshot(root) as db:
        try:
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
            observed_since = db.execute("SELECT min(observed_at) FROM items").fetchone()[0]
            observed_since = _time(observed_since).isoformat() if observed_since else None
            raw = db.execute("SELECT body FROM items WHERE published_at>=? "
                             "ORDER BY published_at DESC,id LIMIT ?",
                             (cutoff.isoformat(), _MAX_ROWS + 1)).fetchall()
        finally:
            db.set_progress_handler(None, 0)
    rows, invalid = [], 0
    for (body,) in raw[:_MAX_ROWS]:
        try:
            if not isinstance(body, str) or len(body) > 8000:
                raise ValueError("oversize_item")
            item = _validate_item(json.loads(body), now)
            if item["kind"] != "repository_discovered" and cutoff <= _time(item["published_at"]) <= now:
                rows.append(item)
        except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
            invalid += 1
    return rows, observed_since, invalid, len(raw) > _MAX_ROWS


def _fields(rows, repo_topics):
    fields, active = defaultdict(set), set()
    for row in rows:
        repo = row["repo"].casefold()
        active.add(repo)
        for topic in repo_topics.get(repo, row["topics"]):
            fields[_TOPICS.get(topic, topic)].add(repo)
    ranked = sorted(fields.items(), key=lambda pair: (-len(pair[1]), pair[0]))[:4]
    return {"active_repositories": len(active), "fields": [
        {"name": name, "repositories": len(repos)} for name, repos in ranked]}


def _related_updates(root, projects, now):
    """A repository push says the project changed, not who authored that change."""
    updates = []
    try:
        with _snapshot(root) as db:
            for project in projects[:2]:
                record = db.execute("SELECT body FROM repositories WHERE name=?",
                                    (project["repo"].casefold(),)).fetchone()
                if not record or len(record[0]) > 8000:
                    continue
                doc = json.loads(record[0])
                if (not isinstance(doc, dict) or doc.get("private") is not False or
                        doc.get("visibility", "public") != "public" or
                        str(doc.get("full_name", "")).casefold() != project["repo"].casefold()):
                    continue
                pushed = _time(doc.get("pushed_at"))
                if now - timedelta(days=14) <= pushed <= now:
                    updates.append({"repo": project["repo"], "url": project["url"], "pushed_at": pushed.isoformat()})
    except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError, RecursionError):
        pass
    return updates


def _spotlight(people, rows, now, root, fresh=True):
    if not people:
        return None
    # Equal rotation; all manual requests on one Korean date show the same person.
    person = people[now.astimezone(_KST).date().toordinal() % len(people)]
    login = person["login"]
    verification = person["verification"]
    affiliation = verification.get("affiliation", {})
    if not isinstance(affiliation, dict):
        affiliation = {}
    primary = affiliation.get("status") == "verified_primary_source"
    name = person.get("name") if isinstance(person.get("name"), str) else login
    topics = person.get("topics", [])
    topics = topics if isinstance(topics, list) else []
    fields = list(dict.fromkeys(_text(_TOPICS.get(t, t), 60) for t in topics if isinstance(t, str)))[:3]
    projects = verification.get("projects", [])
    projects = projects if isinstance(projects, list) else []
    major = []
    for project in projects:
        if isinstance(project, dict) and _REPO.fullmatch(str(project.get("repository", ""))):
            major.append({"repo": project["repository"], "relationship": _text(str(project.get("relationship", "")), 40),
                          "url": "https://github.com/" + project["repository"]})
    sources = affiliation.get("sources", [])
    sources = sources if isinstance(sources, list) else []
    source = next((_source(s) for s in sources if _source(s)), "https://github.com/" + login)
    checked = verification.get("checked_at", "")
    checked = checked if isinstance(checked, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", checked) else ""
    # Ownership/contribution is not evidence that this person authored another actor's work.
    activity = sorted((r for r in rows if r["actor"].casefold() == login.casefold()),
                      key=lambda row: (row["kind"] != "commit", row["kind"] != "release",
                                       -_time(row["published_at"]).timestamp()))
    chosen, seen = [], set()
    for row in activity:
        if row["repo"].casefold() not in seen:
            seen.add(row["repo"].casefold())
            chosen.append(row)
        if len(chosen) == 2:
            break
    return {"login": login, "name": _text(name, 100), "fields": fields,
            "profile_url": "https://github.com/" + login,
            "affiliation": _text(str(affiliation.get("current") or "미확인") if primary else
                                 str(affiliation.get("self_reported") or "미확인"), 200),
            "affiliation_primary": primary, "affiliation_source": source,
            "checked_at": checked, "major_repositories": major[:2], "recent_activity": chosen,
            "related_updates": _related_updates(root, major, now) if not chosen and fresh else [],
            "date": now.astimezone(_KST).date().isoformat()}


def read_briefing_context(project_path, *, now=None, activity=None):
    now = now or datetime.now(_UTC)
    if not project_path:
        return {}
    root = Path(project_path).expanduser().resolve()
    people, repo_topics = [], {}
    try:
        people, repo_topics = _targets(root)
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        pass
    rows, history = [], {"status": "missing", "window_days": 14}
    try:
        rows, observed_since, invalid, truncated = _history(root, now)
        status = "partial" if invalid or truncated else "ok"
        if activity and activity.get("status") not in {"ok", "partial", "baseline"}:
            status, rows = "stale", []
        history = {"status": status, "window_days": 14, "observed_since": observed_since,
                   "initial_records": sum(row["baseline"] for row in rows),
                   "rejected_items": invalid, "truncated": truncated, **_fields(rows, repo_topics)}
    except CollectorBusy:
        history["status"] = "busy"
    except FileNotFoundError:
        pass
    except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        history["status"] = "invalid"
    return {"two_week": history, "spotlight": _spotlight(people, rows, now, root,
            fresh=not activity or activity.get("status") in {"ok", "partial", "baseline"})}


def render_context(context, *, existing_text=""):
    history, person = context.get("two_week", {}), context.get("spotlight")
    if history.get("status") == "missing" and not person:
        return ""
    lines = []
    if history.get("status") in {"ok", "partial"}:
        fields = " · ".join(f"{_slack(f['name'])} {f['repositories']}개 repo" for f in history["fields"])
        lines.append("최근 2주 활동 분야(저장소 태그): " + (fields or "관측된 활동 없음"))
        since = history.get("observed_since")
        if since:
            lines.append(f"추적 시작 {_time(since).astimezone(_KST):%m/%d} · 과거 공개 기록 포함 · 분야 중복 집계")
        if history["status"] == "partial":
            lines.append("최근 2주 집계는 일부 기록만 포함합니다.")
    elif history.get("status") == "busy":
        lines.append("최근 2주 집계: 수집 중이라 이번 조회에서는 생략했습니다.")
    else:
        lines.append("최근 2주 집계: 저장 기록을 확인하지 못했습니다.")
    if not person:
        return "\n".join(lines)
    known = source_urls(existing_text)
    def link(url, label):
        if url in known:
            return _slack(label)
        known.add(url)
        return f"<{url}|{_slack(label)}>"
    lines.append("오늘의 계정: " + link(person["profile_url"], person["name"] + " (@" + person["login"] + ")"))
    affiliation = (person["affiliation"] + (" · " + person["checked_at"] + " 확인" if person["checked_at"] else ""))
    if not person["affiliation_primary"]:
        affiliation += " (GitHub 자기소개, 소속 미검증)" if person["affiliation"] != "미확인" else " (소속 미확인)"
    lines.append("연구/개발 분야: " + "·".join(_slack(f) for f in person["fields"]) + " / 소속: " +
                 link(person["affiliation_source"], affiliation))
    if person["major_repositories"]:
        labels = {"owner": "소유", "contributor": "기여", "lab_project": "연구실 프로젝트"}
        lines.append("주요 작업: " + ", ".join(link(p["url"], p["repo"]) +
                     " (" + labels.get(p["relationship"], "관련 저장소") + ")" for p in person["major_repositories"]))
    if person["recent_activity"]:
        for row in person["recent_activity"]:
            lines.append(f"최근 개발: {row['published_at'][:10]} {_slack(row['repo'])} — " +
                         link(row["url"], row["title"][:100]))
    else:
        lines.append("최근 개발: 수집 범위에서 최근 2주 본인 계정 활동은 확인되지 않았습니다.")
        for repo in person["related_updates"]:
            lines.append("관련 저장소: " + link(repo["url"], repo["repo"]) +
                         " · 마지막 push " + repo["pushed_at"][:10] + " (본인 작업 여부 미확인)")
    return "\n".join(lines)
