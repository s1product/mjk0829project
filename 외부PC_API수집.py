# -*- coding: utf-8 -*-
"""
마켓센싱 L1 수집 — 외부망 API 수집 스크립트
=================================================

용도
----
사내 보안정책상 API 직접 호출이 불가능한 환경(사내망)에서는 이 스크립트를 돌릴 수 없습니다.
이 스크립트는 "외부망(인터넷이 열려 있는 별도 PC)"에서 실행해서,
API 키가 필요한 5개 소스만 모아 호출하고, 결과를 표준 스키마의 JSON 파일 하나로 저장합니다.
그 JSON 파일을 사내로 옮겨(메일 첨부, 승인된 파일전송 등) Claude/워크스페이스에 업로드하면,
나머지 수집물(RSS·크롤링·키워드 웹검색 — 이건 사내에서 계속 처리 가능)과 병합해서 이어서 씁니다.

대상 5개 소스 (sources.json 기준)
----------------------------------
1. 한국은행 ECOS OpenAPI      — REP-25 (BSI·ESI, 필수 지정)
2. KOSIS(통계청) OpenAPI      — SITE-05 / SITE-13 / SITE-37
3. 국가법령정보센터 OpenAPI    — SITE-06 (입법예고 모니터링)
4. 네이버 데이터랩 API        — SITE-32 (검색어 트렌드)
5. 빅카인즈(BIGKinds) OpenAPI — KWD-01 보강용 (언론사 정형 뉴스 검색)

준비물
------
1. Python 3.8+  (외부 PC에 설치)
2. `pip install requests`
3. 같은 폴더의 `api_keys_설정.json`에 발급받은 키를 채워 넣기
   - 아직 키가 없는 항목은 그냥 빈 문자열("")로 두면 해당 소스는 자동으로 건너뜁니다.
   - 한국은행 ECOS 키는 이미 발급되어 있어 채워둔 상태입니다.

실행
----
    python 외부PC_API수집.py

결과
----
같은 폴더에 `외부API수집_YYYY-MM-DD.json` 파일이 생성됩니다.
이 파일을 사내로 반입해서 업로드해주시면 이어서 처리합니다.

주의
----
- ECOS의 BSI·ESI 통계표코드는 제가 문서상으로 추정한 값이라 [미검증]입니다.
  스크립트가 응답의 통계명(STAT_NAME)이 기대 키워드와 다르면 경고를 출력합니다.
  경고가 뜨면 https://ecos.bok.or.kr/api/ 에서 "통계표코드 검색"으로 정확한 코드를 찾아
  아래 ECOS_STAT_CODES 딕셔너리를 직접 수정해주세요.
- KOSIS는 소스별로 조회할 통계표(orgId/tblId)가 달라서, 예시 1건만 넣어뒀습니다.
  실제 필요한 통계표 ID는 kosis.kr에서 원하는 표를 찾은 뒤 "Open API" 버튼으로 확인할 수 있습니다.
- 국가법령정보센터·빅카인즈는 아직 키 발급 전이라고 하셔서 뼈대만 구현해뒀습니다.
  키 발급 후 api_keys_설정.json만 채우면 바로 동작합니다.
"""

import json
import os
import sys
import time
import datetime

try:
    import requests
except ImportError:
    print("[오류] requests 패키지가 없습니다. 먼저 'pip install requests'를 실행해주세요.")
    sys.exit(1)

# ------------------------------------------------------------------
# 0. 공통 설정
# ------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE = os.path.join(BASE_DIR, "api_keys_설정.json")
TODAY = datetime.date.today()
OUT_FILE = os.path.join(BASE_DIR, f"외부API수집_{TODAY.isoformat()}.json")

