"""회사/기관 TLS 검사 프록시 뒤에서도 HTTPS 가 되게 만든다.

이 PC 는 HTTPS 를 가로채는 보안 프록시 뒤에 있어서, 파이썬 기본 인증서(certifi)로는
인증서 검증이 실패한다. truststore 로 Windows 인증서 저장소(=IT 가 심어둔 회사 CA 포함)를
쓰게 하면 aiohttp(Slack/PubMed)·httpx(Notion) 모두 통과한다.

프로세스 시작 시 가장 먼저 import 되도록 배치할 것.
"""
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass
