import traceback, sys, json, urllib.parse, urllib.request, xml.etree.ElementTree as ET, re
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf

APP = Path(__file__).resolve().parent
CACHE = APP / "yf_cache"
CACHE.mkdir(exist_ok=True)

try:
    yf.set_tz_cache_location(str(CACHE))
except Exception:
    pass

TICKERS = APP / "tickers_bist.txt"
REPORT = APP / "Quant_Scanner_Rapor.txt"
EXCEL = APP / "Quant_Scanner_Excel_Raporu.xlsx"
HISTORY = APP / "scanner_history.json"
LOG = APP / "quant_scanner_log.txt"

def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass

def onecol(x):
    if x is None:
        return None
    return x.iloc[:, 0] if isinstance(x, pd.DataFrame) else x

def sf(v, default=np.nan):
    try:
        if v is None or pd.isna(v):
            return default
        return float(v)
    except Exception:
        return default

def fetch(ticker, period="5y"):
    errs = []
    try:
        d = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
        if d is not None and not d.empty:
            return d, "history"
        errs.append("history boş")
    except Exception as e:
        errs.append(f"history {type(e).__name__}: {e}")

    try:
        d = yf.download(
            ticker, period=period, interval="1d",
            auto_adjust=False, progress=False, threads=False, group_by="column"
        )
        if d is not None and not d.empty:
            return d, "download"
        errs.append("download boş")
    except Exception as e:
        errs.append(f"download {type(e).__name__}: {e}")

    msg = " | ".join(errs) if errs else "veri alınamadı"
    log(f"{ticker}: {msg}")
    return None, msg

