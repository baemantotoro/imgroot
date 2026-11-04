#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Daily Insight v3 — 주식·뉴스·날씨·운세 수집기"""

import os, sys, json, re, time
import urllib.request, urllib.parse
import subprocess
from datetime import datetime, timedelta

def ensure(pkg, mod=None):
    try: __import__(mod or pkg)
    except ImportError:
        print(f"  [설치] {pkg}")
        subprocess.check_call([sys.executable,"-m","pip","install",pkg,"--break-system-packages","-q"])

ensure("yfinance"); ensure("feedparser"); ensure("deep-translator","deep_translator")

import yfinance as yf
import feedparser

# ── 설정 로드 ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("OUT_DIR") or SCRIPT_DIR
os.makedirs(OUT_DIR, exist_ok=True)
cfg = {}
try:
    with open(os.path.join(SCRIPT_DIR,"config.env"),encoding="utf-8") as f:
        for line in f:
            s=line.strip()
            if s and not s.startswith("#") and "=" in s:
                k,v=s.split("=",1); cfg[k.strip()]=v.strip()
except FileNotFoundError: print("  [경고] config.env 없음 (환경변수 사용)")
# 클라우드(GitHub Actions) 실행: 환경변수가 있으면 우선 적용
for _k in ("NAVER_CLIENT_ID","NAVER_CLIENT_SECRET","KMA_API_KEY","GITHUB_REPO","GITHUB_BRANCH"):
    if os.environ.get(_k): cfg[_k]=os.environ[_k]
if os.environ.get("GH_PAT"): cfg["GITHUB_TOKEN"]=os.environ["GH_PAT"]
elif os.environ.get("GITHUB_TOKEN") and not cfg.get("GITHUB_TOKEN"): cfg["GITHUB_TOKEN"]=os.environ["GITHUB_TOKEN"]

NAVER_ID  = cfg.get("NAVER_CLIENT_ID","")
NAVER_SEC = cfg.get("NAVER_CLIENT_SECRET","")
KMA_KEY   = cfg.get("KMA_API_KEY","")

# ── 수집 대상 ──────────────────────────────────────────────────────────────────
KR_STOCKS  = {"삼성전자":"005930","SK하이닉스":"000660"}
KR_INDICES = {"KOSPI":"1001","KOSDAQ":"2001"}
US_TICKERS = {"S&P500":"^GSPC","나스닥":"^IXIC","엔비디아":"NVDA","TSMC":"TSM","SOXX":"SOXX","SMH":"SMH"}
NAVER_STOCK_KW = ["삼성전자 반도체","SK하이닉스 HBM","코스피 코스닥","반도체 수출"]
GOOGLE_STOCK_KW = ["Samsung+Electronics+semiconductor","SK+Hynix+HBM+memory","semiconductor+market"]
# 직접 RSS (검증된 URL)
PAPERS_RSS = {
    "경향신문":    "http://www.khan.co.kr/rss/rssdata/total_news.xml",
    "한겨레":      "http://www.hani.co.kr/rss/",
    "노컷뉴스":    "http://rss.nocutnews.co.kr/nocutnews.xml",
    "전자신문":    "http://rss.etnews.com/Section901.xml",
    "보안뉴스":    "https://www.boannews.com/media/news_rss.asp",
    "디지털타임스":"http://www.dt.co.kr/rss/allArticle.xml",
}
# 네이버 뉴스 API fallback (RSS 실패 시 자동 전환)
PAPERS_RSS_FALLBACK = {"전자신문", "보안뉴스", "디지털타임스"}
# 네이버 API 전용 (직접 RSS 없는 언론사)
PAPERS_NAVER = ["중앙일보", "지디넷"]
INTEREST_KW = {
    "IT 신기술·동향":    "IT 신기술 AI 동향",
    "ISMS-P":           "ISMS-P 정보보호관리체계",
    "정보보안·사이버보안":"정보보안 사이버보안 해킹",
    "SW 취약점 진단":   "소프트웨어 보안취약점 취약점진단",
    "정보관리기술사":   "정보관리기술사",
    "정보시스템감리사": "정보시스템감리사",
}

# ── 유틸 ───────────────────────────────────────────────────────────────────────
def strip_html(t): return re.sub(r"<[^>]+>","",t or "").strip()
def fd(s,n=16): return (s or "")[:n]

def prev_day():
    t=datetime.now(); d={0:3,5:1,6:2}.get(t.weekday(),1)
    return (t-timedelta(days=d)).strftime("%Y%m%d")

# ── 데이터 수집 ────────────────────────────────────────────────────────────────
def get_kr():
    """한국 주식·지수: yfinance 사용 (pykrx 로그인 불필요)"""
    # 개별 종목: 005930.KS (삼성전자), 000660.KS (SK하이닉스)
    KR_YF = {"삼성전자":"005930.KS","SK하이닉스":"000660.KS"}
    # 지수: ^KS11 (KOSPI), ^KQ11 (KOSDAQ)
    KR_IDX_YF = {"KOSPI":"^KS11","KOSDAQ":"^KQ11"}
    out={}
    for name,tk in {**KR_YF,**KR_IDX_YF}.items():
        try:
            h=yf.Ticker(tk).history(period="2d")
            if len(h)>=2:
                p,l=float(h["Close"].iloc[-2]),float(h["Close"].iloc[-1])
                chg=round((l-p)/p*100,2)
                out[name]={"ticker":tk,"close":round(l,2),"change_pct":chg,"date":h.index[-1].strftime("%Y-%m-%d")}
            elif len(h)==1:
                out[name]={"ticker":tk,"close":round(float(h["Close"].iloc[-1]),2),"change_pct":None,"date":h.index[-1].strftime("%Y-%m-%d")}
            else:
                out[name]={"ticker":tk,"error":"데이터없음"}
        except Exception as e:
            out[name]={"ticker":tk,"error":str(e)[:50]}
    return out

def get_us():
    out={}
    for name,tk in US_TICKERS.items():
        try:
            h=yf.Ticker(tk).history(period="2d")
            if len(h)>=2:
                p,l=float(h["Close"].iloc[-2]),float(h["Close"].iloc[-1])
                out[name]={"ticker":tk,"close":round(l,2),"change_pct":round((l-p)/p*100,2),"date":h.index[-1].strftime("%Y-%m-%d")}
            elif len(h)==1:
                out[name]={"ticker":tk,"close":round(float(h["Close"].iloc[-1]),2),"change_pct":None,"date":h.index[-1].strftime("%Y-%m-%d")}
            else: out[name]={"ticker":tk,"error":"데이터없음"}
        except Exception as e: out[name]={"ticker":tk,"error":str(e)[:50]}
    return out

def naver_news(query,n=5):
    if not NAVER_ID: return [{"title":"API키 미설정","link":"","pub_date":"","desc":""}]
    url="https://openapi.naver.com/v1/search/news.json?"+urllib.parse.urlencode({"query":query,"display":n,"sort":"date"})
    req=urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id",NAVER_ID); req.add_header("X-Naver-Client-Secret",NAVER_SEC)
    try:
        with urllib.request.urlopen(req,timeout=10) as r:
            data=json.loads(r.read().decode("utf-8"))
        return [{"title":strip_html(i["title"]),"link":i.get("originallink") or i["link"],
                 "pub_date":fd(i.get("pubDate","")),"desc":strip_html(i.get("description","")),"lang":"ko"} for i in data.get("items",[])]
    except Exception as e: return [{"title":f"오류:{e}","link":"","pub_date":"","desc":""}]

def google_news(query,n=5):
    url=f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    try:
        feed=feedparser.parse(url)
        arts=[]
        for e in feed.entries[:n]:
            t=e.get("title",""); src_name=e.get("source",{}).get("title","")
            arts.append({"title":t,"title_ko":translate_ko(t),"link":e.get("link",""),
                         "pub_date":fd(e.get("published","")),"source":src_name,"lang":"en"})
        return arts
    except Exception as e: return [{"title":f"Error:{e}","title_ko":"","link":"","pub_date":"","source":"","lang":"en"}]

def naver_news_by_paper(paper_name, n=15):
    """네이버 뉴스 API로 특정 언론사 최신 기사 검색 (sort=date)"""
    return naver_news(f'"{paper_name}"', n)

def get_exchange_and_gold():
    """yfinance로 달러·엔화 환율 + 금 시세 수집 (살때/팔때 + 5일 추이)"""
    result = {}
    SPREAD      = 0.0175  # 한국 시중은행 현찰 스프레드 ±1.75%
    GOLD_SPREAD = 0.05    # 금 스프레드 ±5%

    def history5(ticker, multiplier=1):
        """5일 종가 리스트 반환 [{date, close}, ...]"""
        try:
            h = yf.Ticker(ticker).history(period="7d")  # 휴장일 감안 7d 요청
            rows = []
            for dt, row in h.iterrows():
                rows.append({
                    "date":  dt.strftime("%m/%d"),
                    "close": round(float(row["Close"]) * multiplier, 2),
                })
            return rows[-5:] if len(rows) >= 5 else rows  # 최근 5거래일
        except Exception:
            return []

    # ── 달러(USD/KRW) ────────────────────────────────────────────────────────
    try:
        hist = history5("USDKRW=X")
        mid  = hist[-1]["close"] if hist else None
        if mid:
            result['usd'] = {
                'label':   '달러(1$)',
                'current': round(mid),
                'buy':     round(mid * (1 + SPREAD)),
                'sell':    round(mid * (1 - SPREAD)),
                'history': [{"date": r["date"], "close": round(r["close"])} for r in hist],
            }
        else:
            result['usd'] = {'label': '달러(1$)', 'error': '데이터없음', 'history': []}
    except Exception as e:
        result['usd'] = {'label': '달러(1$)', 'error': str(e)[:50], 'history': []}

    # ── 엔화(JPY/KRW, 100엔 단위) ────────────────────────────────────────────
    try:
        hist = history5("JPYKRW=X", multiplier=100)
        mid  = hist[-1]["close"] if hist else None
        if mid:
            result['jpy'] = {
                'label':   '엔화(100¥)',
                'current': round(mid, 2),
                'buy':     round(mid * (1 + SPREAD), 2),
                'sell':    round(mid * (1 - SPREAD), 2),
                'history': [{"date": r["date"], "close": round(r["close"], 2)} for r in hist],
            }
        else:
            result['jpy'] = {'label': '엔화(100¥)', 'error': '데이터없음', 'history': []}
    except Exception as e:
        result['jpy'] = {'label': '엔화(100¥)', 'error': str(e)[:50], 'history': []}

    # ── 금(GC=F → KRW 환산, 1돈=3.75g) ─────────────────────────────────────
    try:
        usd_mid  = result.get('usd', {}).get('current')
        gold_hist_usd = history5("GC=F")
        if gold_hist_usd and usd_mid:
            def to_don(usd_oz): return round(usd_oz / 31.1035 * usd_mid * 3.75 / 1000) * 1000
            last_don = to_don(gold_hist_usd[-1]["close"])
            result['gold'] = {
                'label':   '금(1돈·3.75g)',
                'buy':     round(last_don * (1 + GOLD_SPREAD) / 1000) * 1000,
                'sell':    round(last_don * (1 - GOLD_SPREAD) / 1000) * 1000,
                'history': [{"date": r["date"], "close": to_don(r["close"])} for r in gold_hist_usd],
            }
        else:
            result['gold'] = {'label': '금(1돈)', 'error': '데이터없음', 'history': []}
    except Exception as e:
        result['gold'] = {'label': '금(1돈)', 'error': str(e)[:50], 'history': []}
    return result

def fetch_rss(url,n=10):
    try:
        feed=feedparser.parse(url)
        arts=[{"title":strip_html(e.get("title","")),"link":e.get("link",""),
               "pub_date":fd(e.get("published",e.get("updated",""))),"lang":"ko"} for e in feed.entries[:n]]
        return arts if arts else [{"title":"기사없음","link":"","pub_date":""}]
    except Exception as e: return [{"title":f"RSS오류:{e}","link":"","pub_date":""}]


# ── HTML 이스케이프 ─────────────────────────────────────────────────────────────
def html_esc(s):
    return (s or "").replace("&","&amp;").replace('"',"&quot;").replace("<","&lt;").replace(">","&gt;")

# ── 영어→한국어 번역 ────────────────────────────────────────────────────────────
_translator = None
def translate_ko(text):
    global _translator
    if not text: return ""
    try:
        from deep_translator import GoogleTranslator
        if _translator is None:
            _translator = GoogleTranslator(source="en", target="ko")
        result = _translator.translate(text[:4900])
        return result or text
    except Exception:
        return text