def load_keys():
    if not os.path.exists(KEYS_FILE):
        print(f"[오류] 설정 파일이 없습니다: {KEYS_FILE}")
        sys.exit(1)
    with open(KEYS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def make_record(dt, title, summary, source, url, category, track,
                 axis, source_id, collect_path, collect_method, is_required=False):
    """가이드 §7 출력 스키마에 맞춘 표준 레코드"""
    return {
        "dt": dt,
        "title": title,
        "summary": summary,
        "source": source,
        "url": url,
        "category": category,
        "track": track,
        "axis": axis,
        "source_id": source_id,
        "collect_path": collect_path,
        "collect_method": collect_method,
        "is_required": is_required,
    }


# ------------------------------------------------------------------
# 1. 한국은행 ECOS OpenAPI — BSI·ESI (REP-25, 필수)
# ------------------------------------------------------------------

# [미검증] 아래 코드가 정확한지 스크립트가 실행 시 STAT_NAME으로 자가 검증합니다.
ECOS_STAT_CODES = {
    "BSI": {"code": "512Y014", "cycle": "M", "item": "AA", "expect_kw": "업황"},
    "ESI": {"code": "513Y001", "cycle": "M", "item": "E1000", "expect_kw": "경제심리"},
}

def fetch_ecos(key):
    if not key:
        print("[건너뜀] ECOS_KEY 없음")
        return []
    records = []
    end = TODAY.strftime("%Y%m")
    start = (TODAY.replace(day=1) - datetime.timedelta(days=400)).strftime("%Y%m")  # 넉넉히 13개월치
    for name, cfg in ECOS_STAT_CODES.items():
        url = (
            f"https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/20/"
            f"{cfg['code']}/{cfg['cycle']}/{start}/{end}/{cfg['item']}"
        )
        try:
            r = requests.get(url, timeout=15)
            data = r.json()
        except Exception as e:
            print(f"[오류] ECOS {name} 호출 실패: {e}")
            continue

        rows = (data.get("StatisticSearch") or {}).get("row")
        if not rows:
            print(f"[경고] ECOS {name}: 응답에 데이터 없음 — 코드 확인 필요. 응답: {json.dumps(data, ensure_ascii=False)[:300]}")
            continue

        stat_name = rows[0].get("STAT_NAME", "")
        if cfg["expect_kw"] not in stat_name:
            print(f"[경고] ECOS {name}: 통계표코드가 다른 지표를 가리키는 것 같습니다 "
                  f"(응답 STAT_NAME='{stat_name}', 기대 키워드='{cfg['expect_kw']}'). "
                  f"ecos.bok.or.kr에서 정확한 통계표코드를 확인해 ECOS_STAT_CODES를 수정해주세요.")

        latest = rows[-1]
        records.append(make_record(
            dt=TODAY.isoformat(),
            title=f"한국은행 {stat_name} ({latest.get('TIME')})",
            summary=f"{stat_name} {latest.get('TIME')} 값: {latest.get('DATA_VALUE')} {latest.get('UNIT_NAME','')}".strip(),
            source="한국은행 ECOS",
            url="https://www.bok.or.kr",
            category="9. 경제지표",
            track="경제",
            axis="❸ 연구·전문보고서",
            source_id="REP-25",
            collect_path="B",
            collect_method="ECOS OpenAPI",
            is_required=True,
        ))
    return records


# ------------------------------------------------------------------
# 2. KOSIS(통계청) OpenAPI
# ------------------------------------------------------------------

# 실제로 필요한 통계표를 여기 리스트에 추가하세요.
# orgId/tblId는 kosis.kr에서 원하는 통계표를 찾은 뒤 "활용하기 > Open API"에서 확인합니다.
KOSIS_TABLES = [
    # 예시: 경찰청 범죄발생 통계 (실제 orgId/tblId는 확인 후 교체 필요 — [미확인])
    {"name": "경찰청 범죄통계(예시)", "source_id": "SITE-01", "orgId": "132", "tblId": "DT_13204_A001",
     "category": "6. 사회 이슈", "axis": "❶ 공공·정책"},
]

def fetch_kosis(key):
    if not key:
        print("[건너뜀] KOSIS_KEY 없음")
        return []
    records = []
    for tbl in KOSIS_TABLES:
        url = (
            "https://kosis.kr/openapi/Param/statisticsParameterData.do"
            f"?method=getList&apiKey={key}&itmId=ALL&objL1=ALL&format=json"
            f"&jsonVD=Y&prdSe=M&orgId={tbl['orgId']}&tblId={tbl['tblId']}&outputFields=NM+PRD_DE+DT"
        )
        try:
            r = requests.get(url, timeout=15)
            data = r.json()
        except Exception as e:
            print(f"[오류] KOSIS {tbl['name']} 호출 실패: {e}")
            continue
        if not isinstance(data, list) or not data:
            print(f"[경고] KOSIS {tbl['name']}: 데이터 없음 (orgId/tblId 확인 필요). 응답: {str(data)[:300]}")
            continue
        latest = data[-1]
        records.append(make_record(
            dt=TODAY.isoformat(),
            title=f"{tbl['name']} ({latest.get('PRD_DE','')})",
            summary=f"{latest.get('C1_NM', latest.get('NM',''))}: {latest.get('DT')}",
            source="통계청 KOSIS",
            url="https://kosis.kr",
            category=tbl["category"],
            track="",
            axis=tbl["axis"],
            source_id=tbl["source_id"],
            collect_path="A/B",
            collect_method="KOSIS OpenAPI",
        ))
    return records


# ------------------------------------------------------------------
# 3. 국가법령정보센터 OpenAPI — 입법예고 모니터링 (SITE-06)
# ------------------------------------------------------------------

def fetch_law(oc):
    if not oc:
        print("[건너뜀] LAW_OC 없음 (open.law.go.kr 가입 후 발급되는 이메일 ID 앞부분)")
        return []
    records = []
    # 입법예고 목록 조회 — target 값은 open.law.go.kr "활용가이드"에서 최신 스펙 재확인 필요 [미확인]
    url = f"http://www.law.go.kr/DRF/lawSearch.do?OC={oc}&target=lsi&type=JSON&display=20&sort=ddes"
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
    except Exception as e:
        print(f"[오류] 국가법령정보센터 호출 실패: {e}")
        return []
    items = data.get("LsiSearch", {}).get("lsi", []) if isinstance(data, dict) else []
    if isinstance(items, dict):
        items = [items]
    for it in items[:20]:
        records.append(make_record(
            dt=TODAY.isoformat(),
            title=it.get("lsiNm", "입법예고"),
            summary=f"소관부처: {it.get('minNm','')} / 예고기간: {it.get('lsiPstDt','')}",
            source="국가법령정보센터",
            url=it.get("lsiDetlLnkUrl", "https://www.law.go.kr"),
            category="7. 법령·규제",
            track="법령",
            axis="❶ 공공·정책",
            source_id="SITE-06",
            collect_path="A/B",
            collect_method="국가법령정보센터 OpenAPI",
        ))
    return records


# ------------------------------------------------------------------
# 4. 네이버 데이터랩 — 검색어 트렌드 (SITE-32)
# ------------------------------------------------------------------

# 조회할 키워드 그룹 — sources.json의 키워드 57종 중 대표 키워드로 채워 넣으세요.
NAVER_KEYWORD_GROUPS = [
    {"groupName": "무인매장", "keywords": ["무인매장", "무인점포"]},
    {"groupName": "AI CCTV", "keywords": ["AI CCTV", "지능형 영상관제"]},
]

def fetch_naver_datalab(client_id, client_secret):
    if not client_id or not client_secret:
        print("[건너뜀] 네이버 데이터랩 키 없음")
        return []
    end = TODAY.isoformat()
    start = (TODAY - datetime.timedelta(days=30)).isoformat()
    body = {
        "startDate": start,
        "endDate": end,
        "timeUnit": "week",
        "keywordGroups": NAVER_KEYWORD_GROUPS,
    }
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type": "application/json",
    }
    try:
        r = requests.post("https://openapi.naver.com/v1/datalab/search",
                           headers=headers, data=json.dumps(body), timeout=15)
        data = r.json()
    except Exception as e:
        print(f"[오류] 네이버 데이터랩 호출 실패: {e}")
        return []

    records = []
    for series in data.get("results", []):
        vals = series.get("data", [])
        if not vals:
            continue
        latest = vals[-1]
        records.append(make_record(
            dt=TODAY.isoformat(),
            title=f"네이버 검색어 트렌드 — {series.get('title')}",
            summary=f"{latest.get('period')} 기준 상대 검색량 지수: {latest.get('ratio')}",
            source="네이버 데이터랩",
            url="https://datalab.naver.com",
            category="6. 사회 이슈",
            track="트렌드",
            axis="❺ 트렌드 뉴스레터",
            source_id="SITE-32",
            collect_path="A/B",
            collect_method="네이버 데이터랩 API",
        ))
    return records


