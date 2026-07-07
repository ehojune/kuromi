"""음성(TTS): edge-tts 로 합성 → PC 스피커 재생 / Slack 업로드.

VOICE_MODE 로 제어: off | local | slack | both
목소리/이름/캐릭터처럼 보이스도 .env(VOICE_NAME)만 바꾸면 교체된다.
"""
import asyncio
import os
import tempfile
import time

import edge_tts


class Voice:
    def __init__(self, mode: str, voice_name: str, max_chars: int):
        self.mode = mode
        self.voice_name = voice_name
        self.max_chars = max_chars

    async def speak(self, text, slack_client=None, channel=None, thread_ts=None):
        if self.mode == "off":
            return
        clip = (text or "").strip()[: self.max_chars]
        if not clip:
            return

        path = await self._synthesize(clip)
        try:
            if self.mode in ("local", "both"):
                # 재생은 블로킹이라 스레드로 넘긴다 (이벤트 루프를 막지 않도록).
                await asyncio.to_thread(self._play_local, path)
            if self.mode in ("slack", "both") and slack_client and channel:
                await slack_client.files_upload_v2(
                    channel=channel,
                    thread_ts=thread_ts,
                    file=path,
                    filename="kuromi.mp3",
                    title="🖤 음성",
                )
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    async def _synthesize(self, text: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".mp3", prefix="kuromi_")
        os.close(fd)
        await edge_tts.Communicate(text, self.voice_name).save(path)
        return path

    @staticmethod
    def _play_local(path: str):
        import pygame

        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        pygame.mixer.music.unload()  # 파일 핸들 해제 → 이후 삭제 가능
