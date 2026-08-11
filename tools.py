"""쿠로미의 커스텀 도구 (인프로세스 SDK MCP 서버로 등록됨).

지금은 화면 캡처 하나. 나중에 Notion/일정 같은 도구를 여기 추가하면 된다.
"""
import base64
import io

import mss
from PIL import Image

from claude_agent_sdk import tool

# 전송/토큰 절약을 위한 캡처 이미지 가로 상한
_MAX_WIDTH = 1280
# base64 페이로드 상한. brain.py 의 버퍼 상한보다 한참 아래로 잡아 여유를 둔다.
_MAX_PAYLOAD = 700_000
_QUALITY_STEPS = (75, 60, 45, 30)


@tool(
    "capture_screen",
    "사용자의 현재 화면(주 모니터)을 캡처해 이미지를 돌려준다. "
    "사용자가 화면/창/모니터에 보이는 것을 물어보면 먼저 이 도구를 호출해 확인할 것.",
    {},  # 입력 파라미터 없음
)
async def capture_screen(args):
    with mss.mss() as sct:
        monitor = sct.monitors[1]  # 0 은 전체 가상화면, 1 이 주 모니터
        shot = sct.grab(monitor)
        img = Image.frombytes("RGB", shot.size, shot.rgb)

    if img.width > _MAX_WIDTH:
        ratio = _MAX_WIDTH / img.width
        img = img.resize((_MAX_WIDTH, int(img.height * ratio)))

    # PNG 는 화면 내용에 따라 수 MB 까지 부풀어 SDK stdout 버퍼를 터뜨린다(2026-08-08 사고).
    # JPEG 로 고정하고, 그래도 크면 화질을 낮춰 상한 안에 밀어 넣는다.
    for quality in _QUALITY_STEPS:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        data = base64.standard_b64encode(buf.getvalue()).decode()
        if len(data) <= _MAX_PAYLOAD:
            break

    # MCP 이미지 콘텐츠 블록으로 반환 → 모델이 화면을 그대로 "본다".
    return {
        "content": [
            {"type": "image", "data": data, "mimeType": "image/jpeg"},
        ]
    }
