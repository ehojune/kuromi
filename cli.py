"""claude CLI 위치 보장.

Claude Agent SDK 는 내부에서 `claude` 실행파일을 PATH 에서 찾아 띄운다.
표준 설치(`claude` on PATH)가 있으면 그걸 쓰고,
없으면 이 PC 의 Claude 데스크톱 앱에 번들된 exe 를 찾아 PATH 에 임시로 얹어준다.
(번들 경로는 버전마다 바뀌므로 가장 최근 수정된 것을 고른다.)
"""
import glob
import os
import shutil


def ensure_claude_on_path() -> str | None:
    found = shutil.which("claude")
    if found:
        return found

    appdata = os.environ.get("APPDATA", "")
    pattern = os.path.join(appdata, "Claude", "claude-code", "*", "claude.exe")
    candidates = glob.glob(pattern)
    if not candidates:
        return None

    exe = max(candidates, key=os.path.getmtime)  # 가장 최근 버전
    os.environ["PATH"] = os.path.dirname(exe) + os.pathsep + os.environ.get("PATH", "")
    return exe