# ── 날씨 수집 (기상청 단기예보 + Open-Meteo fallback) ─────────────────────────
SKY_LABEL = {"1":"맑음","3":"구름많음","4":"흐림"}
PTY_LABEL = {"0":"","1":"🌧️비","2":"🌨️비/눈","3":"❄️눈","4":"🌦️소나기"}
PTY_ALERT = {"1","2","3","4"}

# Open-Meteo WMO 날씨코드 → 한국어 레이블 + 강수여부
_OM_SKY = {
    0:"맑음",1:"대체로 맑음",2:"구름많음",3:"흐림",
    45:"안개",48:"안개",
    51:"이슬비",53:"이슬비",55:"이슬비",
    61:"🌧️비",63:"🌧️비",65:"🌧️비",
    71:"❄️눈",73:"❄️눈",75:"❄️눈",77:"❄️눈",
    80:"🌦️소나기",81:"🌦️소나기",82:"🌦️소나기",
    95:"⛈️뇌우",96:"⛈️뇌우",99:"⛈️뇌우",
}
_OM_ALERT = {61,63,65,71,73,75,77,80,81,82,95,96,99,51,53,55}

def _get_weather_openmeteo(lat=37.648, lon=127.047):
    """Open-Meteo fallback: 키 없음, 해외 IP 허용, 무제한"""
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=temperature_2m,precipitation_probability,weathercode,windspeed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,weathercode"
        "&timezone=Asia%2FSeoul&forecast_days=3"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error":f"Open-Meteo 오류: {e}","hourly":[],"daily":[],"alert":False,"source":"open-meteo"}

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # 시간별: 오늘 06~21시 3시간 간격
    target_hours = {"06","09","12","15","18","21"}
    hourly = []
    times  = d["hourly"]["time"]
    tmp2m  = d["hourly"]["temperature_2m"]
    pop    = d["hourly"]["precipitation_probability"]
    wcode  = d["hourly"]["weathercode"]
    wsd    = d["hourly"]["windspeed_10m"]
    for i, t in enumerate(times):
        if not t.startswith(today_str): continue
        hh = t[11:13]
        if hh not in target_hours: continue
        code = int(wcode[i])
        sky_label = _OM_SKY.get(code, "")
        is_rain = "🌧️" in sky_label or "❄️" in sky_label or "🌦️" in sky_label or "⛈️" in sky_label
        hourly.append({
            "time": hh+"시",
            "tmp": str(round(tmp2m[i]))+"°",
            "sky": "" if is_rain else sky_label,
            "pty": sky_label if is_rain else "",
            "pop": str(int(pop[i])),
            "wsd": str(round(wsd[i],1)),
            "alert": code in _OM_ALERT,
        })

    # 일별
    daily = []
    for i, dt in enumerate(d["daily"]["time"]):
        m, day = int(dt[5:7]), int(dt[8:10])
        code = int(d["daily"]["weathercode"][i])
        sky_label = _OM_SKY.get(code, "")
        is_rain = code in _OM_ALERT
        daily.append({
            "date": f"{m}/{day}",
            "tmn": str(round(d["daily"]["temperature_2m_min"][i]))+"°",
            "tmx": str(round(d["daily"]["temperature_2m_max"][i]))+"°",
            "sky": "" if is_rain else sky_label,
            "pty": sky_label if is_rain else "",
            "alert": is_rain,
        })

    has_alert = any(h["alert"] for h in hourly)
    return {"hourly":hourly,"daily":daily,"alert":has_alert,"error":None,"source":"open-meteo"}

def get_base_time(now):
    """기상청 발표시각: 02,05,08,11,14,17,20,23시"""
    bases=[2,5,8,11,14,17,20,23]
    h=now.hour
    bt=bases[0]
    for b in bases:
        if h>=b: bt=b
    return f"{bt:02d}00"

def get_weather(nx=61, ny=130):
    if not KMA_KEY:
        print("  [날씨] KMA_API_KEY 미설정 → Open-Meteo fallback 사용")
        return _get_weather_openmeteo()

    now=datetime.now()
    base_date=now.strftime("%Y%m%d")
    base_time=get_base_time(now)
    url=("http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst"
         "?serviceKey="+KMA_KEY
         +"&numOfRows=1000&pageNo=1&dataType=JSON"
         +f"&base_date={base_date}&base_time={base_time}"
         +f"&nx={nx}&ny={ny}")
    items = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                raw=json.loads(r.read().decode("utf-8"))
            rc = raw.get("response",{}).get("header",{}).get("resultCode","")
            if rc not in ("00",""):
                msg = raw["response"]["header"].get("resultMsg","API오류")
                return {"error":f"KMA API 오류 ({rc}): {msg}","hourly":[],"daily":[],"alert":False}
            items=raw["response"]["body"]["items"]["item"]
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                if attempt < 2:
                    print(f"  [날씨] KMA 429 한도초과, {60}초 후 재시도 ({attempt+1}/3)...")
                    time.sleep(60)
                    continue
                # 3회 모두 실패 → Open-Meteo fallback
                print("  [날씨] KMA 429 재시도 실패 → Open-Meteo fallback 사용")
                return _get_weather_openmeteo()
            # 429 외 HTTP 오류도 fallback
            print(f"  [날씨] KMA HTTP {e.code} 오류 → Open-Meteo fallback 사용")
            return _get_weather_openmeteo()
        except Exception as e:
            print(f"  [날씨] KMA 오류 ({e}) → Open-Meteo fallback 사용")
            return _get_weather_openmeteo()
    if items is None:
        print("  [날씨] KMA 데이터 없음 → Open-Meteo fallback 사용")
        return _get_weather_openmeteo()

    # 카테고리별로 (fcstDate,fcstTime) → 값 매핑
    grid={}
    for it in items:
        key=(it["fcstDate"],it["fcstTime"])
        if key not in grid: grid[key]={}
        grid[key][it["category"]]=it["fcstValue"]

    today_str=now.strftime("%Y%m%d")
    hourly=[]
    daily_tmp={}  # date → {tmn,tmx,sky,pty}

    for (fd_,ft_),v in sorted(grid.items()):
        # 일별 최저·최고
        if fd_ not in daily_tmp: daily_tmp[fd_]={"tmn":None,"tmx":None,"sky":[],"pty":[]}
        if "TMN" in v: daily_tmp[fd_]["tmn"]=v["TMN"]
        if "TMX" in v: daily_tmp[fd_]["tmx"]=v["TMX"]
        if "SKY" in v: daily_tmp[fd_]["sky"].append(v["SKY"])
        if "PTY" in v and v["PTY"]!="0": daily_tmp[fd_]["pty"].append(v["PTY"])

        # 오늘 시간별 (3시간 간격)
        if fd_==today_str and ft_ in {"0600","0900","1200","1500","1800","2100","0000"}:
            pty=v.get("PTY","0")
            hourly.append({
                "time":ft_[:2]+"시",
                "tmp":v.get("TMP","?")+"°",
                "sky":SKY_LABEL.get(v.get("SKY",""),""),
                "pty":PTY_LABEL.get(pty,""),
                "pop":v.get("POP","?"),
                "wsd":v.get("WSD","?"),
                "alert":pty in PTY_ALERT,
            })

    daily=[]
    for d,dv in sorted(daily_tmp.items()):
        sky_list=dv["sky"]
        dominant_sky=max(set(sky_list),key=sky_list.count) if sky_list else ""
        pty_list=dv["pty"]
        dominant_pty=max(set(pty_list),key=pty_list.count) if pty_list else "0"
        tmn=dv["tmn"] or "?"
        tmx=dv["tmx"] or "?"
        label=f"{int(d[4:6])}/{int(d[6:8])}"
        daily.append({
            "date":label,
            "tmn":str(tmn)+"°",
            "tmx":str(tmx)+"°",
            "sky":SKY_LABEL.get(dominant_sky,""),
            "pty":PTY_LABEL.get(dominant_pty,""),
            "alert":dominant_pty in PTY_ALERT,
        })

    # 경고는 오늘 시간별 예보만 기준 (내일 이후 비 예보는 포함하지 않음)
    has_alert=any(h["alert"] for h in hourly)
    return {"hourly":hourly,"daily":daily,"alert":has_alert,"base_time":base_time,"error":None,"source":"kma"}

# ── 일진 계산 + 운세 생성 ──────────────────────────────────────────────────────
TIANGAN = ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"]
DIZHI   = ["子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"]
# 기준일: 2026-06-18 = 庚辰日 (index 16)
REF_DATE = datetime(2026,6,18)
REF_IDX  = 16

def get_jinsi(today):
    diff=(today-REF_DATE).days
    idx=(REF_IDX+diff)%60
    tg=TIANGAN[idx%10]; dz=DIZHI[idx%12]
    return tg+dz, idx

# 병화(丙火) 일간 기준 천간 십성