# ------------------------------------------------------------------
# 5. 빅카인즈(BIGKinds) OpenAPI — 뉴스 정형 검색 (KWD-01 보강)
# ------------------------------------------------------------------

BIGKINDS_KEYWORDS = ["무인매장", "AI CCTV", "정보보안관제"]  # 필요 키워드로 조정

def fetch_bigkinds(key):
    if not key:
        print("[건너뜀] 빅카인즈 키 없음")
        return []
    records = []
    end = TODAY.strftime("%Y-%m-%d")
    start = (TODAY - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    # 엔드포인트/파라미터명은 발급 시 제공되는 최신 가이드로 재확인 필요 [미확인]
    url = "https://tools.kinds.or.kr/search/news"
    for kw in BIGKINDS_KEYWORDS:
        body = {
            "access_key": key,
            "argument": {
                "query": kw,
                "published_at": {"from": start, "until": end},
                "sort": {"date": "desc"},
                "return_size": 10,
                "fields": ["title", "content", "provider_link_page", "provider", "published_at"],
            },
        }
        try:
            r = requests.post(url, json=body, timeout=15)
            data = r.json()
        except Exception as e:
            print(f"[오류] 빅카인즈 '{kw}' 호출 실패: {e}")
            continue
        docs = (((data.get("return_object") or {}).get("documents")) or [])
        for doc in docs:
            records.append(make_record(
                dt=doc.get("published_at", TODAY.isoformat())[:10],
                title=doc.get("title", ""),
                summary=(doc.get("content", "") or "")[:200],
                source=doc.get("provider", "빅카인즈"),
                url=doc.get("provider_link_page", ""),
                category="1. 업계 동향",
                track="",
                axis="❷ 미디어·뉴스",
                source_id="KWD-01",
                collect_path="A",
                collect_method="빅카인즈 OpenAPI",
            ))
    return records


# ------------------------------------------------------------------
# 메인
# ------------------------------------------------------------------

def main():
    keys = load_keys()
    all_records = []

    print("=== 한국은행 ECOS ===")
    all_records += fetch_ecos(keys.get("ECOS_KEY", ""))

    print("=== KOSIS ===")
    all_records += fetch_kosis(keys.get("KOSIS_KEY", ""))

    print("=== 국가법령정보센터 ===")
    all_records += fetch_law(keys.get("LAW_OC", ""))

    print("=== 네이버 데이터랩 ===")
    all_records += fetch_naver_datalab(keys.get("NAVER_CLIENT_ID", ""), keys.get("NAVER_CLIENT_SECRET", ""))

    print("=== 빅카인즈 ===")
    all_records += fetch_bigkinds(keys.get("BIGKINDS_KEY", ""))

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.datetime.now().isoformat(),
                   "count": len(all_records),
                   "records": all_records}, f, ensure_ascii=False, indent=2)

    print(f"\n총 {len(all_records)}건 수집 완료 → {OUT_FILE}")
    print("이 파일을 사내로 반입해 Claude/워크스페이스에 업로드해주세요.")


if __name__ == "__main__":
    main()
