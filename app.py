# app.py — Vanilla Trading Web Server
"""
웹 기반 트레이딩 대시보드 진입점.
uvicorn으로 FastAPI 서버를 실행합니다.

사용법:
    python app.py
    → http://localhost:8501 에서 접속
"""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

# 프로젝트 루트 sys.path 추가
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main():
    import uvicorn

    print()
    print("=" * 50)
    print("  Vanilla Trading - Web Dashboard")
    print("  http://localhost:8501")
    print("=" * 50)
    print()

    uvicorn.run(
        "web.server:app",
        host="0.0.0.0",
        port=8501,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[종료] 사용자가 서버를 종료했습니다.")
        sys.exit(0)
    except ImportError as e:
        print(f"\n[오류] 필요한 패키지가 없습니다: {e}")
        print("설치: pip install fastapi uvicorn[standard]")
        sys.exit(1)