FORTUNE_SCORE = {
    # (총운, 금전운, 건강운, 로또운) /100
    "편인": (72, 52, 58, 48),
    "정인": (78, 65, 78, 62),
    "비견": (62, 48, 58, 38),
    "겁재": (48, 32, 45, 18),
    "식신": (88, 82, 72, 88),
    "상관": (65, 68, 52, 42),
    "편재": (82, 88, 72, 78),
    "정재": (78, 78, 82, 65),
    "편관": (52, 42, 48, 18),
    "정관": (78, 72, 78, 58),
}
SIPSUNG = {
    "甲":"편인","乙":"정인","丙":"비견","丁":"겁재",
    "戊":"식신","己":"상관","庚":"편재","辛":"정재",
    "壬":"편관","癸":"정관"
}
# 십성별 운세 템플릿 (총운, 금전, 건강, 로또, 직장)
FORTUNE_TMPL = {
    "편인": ("정신적 에너지가 모이는 날. 공부·자격증·기획에 집중하면 성과가 나온다.",
             "직접적 수입보다 실력 축적에 투자하는 날. 충동 지출 주의.",
             "두뇌 과부하 주의. 눈 피로, 어깨 결림에 주의하고 충분히 수면.",
             "◐ 보통. 번호 선택보다 직관에 의존해볼 만한 날.",
             "오늘은 정신적 집중력이 절정에 달하는 날입니다. 공부·기획·자격증 준비처럼 두뇌를 쓰는 작업에 집중하면 평소보다 훨씬 깊이 파고들 수 있습니다. 재물보다 실력을 쌓는 방향으로 에너지를 쓰는 것이 유리하며, 충동 지출은 경계하세요. 눈과 어깨의 피로가 쌓이기 쉬우니 틈틈이 스트레칭하고 충분한 수면을 확보하는 것이 중요합니다. 아이디어가 풍부하게 떠오르는 날이니 메모 습관을 활용해 놓치지 마세요. 혼자 집중하는 환경이 외부 자극보다 훨씬 효율적인 하루입니다.",
             "오늘은 정신적 집중력이 절정에 달하는 날입니다. 공부·기획·자격증 준비처럼 두뇌를 쓰는 작업에 집중하면 평소보다 훨씬 깊이 파고들 수 있습니다. 재물보다 실력을 쌓는 방향으로 에너지를 쓰는 것이 유리하며 충동 지출은 반드시 경계하세요. 눈과 어깨의 피로가 쌓이기 쉬우니 틈틈이 스트레칭하고 충분한 수면을 확보하는 것이 중요합니다. 아이디어가 풍부하게 떠오르는 날이니 메모 습관을 활용해 좋은 생각을 놓치지 마세요. 혼자 집중하는 환경이 외부 자극보다 훨씬 효율적인 하루이며 배움에 투자할수록 미래 수익으로 돌아올 것입니다. 과부하가 걸리기 전에 짧은 휴식을 반복하는 것이 오늘의 지혜입니다."),
    "정인": ("협력과 문서의 날. 계약서·자격·인허가 관련 일이 잘 풀린다.",
             "도움 받는 날. 이미 진행 중인 수입 흐름에 집중.",
             "전반적으로 안정. 소화기·위장 약간 주의.",
             "○ 양호. 짝수 위주 선택.",
             "협력·문서·제도가 나를 돕는 날입니다. 계약서 검토, 자격증 신청, 인허가 처리 등 공식적인 일들이 순조롭게 흘러갑니다. 이미 진행 중인 수입 흐름에 집중하고 새 모험보다 기존 관계를 다지는 것이 현명합니다. 전반적으로 몸 상태가 안정적이나 소화기·위장을 가볍게 챙기면 더욱 좋습니다. 어른이나 스승의 조언이 특히 도움이 되는 날이며, 배움의 기회를 적극 받아들이세요. 감사하는 마음이 좋은 인연을 불러오는 하루입니다.",
             "협력·문서·제도가 나를 돕는 날입니다. 계약서 검토, 자격증 신청, 인허가 처리 등 공식적인 일들이 순조롭게 흘러갑니다. 이미 진행 중인 수입 흐름에 집중하고 새로운 모험보다 기존 관계를 더욱 공고히 다지는 것이 현명합니다. 전반적으로 몸 상태가 안정적이나 소화기·위장을 가볍게 챙기면 더욱 좋습니다. 어른이나 스승의 조언이 특히 도움이 되는 날이며 배움의 기회를 적극 받아들이세요. 감사하는 마음이 좋은 인연을 불러오는 하루로, 오랫동안 미뤄둔 공식 서류 처리를 마무리하기에도 최적의 날입니다. 원칙과 성실함이 빛을 발하는 시간입니다."),
    "비견": ("독립적 에너지가 넘치는 날. 자기 주장이 강해지니 협업 시 양보도 필요.",
             "경쟁 심리 주의. 투자·도박 자제. 개인 기술로 버는 수입은 OK.",
             "심장·혈압 관리. 과식·음주 자제.",
             "△ 평범. 숫자에 집착하지 않는 날.",
             "나 자신과 동등한 기운이 강해지는 날입니다. 자립심과 자존감이 높아지나 지나치면 주변과 마찰이 생길 수 있습니다. 투자·도박·경쟁적 지출은 자제하고, 개인 기술과 실력으로 수익을 창출하는 방향은 괜찮습니다. 심장과 혈압을 관리하고 과식이나 음주는 피하세요. 팀 안에서 한 발 양보하면 하루가 훨씬 편해집니다. 경쟁보다 협력을 택할 때 더 큰 성과가 따라오는 날이며, 자신의 장점을 묵묵히 발휘하는 것이 최선이며 꾸준함이 결국 경쟁에서 이기는 원동력이 됩니다.",
             "나 자신과 동등한 기운이 강해지는 날입니다. 자립심과 자존감이 높아지나 지나치면 주변과 마찰이 생길 수 있습니다. 투자·도박·경쟁적 지출은 자제하고 개인 기술과 실력으로 수익을 창출하는 방향은 괜찮습니다. 심장과 혈압을 관리하고 과식이나 음주는 피하세요. 팀 안에서 한 발 양보하면 하루가 훨씬 편해집니다. 경쟁보다 협력을 택할 때 더 큰 성과가 따라오는 날이며 자신의 장점을 묵묵히 발휘하는 것이 최선입니다. 승부욕이 앞서는 상황에서도 상대방의 입장을 먼저 헤아리는 연습이 오늘의 핵심 과제이며 이를 통해 신뢰가 쌓입니다."),
    "겁재": ("경쟁과 지출이 겹칠 수 있는 날. 돈 거래·보증 자제.",
             "⚠️ 지출 발생 주의. 현금 흐름 확인 필수.",
             "과로, 신경 피로 주의. 무리한 운동은 부상 위험.",
             "✕ 불리. 이날은 복권 구입 건너뛰는 것 추천.",
             "경쟁과 예상치 못한 지출이 겹칠 수 있는 날입니다. 돈 거래·보증·투기는 반드시 자제하고, 현금 흐름을 꼼꼼히 점검해 두세요. 신경 피로와 과로가 쌓이기 쉬우니 무리한 스케줄은 줄이는 것이 좋습니다. 직접 대립보다 정보 수집에 집중하면 경쟁에서 유리한 위치를 차지할 수 있습니다. 감정 소비를 최소화하고 꼭 필요한 지출만 집행하는 날입니다. 인내심이 오늘의 가장 큰 무기이며, 조급하게 결정하지 않는 것이 나중에 이득이 됩니다.",
             "경쟁과 예상치 못한 지출이 겹칠 수 있는 날입니다. 돈 거래·보증·투기는 반드시 자제하고 현금 흐름을 꼼꼼히 점검해 두세요. 신경 피로와 과로가 쌓이기 쉬우니 무리한 스케줄은 줄이는 것이 좋습니다. 직접 대립보다 정보 수집에 집중하면 경쟁에서 유리한 위치를 차지할 수 있습니다. 감정 소비를 최소화하고 꼭 필요한 지출만 집행하는 날입니다. 인내심이 오늘의 가장 큰 무기이며 조급하게 결정하지 않는 것이 나중에 이득이 됩니다. 주변의 달콤한 제안에 흔들리지 않고 원칙을 지키는 것이 장기적으로 재물을 지키는 비결이며 오늘 하루 신중함을 최고의 전략으로 삼으세요."),
    "식신": ("결과물을 만들기 가장 좋은 날. 창작·개발·문서 작업이 잘 된다.",
             "기술·능력으로 수입 창출 기회. 외식·소비는 즐거움으로 OK.",
             "식욕 왕성. 소화기 과부하 주의. 가벼운 운동 권장.",
             "◎ 길한 편. 직감대로 고르는 날.",
             "창의와 생산의 기운이 넘치는 날입니다. 오늘 만든 결과물은 평소보다 완성도가 높으니 발표·제안·납품처럼 성과를 보여주는 일에 집중하세요. 기술과 능력으로 수입을 올릴 기회가 생기며, 외식이나 가벼운 소비도 기분 전환에 도움이 됩니다. 다만 식욕이 왕성해지니 과식은 주의하고 가벼운 운동으로 소화를 돕는 것이 좋습니다. 주변 사람들에게 재능을 나눠주는 것도 큰 복이 되는 날이며, 즐겁게 일할수록 더 좋은 결과가 나옵니다.",
             "창의와 생산의 기운이 넘치는 날입니다. 오늘 만든 결과물은 평소보다 완성도가 높으니 발표·제안·납품처럼 성과를 보여주는 일에 집중하세요. 기술과 능력으로 수입을 올릴 기회가 생기며 외식이나 가벼운 소비도 기분 전환에 도움이 됩니다. 다만 식욕이 왕성해지니 과식은 주의하고 가벼운 운동으로 소화를 돕는 것이 좋습니다. 주변 사람들에게 재능을 나눠주는 것도 큰 복이 되는 날이며 즐겁게 일할수록 더 좋은 결과가 나옵니다. 오늘 완성한 것은 반드시 기록에 남겨두면 나중에 포트폴리오가 되어 더 큰 기회를 열어줍니다. 오늘의 창의적 성과를 소중히 간직하세요."),
    "상관": ("변화와 창의의 날. 규칙을 벗어난 발상이 빛나지만 규정 충돌 주의.",
             "새 수입원 모색에 좋으나 계약서 없는 거래는 위험.",
             "신경계·스트레스 주의. 충분한 휴식과 스트레칭.",
             "△ 변동성 있음. 즉흥 번호보다 평소 좋아하는 번호로.",
             "자유로운 사고와 창의력이 폭발하는 날입니다. 기존 틀을 깨는 아이디어가 빛을 발하지만 규정과 충돌하지 않도록 주의가 필요합니다. 새로운 수입원을 모색하기 좋으나, 계약서 없는 거래는 반드시 피하세요. 신경계가 예민해지기 쉬우니 충분한 휴식과 스트레칭으로 긴장을 풀고, 상사나 고객에게는 부드럽고 유연하게 의견을 전달하는 방식이 효과적입니다. 말의 힘이 강한 날인 만큼 긍정적인 언어 사용이 분위기를 좌우하며, 독창성이 빛날수록 주목받는 하루입니다.",
             "자유로운 사고와 창의력이 폭발하는 날입니다. 기존 틀을 깨는 아이디어가 빛을 발하지만 규정과 충돌하지 않도록 주의가 필요합니다. 새로운 수입원을 모색하기 좋으나 계약서 없는 거래는 반드시 피하세요. 신경계가 예민해지기 쉬우니 충분한 휴식과 스트레칭으로 긴장을 풀고 상사나 고객에게는 부드럽고 유연하게 의견을 전달하는 방식이 효과적입니다. 말의 힘이 강한 날인 만큼 긍정적인 언어 사용이 분위기를 좌우하며 독창성이 빛날수록 주목받는 하루입니다. 감정 기복이 클 수 있으니 중요한 판단은 차분해진 뒤에 내리는 것이 현명하며 충동적 결정이 나중에 후회로 이어지지 않도록 주의하세요."),
    "편재": ("실용적 재물 기운이 활성화되는 날. 외부 프로젝트·협상에 유리.",
             "◎ 재물 흐름 양호. 단, 과욕은 금물.",
             "활동량 늘리면 컨디션 업. 혈압·혈관 관리.",
             "○ 좋은 날. 홀수 위주 선택.",
             "재물 기운이 활발하게 움직이는 날입니다. 외부 미팅·협상·제안 등 바깥 활동에서 기회가 찾아오기 쉬우며, 수익으로 연결되는 대화에 집중하면 좋은 결과를 얻을 수 있습니다. 단, 과욕은 금물입니다. 몸을 활발히 움직일수록 컨디션이 좋아지나 혈압과 혈관 건강을 가볍게 체크해 두세요. 사교적인 에너지가 넘치는 날이므로 새로운 인맥을 만들기에도 최적이며, 적극적인 태도가 기회를 더 크게 만들어 줍니다.",
             "재물 기운이 활발하게 움직이는 날입니다. 외부 미팅·협상·제안 등 바깥 활동에서 기회가 찾아오기 쉬우며 수익으로 연결되는 대화에 집중하면 좋은 결과를 얻을 수 있습니다. 단 과욕은 금물입니다. 몸을 활발히 움직일수록 컨디션이 좋아지나 혈압과 혈관 건강을 가볍게 체크해 두세요. 사교적인 에너지가 넘치는 날이므로 새로운 인맥을 만들기에도 최적이며 적극적인 태도가 기회를 더 크게 만들어 줍니다. 한 번에 큰 것을 노리기보다 여러 작은 성과를 착실히 쌓아가는 전략이 오늘 하루를 가장 알차게 마무리하는 방법이며 오늘의 인맥이 내일의 재물이 됩니다."),
    "정재": ("안정적 수입과 성실함의 날. 꼼꼼한 작업이 빛을 발한다.",
             "안정적 수입 유지. 새 투자보다 기존 자산 점검.",
             "전반 안정. 규칙적 식사·수면 유지가 핵심.",
             "○ 무난. 자주 쓰는 번호 그대로.",
             "안정과 성실이 빛나는 날입니다. 화려한 도전보다 맡은 일을 꼼꼼하게 마무리하는 것이 신뢰를 쌓는 지름길입니다. 재물 면에서는 새로운 투자보다 기존 자산과 수입 흐름을 점검하는 것이 유리합니다. 규칙적인 식사와 수면을 유지하면 전반적인 컨디션이 안정적으로 유지됩니다. 묵묵히 성실하게 임하는 태도가 주변의 신뢰를 얻는 하루이며, 작은 일에서도 정성을 다하면 이후에 큰 보상이 따릅니다. 절약과 계획적 소비가 재물을 지키는 핵심입니다.",
             "안정과 성실이 빛나는 날입니다. 화려한 도전보다 맡은 일을 꼼꼼하게 마무리하는 것이 신뢰를 쌓는 지름길입니다. 재물 면에서는 새로운 투자보다 기존 자산과 수입 흐름을 점검하는 것이 유리합니다. 규칙적인 식사와 수면을 유지하면 전반적인 컨디션이 안정적으로 유지됩니다. 묵묵히 성실하게 임하는 태도가 주변의 신뢰를 얻는 하루이며 작은 일에서도 정성을 다하면 이후에 큰 보상이 따릅니다. 절약과 계획적 소비가 재물을 지키는 핵심이며 오늘 아낀 것이 내일의 여유를 만들어 줍니다. 루틴을 지키는 것이 오늘 가장 강력한 전략이며 신뢰와 성실함으로 쌓은 것은 결코 무너지지 않습니다."),
    "편관": ("긴장과 도전의 날. 압박이 있지만 돌파하면 성장한다.",
             "지출·손실 주의. 긴급 지출 대비책 확인.",
             "⚠️ 면역·피로 주의. 충분한 수면·수분 섭취.",
             "✕ 불리. 무리한 기대 금물.",
             "긴장과 압박이 찾아올 수 있는 날이지만, 이를 돌파하면 오히려 한 단계 성장하는 기회가 됩니다. 예상치 못한 지출이나 손실에 대비해 현금 흐름을 미리 점검하세요. 면역력이 떨어지기 쉬우니 충분한 수면과 수분 섭취가 특히 중요합니다. 마감이나 압박 상황에서도 충돌을 피하고 침착하게 대응하면 좋은 결과를 얻을 수 있습니다. 오늘의 어려움은 내일의 경험이 되며, 포기하지 않는 끈기가 가장 강한 무기인 하루입니다.",
             "긴장과 압박이 찾아올 수 있는 날이지만 이를 돌파하면 오히려 한 단계 성장하는 기회가 됩니다. 예상치 못한 지출이나 손실에 대비해 현금 흐름을 미리 점검하세요. 면역력이 떨어지기 쉬우니 충분한 수면과 수분 섭취가 특히 중요합니다. 마감이나 압박 상황에서도 충돌을 피하고 침착하게 대응하면 좋은 결과를 얻을 수 있습니다. 오늘의 어려움은 내일의 경험이 되며 포기하지 않는 끈기가 가장 강한 무기인 하루입니다. 무리한 계획보다 하나씩 해결해 나가는 분할 접근법이 스트레스를 줄이고 성과를 높이는 핵심 전략이며 오늘의 인내가 내일의 자신감으로 돌아옵니다."),
    "정관": ("제도·규칙·조직이 나를 도와주는 날. 공식 절차를 따르면 유리.",
             "안정 수입 유지. 투기·비공식 거래 피한다.",
             "전반 양호. 혈압·신장 가볍게 체크.",
             "◐ 보통. 짝수·홀수 균형 선택.",
             "조직과 제도가 나를 든든하게 받쳐주는 날입니다. 공식 절차와 규칙을 따르면 상사·기관의 협조를 쉽게 얻을 수 있습니다. 수입은 안정적으로 유지되나 투기나 비공식 거래는 피하는 것이 좋습니다. 전반적으로 컨디션이 양호하나 혈압과 신장을 가볍게 챙기면 더욱 완벽한 하루가 됩니다. 원칙과 신뢰를 바탕으로 움직이면 모든 일이 제자리를 찾는 날이며, 평판과 신용이 쌓이는 방향으로 행동하는 것이 장기적으로 가장 큰 이익입니다.",
             "조직과 제도가 나를 든든하게 받쳐주는 날입니다. 공식 절차와 규칙을 따르면 상사·기관의 협조를 쉽게 얻을 수 있습니다. 수입은 안정적으로 유지되나 투기나 비공식 거래는 피하는 것이 좋습니다. 전반적으로 컨디션이 양호하나 혈압과 신장을 가볍게 챙기면 더욱 완벽한 하루가 됩니다. 원칙과 신뢰를 바탕으로 움직이면 모든 일이 제자리를 찾는 날이며 평판과 신용이 쌓이는 방향으로 행동하는 것이 장기적으로 가장 큰 이익입니다. 규정을 지키는 것이 때로는 느려 보이지만 결국 가장 빠른 길이 되는 것이 오늘의 메시지이며 신뢰를 잃지 않는 것이 최고의 자산입니다."),
}

