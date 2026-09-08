
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from threading import Thread, Lock
from pathlib import Path
from datetime import datetime
import uuid, traceback, math
import pandas as pd

import engine

app = FastAPI(title="Quant Scanner Mobile API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=False,
    allow_methods=["*"], allow_headers=["*"],
)

jobs = {}
scan_lock = Lock()

def _safe(v):
    if v is None:
        return None
    try:
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
    except Exception:
        pass
    if hasattr(v, "item"):
        try: return v.item()
        except Exception: pass
    return v

def _records(df):
    if df is None or getattr(df, "empty", True):
        return []
    out=[]
    for _, row in df.iterrows():
        out.append({str(k): _safe(v) for k,v in row.to_dict().items()})
    return out

def _run_job(job_id):
    jobs[job_id]["status"]="running"
    jobs[job_id]["started_at"]=datetime.now().isoformat(timespec="seconds")
    try:
        with scan_lock:
            df, stable, macro = engine.scan()

        bist = df[df["Tur"]=="BIST"].copy()
        top = bist[bist["NihaiKarar"].astype(str).str.contains("AL İÇİN ADAY", na=False)].sort_values(
            ["CakilmaRiski","GenelPuan"], ascending=[True,False]
        ).head(20)

        dip = bist[bist["DipDurum"].astype(str).str.contains("DİPTEN DÖNÜŞ", na=False)].sort_values(
            ["DipPuan","CakilmaRiski"], ascending=[False,True]
        ).head(20)

        risk = bist.sort_values(["CakilmaRiski","GenelPuan"], ascending=[False,True]).head(20)
        backtest = bist.sort_values(["BT_3G_Kazanma%","BT_SinyalSayisi"], ascending=[False,False]).head(20)

        result = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "macro": {k:_safe(v) for k,v in macro.items()},
            "counts": {
                "total_bist": int(len(bist)),
                "top_candidates": int(len(top)),
                "dip_candidates": int(len(dip))
            },
            "top_candidates": _records(top),
            "dip_candidates": _records(dip),
            "risk_radar": _records(risk),
            "backtest_leaders": _records(backtest),
            "stable_candidates": _records(stable if isinstance(stable,pd.DataFrame) else pd.DataFrame()),
            "all_bist": _records(bist)
        }
        jobs[job_id]["result"]=result
        jobs[job_id]["status"]="done"
        jobs[job_id]["finished_at"]=datetime.now().isoformat(timespec="seconds")
    except Exception as e:
        jobs[job_id]["status"]="error"
        jobs[job_id]["error"]=f"{type(e).__name__}: {e}"
        jobs[job_id]["trace"]=traceback.format_exc()

@app.get("/")
def root():
    return {"name":"Quant Scanner Mobile API","version":"1.0","tickers":len(clean_tickers())}

def clean_tickers():
    p=Path(__file__).with_name("tickers_bist.txt")
    vals=[]
    seen=set()
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        x=line.strip().upper()
        if not x or x=="MENKUL" or x in seen: continue
        seen.add(x); vals.append(x)
    return vals

@app.get("/health")
def health():
    return {
        "ok": True,
        "ticker_count": len(clean_tickers()),
        "engine": "v6.4 + Dip Hunter + Capital Protection + Social + Backtest"
    }

@app.get("/tickers")
def tickers():
    return {"count":len(clean_tickers()),"items":clean_tickers()}

@app.post("/scan/start")
def scan_start():
    running=[k for k,v in jobs.items() if v.get("status") in ("queued","running")]
    if running:
        return {"job_id":running[0],"status":jobs[running[0]]["status"],"message":"Tarama zaten çalışıyor."}
    job_id=str(uuid.uuid4())
    jobs[job_id]={"status":"queued","created_at":datetime.now().isoformat(timespec="seconds")}
    Thread(target=_run_job,args=(job_id,),daemon=True).start()
    return {"job_id":job_id,"status":"queued"}

@app.get("/scan/status/{job_id}")
def scan_status(job_id:str):
    if job_id not in jobs:
        raise HTTPException(404,"İş bulunamadı")
    j=jobs[job_id]
    return {k:v for k,v in j.items() if k!="result" and k!="trace"}

@app.get("/scan/result/{job_id}")
def scan_result(job_id:str):
    if job_id not in jobs:
        raise HTTPException(404,"İş bulunamadı")
    j=jobs[job_id]
    if j.get("status")=="error":
        raise HTTPException(500,j.get("error","Tarama hatası"))
    if j.get("status")!="done":
        return {"status":j.get("status")}
    return j["result"]
