# 전국 숙박시설 현황 대시보드

행정안전부 지방행정인허가 API 8종을 매일 자동으로 모아 전국 숙박·야영 시설을 지도와 차트로 보여줍니다.

| API | 업종 |
|---|---|
| `lodgings` | 숙박업 (소분류: 숙박업(생활)·일반 등) |
| `tourist_accommodations` | 관광숙박업 (소분류: 관광호텔업·호스텔업·소형호텔업 등) |
| `foreigner_city_homestays` | 외국인관광 도시민박업 |
| `rural_homestays` | 농어촌민박업 |
| `tourist_pensions` | 관광펜션업 |
| `hanok_experience` | 한옥체험업 |
| `general_campgrounds` | 일반야영장업 |
| `auto_campgrounds` | 자동차야영장업 |

주소 형식: `https://apis.data.go.kr/1741000/<API>/info`

관광 정보는 한국관광공사 TourAPI(`https://apis.data.go.kr/B551011/KorService2/areaBasedList2`)에서 관광지(12)·문화시설(14)·레포츠(28)를 받습니다. 같은 공공데이터포털 키를 씁니다.

방문객 수는 한국관광공사 데이터랩(`https://apis.data.go.kr/B551011/DataLabService`)의 광역·기초 지자체 일별 방문자 수를 2018년부터 받아 월별로 합칩니다. 수급 지표는 최근 12개월 외지인·외국인을 1년치로 환산하고, 추이 차트는 분기·연도별로 보여줍니다. 같은 키를 씁니다.

방한 외래관광객은 한국문화관광연구원 출입국관광통계(`https://apis.data.go.kr/B551940/EdrcntTourismStatsService`)에서 2018년부터 국적별 월별 입국자 수를 받습니다(전국 단위). 같은 키를 씁니다.

지도 지형(산 음영, 3D)은 AWS Terrain Tiles(Terrarium)를 씁니다.

## 구조

- `scripts/fetch.py` — 8개 API 전체를 `raw/*.jsonl`로 받습니다. 키는 환경변수 `DATA_GO_KR_KEY`에서만 읽습니다.
- `scripts/build.py` — 열 이름 통일, 좌표 변환(EPSG:5174 → WGS84), 시도·시군구 추출, 숙박업↔관광숙박업 중복 제거, 좌표 없는 야영장 제외 후 `site/data/`를 만듭니다.
- `site/` — 정적 웹페이지(MapLibre 지도, 광역·기초·읍면동·리·영업상태 드롭다운, 업종 소분류 필터, 비중·연도별 추이·지역 순위, 휴업·폐업 현황).
- `.github/workflows/update.yml` — 매일 03:17(KST) 수집 → 빌드 → GitHub Pages 배포.

## 화면 구성과 연구용 자료

탭은 관광 수용태세 영역별로 묶었습니다: 지역 진단(종합·지역 비교) · 관광 수요 · 숙박 공급 · 수급 균형 · 접근성 · 연계 자원(관광지·국립공원·축제·미식) · 정책 맥락(규제·지정과 검토 신호·도시민박) · 데이터·방법.

- `site/indicators.json` — 종합 지표의 정의(영역·신뢰 수준 A/B/C·산식·근거·쉬운 설명). 종합 탭과 `codebook.html`이 같은 파일을 읽으니 지표를 바꿀 때는 이 파일과 `app.js`의 `ovStats`(계산)를 함께 고칩니다.
- `site/data/download/panel_sgg.csv` — 시군구 × 연도 패널(2010년~지난해). 종합 탭의 '전체 시군구 CSV'는 현재 지표를 시군구별로 내려받습니다.
- 데이터·방법 탭의 공식 통계 대조는 문화체육관광부 「전국 관광숙박시설 현황」(공공데이터포털 3075666)을 씁니다. 공공데이터포털에서 이 데이터의 **활용신청**을 해야 `DATA_GO_KR_KEY`로 받아집니다(신청 전에는 건너뜀).
- `CITATION.cff` — GitHub의 'Cite this repository'. 월별 스냅샷에 DOI를 붙이려면(선택) zenodo.org 개인 토큰(deposit:write, deposit:actions)을 secret `ZENODO_TOKEN`으로 넣습니다. 첫 달에 새 레코드가 만들어지고 로그에 나온 레코드 번호를 variable `ZENODO_DEPOSITION`에 넣으면 다음 달부터 같은 DOI의 새 버전이 됩니다. 라이선스는 variable `ZENODO_LICENSE`(예: `cc-by-4.0`), 저자명은 `ZENODO_CREATOR`. `ZENODO_API=https://sandbox.zenodo.org/api`로 먼저 시험할 수 있습니다(`scripts/zenodo.py`).