# 행운색 (일진 천간 오행 기준)
LUCKY_COLOR = {
    "甲":"청색·녹색","乙":"청색·연두","丙":"붉은색·오렌지","丁":"분홍·자주",
    "戊":"황색·갈색","己":"황색·베이지","庚":"흰색·은색","辛":"흰색·크림",
    "壬":"흑색·남색","癸":"남색·회색"
}

def lucky_numbers(seed):
    """날짜 시드 기반 행운 번호 6개 (1~45, 중복없음)"""
    import hashlib
    h=int(hashlib.md5(str(seed).encode()).hexdigest(),16)
    nums=set()
    i=0
    while len(nums)<6:
        nums.add((h+i*37)%45+1); i+=1
    return sorted(nums)

# 전갈자리 운세 (주차별 순환, 7개 템플릿)
SCORPIO_WEEKLY = [
    # 주간 운세 0~6 (week_num % 7)
    "이번 주 전갈자리는 내면의 변화와 외부 세계의 충돌을 조율하는 한 주입니다. 깊은 통찰력이 빛을 발하는 시기로 표면 아래의 진실을 꿰뚫어 보는 능력이 극대화됩니다. 재물 흐름은 안정적이나 예상치 못한 지출 요인이 숨어 있을 수 있으니 꼼꼼한 점검이 필요합니다. 인간관계에서는 진정성 있는 연결을 우선시하고 겉치레 관계는 과감히 정리하는 용기가 필요한 시기입니다. 주중 후반부로 갈수록 에너지가 상승하며 금요일 전후로 중요한 기회가 열릴 수 있습니다. 도전적인 상황일수록 전갈자리의 강인한 회복력이 빛을 발합니다. 주말에는 충분한 휴식으로 다음 주를 위한 에너지를 비축하세요.",
    "전갈자리에게 이번 주는 정보와 지식이 핵심 자원이 되는 한 주입니다. 알면 알수록 유리한 상황이 전개되며 적극적인 학습과 조사가 빛을 발합니다. 주초에는 다소 에너지가 낮을 수 있으나 수요일을 기점으로 집중력이 회복됩니다. 재정 면에서는 섣부른 투자보다 정보 수집과 분석에 집중하는 것이 현명합니다. 주말에는 잠시 일상에서 벗어나 재충전하는 시간을 갖는 것이 다음 주를 위한 최선의 준비입니다. 배운 것을 즉시 적용하는 실천력이 이번 주를 빛나게 합니다. 지식이 곧 재물로 연결되는 흐름을 놓치지 마세요. 모르는 것을 솔직히 인정하고 배우는 자세가 이번 주 신뢰를 높이는 비결입니다.",
    "감정과 이성 사이의 균형을 잡아야 하는 중요한 한 주입니다. 전갈자리의 예민한 감수성이 특히 강하게 작동하여 주변 상황을 예리하게 인식하지만 그만큼 상처받기도 쉬운 시기입니다. 감정적 결정은 최대한 뒤로 미루고 논리와 사실에 근거해 판단하는 연습이 필요합니다. 가까운 사람과의 솔직한 대화가 관계를 강화하는 촉매가 되며, 쌓인 감정을 적절히 표현하는 것이 오히려 내면의 안정을 가져옵니다. 운동이나 창작 활동으로 에너지를 건강하게 발산하세요. 내면의 안정이 외부 성과로 이어지는 구조를 이번 주 직접 경험하게 됩니다. 자신을 돌보는 것이 가장 생산적인 투자임을 잊지 마세요.",
    "재생과 성장의 에너지가 넘치는 한 주입니다. 과거에 마무리 짓지 못한 일들을 완성할 절호의 기회가 찾아옵니다. 전갈자리 특유의 끈기와 집중력이 시너지를 이루어 오래된 숙제를 해결하는 데 탁월한 능력을 발휘합니다. 재물 운은 꾸준한 노력에 비례해 상승하며, 단기 수익보다 장기적 성장에 투자하는 방향이 유리합니다. 주중에 새로운 파트너십이나 협력 제안이 들어올 수 있으니 열린 마음으로 검토해보세요. 이번 주의 노력은 앞으로 몇 달치 성과의 씨앗이 됩니다. 포기하지 않는 끈기가 이번 주 가장 강력한 무기입니다. 완벽하지 않아도 시작하는 용기가 이번 주 가장 중요한 자질입니다. 작은 전진이 큰 변화의 출발점이 됩니다.",
    "소통과 관계의 에너지가 강조되는 한 주입니다. 전갈자리는 깊이 있는 관계를 선호하지만 이번 주만큼은 더 넓은 네트워크를 향해 문을 여는 것이 이득입니다. 예상치 못한 곳에서 귀한 인맥이 형성될 수 있으며 그 연결이 장기적으로 큰 자원이 됩니다. 협업 프로젝트에서 두각을 나타낼 기회가 있으니 팀 활동에 적극 참여하세요. 건강 면에서는 수분 섭취와 규칙적인 수면이 특히 중요한 한 주입니다. 진심 어린 대화 한 마디가 중요한 문을 열어주는 열쇠가 됩니다. 먼저 손을 내미는 용기가 관계를 풍성하게 만드는 이번 주입니다. 경청의 힘을 발휘하면 상대방의 마음을 얻고 더 깊은 신뢰를 쌓을 수 있습니다.",
    "직관과 분석이 완벽하게 조화를 이루는 생산적인 한 주입니다. 전갈자리의 두 가지 핵심 강점이 동시에 발동되는 드문 시기로 어떤 문제에 접근해도 탁월한 해법을 찾아낼 수 있습니다. 업무에서 복잡한 과제에 도전하거나 창의적인 프로젝트를 추진하기에 최적의 타이밍입니다. 재정적으로도 좋은 흐름이 이어지며 협상 결과가 기대 이상으로 나타날 가능성이 있습니다. 자신을 믿고 과감하게 나아가세요. 이번 주의 성과가 앞으로 몇 달을 이끌어가는 동력이 됩니다. 이번 주의 성취는 자신감으로 이어져 다음 도전의 발판이 됩니다. 최선을 다한 하루하루가 쌓여 큰 성공을 만들어 냅니다.",
    "재물과 여유가 함께 찾아오는 풍요로운 한 주입니다. 이미 쌓아온 노력의 결실이 가시적으로 드러나기 시작하는 시기이며 진행 중인 수입 경로에서 예상보다 좋은 성과가 나올 수 있습니다. 전갈자리의 신중한 판단력이 재정 결정에서 빛을 발하며 새로운 투자 기회를 냉철하게 평가하는 능력도 향상됩니다. 주말에는 자신에게 작은 보상을 주는 시간을 갖고 내면의 에너지를 재충전하는 것이 다음 주를 위한 최선의 준비가 됩니다. 풍요로움을 나누면 더 큰 풍요가 돌아오는 법을 이번 주 경험하게 됩니다. 감사하는 마음이 행운을 지속시키는 비결입니다. 지금의 풍요로움을 다음 도약을 위한 발판으로 삼는 지혜가 필요한 한 주입니다.",
]
SCORPIO_DAILY = [
    # 월요일
    "한 주가 시작되는 오늘, 전갈자리에게는 예민한 직관이 가장 강력한 도구입니다. 내면 깊은 곳에서 올라오는 신호를 무시하지 마세요. 표면적으로 드러난 상황보다 그 이면을 파악하는 능력이 빛나는 날입니다. 중요한 결정을 앞두고 있다면 서두르지 말고 직감이 명확해질 때까지 기다리는 것이 현명합니다. 오늘은 새로운 정보를 수집하고 분석하는 데 에너지를 투자하세요. 주변의 말보다 자신의 내면 목소리를 신뢰할 때 가장 좋은 결과가 나옵니다. 자신을 믿고 내면의 나침반을 따라가면 오늘 하루 최선의 선택을 할 수 있습니다. 에너지를 아끼되 집중이 필요한 순간에는 전력을 다하세요.",
    # 화요일
    "과거의 인연이나 잊고 있던 정보가 오늘의 실마리를 제공할 수 있습니다. 오래된 대화, 메모, 아카이브를 뒤적여볼 때 예상치 못한 통찰을 얻게 됩니다. 전갈자리의 강점인 탐구 본능이 활발해지는 날로, 표면 아래의 진실을 파헤치는 능력이 빛을 발합니다. 인간관계에서도 오래된 연결고리를 점검하면 가치 있는 것을 재발견할 수 있습니다. 과거를 단순히 되짚는 것이 아니라 현재에 적용할 교훈을 찾는 시각으로 접근하면 오늘 하루가 매우 생산적인 날이 됩니다. 재발견의 기쁨을 즐기며 예상 밖의 통찰이 새로운 방향을 열어줄 수 있습니다. 내면의 고요함이 외부 정보를 더 잘 받아들이게 해줍니다.",
    # 수요일
    "감정 에너지가 특히 높은 날입니다. 전갈자리 특유의 깊은 감수성이 극대화되어 주변의 분위기와 감정을 예민하게 포착합니다. 이 능력은 장점이지만 지나치면 감정 과부하로 이어질 수 있으니 주의가 필요합니다. 충동적인 언행보다 냉정한 관찰자의 시선을 유지하는 것이 훨씬 유리합니다. 중요한 협상이나 대화가 있다면 감정보다 논리를 앞세우세요. 명상이나 짧은 산책으로 감정 에너지를 정화하면 하루를 훨씬 균형 있게 마무리할 수 있습니다. 이 감수성은 예술적 창의력이나 깊은 공감 능력으로 승화시킬 때 빛을 발합니다. 균형을 유지하며 감정의 파도를 지혜롭게 타세요.",
    # 목요일
    "재생과 변화의 기운이 강하게 흐르는 날입니다. 한때 포기했거나 중단했던 계획을 다시 꺼내 검토해보세요. 전갈자리는 불사조처럼 재기하는 힘을 타고난 별자리입니다. 오늘은 그 본능이 특히 강하게 발동되는 시점입니다. 실패로 여겼던 프로젝트, 끊어진 인맥, 보류한 아이디어 중 지금 시점에서 새로운 가능성을 품은 것이 반드시 있습니다. 두려움 없이 다시 시작할 용기를 내는 것이 오늘의 핵심 과제이며, 한 번의 재시도가 인생을 바꾸는 전환점이 될 수 있습니다. 오늘의 용기 있는 한 걸음이 긴 여정의 시작이 됩니다. 두려움보다 가능성에 집중하면 놀라운 결과가 기다리고 있습니다.",
    # 금요일
    "파트너나 협력자와의 소통이 특별히 원활한 날입니다. 전갈자리는 평소 단독으로 움직이는 경향이 있지만 오늘은 협력의 에너지가 강하게 작동합니다. 오랫동안 쌓인 이견이나 오해가 있다면 오늘 대화로 풀기에 가장 좋은 시점입니다. 진지하면서도 열린 태도로 상대방의 이야기를 들으면 의외의 접점을 발견하게 됩니다. 감추기보다 솔직하게 표현하는 것이 관계를 더욱 단단하게 만들고, 팀워크를 통해 혼자서는 만들 수 없는 결과물이 탄생하는 날입니다. 혼자서는 볼 수 없었던 사각지대를 협력자가 채워주며 더 큰 그림이 완성됩니다. 감사의 표현을 아끼지 말고 관계에 온기를 더하세요.",
    # 토요일
    "집중력이 최고조에 달하는 날입니다. 전갈자리의 몰입 능력이 절정에 이르러 깊이 있는 연구, 개발, 학습에 최적의 환경이 만들어집니다. 외부 자극을 최소화하고 오직 하나의 목표에 집중하면 평소 일주일이 걸릴 작업을 하루에 해낼 수 있는 잠재력이 있습니다. 방해 요소를 사전에 차단하고 몰입의 흐름을 끊지 않는 것이 중요합니다. 지적 호기심이 자극받는 주제를 탐구하거나 어렵게 느꼈던 개념을 정복하는 날로 활용하면 큰 만족감과 성취감을 얻을 수 있습니다. 오늘 성취한 것을 기록으로 남겨두면 나중에 중요한 참조 자료가 됩니다. 이 몰입의 경험이 앞으로도 당신의 최대 무기가 될 것입니다.",
    # 일요일
    "재물 기운이 은근하게 살아있는 날입니다. 전갈자리에게 오늘은 눈에 띄는 큰 수입보다 이미 만들어둔 수입 경로를 점검하고 최적화하는 날입니다. 진행 중인 프로젝트의 수익성을 재검토하거나, 놓친 정산이나 청구가 있는지 확인해보세요. 에너지를 새로운 곳에 흩뿌리기보다 검증된 경로에 집중적으로 투입하는 것이 훨씬 효율적입니다. 조용한 주말을 이용해 재정 계획을 정비하면 다가오는 한 주를 훨씬 여유롭게 시작할 수 있는 기반이 마련됩니다. 숨겨진 가치를 발굴하는 능력이 발휘되는 날이기도 합니다. 재정 계획을 정비하며 내일을 위한 탄탄한 기반을 만드세요.",
]