def indicators(df):
    if df is None or getattr(df, "empty", True):
        return None
    try:
        for col in ("Close", "High", "Low"):
            if col not in df:
                return None

        c = pd.to_numeric(onecol(df["Close"]), errors="coerce").dropna()
        h = pd.to_numeric(onecol(df["High"]), errors="coerce").reindex(c.index)
        l = pd.to_numeric(onecol(df["Low"]), errors="coerce").reindex(c.index)

        if "Volume" in df:
            v = pd.to_numeric(onecol(df["Volume"]), errors="coerce").reindex(c.index).fillna(0)
        else:
            v = pd.Series(0.0, index=c.index)

        if len(c) < 260:
            return None

        x = pd.DataFrame(index=c.index)
        x["close"] = c
        for n in (20, 50, 200):
            x[f"ma{n}"] = c.rolling(n).mean()

        delta = c.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        ag = gain.ewm(alpha=1/14, adjust=False).mean()
        al = loss.ewm(alpha=1/14, adjust=False).mean()
        rs = ag / al.replace(0, np.nan)
        x["rsi"] = (100 - 100/(1+rs)).fillna(50)

        e12 = c.ewm(span=12, adjust=False).mean()
        e26 = c.ewm(span=26, adjust=False).mean()
        x["macd"] = e12 - e26
        x["macds"] = x["macd"].ewm(span=9, adjust=False).mean()

        prev = c.shift(1)
        tr = pd.concat([(h-l).abs(), (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
        x["atr"] = tr.rolling(14).mean()
        x["atrp"] = x["atr"] / c * 100

        x["vol20"] = v.rolling(20).mean()
        x["volr"] = v / x["vol20"].replace(0, np.nan)

        x["lo20"] = l.rolling(20).min()
        x["lo252"] = l.rolling(252).min()
        x["hi55"] = h.rolling(55).max()
        x["hi252"] = h.rolling(252).max()

        for n, name in ((21, "r1m"), (63, "r3m"), (105, "r5m"), (252, "r12m")):
            x[name] = c.pct_change(n) * 100

        x["dd252"] = (c / x["hi252"] - 1) * 100
        return x
    except Exception as e:
        log(f"indicator hata: {type(e).__name__}: {e}")
        return None

def technical_score(ind, bench=None, mult=1.0, metal=False):
    if ind is None or ind.empty:
        return None

    z = ind.iloc[-1]
    p = sf(z.get("close"))
    if pd.isna(p):
        return None

    s = 0
    why = []

    def add(cond, pts, txt):
        nonlocal s
        try:
            if bool(cond):
                s += pts
                why.append(txt)
        except Exception:
            pass

    m20, m50, m200 = sf(z.get("ma20")), sf(z.get("ma50")), sf(z.get("ma200"))
    rsi = sf(z.get("rsi"), 50)
    macd, macds = sf(z.get("macd"), 0), sf(z.get("macds"), 0)
    r1, r3, r5, r12 = sf(z.get("r1m"), 0), sf(z.get("r3m"), 0), sf(z.get("r5m"), 0), sf(z.get("r12m"), 0)
    vr = sf(z.get("volr"), 1)
    atr, atrp = sf(z.get("atr"), 0), sf(z.get("atrp"), 0)
    hi, lo = sf(z.get("hi55"), p), sf(z.get("lo20"), p)
    dd = sf(z.get("dd252"), 0)

    add(not pd.isna(m20) and p > m20, 8, "MA20 üstü")
    add(not pd.isna(m50) and p > m50, 10, "MA50 üstü")
    add(not pd.isna(m200) and p > m200, 12, "MA200 üstü")
    add(not pd.isna(m20) and not pd.isna(m50) and m20 > m50, 8, "20>50")
    add(not pd.isna(m50) and not pd.isna(m200) and m50 > m200, 10, "50>200")
    add(macd > macds, 8, "MACD+")
    add(50 <= rsi <= 68, 8, "RSI dengeli")
    add(r1 > 0, 4, "1A+")
    add(r3 > 0, 5, "3A+")
    add(r5 > 0, 4, "5A+")

    if not metal:
        add(vr >= 1.2, 6, "Hacim+")
        add(p >= hi * .995 and vr >= 1.15, 8, "55G kırılım")
    else:
        add(p >= hi * .995, 5, "55G kırılım")

    rel = np.nan
    if bench is not None and not bench.empty:
        br3 = sf(bench.iloc[-1].get("r3m"))
        if not pd.isna(br3):
            rel = r3 - br3
            if rel > 5:
                s += 7
                why.append("Relatif güç+")
            elif rel < 0:
                s -= 5

    if not pd.isna(m20) and m20 and (p/m20 - 1)*100 > 15:
        s -= 10
    if rsi > 75:
        s -= 10
    if atrp > 6:
        s -= 5
    if dd < -30:
        s -= 4

    s = int(max(0, min(100, round(s * mult))))

    if rsi >= 76 or (not pd.isna(m20) and m20 and (p/m20-1)*100 > 15):
        phase = "AŞIRI ISINMIŞ"
    elif p >= hi*.995 and vr >= 1.15:
        phase = "KIRILIM"
    elif not any(pd.isna(q) for q in (m20,m50,m200)) and p > m50 and p > m200 and m20 > m50 and rsi >= 50:
        phase = "GÜÇLÜ TREND"
    elif not any(pd.isna(q) for q in (m20,m50,m200)) and p > m200 and m20 > m50 and 45 <= rsi <= 62:
        phase = "ERKEN / DÖNÜŞ"
    elif not pd.isna(m200) and p < m200:
        phase = "ZAYIF TREND"
    else:
        phase = "KARMA"

    stop = max(lo, p - 2*atr) if atr > 0 else lo
    risk = max(p-stop, 0.0001)
    target = max(hi, p + 3*atr) if atr > 0 else hi
    rr = max(0, (target-p)/risk)

    return {
        "TeknikPuan": s,
        "Evre": phase,
        "Fiyat": round(p,2),
        "RSI": round(rsi,1),
        "ATR%": round(atrp,2),
        "1Ay%": round(r1,2),
        "3Ay%": round(r3,2),
        "5Ay%": round(r5,2),
        "12Ay%": round(r12,2),
        "Relatif3Ay%": round(rel,2) if not pd.isna(rel) else "",
        "Destek": round(lo,2),
        "Direnc": round(hi,2),
        "ATR_Stop": round(stop,2),
        "ATR_Hedef": round(target,2),
        "RiskOdul": round(rr,2),
        "52H_Zirve_Uzaklik%": round(dd,2),
        "TeknikNeden": "; ".join(why)
    }

def fundamental_engine(ticker):
    out = {
        "TemelPuan": 50,
        "TemelDurum": "VERİ SINIRLI",
        "CiroBuyume%": "",
        "NetKarBuyume%": "",
        "ROE%": "",
        "BorcOzsermaye": "",
        "CariOran": "",
        "FK": "",
        "PDDD": "",
        "TemelNeden": ""
    }
    try:
        info = yf.Ticker(ticker).info or {}
        vals = {
            "rev": sf(info.get("revenueGrowth")),
            "earn": sf(info.get("earningsGrowth")),
            "roe": sf(info.get("returnOnEquity")),
            "de": sf(info.get("debtToEquity")),
            "cur": sf(info.get("currentRatio")),
            "pe": sf(info.get("trailingPE")),
            "pb": sf(info.get("priceToBook"))
        }

        score = 50
        known = 0
        reasons = []

        if not pd.isna(vals["rev"]):
            known += 1
            out["CiroBuyume%"] = round(vals["rev"]*100,1)
            if vals["rev"] > .20: score += 12; reasons.append("Ciro güçlü")
            elif vals["rev"] > .05: score += 6
            elif vals["rev"] < 0: score -= 10; reasons.append("Ciro daralıyor")

        if not pd.isna(vals["earn"]):
            known += 1
            out["NetKarBuyume%"] = round(vals["earn"]*100,1)
            if vals["earn"] > .25: score += 15; reasons.append("Kâr güçlü")
            elif vals["earn"] > .05: score += 7
            elif vals["earn"] < 0: score -= 15; reasons.append("Kâr geriliyor")

        if not pd.isna(vals["roe"]):
            known += 1
            out["ROE%"] = round(vals["roe"]*100,1)
            if vals["roe"] > .25: score += 12
            elif vals["roe"] > .12: score += 6
            elif vals["roe"] < .05: score -= 8

        if not pd.isna(vals["de"]):
            known += 1
            out["BorcOzsermaye"] = round(vals["de"],1)
            if vals["de"] < 60: score += 7
            elif vals["de"] > 200: score -= 12; reasons.append("Borç yüksek")

        if not pd.isna(vals["cur"]):
            known += 1
            out["CariOran"] = round(vals["cur"],2)
            if vals["cur"] >= 1.5: score += 5
            elif vals["cur"] < .8: score -= 7

        if not pd.isna(vals["pe"]):
            known += 1
            out["FK"] = round(vals["pe"],2)
            if 0 < vals["pe"] < 12: score += 5
            elif vals["pe"] > 35: score -= 5

        if not pd.isna(vals["pb"]):
            known += 1
            out["PDDD"] = round(vals["pb"],2)
            if 0 < vals["pb"] < 2.5: score += 3
            elif vals["pb"] > 8: score -= 3

        if known == 0:
            out["TemelDurum"] = "VERİ ALINAMADI"
            out["TemelNeden"] = "Yahoo temel veri sağlamadı"
            return out

        score = int(max(0, min(100, score)))
        out["TemelPuan"] = score
        out["TemelDurum"] = "GÜÇLÜ" if score >= 75 else "OLUMLU" if score >= 60 else "KARMA" if score >= 45 else "ZAYIF"
        out["TemelNeden"] = "; ".join(reasons) if reasons else "Temel görünüm nötr"
        return out
    except Exception as e:
        log(f"{ticker} fundamental: {type(e).__name__}: {e}")
        out["TemelDurum"] = "HATA"
        out["TemelNeden"] = str(e)
        return out

def pct_change(df, periods):
    try:
        c = pd.to_numeric(onecol(df["Close"]), errors="coerce").dropna()
        if len(c) <= periods:
            return np.nan
        return float((c.iloc[-1]/c.iloc[-1-periods]-1)*100)
    except Exception:
        return np.nan

def news_risk():
    out = {"HaberPuan": 50, "HaberDurum": "VERİ YOK", "HaberNeden": ""}
    try:
        q = urllib.parse.quote("Türkiye ekonomi jeopolitik risk savaş yaptırım gerilim piyasalar")
        url = f"https://news.google.com/rss/search?q={q}&hl=tr&gl=TR&ceid=TR:tr"
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read()

        root = ET.fromstring(raw)
        titles = [(i.findtext("title") or "").lower() for i in root.findall(".//item")[:30]]

        bad = ["savaş","çatışma","gerilim","yaptırım","kriz","saldırı","ambargo","belirsizlik","daralma"]
        good = ["ateşkes","anlaşma","normalleşme","istikrar","barış","uzlaşma","iyileşme"]

        risk_hits = sum(sum(1 for k in bad if k in t) for t in titles)
        good_hits = sum(sum(1 for k in good if k in t) for t in titles)

        score = 60 - min(35, risk_hits*3) + min(20, good_hits*4)
        score = int(max(10, min(90, score)))

        out["HaberPuan"] = score
        out["HaberDurum"] = "DÜŞÜK RİSK" if score >= 70 else "ORTA RİSK" if score >= 45 else "YÜKSEK RİSK"
        out["HaberNeden"] = f"Risk eşleşmesi {risk_hits}, olumlu eşleşme {good_hits}"
        return out
    except Exception as e:
        out["HaberNeden"] = f"Haber akışı alınamadı: {type(e).__name__}"
        return out

def macro_engine():
    result = {
        "MakroPuan": 50, "MakroDurum": "KARMA",
        "JeopolitikPuan": 50, "JeopolitikDurum": "ORTA RİSK",
        "USDTRY_3Ay%": "", "Brent_3Ay%": "", "Altin_3Ay%": "", "VIX_1Ay%": "",
        "MakroNeden": "", "JeopolitikNeden": ""
    }

    assets = {"usd":"TRY=X", "brent":"BZ=F", "gold":"GC=F", "vix":"^VIX", "bist":"XU100.IS"}
    data = {}
    for k,t in assets.items():
        d,_ = fetch(t, "1y")
        data[k] = d

    usd3 = pct_change(data["usd"],63) if data["usd"] is not None else np.nan
    brent3 = pct_change(data["brent"],63) if data["brent"] is not None else np.nan
    gold3 = pct_change(data["gold"],63) if data["gold"] is not None else np.nan
    vix1 = pct_change(data["vix"],21) if data["vix"] is not None else np.nan
    bist3 = pct_change(data["bist"],63) if data["bist"] is not None else np.nan

    result["USDTRY_3Ay%"] = "" if pd.isna(usd3) else round(usd3,2)
    result["Brent_3Ay%"] = "" if pd.isna(brent3) else round(brent3,2)
    result["Altin_3Ay%"] = "" if pd.isna(gold3) else round(gold3,2)
    result["VIX_1Ay%"] = "" if pd.isna(vix1) else round(vix1,2)

    macro = 55
    reasons = []
    if not pd.isna(bist3):
        if bist3 > 8: macro += 12
        elif bist3 < -8: macro -= 12; reasons.append("BIST zayıf")
    if not pd.isna(usd3):
        if usd3 > 12: macro -= 12; reasons.append("Kur baskısı")
        elif usd3 < 5: macro += 5
    if not pd.isna(brent3) and brent3 > 15:
        macro -= 8; reasons.append("Petrol baskısı")
    if not pd.isna(vix1):
        if vix1 > 25: macro -= 10; reasons.append("VIX yüksek")
        elif vix1 < -15: macro += 5
    macro = int(max(0, min(100, macro)))

    news = news_risk()
    geo = 60
    greasons = []
    if not pd.isna(vix1) and vix1 > 25:
        geo -= 15; greasons.append("VIX")
    if not pd.isna(brent3) and brent3 > 15:
        geo -= 12; greasons.append("Petrol")
    if not pd.isna(gold3) and gold3 > 12:
        geo -= 8; greasons.append("Altın güvenli liman")
    if not pd.isna(usd3) and usd3 > 12:
        geo -= 8; greasons.append("Kur stresi")
    geo = int(max(0, min(100, geo*.6 + news["HaberPuan"]*.4)))

    result["MakroPuan"] = macro
    result["MakroDurum"] = "DESTEKLEYİCİ" if macro >= 70 else "NÖTR" if macro >= 45 else "BASKILI"
    result["JeopolitikPuan"] = geo
    result["JeopolitikDurum"] = "DÜŞÜK RİSK" if geo >= 70 else "ORTA RİSK" if geo >= 45 else "YÜKSEK RİSK"
    result["MakroNeden"] = "; ".join(reasons) if reasons else "Makro göstergeler nötr"
    result["JeopolitikNeden"] = "; ".join(greasons + [news["HaberNeden"]])
    return result



def signal_validation_engine(ind):
    """
    Bugünkü teknik koşullara benzeyen geçmiş sinyallerde 2/3/5 işlem günü
    sonrası getiri ve Maximum Adverse Excursion (MAE) ölçer.
    Sinyal günü yalnızca o güne kadar oluşmuş indikatörler kullanılır.
    """
    out={
        "BT_SinyalSayisi":0,
        "BT_2G_Kazanma%":"","BT_3G_Kazanma%":"","BT_5G_Kazanma%":"",
        "BT_2G_OrtGetiri%":"","BT_3G_OrtGetiri%":"","BT_5G_OrtGetiri%":"",
        "BT_2G_OrtMAE%":"","BT_3G_OrtMAE%":"","BT_5G_OrtMAE%":"",
        "BT_EnKotuMAE%":"","BT_Guven":"YETERSİZ VERİ","BT_Not":""
    }
    try:
        if ind is None or len(ind)<140:
            out["BT_Not"]="Yeterli tarihsel veri yok."
            return out

        x=ind.copy().reset_index(drop=True)

        # Normal trend sinyali
        trend=(
            (x["close"]>x["ma20"]) &
            (x["rsi"].between(45,72)) &
            (x["macd"]>x["macds"]) &
            (x["r1m"]>-5) &
            (x["atrp"]<7)
        )

        # Dipten dönüş sinyali
        prsi=x["rsi"].shift(1)
        pmacd=x["macd"].shift(1)
        psig=x["macds"].shift(1)
        dip=(
            (x["close"]<=x["lo252"]*1.12) &
            (
                ((prsi<35)&(x["rsi"]>=35)) |
                ((pmacd<=psig)&(x["macd"]>x["macds"]))
            ) &
            (x["atrp"]<7)
        )

        sig=(trend|dip).fillna(False)
        records=[]
        last_signal=-99

        for i in range(len(x)-5):
            if not bool(sig.iloc[i]):
                continue
            # Aynı trend içindeki ardışık günleri tek sinyal gibi say.
            if i-last_signal<3:
                continue
            last_signal=i

            entry=sf(x.loc[i,"close"])
            if pd.isna(entry) or entry<=0:
                continue

            rec={}
            for h in (2,3,5):
                exitp=sf(x.loc[i+h,"close"])
                if pd.isna(exitp):
                    continue
                rec[f"r{h}"]=(exitp/entry-1)*100
                lows=pd.to_numeric(x.loc[i+1:i+h,"low"],errors="coerce").dropna()
                rec[f"m{h}"]=((float(lows.min())/entry)-1)*100 if len(lows) else np.nan
            records.append(rec)

        out["BT_SinyalSayisi"]=len(records)
        if len(records)<8:
            out["BT_Not"]="Benzer geçmiş sinyal sayısı az; istatistik zayıf."
            return out

        bt=pd.DataFrame(records)
        all_mae=[]
        for h in (2,3,5):
            r=pd.to_numeric(bt.get(f"r{h}"),errors="coerce").dropna()
            m=pd.to_numeric(bt.get(f"m{h}"),errors="coerce").dropna()
            if len(r):
                out[f"BT_{h}G_Kazanma%"]=round(float((r>0).mean()*100),1)
                out[f"BT_{h}G_OrtGetiri%"]=round(float(r.mean()),2)
            if len(m):
                out[f"BT_{h}G_OrtMAE%"]=round(float(m.mean()),2)
                all_mae.extend(m.tolist())

        if all_mae:
            out["BT_EnKotuMAE%"]=round(float(min(all_mae)),2)

        n=len(records)
        win3=sf(out["BT_3G_Kazanma%"],0)
        avg3=sf(out["BT_3G_OrtGetiri%"],0)
        mae3=sf(out["BT_3G_OrtMAE%"],-99)

        if n>=30 and win3>=60 and avg3>0 and mae3>-4:
            out["BT_Guven"]="GÜÇLÜ"
        elif n>=15 and win3>=55 and avg3>0 and mae3>-6:
            out["BT_Guven"]="ORTA"
        else:
            out["BT_Guven"]="ZAYIF"

        out["BT_Not"]="Teknik geçmiş doğrulama; geçmiş başarı gelecek sonucu garanti etmez."
        return out
    except Exception as e:
        log(f"backtest: {type(e).__name__}: {e}")
        out["BT_Not"]=str(e)
        return out

def dip_hunter_engine(ind, tech, fund, macro, social=None):
    out={"DipPuan":0,"DipDurum":"DİP ADAYI DEĞİL","DiptenUzaklik%":"",
         "DipTeyitSayisi":0,"DipNeden":""}
    try:
        if ind is None or ind.empty: return out
        z=ind.iloc[-1]
        p=sf(z.get("close")); low=sf(z.get("lo252"))
        if pd.isna(p) or pd.isna(low) or low<=0: return out
        dist=(p/low-1)*100
        out["DiptenUzaklik%"]=round(dist,2)
        if dist>20:
            out["DipNeden"]="52 haftalık dip bölgesinden uzak"; return out

        score=30 if dist<=3 else 24 if dist<=7 else 16 if dist<=12 else 7
        confirms=0; why=[]
        rsi=sf(z.get("rsi"),50); prev_rsi=sf(ind["rsi"].iloc[-2],50)
        macd=sf(z.get("macd"),0); sig=sf(z.get("macds"),0)
        pmacd=sf(ind["macd"].iloc[-2],0); psig=sf(ind["macds"].iloc[-2],0)
        ma20=sf(z.get("ma20")); ma50=sf(z.get("ma50"))
        prevc=sf(ind["close"].iloc[-2],p); prevma=sf(ind["ma20"].iloc[-2],ma20)
        volr=sf(z.get("volr"),1); r1=sf(z.get("r1m"),0); r3=sf(z.get("r3m"),0)
        atrp=sf(z.get("atrp"),0); f=sf(fund.get("TemelPuan"),50); m=sf(macro.get("MakroPuan"),50)
        hype=sf((social or {}).get("SosyalCoskuRiski"),0)

        if prev_rsi<35 and rsi>=35 and rsi>prev_rsi:
            score+=16; confirms+=1; why.append("RSI aşırı satımdan dönüyor")
        elif 35<=rsi<=52 and rsi>prev_rsi:
            score+=8; confirms+=1; why.append("RSI toparlanıyor")
        if macd>sig and pmacd<=psig:
            score+=16; confirms+=1; why.append("MACD yukarı kesişim")
        elif macd>sig:
            score+=8; confirms+=1; why.append("MACD pozitif")
        if not pd.isna(ma20) and p>ma20 and prevc<=prevma:
            score+=14; confirms+=1; why.append("MA20 geri alındı")
        elif not pd.isna(ma20) and p>ma20:
            score+=7; confirms+=1
        if volr>=1.5:
            score+=12; confirms+=1; why.append("hacimli dönüş")
        elif volr>=1.15:
            score+=6; confirms+=1; why.append("hacim teyidi")
        if r1>0:
            score+=8; confirms+=1; why.append("1A momentum pozitif")
        if not pd.isna(ma20) and not pd.isna(ma50) and ma20<ma50 and p<ma20:
            score-=12; why.append("düşen trend sürüyor")
        if r3<-20: score-=10; why.append("3A sert negatif")
        if atrp>=7: score-=10; why.append("volatilite yüksek")
        if f<40: score-=12; why.append("temel zayıf")
        if m<38: score-=8; why.append("makro baskı")
        if hype>=70: score-=8; why.append("sosyal coşku riski")

        score=int(max(0,min(100,score)))
        out["DipPuan"]=score; out["DipTeyitSayisi"]=confirms
        if dist<=12 and score>=72 and confirms>=3 and f>=45 and atrp<7:
            durum="DİPTEN DÖNÜŞ - ALIM İÇİN ADAY"
        elif dist<=12 and score>=55 and confirms>=2:
            durum="DİP BÖLGESİ - TEYİT BEKLE"
        elif dist<=12:
            durum="DİBE YAKIN AMA ALMA"
        else:
            durum="DİP ADAYI DEĞİL"
        out["DipDurum"]=durum; out["DipNeden"]="; ".join(why)
        return out
    except Exception as e:
        log(f"dip hunter: {type(e).__name__}: {e}")
        out["DipDurum"]="DİP ANALİZ HATASI"; out["DipNeden"]=str(e); return out

def _fetch_xml_titles(url, timeout=7):
    titles = []
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) QuantScanner/6.2",
                "Accept":"application/rss+xml, application/xml, text/xml, */*"
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        root = ET.fromstring(raw)
        for item in root.findall(".//item"):
            t = item.findtext("title") or ""
            if t.strip():
                titles.append(t.strip())
        if not titles:
            for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                el = entry.find("{http://www.w3.org/2005/Atom}title")
                if el is not None and (el.text or "").strip():
                    titles.append(el.text.strip())
    except Exception as e:
        log(f"RSS hata {url}: {type(e).__name__}: {e}")
    return titles

def social_sentiment_engine(symbol):
    """
    Kamuya açık başlık/yorum akışlarından kısa vadeli duyarlılık.
    Kaynak bulunamazsa puan uydurmaz, kapsama 0 döndürür.
    Sosyal puan tek başına AL sinyali oluşturmaz.
    """
    sym = symbol.replace(".IS","").upper()
    out = {
        "SosyalPuan":"",
        "SosyalDurum":"VERİ YOK",
        "SosyalKapsam":0,
        "SosyalPozitif":0,
        "SosyalNegatif":0,
        "SosyalCoskuRiski":0,
        "SosyalKaynak":"",
        "SosyalNeden":""
    }

    titles = []
    sources = []

    # Google News RSS: haber + yorum/analiz başlıkları
    for q in (
        f"{sym} Borsa İstanbul hisse",
        f"{sym} teknik analiz",
        f"{sym} yatırımcı yorum"
    ):
        try:
            qq = urllib.parse.quote(q)
            url = f"https://news.google.com/rss/search?q={qq}&hl=tr&gl=TR&ceid=TR:tr"
            got = _fetch_xml_titles(url)
            if got:
                titles.extend(got[:20])
                sources.append("GoogleNews")
        except Exception as e:
            log(f"{sym} GoogleNews: {type(e).__name__}: {e}")

    # Reddit public RSS search. Erişilemezse sessizce atlanır.
    try:
        qq = urllib.parse.quote(f"{sym} BIST")
        reddit_url = f"https://www.reddit.com/search.rss?q={qq}&sort=new&t=week"
        got = _fetch_xml_titles(reddit_url)
        if got:
            titles.extend(got[:20])
            sources.append("Reddit")
    except Exception as e:
        log(f"{sym} Reddit: {type(e).__name__}: {e}")

    # Yahoo Finance haber başlıkları
    try:
        news = yf.Ticker(sym + ".IS").news or []
        ytitles = []
        for item in news[:20]:
            if isinstance(item, dict):
                title = item.get("title")
                if not title and isinstance(item.get("content"), dict):
                    title = item["content"].get("title")
                if title:
                    ytitles.append(str(title))
        if ytitles:
            titles.extend(ytitles)
            sources.append("YahooNews")
    except Exception as e:
        log(f"{sym} YahooNews: {type(e).__name__}: {e}")

    # normalize and de-duplicate
    clean = []
    seen = set()
    for t in titles:
        x = re.sub(r"\s+"," ",str(t)).strip()
        key = re.sub(r"[^a-zA-Z0-9çğıöşüÇĞİÖŞÜ]+"," ",x.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            clean.append(x)

    if not clean:
        out["SosyalNeden"] = "Kamuya açık güncel başlık/yorum akışı alınamadı."
        return out

    positive = [
        "alım","güçlü","yükseliş","pozitif","hedef","rekor","büyüme","kâr artışı",
        "kar artışı","olumlu","toparlanma","kırılım","yukarı","prim","iyi bilanço",
        "beklenti üstü","temettü","geri alım"
    ]
    negative = [
        "satış","düşüş","negatif","zarar","risk","ceza","soruşturma","borç","daralma",
        "beklenti altı","aşağı","zayıf","sert satış","uyarı","kayba","gerileme",
        "iflas","konkordato","dava"
    ]
    hype = [
        "uçacak","roket","tavan","kaçırma","kaçırmayın","kesin yükselecek","katlayacak",
        "patlayacak","bedava","fırsat kaçmaz","hedef x","10x","5x","garanti"
    ]

    pos = neg = hype_hits = 0
    for t in clean:
        low = t.lower()
        pos += sum(1 for k in positive if k in low)
        neg += sum(1 for k in negative if k in low)
        hype_hits += sum(1 for k in hype if k in low)

    mentions = len(clean)
    raw = 50 + min(30, pos*3) - min(35, neg*4)
    score = int(max(10, min(90, raw)))
    hype_risk = int(max(0, min(100, hype_hits*18 + max(0, mentions-25)*2)))

    if score >= 65:
        label = "OLUMLU"
    elif score <= 40:
        label = "OLUMSUZ"
    else:
        label = "KARMA"

    out.update({
        "SosyalPuan":score,
        "SosyalDurum":label,
        "SosyalKapsam":mentions,
        "SosyalPozitif":pos,
        "SosyalNegatif":neg,
        "SosyalCoskuRiski":hype_risk,
        "SosyalKaynak":"+".join(sorted(set(sources))) if sources else "RSS",
        "SosyalNeden":f"{mentions} benzersiz başlık; +{pos} / -{neg}; coşku eşleşmesi {hype_hits}"
    })
    return out


def capital_protection(tech, fund, macro, social=None):
    risk, reasons = 0, []
    rsi=sf(tech.get("RSI"),50); atr=sf(tech.get("ATR%"),0)
    r1=sf(tech.get("1Ay%"),0); r3=sf(tech.get("3Ay%"),0)
    rel=sf(tech.get("Relatif3Ay%"),0); rr=sf(tech.get("RiskOdul"),0)
    f=sf(fund.get("TemelPuan"),50); m=sf(macro.get("MakroPuan"),50); g=sf(macro.get("JeopolitikPuan"),50)
    phase=str(tech.get("Evre",""))
    social = social or {}
    sp = sf(social.get("SosyalPuan"), np.nan)
    scov = int(sf(social.get("SosyalKapsam"), 0))
    hype = sf(social.get("SosyalCoskuRiski"), 0)

    def add(cond, pts, why):
        nonlocal risk
        if cond: risk += pts; reasons.append(why)

    add(atr>=7,24,"çok yüksek volatilite"); add(5<=atr<7,14,"yüksek volatilite")
    add(rsi>=78,22,"RSI aşırı ısınmış"); add(70<=rsi<78,10,"RSI yüksek")
    add("AŞIRI ISINMIŞ" in phase,18,"fiyat aşırı uzamış")
    add(r1<-8,18,"1 aylık momentum sert negatif"); add(-8<=r1<-3,9,"1 aylık momentum negatif")
    add(r3<0,9,"3 aylık trend negatif"); add(rel<-5,10,"endekse göre güç kaybı")
    add(rr<1,18,"risk/ödül yetersiz"); add(1<=rr<1.5,8,"risk/ödül düşük")
    add(f<40,15,"şirket temeli zayıf"); add(m<40,18,"makro ortam baskılı"); add(g<40,14,"jeopolitik risk yüksek")

    # Sosyal medya/forum verisi sadece teyit veya risk filtresi olarak kullanılır.
    if scov >= 5 and not pd.isna(sp):
        add(sp <= 35, 10, "sosyal/yorum duyarlılığı olumsuz")
        add(hype >= 50 and rsi >= 68, 16, "sosyal coşku + yüksek RSI")
        add(hype >= 70, 12, "manipülasyon/coşku riski")
        add(scov >= 25 and sp >= 75 and r1 > 12, 10, "kalabalık işlem / kovalamaca riski")

    risk=int(max(0,min(100,risk)))
    veto = atr>=8 or rsi>=82 or rr<0.8 or m<32 or g<30 or f<30 or (r1<-8 and rel<-5) or (hype>=80 and rsi>=72)
    karar="ALMA" if veto or risk>=65 else "BEKLE" if risk>=40 else "AL İÇİN ADAY"
    return {"CakilmaRiski":risk,"KorumaKarari":karar,
            "KorumaNedeni":"; ".join(reasons) if reasons else "belirgin risk alarmı yok"}

def combined(technical, fundamental, macro, social=None):
    t = int(technical.get("TeknikPuan",50))
    f = int(fundamental.get("TemelPuan",50))
    m = int(macro.get("MakroPuan",50))
    g = int(macro.get("JeopolitikPuan",50))
    base = t*.35 + f*.30 + m*.20 + g*.15

    social = social or {}
    sp = sf(social.get("SosyalPuan"), np.nan)
    cov = int(sf(social.get("SosyalKapsam"), 0))
    hype = sf(social.get("SosyalCoskuRiski"), 0)

    # Social sentiment is only a small confirmation/penalty, never the main driver.
    adj = 0
    if cov >= 5 and not pd.isna(sp):
        adj += max(-5, min(5, (sp-50)/6))
        if hype >= 60:
            adj -= min(8, (hype-50)/6)

    total = int(max(0, min(100, round(base + adj))))
    if total >= 80: label = "ÇOK GÜÇLÜ ADAY"
    elif total >= 70: label = "GÜÇLÜ ADAY"
    elif total >= 60: label = "İZLE"
    elif total >= 45: label = "KARMA / TAKİP"
    else: label = "UZAK DUR / ZAYIF"
    return total, label

def load_history():
    try:
        if HISTORY.exists():
            h = json.loads(HISTORY.read_text(encoding="utf-8"))
            return h[-10:] if isinstance(h,list) else []
    except Exception as e:
        log(f"history read: {e}")
    return []

def save_history(df):
    try:
        b = df[df["Tur"]=="BIST"]
        snap = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "scores": {str(r["Varlik"]): int(r["GenelPuan"]) for _,r in b.iterrows()}
        }
        h = load_history()
        h.append(snap)
        HISTORY.write_text(json.dumps(h[-10:], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log(f"history save: {e}")

def stability(df):
    b = df[df["Tur"]=="BIST"]
    hist = load_history()
    current = {str(r["Varlik"]): int(r["GenelPuan"]) for _,r in b.iterrows()}
    snaps = [h.get("scores",{}) for h in hist[-4:]] + [current]
    rows = []

    for _,r in b.iterrows():
        name = str(r["Varlik"])
        vals = [sf(s.get(name)) for s in snaps]
        vals = [v for v in vals if not pd.isna(v)]
        if not vals:
            continue
        avg = float(np.mean(vals))
        std = float(np.std(vals)) if len(vals)>1 else 0
        top10 = 0
        for s in snaps:
            ranked = sorted([(k,sf(v,-999)) for k,v in s.items()], key=lambda q:q[1], reverse=True)[:10]
            if name in [k for k,_ in ranked]:
                top10 += 1
        persist = 100*top10/len(snaps)
        stable = max(0,min(100,avg*.72 + persist*.28 - std*.8))
        rows.append({
            "Varlik":name,
            "AnlikGenelPuan":int(r["GenelPuan"]),
            "OrtalamaPuan":round(avg,1),
            "PuanSapma":round(std,1),
            "Top10Kalis%":round(persist,1),
            "IstikrarPuani":round(stable,1)
        })

    return pd.DataFrame(rows).sort_values(["IstikrarPuani","OrtalamaPuan"], ascending=False) if rows else pd.DataFrame()

def test_connection():
    d,src = fetch("THYAO.IS","1y")
    if d is None:
        return False,src
    c = pd.to_numeric(onecol(d["Close"]),errors="coerce").dropna()
    if c.empty:
        return False,"THYAO.IS kapanış verisi boş"
    return True,f"Bağlantı başarılı.\nTHYAO.IS: {float(c.iloc[-1]):.2f}\nKaynak: {src}"

def scan():
    if not TICKERS.exists():
        raise FileNotFoundError("tickers_bist.txt bulunamadı.")

    status.set("Makro ve jeopolitik risk hesaplanıyor...")
    root.update_idletasks()
    macro = macro_engine()

    status.set("BIST 100 verisi alınıyor...")
    bd,_ = fetch("XU100.IS")
    bench = indicators(bd)

    rows = []
    errors = []

    raw_names = [x.strip().upper() for x in TICKERS.read_text(encoding="utf-8-sig").splitlines() if x.strip()]
    names = []
    seen_names = set()
    for x in raw_names:
        if x == "MENKUL" or x in seen_names:
            continue
        seen_names.add(x)
        names.append(x)

    for i,n in enumerate(names,1):
        t = n.upper() if n.upper().endswith(".IS") else n.upper()+".IS"
        status.set(f"{i}/{len(names)} {t} — teknik analiz")
        root.update_idletasks()

        d,src = fetch(t)
        ind = indicators(d)
        if ind is None:
            errors.append(f"{t}: {src if d is None else 'veri yetersiz'}")
            continue

        tech = technical_score(ind, bench, 1.0, False)
        if tech is None:
            errors.append(f"{t}: teknik puan yok")
            continue

        status.set(f"{t} — şirket finansalları")
        root.update_idletasks()
        fund = fundamental_engine(t)

        status.set(f"{t} — sosyal medya / forum / haber duyarlılığı")
        root.update_idletasks()
        social = social_sentiment_engine(t)

        total, decision = combined(tech, fund, macro, social)
        protect = capital_protection(tech, fund, macro, social)
        dip = dip_hunter_engine(ind, tech, fund, macro, social)
        bt = signal_validation_engine(ind)
        if protect["KorumaKarari"] == "ALMA":
            final = "ALMA"
        elif protect["KorumaKarari"] == "BEKLE":
            final = "BEKLE / TEYİT"
        elif bt.get("BT_Guven") == "ZAYIF" and int(bt.get("BT_SinyalSayisi",0) or 0) >= 15:
            final = "BEKLE / GEÇMİŞ TEST ZAYIF"
        elif total >= 72 and tech["TeknikPuan"] >= 65 and fund["TemelPuan"] >= 45:
            final = "AL İÇİN ADAY"
        else:
            final = "BEKLE"

        row = {"Varlik":t.replace(".IS",""),"Tur":"BIST"}
        row.update(tech); row.update(fund); row.update(social); row.update(protect); row.update(dip); row.update(bt)
        row.update({
            "MakroPuan":macro["MakroPuan"],"MakroDurum":macro["MakroDurum"],
            "JeopolitikPuan":macro["JeopolitikPuan"],"JeopolitikDurum":macro["JeopolitikDurum"],
            "GenelPuan":total,"GenelKarar":decision,"NihaiKarar":final
        })
        rows.append(row)

    # Metals
    usd_d,_ = fetch("TRY=X")
    usd_ind = indicators(usd_d)
    usdtry = sf(usd_ind["close"].iloc[-1]) if usd_ind is not None else np.nan

    for label,t in (("ALTIN_ONS","GC=F"),("GUMUS_ONS","SI=F")):
        d,src = fetch(t)
        ind = indicators(d)
        if ind is None:
            errors.append(f"{label}: veri yok")
            continue
        tech = technical_score(ind, None, 1.0, True)
        total = int(round(tech["TeknikPuan"]*.55 + macro["MakroPuan"]*.20 + macro["JeopolitikPuan"]*.25))
        row = {"Varlik":label,"Tur":"METAL"}
        row.update(tech)
        row.update({
            "TemelPuan":"",
            "TemelDurum":"METAL",
            "MakroPuan":macro["MakroPuan"],
            "MakroDurum":macro["MakroDurum"],
            "JeopolitikPuan":macro["JeopolitikPuan"],
            "JeopolitikDurum":macro["JeopolitikDurum"],
            "GenelPuan":total,
             "GenelKarar":"GÜÇLÜ ADAY" if total>=70 else "İZLE" if total>=60 else "TAKİP",
            "SosyalPuan":"","SosyalDurum":"METAL","SosyalKapsam":0,"SosyalPozitif":0,
            "SosyalNegatif":0,"SosyalCoskuRiski":0,"SosyalKaynak":"","SosyalNeden":"",
            "DipPuan":"","DipDurum":"METAL","DiptenUzaklik%":"","DipTeyitSayisi":"","DipNeden":"",
            "BT_SinyalSayisi":"","BT_2G_Kazanma%":"","BT_3G_Kazanma%":"","BT_5G_Kazanma%":"",
            "BT_2G_OrtGetiri%":"","BT_3G_OrtGetiri%":"","BT_5G_OrtGetiri%":"",
            "BT_2G_OrtMAE%":"","BT_3G_OrtMAE%":"","BT_5G_OrtMAE%":"","BT_EnKotuMAE%":"",
            "BT_Guven":"METAL","BT_Not":"",
            "CakilmaRiski":"","KorumaKarari":"METAL","KorumaNedeni":"","NihaiKarar":"METAL"
        })
        if not pd.isna(usdtry):
            row["Yaklasik_TL_Gram"] = round(sf(ind["close"].iloc[-1]) * usdtry / 31.1034768, 2)
        rows.append(row)

    if not rows:
        raise RuntimeError("Hiç sonuç üretilemedi.")

    df = pd.DataFrame(rows).sort_values(["GenelPuan","TeknikPuan","RiskOdul"], ascending=False)
    stable = stability(df)

    bist = df[df["Tur"]=="BIST"]
    adaylar = bist[bist["NihaiKarar"]=="AL İÇİN ADAY"].sort_values(["CakilmaRiski","GenelPuan"],ascending=[True,False])
    anlik5 = adaylar.head(5)
    uzak10 = bist.sort_values(["CakilmaRiski","GenelPuan"],ascending=[False,True]).head(10)
    metals = df[df["Tur"]=="METAL"]
    dip_adaylari = bist[bist["DipDurum"]=="DİPTEN DÖNÜŞ - ALIM İÇİN ADAY"].sort_values(["DipPuan","CakilmaRiski"],ascending=[False,True]).head(10)
    dip_bekle = bist[bist["DipDurum"].isin(["DİP BÖLGESİ - TEYİT BEKLE","DİBE YAKIN AMA ALMA"])].sort_values(["DipPuan","DiptenUzaklik%"],ascending=[False,True]).head(15)

    lines = [
        "QUANT SCANNER v6.4 — BACKTEST & SIGNAL VALIDATION",
        "="*110,
        f"Makro: {macro['MakroPuan']}/100 {macro['MakroDurum']}",
        f"Jeopolitik: {macro['JeopolitikPuan']}/100 {macro['JeopolitikDurum']}",
        "Genel Puan = Teknik %35 + Temel %30 + Makro %20 + Jeopolitik %15",
        "Yatırım tavsiyesi değildir.",
        "",
        "ANLIK İLK 5",
        "-"*110
    ]

    for i,(_,r) in enumerate(anlik5.iterrows(),1):
        lines.append(
            f"{i}. {r['Varlik']} | GENEL {r['GenelPuan']} | {r['GenelKarar']} | "
            f"Teknik {r['TeknikPuan']} | Temel {r['TemelPuan']} | "
            f"Makro {r['MakroPuan']} | Jeopolitik {r['JeopolitikPuan']} | {r['Evre']}"
        )

    lines += ["","İSTİKRARLI İLK 5","-"*110]
    if not stable.empty:
        for i,(_,r) in enumerate(stable.head(5).iterrows(),1):
            lines.append(
                f"{i}. {r['Varlik']} | İstikrar {r['IstikrarPuani']} | "
                f"Ort {r['OrtalamaPuan']} | Anlık {r['AnlikGenelPuan']}"
            )

    lines += ["","UZAK DUR / EN ZAYIF 10","-"*110]
    for i,(_,r) in enumerate(uzak10.iterrows(),1):
        lines.append(
            f"{i}. {r['Varlik']} | GENEL {r['GenelPuan']} | {r['GenelKarar']} | "
            f"Teknik {r['TeknikPuan']} | Temel {r['TemelPuan']} | {r['Evre']}"
        )

    lines += ["","GEÇMİŞ SİNYAL DOĞRULAMA - 2 / 3 / 5 GÜN","-"*110]
    bt_show=bist.sort_values(["BT_3G_Kazanma%","BT_SinyalSayisi"],ascending=[False,False]).head(15)
    for i,(_,r) in enumerate(bt_show.iterrows(),1):
        lines.append(
            f"{i}. {r['Varlik']} | N={r['BT_SinyalSayisi']} | 2G Başarı %{r['BT_2G_Kazanma%']} | "
            f"3G Başarı %{r['BT_3G_Kazanma%']} | 5G Başarı %{r['BT_5G_Kazanma%']} | "
            f"3G Ort Getiri %{r['BT_3G_OrtGetiri%']} | 3G MAE %{r['BT_3G_OrtMAE%']} | {r['BT_Guven']}"
        )

    lines += ["","DİPTEN DÖNÜŞ ADAYLARI","-"*110]
    if dip_adaylari.empty:
        lines.append("BUGÜN DÖNÜŞ TEYİDİ YETERLİ DİP ADAYI YOK.")
    else:
        for i,(_,r) in enumerate(dip_adaylari.iterrows(),1):
            lines.append(f"{i}. {r['Varlik']} | DİP {r['DipPuan']}/100 | DİPTEN %{r['DiptenUzaklik%']} UZAK | TEYİT {r['DipTeyitSayisi']} | RİSK {r['CakilmaRiski']}/100")
    lines += ["","DİBE YAKIN - TEYİT BEKLE / ALMA","-"*110]
    for i,(_,r) in enumerate(dip_bekle.iterrows(),1):
        lines.append(f"{i}. {r['Varlik']} | DİP {r['DipPuan']} | DİPTEN %{r['DiptenUzaklik%']} UZAK | {r['DipDurum']}")
    lines += ["","ALTIN / GÜMÜŞ","-"*110]
    for _,r in metals.iterrows():
        lines.append(
            f"{r['Varlik']} | GENEL {r['GenelPuan']} | {r['GenelKarar']} | "
            f"Teknik {r['TeknikPuan']} | TL/gram≈{r.get('Yaklasik_TL_Gram','')}"
        )

    lines += ["","HATALAR / NOTLAR","-"*60] + (errors if errors else ["Yok"])
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    # Excel
    try:
        with pd.ExcelWriter(EXCEL, engine="xlsxwriter") as writer:
            anlik5.to_excel(writer, sheet_name="Koruma Onayli Adaylar", index=False)
            bist.sort_values(["CakilmaRiski","GenelPuan"],ascending=[False,True]).head(15).to_excel(writer, sheet_name="Risk Radari", index=False)
            bist.sort_values(["SosyalKapsam","SosyalCoskuRiski"],ascending=[False,False]).head(20).to_excel(writer, sheet_name="Sosyal Duyarlilik", index=False)
            dip_adaylari.to_excel(writer, sheet_name="Dip Donus Adaylari", index=False)
            dip_bekle.to_excel(writer, sheet_name="Dibe Yakin Bekle", index=False)
            bist.sort_values(["BT_3G_Kazanma%","BT_SinyalSayisi"],ascending=[False,False]).to_excel(writer, sheet_name="Backtest 2-3-5 Gun", index=False)
            stable.head(5).to_excel(writer, sheet_name="Istikrarli Ilk 5", index=False)
            uzak10.to_excel(writer, sheet_name="Uzak Dur Ilk 10", index=False)
            bist.to_excel(writer, sheet_name="Tum BIST", index=False)
            metals.to_excel(writer, sheet_name="Altin Gumus", index=False)

            wb = writer.book
            head = wb.add_format({"bold":True,"font_color":"white","bg_color":"#1F4E78","border":1})
            good = wb.add_format({"bg_color":"#E2F0D9"})
            warn = wb.add_format({"bg_color":"#FFF2CC"})
            bad = wb.add_format({"bg_color":"#F4CCCC"})

            for sname, data in {
                "Koruma Onayli Adaylar":anlik5,
                "Risk Radari":bist.sort_values(["CakilmaRiski","GenelPuan"],ascending=[False,True]).head(15),
                "Sosyal Duyarlilik":bist.sort_values(["SosyalKapsam","SosyalCoskuRiski"],ascending=[False,False]).head(20),
                "Dip Donus Adaylari":dip_adaylari,
                "Dibe Yakin Bekle":dip_bekle,
                "Backtest 2-3-5 Gun":bist.sort_values(["BT_3G_Kazanma%","BT_SinyalSayisi"],ascending=[False,False]),
                "Istikrarli Ilk 5":stable.head(5),
                "Uzak Dur Ilk 10":uzak10,
                "Tum BIST":bist,
                "Altin Gumus":metals
            }.items():
                ws = writer.sheets[sname]
                ws.freeze_panes(1,1)
                if len(data.columns):
                    ws.autofilter(0,0,max(len(data),1),len(data.columns)-1)
                for ci,col in enumerate(data.columns):
                    ws.write(0,ci,str(col),head)
                    vals = data[col].astype(str).tolist() if len(data) else []
                    width = min(max([len(str(col))]+[len(v) for v in vals[:100]])+2, 34)
                    ws.set_column(ci,ci,max(width,11))

                if "BT_3G_Kazanma%" in data.columns and len(data):
                    c = data.columns.get_loc("BT_3G_Kazanma%")
                    ws.conditional_format(1,c,len(data),c,{
                        "type":"3_color_scale","min_color":"#F8696B",
                        "mid_color":"#FFEB84","max_color":"#63BE7B"
                    })

                if "GenelPuan" in data.columns and len(data):
                    c = data.columns.get_loc("GenelPuan")
                    ws.conditional_format(1,c,len(data),c,{
                        "type":"3_color_scale","min_color":"#F8696B",
                        "mid_color":"#FFEB84","max_color":"#63BE7B"
                    })
                if "GenelKarar" in data.columns and len(data):
                    c = data.columns.get_loc("GenelKarar")
                    ws.conditional_format(1,c,len(data),c,{"type":"text","criteria":"containing","value":"GÜÇLÜ","format":good})
                    ws.conditional_format(1,c,len(data),c,{"type":"text","criteria":"containing","value":"İZLE","format":warn})
                    ws.conditional_format(1,c,len(data),c,{"type":"text","criteria":"containing","value":"UZAK","format":bad})

            ws = wb.add_worksheet("Ozet")
            title = wb.add_format({"bold":True,"font_size":18,"font_color":"#1F4E78"})
            label = wb.add_format({"bold":True,"bg_color":"#D9EAF7","border":1})
            val = wb.add_format({"border":1})
            ws.write("A1","QUANT SCANNER v6.4",title)
            ws.write("A3","Makro Puan",label); ws.write("B3",macro["MakroPuan"],val)
            ws.write("C3","Makro Durum",label); ws.write("D3",macro["MakroDurum"],val)
            ws.write("F3","Jeopolitik Puan",label); ws.write("G3",macro["JeopolitikPuan"],val)
            ws.write("H3","Jeopolitik Durum",label); ws.write("I3",macro["JeopolitikDurum"],val)
            ws.write("A5","Rapor Tarihi",label); ws.write("B5",datetime.now().strftime("%d.%m.%Y %H:%M"),val)
            ws.set_column("A:I",18)

    except Exception as e:
        errors.append(f"Excel raporu: {type(e).__name__}: {e}")
        log(traceback.format_exc())

    save_history(df)
    return df, stable, macro

