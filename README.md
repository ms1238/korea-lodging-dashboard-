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

방문객 수는 한국관광공사 데이터랩(`https://apis.data.go.kr/B551011/DataLabService`)의 광역·기초 지자체 일별 방문자 수에서 최근 365일 외지인·외국인을 합산합니다. 같은 키를 씁니다.

지도 지형(산 음영, 3D)은 AWS Terrain Tiles(Terrarium)를 씁니다.

## 구조

- `scripts/fetch.py` — 8개 API 전체를 `raw/*.jsonl`로 받습니다. 키는 환경변수 `DATA_GO_KR_KEY`에서만 읽습니다.
- `scripts/build.py` — 열 이름 통일, 좌표 변환(EPSG:5174 → WGS84), 시도·시군구 추출, 숙박업↔관광숙박업 중복 제거, 좌표 없는 야영장 제외 후 `site/data/`를 만듭니다.
- `site/` — 정적 웹페이지(MapLibre 지도, 광역·기초·읍면동·리·영업상태 드롭다운, 업종 소분류 필터, 비중·연도별 추이·지역 순위, 휴업·폐업 현황).
- `.github/workflows/update.yml` — 매일 03:17(KST) 수집 → 빌드 → GitHub Pages 배포.

## 처음 설정

1. Settings → Secrets and variables → Actions → New repository secret: 이름 `DATA_GO_KR_KEY`, 값은 공공데이터포털 일반 인증키.
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**.
3. Actions 탭 → "Update data and deploy" → Run workflow.

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