def get_fortune(today):
    jinsi, idx = get_jinsi(today)
    tg = jinsi[0]
    sipsung = SIPSUNG.get(tg, "비견")
    tmpl = FORTUNE_TMPL.get(sipsung, FORTUNE_TMPL["비견"])
    color = LUCKY_COLOR.get(tg, "흰색")
    nums = lucky_numbers(today.strftime("%Y%m%d"))
    week_num = today.isocalendar()[1]
    day_num  = today.weekday()
    is_monday = day_num == 0
    scorpio_weekly = SCORPIO_WEEKLY[week_num % 7]
    scorpio_daily  = SCORPIO_DAILY[day_num % 7]
    # 항상 이번 주 전체(월~일) 계산
    dow_names = ["월","화","수","목","금","토","일"]
    monday = today - timedelta(days=day_num)  # 이번 주 월요일
    weekly_rows = []
    for i in range(7):
        d = monday + timedelta(days=i)
        js, _ = get_jinsi(d)
        sg = SIPSUNG.get(js[0], "비견")
        t  = FORTUNE_TMPL.get(sg, FORTUNE_TMPL["비견"])
        lc = LUCKY_COLOR.get(js[0], "흰색")
        ln = lucky_numbers(d.strftime("%Y%m%d"))
        is_today = (d.date() == today.date())
        weekly_rows.append({
            "dow": dow_names[i], "date": d.strftime("%m/%d"),
            "jinsi": js, "sipsung": sg,
            "total": t[0], "money": t[1], "health": t[2],
            "lotto": t[3], "work": t[4],
            "summary": t[5] if len(t) > 5 else t[0],
            "color": lc, "nums": ln,
            "is_today": is_today,
        })
    sc = FORTUNE_SCORE.get(sipsung, (60, 60, 60, 50))
    return {
        "jinsi": jinsi, "sipsung": sipsung,
        "total": tmpl[0], "money": tmpl[1], "health": tmpl[2],
        "lotto": tmpl[3], "work": tmpl[4],
        "summary": tmpl[5] if len(tmpl) > 5 else tmpl[0],
        "color": color, "nums": nums,
        "score_total": sc[0], "score_money": sc[1],
        "score_health": sc[2], "score_lotto": sc[3],
        "scorpio_weekly": scorpio_weekly, "scorpio_daily": scorpio_daily,
        "is_monday": is_monday, "weekly_rows": weekly_rows,
        "today": today,
    }

# HTML 헬퍼
def badge(pct):
    if pct is None: return '<span class="b neu">—</span>'
    cls = "up" if pct > 0 else "dn" if pct < 0 else "neu"
    ar  = "▲" if pct > 0 else "▼" if pct < 0 else "─"
    return f'<span class="b {cls}">{ar} {abs(pct):.2f}%</span>'

def _news_a(a, display_text):
    href = a.get("link","")
    if not href: return display_text
    t     = html_esc(a.get("title",""))
    t_ko  = html_esc(a.get("title_ko","") or a.get("title",""))
    desc  = html_esc(a.get("desc_ko","") or a.get("desc",""))
    src_  = html_esc(a.get("source",""))
    date_ = html_esc(a.get("pub_date",""))
    lang_ = a.get("lang","ko")
    return f'<a href="{html_esc(href)}" class="news-link" target="_blank" rel="noopener noreferrer">{display_text}</a>'

def ul_links(arts, src=False):
    items = ""
    for a in arts:
        lbl  = a.get("source","") if src else a.get("pub_date","")
        lang = a.get("lang","ko")
        show = a.get("title_ko","") if lang=="en" and a.get("title_ko") else a.get("title","")
        tag  = _news_a(a, show) if a.get("link") else show
        items += f"<li>{tag}<span class='meta'>{lbl}</span></li>"
    return f"<ul>{items}</ul>"

def ol_links(arts):
    items = ""
    for i, a in enumerate(arts, 1):
        pd   = a.get("pub_date","")
        show = a.get("title","")
        tag  = _news_a(a, show) if a.get("link") else show
        items += f"<li><span class='idx'>{i}</span>{tag}<span class='meta'>{pd}</span></li>"
    return f"<ol>{items}</ol>" 

def stock_tbl(data, usd=False):
    rows = ""
    for name, d in data.items():
        if "error" in d:
            rows += f"<tr><td>{name}</td><td colspan='3' class='err'>{d['error']}</td></tr>"
        else:
            tk  = d.get("ticker",""); lbl = f"{name}<small>{tk}</small>" if tk else name
            price = f"${d['close']:,.2f}" if usd else f"{d['close']:,}"
            rows += f"<tr><td>{lbl}</td><td class='num'>{price}</td><td>{badge(d.get('change_pct'))}</td><td class='dt'>{d.get('date','')}</td></tr>"
    return "<table><thead><tr><th>종목</th><th>가격</th><th>등락</th><th>날짜</th></tr></thead><tbody>" + rows + "</tbody></table>"

# 탭 HTML 함수들
def tab1_html(kr, us):
    return ("<div class='two-col'>"
            "<div class='card'><h2>🇰🇷 한국 시장</h2>" + stock_tbl(kr) + "</div>"
            "<div class='card'><h2>🇺🇸 미국 시장</h2>" + stock_tbl(us, True) + "</div>"
            "</div>")

def tab2_html(kr_news, en_news):
    kr_html = "".join(f"<h3>{kw}</h3>" + ul_links(arts) for kw, arts in kr_news.items())
    en_html = "".join(f"<h3>{kw.replace('+',' ')}</h3>" + ul_links(arts, src=True) for kw, arts in en_news.items())
    return ("<div class='two-col'>"
            "<div class='card'><h2>📰 한국 뉴스</h2>" + kr_html + "</div>"
            "<div class='card'><h2>🌐 해외 뉴스</h2>" + en_html + "</div>"
            "</div>")

def tab3_html(papers):
    blocks = "".join(
        f"<div class='block'><h3>{name}</h3>" + ol_links(arts) + "</div>"
        for name, arts in papers.items()
    )
    return "<div class='card'><h2>🗞️ 언론사별 최신 뉴스</h2><div class='grid3'>" + blocks + "</div></div>"

def tab4_html(interest):
    blocks = "".join(
        f"<div class='block'><h3>{label}</h3>" + ul_links(arts) + "</div>"
        for label, arts in interest.items()
    )
    return "<div class='card'><h2>💡 관심 분야</h2><div class='grid3'>" + blocks + "</div></div>"

def tab5_html(weather):
    if weather.get("error"):
        return f"<div class='card'><h2>🌤️ 날씨</h2><p class='err'>오류: {weather['error']}</p></div>"
    alert_banner = ""
    if weather.get("alert"):
        alert_banner = "<div class='weather-alert'>⚠️ 오늘 비 또는 눈 예보가 있습니다. 우산을 챙기세요!</div>"
    h_rows = ""
    for h in weather.get("hourly", []):
        cls = " class='rain-row'" if h["alert"] else ""
        h_rows += (f"<tr{cls}><td>{h['time']}</td><td>{h['tmp']}</td>"
                   f"<td>{h['sky']} {h['pty']}</td>"
                   f"<td>{h['pop']}%</td><td>{h['wsd']}m/s</td></tr>")
    h_tbl = ("<table><thead><tr><th>시간</th><th>기온</th><th>날씨</th><th>강수확률</th><th>풍속</th></tr></thead>"
             "<tbody>" + h_rows + "</tbody></table>") if h_rows else "<p class='sub'>시간별 데이터 없음</p>"
    d_rows = ""
    for d in weather.get("daily", []):
        cls = " class='rain-row'" if d["alert"] else ""
        d_rows += (f"<tr{cls}><td>{d['date']}</td><td>{d['tmn']}</td>"
                   f"<td>{d['tmx']}</td><td>{d['sky']} {d['pty']}</td></tr>")
    d_tbl = ("<table><thead><tr><th>날짜</th><th>최저</th><th>최고</th><th>날씨</th></tr></thead>"
             "<tbody>" + d_rows + "</tbody></table>") if d_rows else "<p class='sub'>일별 데이터 없음</p>"
    bt = weather.get("base_time", "")
    src = weather.get("source","kma")
    if src == "open-meteo":
        src_label = "<span style='color:#888;font-size:0.75em'> ※ Open-Meteo 데이터 (기상청 API 일시 불가)</span>"
        time_label = ""
    else:
        src_label = ""
        time_label = f"<p class='sub'>발표시각 {bt[:2]}:{bt[2:]} 기준</p>" if bt else ""
    return "".join([
        "<div class='weather-wrap'>",
        alert_banner,
        "<div class='two-col'>",
        f"<div class='card'><h2>⏰ 오늘 시간별 예보 <small>(서울 도봉구 창동)</small>{src_label}</h2>",
        time_label,
        h_tbl, "</div>",
        "<div class='card'><h2>📅 3일 예보</h2>",
        d_tbl, "</div>",
        "</div></div>",
    ])

