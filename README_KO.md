# Investment Committee Copilot v0.3.0

금융 컨설턴트용 로컬 Investment Committee 의사결정 지원 앱입니다.

## v0.3.0 핵심: LOCAL / HYBRID / CLOUD

### LOCAL — 기본값, OpenAI API 비용 0원
- LLM 추론: **LM Studio의 로컬 모델**
- 시장 스냅샷/Quant: 노트북의 Python + Yahoo Finance
- 고객 DB: 로컬 SQLite
- OpenAI API key/크레딧: **사용하지 않음**
- Macro는 Yahoo Finance 벤치마크의 최근 수익률/변동성/드로다운만 보고 판단합니다.
- Product는 앱에 포함된 작은 고정 카탈로그와 고객의 기존 보유종목 안에서만 고릅니다.
- Fact Checker는 웹 검증이 아니라 **로컬 일관성 검사**이므로 외부 상품 구조/세금/법규는 사람 확인이 필요합니다.

### HYBRID — API 비용 절감 + 웹 검증
- Macro / Product / Fact Check: OpenAI + 웹 리서치
- Suitability / Bear / Compliance / CIO: 로컬 모델
- Quant / DB: 로컬

### CLOUD
- 기존처럼 전체 AI 위원회를 OpenAI API로 실행합니다.

## 이 노트북에 권장하는 LOCAL 모델
현재 사양(16GB RAM, Intel Arc 내장 GPU) 기준 권장값:
- **Qwen3 8B**
- GGUF **Q4_K_M**
- Context length: **8192**
- 한 번에 모델 하나만 로드
- 니케 등 게임은 LOCAL 투자위원회 실행 전에 종료 권장

## LOCAL AI 설치
앱의 `설정` 메뉴에서 **LOCAL AI 설치/준비 도우미**를 누르거나, 폴더의 `LOCAL_AI_SETUP.bat`을 더블클릭합니다.

1. LM Studio가 없으면 공식 다운로드 페이지를 엽니다.
2. LM Studio 설치 후 **한 번 실행**합니다.
3. `LOCAL_AI_SETUP.bat`을 다시 실행하면 Qwen3 8B Q4_K_M 다운로드를 시도합니다.
4. 모델을 `investment-local`이라는 ID로 로드하고 로컬 서버(`127.0.0.1:1234`) 시작을 시도합니다.
5. 앱 → 설정 → `LOCAL` → `로컬 AI 연결 확인` → 모델 선택 → `AI 엔진 설정 저장`.

자동 모델 다운로드/로드가 PC 환경에 따라 실패하면 LM Studio에서 수동으로:
- Discover: `qwen3 8b`
- 4-bit/Q4_K_M GGUF 선택
- Load context 8192
- Developer → Start server

## 실제 분석 흐름
1. Macro Agent
2. Product Agent
3. Suitability Agent
4. Python Local Quant Constructor — C1/C2/C3 비중 계산
5. Python Quant Validator — 수익률/변동성/Sharpe/MDD/VaR/CVaR/위험기여
6. Bear Agent
7. Fact Checker
8. Compliance Agent
9. CIO — 이미 계산된 C1/C2/C3 중 하나만 선택
10. Guardrail — FAIL/Quant 실패 시 HUMAN_REVIEW_REQUIRED

LOCAL 모드에서는 7개의 에이전트가 **7개 모델을 동시에 띄우는 것이 아닙니다.** 로컬 모델 하나를 역할별로 순차 호출하므로 16GB 시스템에서도 운용 가능성을 높였습니다.

## Windows 시작
1. `START_HERE.bat` 실행
2. 브라우저에서 앱 열림
3. `설정`에서 AI 모드 선택
4. `고객 & 분석`에서 고객 프로필/현재 포트폴리오 입력
5. `투자위원회 실행`

## 고객정보/보안
- 실명·주민번호·계좌번호 대신 Client Code 사용 권장
- 고객 DB와 분석 기록은 `data/`에 로컬 저장
- LOCAL 모드의 LLM 요청은 기본적으로 `localhost`의 LM Studio로 전송
- API key는 앱 DB가 아니라 Windows Credential Manager 사용
- 자동매매/주문 전송 기능 없음

## LOCAL 모드의 중요한 한계
LOCAL은 **무료라고 해서 CLOUD와 같은 정보 범위를 가진 것은 아닙니다.**
- OpenAI 웹검색 없음
- 뉴스/공시/금리/세금의 실시간 외부 사실검증 없음
- 현재 버전의 시장환경 입력은 Yahoo Finance 가격 기반 스냅샷 중심
- 고객에게 공식 추천을 전달하기 전 상품 구조, 세금, 규정, 최신 공시는 사람이 승인된 정보원으로 재확인해야 함

향후 DART/FRED 등 무료/공식 데이터 소스를 LOCAL Research Pack에 추가할 수 있습니다.

## 업데이트
`data/`와 Windows Credential Manager의 API key는 업데이트에서 보존됩니다.
GitHub update manifest를 통해 앱 내 `업데이트 확인 → 지금 업데이트`를 사용합니다.

## 개발자 테스트
```bash
python -m compileall .
pytest -q
python scripts/schema_preflight.py
```