## 앱(PWA) '숙박관광 대시보드'

사이트가 설치형 웹앱입니다. 안드로이드·PC 크롬/엣지는 머리말의 '앱으로 설치' 단추(또는 주소창 설치 아이콘), iPhone·iPad는 Safari 공유 단추 → '홈 화면에 추가'.

- `site/manifest.webmanifest` — 앱 이름·아이콘·색. `id`는 바꾸지 마세요(설치된 앱의 신원).
- `site/sw.js` — 한 번 연 화면과 자료를 저장해 오프라인에서도 열림(자료는 온라인이면 늘 새로 받음). 배포 때 워크플로가 `__BUILD__`에 커밋을 넣어 새 버전으로 바뀝니다. 지도 타일과 CSV 내려받기는 저장하지 않습니다.
- `site/pwa.js` — 서비스 워커 등록, 설치 단추, iPhone 안내. `site/icons/` — 아이콘(원본 `icon.svg`, 안드로이드 둥근 마스크용 `maskable.svg`).

상용화(스토어 등록) 전에 정할 것:
1. **도메인**: 설치된 앱은 주소(origin)에 묶여, 나중에 도메인을 옮기면 사용자가 다시 설치해야 합니다. 상용화하려면 자체 도메인을 먼저 정하세요.
2. **Google Play(TWA)**: PWABuilder나 Bubblewrap으로 이 PWA를 감쌉니다. 도메인 루트에 `/.well-known/assetlinks.json`이 있어야 해서 지금 주소(`ms1238.github.io/korea-lodging-dashboard-/`)로는 어렵고 자체 도메인이 필요합니다. 개발자 등록비, 개인정보처리방침 URL, 신규 개인 계정의 비공개 테스트 요건은 등록 시점 정책을 확인하세요.
3. **App Store**: 웹을 감싸기만 한 앱은 심사(최소 기능 기준)에서 거절되기 쉬워, 알림·즐겨찾기 지역 같은 앱 전용 기능을 먼저 갖추는 편이 낫습니다.
4. **자료 이용 조건**: 공공누리 1유형(출처 표시)은 상업 이용이 됩니다. VWorld(페이지에 키가 노출됨), 지도 타일(OpenFreeMap), 한국관광공사 데이터랩·TourAPI는 상업 서비스 조건을 각각 확인하세요.

## 처음 설정

1. Settings → Secrets and variables → Actions → New repository secret: 이름 `DATA_GO_KR_KEY`, 값은 공공데이터포털 일반 인증키.
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**.
3. Actions 탭 → "Update data and deploy" → Run workflow. 새로 활용신청한 API처럼 **빠진 자료만** 받으려면 'only_missing'을 켜고 실행하세요(다른 API의 하루 호출 한도를 다시 쓰지 않음).

## 로컬 실행

```bash
pip install -r requirements.txt
DATA_GO_KR_KEY=... python scripts/fetch.py
python scripts/build.py
python -m http.server -d site 8000
```

## 처리 규칙

- 영업 상태: `SALS_STTS_NM`/`DTL_SALS_STTS_NM` 기준으로 영업·휴업·폐업(취소·말소 포함)으로 나눕니다.
- 중복: 숙박업 레코드가 관광숙박업 레코드와 도로명(또는 지번) 주소가 같고 상호가 비슷하면 숙박업 쪽을 뺍니다. 제거 건수와 예시는 `site/data/meta.json`의 `dedupe`에 남습니다.
- 좌표: 야영장은 좌표가 없으면 제외합니다. 나머지 업종은 같은 시군구·동의 중앙 위치로 대신하고, 그마저 없으면 통계에만 넣고 지도에서는 뺍니다.
- 읍·면·동과 리: 지번 주소의 법정동·법정리 기준(도로명 주소만 있으면 괄호 속 동이나 읍·면). 행정동과 다를 수 있습니다.
- 지역: 주소 첫 두 단어로 시도·시군구를 정하고, 옛 명칭(강원도·전라북도, 광주광역시·전라남도→전남광주통합특별시)을 통일합니다. 일반구는 시 단위로 묶습니다.