def tab6_html(f):
    jinsi = f["jinsi"]; sipsung = f["sipsung"]
    def row(label, val):
        return f"<tr><td class='f-label'>{label}</td><td>{val}</td></tr>"
    def score_bar(score):
        color = "#3fb950" if score>=75 else "#f0883e" if score>=50 else "#f85149"
        return (f"<span class='sc-num'>{score}점</span>"
                f"<span class='sc-bar'><span class='sc-fill' style='width:{score}%;background:{color}'></span></span>")
    def score_row(label, val, score):
        return f"<tr><td class='f-label'>{label}</td><td>{val}<div class='sc-wrap'>{score_bar(score)}</div></td></tr>"
    nums_str = " · ".join(str(n) for n in f["nums"])
    summary = f.get("summary", f["total"])
    daily_tbl = "".join([
        "<table class='fortune-tbl'>",
        row("📅 오늘 일진", f"<strong>{jinsi}</strong> ({sipsung})"),
        f"<tr><td class='f-label'>🌟 총운</td><td><div class='fortune-summary-text'>{summary}</div><div class='sc-wrap'>{score_bar(f.get('score_total',60))}</div></td></tr>",
        score_row("💰 금전운", f["money"], f.get("score_money",60)),
        score_row("💪 건강운", f["health"], f.get("score_health",60)),
        score_row("🎰 로또운", f["lotto"], f.get("score_lotto",50)),
        row("💼 직장운", f["work"]),
        row("🎨 행운색", f["color"]),
        row("🔢 행운번호", nums_str),
        "</table>",
    ])
    w_rows = ""
    for r in f["weekly_rows"]:
        ns = " ".join(str(x) for x in r["nums"])
        today_cls = " class='today-row'" if r.get("is_today") else ""
        w_rows += (f"<tr{today_cls}><td><strong>{r['dow']}</strong><span class='meta'>{r['date']}</span></td>"
                   f"<td><strong>{r['jinsi']}</strong><small>({r['sipsung']})</small></td>"
                   f"<td>{r['total']}</td><td>{r['money']}</td>"
                   f"<td>{r['health']}</td>"
                   f"<td><span class='color-dot' style='background:var(--acc)'></span>{r['color']}</td>"
                   f"<td class='num lotto-nums'>{ns}</td></tr>")
    weekly_section = "".join([
        "<div class='card weekly-card'>",
        "<h2>📆 이번 주 운세 (월~일)</h2>",
        "<div class='weekly-scroll'>",
        "<table class='weekly-tbl'><thead><tr>",
        "<th>요일</th><th>일진(십성)</th><th>총운</th><th>금전</th><th>건강</th><th>행운색</th><th>행운번호</th>",
        "</tr></thead><tbody>", w_rows, "</tbody></table></div></div>",
    ])
    star_section = "".join([
        "<div class='card'><h2>♏ 전갈자리 운세</h2>",
        "<p class='fortune-star-label'>오늘의 흐름</p>",
        f"<p class='fortune-star-daily'>{f['scorpio_daily']}</p>",
        "<p class='fortune-star-label' style='margin-top:14px'>주간 흐름</p>",
        f"<p class='fortune-star-weekly'>{f['scorpio_weekly']}</p>",
        "</div>",
    ])
    return "".join([
        "<div class='two-col'>",
        "<div class='card'><h2>🔮 오늘의 사주 운세</h2>",
        f"<p class='sub'>병화(丙火) 일간 · {f['today'].strftime('%Y년 %m월 %d일')}</p>",
        daily_tbl, "</div>",
        star_section,
        "</div>",
        weekly_section,
    ])


CSS = '''
:root{--bg:#0d1117;--card:#161b22;--bdr:#21262d;--txt:#e6edf3;--sub:#8b949e;
      --up:#3fb950;--dn:#f85149;--acc:#58a6ff;--up-bg:#0d2119;--dn-bg:#2d1117;--neu:#1c2128}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font-family:'Segoe UI',system-ui,sans-serif;padding:20px 24px;max-width:1280px;margin:0 auto}
h1{font-size:1.5rem;color:var(--acc);margin-bottom:3px}
.sub{color:var(--sub);font-size:.8rem;margin-bottom:18px}
.tabs{display:flex;gap:2px;border-bottom:1px solid var(--bdr);margin-bottom:18px}
.tab-btn{background:none;border:none;color:var(--sub);font-size:.88rem;padding:9px 18px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}
.tab-btn:hover{color:var(--txt)}
.tab-btn.active{color:var(--acc);border-bottom-color:var(--acc)}
.tab-pane{display:none}
.tab-pane.active{display:block}
.card{background:var(--card);border:1px solid var(--bdr);border-radius:10px;padding:18px;margin-bottom:16px}
.card h2{font-size:.95rem;color:var(--acc);margin-bottom:12px}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}
table{width:100%;border-collapse:collapse}
th{color:var(--sub);font-size:.72rem;text-align:left;padding:5px 6px;border-bottom:1px solid var(--bdr)}
td{padding:7px 6px;font-size:.87rem;border-bottom:1px solid var(--bdr)}
td.num{font-weight:600;font-variant-numeric:tabular-nums}
td small{color:var(--sub);font-size:.7rem;margin-left:4px}
td.err{color:var(--dn);font-size:.78rem}
td.dt{color:var(--sub);font-size:.75rem}
.b{display:inline-block;padding:2px 6px;border-radius:99px;font-size:.74rem;font-weight:600}
.b.up{background:var(--up-bg);color:var(--up)}
.b.dn{background:var(--dn-bg);color:var(--dn)}
.b.neu{background:var(--neu);color:var(--sub)}
h3{font-size:.82rem;color:var(--sub);margin:12px 0 7px;padding-bottom:5px;border-bottom:1px solid var(--bdr)}
.block h3{font-size:.85rem;color:var(--acc);margin-top:0}
ul,ol{list-style:none;padding:0}
li{padding:5px 0;border-bottom:1px solid var(--bdr);font-size:.83rem;line-height:1.45;display:flex;align-items:baseline;gap:6px;flex-wrap:wrap}
li:last-child{border-bottom:none}
a{color:var(--txt);text-decoration:none}
a:hover{color:var(--acc)}
.meta{color:var(--sub);font-size:.7rem;white-space:nowrap;margin-left:auto}
.idx{color:var(--sub);font-size:.72rem;min-width:18px;flex-shrink:0}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media(max-width:900px){.two-col,.grid3{grid-template-columns:1fr 1fr}}
@media(max-width:600px){.two-col,.grid3{grid-template-columns:1fr};body{padding:12px}}
.weather-alert{background:#2d1117;border:1px solid var(--dn);color:var(--dn);padding:10px 16px;border-radius:8px;margin-bottom:14px;font-size:.87rem}
.rain-row td{background:#1a1520;color:#e8c0ff}
.weather-wrap .two-col .card{min-width:0}
.fortune-tbl{width:100%;border-collapse:collapse}
.fortune-tbl td{padding:8px 10px;font-size:.85rem;border-bottom:1px solid var(--bdr);vertical-align:top}
.fortune-tbl td.f-label{color:var(--acc);white-space:nowrap;width:90px;font-weight:600}
.fortune-star-daily{font-size:.88rem;line-height:1.75;margin-bottom:10px;color:var(--txt)}
.fortune-star-label{font-size:.72rem;color:var(--acc);font-weight:700;letter-spacing:.05em;text-transform:uppercase;margin-bottom:6px}
.fortune-summary-text{font-size:.88rem;line-height:1.75;color:var(--txt);margin-bottom:8px}
.sc-wrap{display:flex;align-items:center;gap:8px;margin-top:5px}
.sc-num{font-size:.75rem;font-weight:700;color:var(--sub);min-width:32px}
.sc-bar{flex:1;height:6px;background:var(--bdr);border-radius:99px;overflow:hidden}
.sc-fill{height:100%;border-radius:99px;transition:width .4s}
.fortune-star-weekly{font-size:.83rem;color:var(--sub);line-height:1.5}
.weekly-card{margin-top:16px}
.weekly-scroll{overflow-x:auto}
.weekly-tbl{width:100%;border-collapse:collapse;min-width:700px}
.weekly-tbl th{color:var(--sub);font-size:.72rem;text-align:left;padding:6px 8px;border-bottom:2px solid var(--bdr);white-space:nowrap}
.weekly-tbl td{padding:8px 8px;font-size:.82rem;border-bottom:1px solid var(--bdr);vertical-align:top}
.weekly-tbl td:first-child{white-space:nowrap;font-size:.85rem}
.weekly-tbl td small{color:var(--sub);font-size:.7rem;margin-left:4px}
.today-row td{background:#0d2230;border-left:3px solid var(--acc)}
.today-row td:first-child{color:var(--acc);font-weight:700}
.lotto-nums{font-size:.78rem;color:var(--sub);letter-spacing:.03em}
.color-dot{display:none}
.home-wrap{display:flex;flex-direction:column;gap:16px}
.home-row{display:flex;gap:16px;flex-wrap:wrap}
.home-card{background:var(--card);border:1px solid var(--bdr);border-radius:12px;padding:18px 20px;flex:1;min-width:240px}
.home-card.full-row{flex:1 1 100%}
.fx-grid{display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start}
.fx-main{flex:0 0 auto;min-width:340px}.fx-main th,.fx-main td{font-size:.82rem;padding:6px 8px}
.fx-lbl{color:var(--sub);white-space:nowrap}
.fx-spark{vertical-align:middle;white-space:nowrap}
.spark-wrap{display:inline-flex;align-items:center;gap:6px}
.spark-chg{font-size:.75rem;font-weight:600;white-space:nowrap}
.fx-detail{flex:1;min-width:240px}.fx-detail th,.fx-detail td{font-size:.78rem;padding:5px 7px;text-align:right}
.fx-detail th:first-child,.fx-detail td:first-child{text-align:left;color:var(--sub)}
.fx-note{font-size:.7rem;color:var(--sub);margin-top:8px}
.hc-title{font-size:.8rem;color:var(--sub);font-weight:600;letter-spacing:.04em;text-transform:uppercase;margin-bottom:12px}
.hc-title small{font-size:.72rem;margin-left:6px;font-weight:400}
.hw-alert{background:var(--dn);color:#fff;font-size:.65rem;padding:2px 7px;border-radius:99px;margin-left:8px;vertical-align:middle}
.hw-main{display:flex;align-items:baseline;gap:10px;margin-bottom:4px}
.hw-tmp{font-size:2.2rem;font-weight:700;color:var(--txt)}
.hw-sky{font-size:1rem;color:var(--sub)}
.hw-range{font-size:.78rem;color:var(--sub);margin-bottom:10px}
.hw-hourly{display:flex;gap:6px;flex-wrap:wrap}
.hw-slot{background:var(--bg);border:1px solid var(--bdr);border-radius:8px;padding:6px 10px;font-size:.72rem;color:var(--sub);text-align:center;line-height:1.6}
.hw-slot.alert{border-color:var(--dn);color:var(--dn)}
.hf-jinsi{font-size:1.5rem;font-weight:700;color:var(--acc);margin-bottom:6px}
.hf-ss{font-size:.78rem;color:var(--sub);margin-left:8px;font-weight:400}
.hf-total{font-size:.88rem;color:var(--txt);line-height:1.6;margin-bottom:6px}
.hf-summary{font-size:.84rem;color:#adbac7;line-height:1.7;margin:8px 0 10px;white-space:pre-wrap}
.hf-meta{font-size:.74rem;color:var(--sub)}
.idx-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px}
.idx-item{background:var(--bg);border:1px solid var(--bdr);border-radius:8px;padding:10px 14px}
.idx-name{font-size:.72rem;color:var(--sub);margin-bottom:4px}
.idx-val{font-size:1.05rem;font-weight:700;color:var(--txt)}
.idx-chg{font-size:.78rem;margin-top:2px}
.idx-chg.up{color:var(--up)}.idx-chg.dn{color:var(--dn)}
.hn-list{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:8px}
.hn-item{display:flex;align-items:baseline;gap:8px;font-size:.85rem;color:var(--txt)}
.hn-cat{font-size:.65rem;background:var(--acc);color:#0d1117;padding:2px 7px;border-radius:99px;white-space:nowrap;flex-shrink:0}
.hn-cat.en{background:#f0883e}
.news-link{cursor:pointer;border-bottom:1px dashed var(--sub)}
.news-link:hover{color:var(--acc);border-bottom-color:var(--acc)}
.art-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);opacity:0;pointer-events:none;transition:opacity .25s;z-index:200}
.art-overlay.open{opacity:1;pointer-events:all}
.art-panel{position:fixed;bottom:0;left:0;right:0;background:var(--card);border-top:2px solid var(--acc);border-radius:16px 16px 0 0;padding:22px 28px 28px;transform:translateY(100%);transition:transform .3s cubic-bezier(.32,.72,0,1);z-index:201;max-height:55vh;overflow-y:auto;box-shadow:0 -8px 40px rgba(0,0,0,.4)}
.art-panel.open{transform:translateY(0)}
.art-panel-hdr{display:flex;align-items:center;gap:8px;margin-bottom:14px}
.art-badge{background:var(--acc);color:#0d1117;font-size:.7rem;font-weight:700;padding:2px 8px;border-radius:99px}
.art-badge.en{background:#f0883e;color:#0d1117}
.art-panel-src{color:var(--sub);font-size:.78rem}
.art-panel-date{color:var(--sub);font-size:.75rem;margin-left:auto}
.art-panel-close{background:none;border:none;color:var(--sub);font-size:1.3rem;cursor:pointer;line-height:1;padding:0 0 0 12px}
.art-panel-close:hover{color:var(--dn)}
.art-title-ko{font-size:1.05rem;font-weight:600;color:var(--txt);line-height:1.45;margin-bottom:6px}
.art-title-orig{font-size:.78rem;color:var(--sub);font-style:italic;margin-bottom:12px}
.art-desc{font-size:.85rem;color:#adbac7;line-height:1.65;margin-bottom:18px;white-space:pre-wrap}
.art-actions{display:flex;gap:10px;align-items:center}
.art-btn{display:inline-block;background:var(--acc);color:#0d1117;padding:8px 20px;border-radius:8px;font-size:.83rem;font-weight:700;text-decoration:none;transition:background .15s}
.art-btn:hover{background:#79b8ff;color:#0d1117}
.art-btn-copy{background:var(--neu);color:var(--txt);padding:8px 14px;border-radius:8px;font-size:.83rem;border:none;cursor:pointer}
.art-btn-copy:hover{background:var(--bdr)}
'''

JS = """
document.querySelectorAll('.tab-btn').forEach(function(btn){
  btn.addEventListener('click',function(){
    closePanel();
    document.querySelectorAll('.tab-btn').forEach(function(b){b.classList.remove('active');});
    document.querySelectorAll('.tab-pane').forEach(function(p){p.classList.remove('active');});
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  });
});
function openPanel(el){
  var d=el.dataset;
  var isEn=(d.lang==='en');
  var titleKo=d.titleKo||d.title;
  var titleOrig=isEn?d.title:'';
  var desc=d.desc||'';
  var src=d.src||'';
  var date=d.date||'';
  document.getElementById('art-badge').textContent=isEn?'EN':'KR';
  document.getElementById('art-badge').className='art-badge'+(isEn?' en':'');
  document.getElementById('art-panel-src').textContent=src;
  document.getElementById('art-panel-date').textContent=date;
  document.getElementById('art-title-ko').textContent=titleKo;
  var origEl=document.getElementById('art-title-orig');
  origEl.textContent=titleOrig?'원문: '+titleOrig:'';
  origEl.style.display=titleOrig?'block':'none';
  document.getElementById('art-desc').textContent=desc;
  document.getElementById('art-desc').style.display=desc?'block':'none';
  document.getElementById('art-link').href=d.href||'#';
  document.getElementById('art-panel').classList.add('open');
  document.getElementById('art-overlay').classList.add('open');
  document.getElementById('art-copy-btn').dataset.url=d.href||'';
}
function closePanel(){
  document.getElementById('art-panel').classList.remove('open');
  document.getElementById('art-overlay').classList.remove('open');
}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closePanel();});
function copyUrl(btn){
  var url=btn.dataset.url;
  if(!url)return;
  navigator.clipboard.writeText(url).then(function(){
    btn.textContent='복사됨!';
    setTimeout(function(){btn.textContent='링크 복사';},1500);
  });
}
"""


def _sparkline_svg(history, color="#58a6ff"):
    """5일 종가로 인라인 SVG 스파크라인 생성"""
    if not history or len(history) < 2:
        return ""
    vals = [r["close"] for r in history]
    mn, mx = min(vals), max(vals)
    rng = mx - mn if mx != mn else 1
    W, H, PAD = 120, 36, 4
    pts = []
    for i, v in enumerate(vals):
        x = PAD + i * (W - PAD*2) / (len(vals)-1)
        y = H - PAD - (v - mn) / rng * (H - PAD*2)
        pts.append(f"{x:.1f},{y:.1f}")
    last_chg = vals[-1] - vals[-2]
    chg_col  = "#3fb950" if last_chg >= 0 else "#f85149"
    chg_str  = f"{'▲' if last_chg>=0 else '▼'}{abs(last_chg):,.0f}"
    return (
        f"<div class='spark-wrap'>"
        f"<svg width='{W}' height='{H}' viewBox='0 0 {W} {H}'>"
        f"<polyline points='{' '.join(pts)}' fill='none' stroke='{color}' stroke-width='1.8' stroke-linejoin='round'/>"
        f"</svg>"
        f"<span class='spark-chg' style='color:{chg_col}'>{chg_str}</span>"
        f"</div>"
    )

def fx_card_html(fx):
    """환율/금 시세 카드 — 살때/팔때 테이블 + 5일 스파크라인"""
    def row(key, color):
        d = fx.get(key, {})
        lbl  = d.get('label', key)
        if 'error' in d:
            return f"<tr><td>{lbl}</td><td colspan='3' class='err'>{d['error']}</td></tr>"
        buy  = f"{d['buy']:,}원"  if d.get('buy')  else '-'
        sell = f"{d['sell']:,}원" if d.get('sell') else '-'
        spark = _sparkline_svg(d.get('history', []), color)
        return (f"<tr><td class='fx-lbl'>{lbl}</td>"
                f"<td class='num'>{buy}</td><td class='num'>{sell}</td>"
                f"<td class='fx-spark'>{spark}</td></tr>")

    tbl_rows = (row('usd','#58a6ff') + row('jpy','#f0883e') + row('gold','#ffd700'))

    # 5일 추이 상세 테이블
    def detail_rows(key):
        hist = fx.get(key, {}).get('history', [])
        if not hist: return ""
        cells = "".join(
            f"<td class='num'>{r['close']:,}</td>" for r in hist
        )
        return f"<tr><td class='fx-lbl'>{fx[key]['label']}</td>{cells}</tr>"

    dates = fx.get('usd',{}).get('history',[])
    date_hdr = "".join(f"<th>{r['date']}</th>" for r in dates)
    detail = (
        f"<table class='fx-detail'><thead><tr><th>항목</th>{date_hdr}</tr></thead><tbody>"
        + detail_rows('usd') + detail_rows('jpy') + detail_rows('gold')
        + "</tbody></table>"
    ) if dates else ""

    return "".join([
        "<div class='home-card fx-card full-row'>",
        "<div class='hc-title'>💱 환율 / 금 시세</div>",
        "<div class='fx-grid'>",
        "<table class='fx-main'><thead><tr>"
        "<th>항목</th><th>살 때</th><th>팔 때</th><th>5일 추이</th>"
        "</tr></thead><tbody>", tbl_rows, "</tbody></table>",
        detail,
        "</div>",
        "<p class='fx-note'>※ 살때/팔때: 기준환율 ±1.75% 추정(시중은행 평균) | 금 ±5% | 국제시세 환산</p>",
        "</div>",
    ])

def tab0_html(kr, us, kr_news, en_news, weather, fortune, fx=None):
    """메인(홈) 탭 - 날씨·운세·주가지수·속보 요약"""
    parts = ["<div class='home-wrap'>"]

    # ── 날씨 요약 ──────────────────────────────────────────────
    alert = weather.get("alert", False)
    hourly = weather.get("hourly", [])
    daily  = weather.get("daily", [])
    h0 = hourly[0] if hourly else {}
    d0 = daily[0]  if daily  else {}
    alert_badge = "<span class='hw-alert'>⚠ 비/눈</span>" if alert else ""
    parts += [
        "<div class='home-row'>",
        "<div class='home-card weather-card'>",
        "<div class='hc-title'>🌤 오늘 날씨 <small>창동</small>",alert_badge,"</div>",
        "<div class='hw-main'>",
        f"<span class='hw-tmp'>{h0.get('tmp','--')}</span>",
        f"<span class='hw-sky'>{h0.get('pty','') or h0.get('sky','--')}</span>",
        "</div>",
        f"<div class='hw-range'>{d0.get('tmn','--')} / {d0.get('tmx','--')} &nbsp;강수확률 {h0.get('pop','--')}%</div>",
    ]
    # 시간별 미니 예보 (최대 4개)
    if hourly:
        parts.append("<div class='hw-hourly'>")
        for h in hourly[:7]:
            flag = "🌧" if h.get("alert") else ""
            slot_cls = "hw-slot alert" if h.get("alert") else "hw-slot"
            sky_txt  = h.get("pty","") or h.get("sky","")
            parts.append(f"<span class='{slot_cls}'>{h['time']}<br>{sky_txt}<br>{h['tmp']}</span>")
        parts.append("</div>")
    parts += ["</div>"]  # weather-card

    # ── 오늘 운세 요약 ─────────────────────────────────────────
    today_row = next((r for r in fortune.get("weekly_rows",[]) if r.get("is_today")), None)
    if today_row:
        jinsi = today_row.get("jinsi","")
        sipsung = today_row.get("sipsung","")
        total = today_row.get("total","")
        lotto = today_row.get("lotto","")
        color = today_row.get("color","")
        stars = ["★"*int(lotto)+"☆"*(5-int(lotto)) if str(lotto).isdigit() else lotto][0]
        summary = today_row.get("summary", total)
        parts += [
            "<div class='home-card fortune-card'>",
            "<div class='hc-title'>🔮 오늘의 운세</div>",
            f"<div class='hf-jinsi'>{jinsi} <small class='hf-ss'>{sipsung}</small></div>",
            f"<div class='hf-summary'>{summary}</div>",
            f"<div class='hf-meta'>행운색: {color} &nbsp;|&nbsp; 지수: {stars}</div>",
            "</div>",
        ]
    parts += ["</div>"]  # home-row

    # ── 주요 지수 ──────────────────────────────────────────────
    parts += ["<div class='home-row'>","<div class='home-card idx-card full-row'>","<div class='hc-title'>📈 주요 지수</div>","<div class='idx-grid'>"]
    for name, d in list(kr.items()) + list(us.items()):
        pct = d.get("change_pct")
        if pct is None: continue
        cls = "up" if pct > 0 else "dn" if pct < 0 else ""
        arrow = "▲" if pct > 0 else "▼" if pct < 0 else "─"
        close = d.get("close","")
        try:
            close_fmt = f"{float(close):,.0f}" if float(str(close).replace(',','')) > 100 else f"{float(close):,.2f}"
        except Exception:
            close_fmt = str(close)
        parts.append(f"<div class='idx-item'><div class='idx-name'>{name}</div><div class='idx-val'>{close_fmt}</div><div class='idx-chg {cls}'>{arrow} {abs(pct):.2f}%</div></div>")
    parts += ["</div>","</div>","</div>"]  # idx-grid, idx-card, home-row

    # ── 환율 / 금 시세 (주요지수 아래, 속보 위) ──────────────────
    if fx:
        parts += ["<div class='home-row'>", fx_card_html(fx), "</div>"]

    # ── 속보 뉴스 ─────────────────────────────────────────────
    parts += ["<div class='home-row'>","<div class='home-card news-card full-row'>","<div class='hc-title'>📰 속보</div>","<ul class='hn-list'>"]
    added = 0
    # 한국 주식 뉴스
    for cat, arts in kr_news.items():
        if arts and added < 4:
            a = arts[0]
            show = a.get("title","")
            tag = _news_a(a, show) if a.get("link") else show
            parts.append(f"<li class='hn-item'><span class='hn-cat'>{cat}</span>{tag}</li>")
            added += 1
    # 영어 뉴스
    for cat, arts in en_news.items():
        if arts and added < 7:
            a = arts[0]
            show = a.get("title_ko","") or a.get("title","")
            tag = _news_a(a, show) if a.get("link") else show
            parts.append(f"<li class='hn-item'><span class='hn-cat en'>EN</span>{tag}</li>")
            added += 1
    parts += ["</ul>","</div>","</div>"]  # hn-list, news-card, home-row
    parts.append("</div>")  # home-wrap
    return "".join(parts)

def build_html(kr, us, kr_news, en_news, papers, interest, weather, fortune, date_str, fx=None):
    now_str = datetime.now().strftime("%Y년 %m월 %d일 %H:%M")
    alert_flag = " 비/눈" if weather.get("alert") else ""
    parts = [
        "<!DOCTYPE html><html lang='ko'><head>",
        "<meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>Daily Insight - {date_str}{alert_flag}</title>",
        f"<style>{CSS}</style></head><body>",
        "<h1>Daily Insight</h1>",
        f"<p class='sub'>생성: {now_str} | 한국 주식: 전일 종가 기준</p>",
        "<div class='tabs'>",
        "<button class='tab-btn active' data-tab='t0'>홈</button>",
        "<button class='tab-btn' data-tab='t1'>주식</button>",
        "<button class='tab-btn' data-tab='t2'>주식 뉴스</button>",
        "<button class='tab-btn' data-tab='t3'>언론사</button>",
        "<button class='tab-btn' data-tab='t4'>관심 분야</button>",
        "<button class='tab-btn' data-tab='t5'>날씨</button>",
        "<button class='tab-btn' data-tab='t6'>운세</button>",
        "</div>",
        "<div id='t0' class='tab-pane active'>", tab0_html(kr, us, kr_news, en_news, weather, fortune, fx), "</div>",
        "<div id='t1' class='tab-pane'>", tab1_html(kr, us), "</div>",
        "<div id='t2' class='tab-pane'>", tab2_html(kr_news, en_news), "</div>",
        "<div id='t3' class='tab-pane'>", tab3_html(papers), "</div>",
        "<div id='t4' class='tab-pane'>", tab4_html(interest), "</div>",
        "<div id='t5' class='tab-pane'>", tab5_html(weather), "</div>",
        "<div id='t6' class='tab-pane'>", tab6_html(fortune), "</div>",
        "<div id='art-overlay' onclick='closePanel()'></div>","<div id='art-panel' class='art-panel'>","<div class='art-panel-hdr'>","<span id='art-badge' class='art-badge'>KR</span>","<span id='art-panel-src' class='art-panel-src'></span>","<span id='art-panel-date' class='art-panel-date'></span>","<button class='art-panel-close' onclick='closePanel()'>&#x2715;</button>","</div>","<div id='art-title-ko' class='art-title-ko'></div>","<div id='art-title-orig' class='art-title-orig'></div>","<div id='art-desc' class='art-desc'></div>","<div class='art-actions'>","<a id='art-link' href='#' target='_blank' class='art-btn'>원문 보기 &#x2192;</a>","<button id='art-copy-btn' class='art-btn-copy' onclick='copyUrl(this)'>링크 복사</button>","</div></div>",
        f"<script>{JS}</script>",
        "</body></html>",
    ]
    return "".join(parts)

def ar(pct):
    if pct is None: return "-"
    return f"{'up' if pct>0 else 'dn' if pct<0 else '-'} {abs(pct):.2f}%"

def build_md(kr, us, kr_news, en_news, papers, interest, weather, fortune, date_str):
    L = []
    L += [f"# Daily Insight - {date_str}",
          f"> 생성: {datetime.now().strftime('%Y-%m-%d %H:%M')} | 한국: 전일 종가 기준", "", "---", "",
          "## 1. 주식", "", "### 한국 시장",
          "| 종목 | 종가 | 등락 | 날짜 |", "|------|-----:|:----:|------|"]
    for name, d in kr.items():
        if "error" in d: L.append(f"| {name} | - | 오류 | {d.get('date','')} |")
        else:
            tk = f" ({d['ticker']})" if d.get("ticker") else ""
            chg = ar(d.get("change_pct"))
            L.append(f"| {name}{tk} | {d['close']:,} | {chg} | {d.get('date','')} |")
    L += ["", "### 미국 시장", "| 종목 | 가격 | 등락 | 날짜 |", "|------|-----:|:----:|------|"]
    for name, d in us.items():
        if "error" in d: L.append(f"| {name} ({d.get('ticker','')}) | - | 오류 | - |")
        else:
            chg = ar(d.get("change_pct"))
            L.append(f"| {name} ({d['ticker']}) | ${d['close']:,.2f} | {chg} | {d.get('date','')} |")
    L += ["", "---", "", "## 2. 주식 관련 뉴스", "", "### 한국 뉴스"]
    for kw, arts in kr_news.items():
        L.append(f"\n#### {kw}")
        for a in arts: L.append(f"- [{a['title']}]({a['link']})")
    L += ["", "### 해외 뉴스"]
    for kw, arts in en_news.items():
        L.append(f"\n#### {kw.replace('+',' ')}")
        for a in arts: L.append(f"- [{a['title']}]({a['link']}) - {a.get('source','')}")
    L += ["", "---", "", "## 3. 언론사별 뉴스 (최신 10건)"]
    for name, arts in papers.items():
        L.append(f"\n### {name}")
        for i, a in enumerate(arts, 1): L.append(f"{i}. [{a['title']}]({a['link']}) - {a.get('pub_date','')}")
    L += ["", "---", "", "## 4. 관심 분야"]
    for label, arts in interest.items():
        L.append(f"\n### {label}")
        for a in arts: L.append(f"- [{a['title']}]({a['link']}) - {a.get('pub_date','')}")
    L += ["", "---", "", "## 5. 날씨 (서울 도봉구 창동)"]
    if weather.get("error"):
        L.append(f"> 오류: {weather['error']}")
    else:
        if weather.get("alert"): L.append("> 오늘 비 또는 눈 예보가 있습니다!")
        L += ["", "### 오늘 시간별 예보", "| 시간 | 기온 | 날씨 | 강수확률 | 풍속 |", "|------|------|------|----------|------|"]
        for h in weather.get("hourly", []):
            L.append(f"| {h['time']} | {h['tmp']} | {h['sky']} {h['pty']} | {h['pop']}% | {h['wsd']}m/s |")
        L += ["", "### 3일 예보", "| 날짜 | 최저 | 최고 | 날씨 |", "|------|------|------|------|"]
        for d in weather.get("daily", []):
            L.append(f"| {d['date']} | {d['tmn']} | {d['tmx']} | {d['sky']} {d['pty']} |")
    L += ["", "---", "", "## 6. 운세"]
    f = fortune
    L += ["", f"### 오늘의 사주 운세 - {f['jinsi']} ({f['sipsung']})",
          "", "| 항목 | 내용 |", "|------|------|",
          f"| 총운 | {f['total']} |",
          f"| 금전운 | {f['money']} |",
          f"| 건강운 | {f['health']} |",
          f"| 로또운 | {f['lotto']} |",
          f"| 직장운 | {f['work']} |",
          f"| 행운색 | {f['color']} |",
          f"| 행운번호 | {' '.join(str(n) for n in f['nums'])} |",
          "", "### 전갈자리 운세",
          f"- 오늘: {f['scorpio_daily']}",
          f"- 주간: {f['scorpio_weekly']}"]
    if f["weekly_rows"]:
        L += ["", "### 이번 주 운세 (월~일)", "| 요일 | 일진 | 총운요약 | 행운색 | 행운번호 |",
              "|------|------|---------|--------|--------|"]
        for r in f["weekly_rows"]:
            ns = " ".join(str(x) for x in r["nums"])
            today_mark = " ◀오늘" if r.get("is_today") else ""
            L.append(f"| {r['dow']}({r['date']}){today_mark} | {r['jinsi']}({r['sipsung']}) | {r['total'][:25]}... | {r['color']} | {ns} |")
    return "\n".join(L)

# 메인
def main():
    today = datetime.now()
    date_str = today.strftime("%Y-%m-%d")
    print(f"[{today:%H:%M:%S}] Daily Insight v3: {date_str}")
    print("  -> 한국 주식..."); kr = get_kr()
    print("  -> 미국 주식..."); us = get_us()
    print("  -> 주식 한국 뉴스...")
    kr_news = {}
    for kw in NAVER_STOCK_KW: kr_news[kw] = naver_news(kw, 5); time.sleep(0.2)
    print("  -> 주식 해외 뉴스...")
    en_news = {kw: google_news(kw, 5) for kw in GOOGLE_STOCK_KW}
    print("  -> 환율/금 시세 (네이버 금융)..."); fx = get_exchange_and_gold()
    print("  -> 언론사 뉴스...")
    papers = {}
    for name, url in PAPERS_RSS.items():
        arts = fetch_rss(url, 15)
        # RSS 실패 또는 기사 없음 → 네이버 API fallback
        if name in PAPERS_RSS_FALLBACK and (not arts or arts[0].get("title","").startswith("RSS오류") or arts[0].get("title") == "기사없음"):
            print(f"     {name} (RSS실패→네이버)"); arts = naver_news_by_paper(name, 15)
        else:
            print(f"     {name} (RSS {len(arts)}건)")
        papers[name] = arts; time.sleep(0.3)
    for name in PAPERS_NAVER:
        print(f"     {name} (네이버)"); papers[name] = naver_news_by_paper(name, 15); time.sleep(0.3)
    print("  -> 관심 분야...")
    interest = {}
    for label, kw in INTEREST_KW.items():
        print(f"     {label}"); interest[label] = naver_news(kw, 5); time.sleep(0.2)
    print("  -> 날씨 (기상청)..."); weather = get_weather()
    print("  -> 운세 계산..."); fortune = get_fortune(today)
    html_path = os.path.join(OUT_DIR, f"{date_str}.html")
    md_path   = os.path.join(OUT_DIR, f"{date_str}.md")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(build_html(kr, us, kr_news, en_news, papers, interest, weather, fortune, date_str, fx))
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(build_md(kr, us, kr_news, en_news, papers, interest, weather, fortune, date_str))
    if weather.get("alert"): print("  >> 오늘 강수 예보 있음!")
    print(f"  일진: {fortune['jinsi']} ({fortune['sipsung']})")
    print(f"  OK {html_path}")
    print(f"  OK {md_path}")

    # GitHub 업로드
    ym  = date_str[:7].replace("-","_")   # 2026_06
    ymd = date_str.replace("-","_")       # 2026_06_18
    gh_html_path = f"daily_insight/{ym}/{ymd}.html"
    gh_md_path   = f"daily_insight/{ym}/{ymd}.md"
    print(f"[{datetime.now():%H:%M:%S}] GitHub 업로드 중...")
    upload_to_github(html_path, gh_html_path, f"Daily Insight {date_str} HTML")
    upload_to_github(md_path,   gh_md_path,   f"Daily Insight {date_str} MD")
    pages_url = github_pages_url(date_str)
    print(f"  Pages URL: {pages_url}")

    # GitHub Pages 배포 완료 대기 (최대 15분, 30초 간격)
    # - 오늘 날짜 문자열이 본문에 포함될 때만 배포 완료로 인정
    ensure("requests"); import requests as _req
    # 날짜 마커: HTML 본문에 포함되는 형식 둘 다 허용
    date_marker_dash  = date_str                    # 2026-06-18
    date_marker_under = date_str.replace("-","_")   # 2026_06_18
    print(f"[{datetime.now():%H:%M:%S}] GitHub Pages 배포 대기 중... (마커: {date_marker_dash})")
    pages_ready = False
    print("  최소 60초 대기 중...", end="\r")
    time.sleep(60)  # GitHub Actions 트리거 최소 대기
    for attempt in range(28):  # 28 x 30초 = 최대 14분
        try:
            resp = _req.get(pages_url, timeout=10)
            if resp.status_code == 200 and (
                date_marker_dash in resp.text or date_marker_under in resp.text
            ):
                pages_ready = True
                elapsed = 60 + attempt * 30
                print(f"  Pages 배포 완료! ({elapsed}초 경과)")
                break
        except Exception:
            pass
        if attempt < 27:
            elapsed = 60 + (attempt + 1) * 30
            print(f"  대기 중... {elapsed}초", end="\r")
            time.sleep(30)
    if not pages_ready:
        print("  [경고] Pages 배포 확인 타임아웃 (15분). URL이 곧 활성화됩니다.")

    # 카카오톡 알림용 신호 파일 저장 (Pages 배포 확인 후)
    import json as _json
    summary = {
        "date": date_str,
        "pages_url": pages_url,
        "pages_ready": pages_ready,
        "weather_alert": bool(weather.get("alert")),
        "sipsung": fortune.get("sipsung",""),
        "jinsi": fortune.get("jinsi",""),
        "kospi": (kr.get("KOSPI") or {}).get("close","") if kr else "",
        "kospi_change": (kr.get("KOSPI") or {}).get("change_pct","") if kr else "",
        "generated_at": datetime.now().isoformat(),
    }
    last_run_path = os.path.join(OUT_DIR, "last_run.json")
    with open(last_run_path, "w", encoding="utf-8") as fh:
        _json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(f"  last_run.json 저장 완료")
    upload_to_github(last_run_path, "daily_insight/last_run.json", f"Daily Insight {date_str} last_run")
    print(f"[{datetime.now():%H:%M:%S}] 완료!")


# ─────────────────────────────────────────────
# GitHub 업로드
# ─────────────────────────────────────────────
def upload_to_github(local_path, repo_path, commit_msg):
    """GitHub REST API로 파일 업로드/업데이트"""
    import base64, json
    ensure("requests")
    import requests

    token  = cfg.get("GITHUB_TOKEN","")
    repo   = cfg.get("GITHUB_REPO","baemantotoro/imgroot")
    branch = cfg.get("GITHUB_BRANCH","main")

    if not token:
        print("[GitHub] GITHUB_TOKEN 없음, 건너뜀")
        return None

    with open(local_path,"rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    api_url = f"https://api.github.com/repos/{repo}/contents/{repo_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # 기존 파일 SHA 조회 (업데이트 시 필요)
    sha = None
    r = requests.get(api_url, headers=headers, params={"ref": branch}, timeout=15)
    if r.status_code == 200:
        sha = r.json().get("sha")

    payload = {"message": commit_msg, "content": content_b64, "branch": branch}
    if sha:
        payload["sha"] = sha

    r2 = requests.put(api_url, headers=headers, data=json.dumps(payload), timeout=30)
    if r2.status_code in (200, 201):
        info = r2.json().get("content", {})
        print(f"[GitHub] 업로드 완료: {repo_path}")
        return info.get("html_url","")
    else:
        print(f"[GitHub] 업로드 실패 {r2.status_code}: {r2.text[:200]}")
        return None


def github_pages_url(date_str):
    """GitHub Pages HTML 링크 반환"""
    ym = date_str[:7].replace("-","_")   # 2026_06
    ymd = date_str.replace("-","_")      # 2026_06_18
    return f"https://baemantotoro.github.io/imgroot/daily_insight/{ym}/{ymd}.html"


if __name__ == "__main__": main()
