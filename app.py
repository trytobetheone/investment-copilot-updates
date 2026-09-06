from __future__ import annotations

import os
import sys

import pandas as pd
import psutil
import streamlit as st

from investment_copilot.ai_backend import AIConfig, list_local_models, load_ai_config, needs_openai_api, save_ai_config
from investment_copilot.config import BASE_DIR
from investment_copilot.db import Database
from investment_copilot.orchestrator import run_investment_committee
from investment_copilot.reports import build_html_report, selected_candidate, selected_quant
from investment_copilot.schema import ClientProfile, Holding
from investment_copilot.secrets import get_openai_api_key, save_openai_api_key
from investment_copilot.updater import (
    check_for_update, current_version, download_update, launch_updater_and_exit,
    load_update_config, save_update_config, stage_update,
)

st.set_page_config(page_title="Investment Committee Copilot", page_icon="📊", layout="wide")
db = Database()

ASSET = {"US_EQUITY":"미국 주식","KR_EQUITY":"한국 주식","DM_EQUITY":"선진국 주식","EM_EQUITY":"신흥국 주식","GOV_BOND":"국채","IG_CREDIT":"투자등급 회사채","HY_CREDIT":"하이일드","GOLD":"금","COMMODITY":"원자재","REIT":"리츠","CASH":"현금","OTHER":"기타"}
STATUS = {"PASS":"통과","REVIEW":"검토 필요","FAIL":"부적합/실패","OK":"정상","PARTIAL":"일부 데이터","FAILED":"실패"}
RISK = {"LOW":"낮음","MEDIUM":"보통","HIGH":"높음","VERY_HIGH":"매우 높음"}
EXEC = {"NOT_EXECUTED":"아직 실행 안 함","EXECUTED_AS_RECOMMENDED":"추천안 그대로 실행","EXECUTED_MODIFIED":"일부 수정 후 실행","REJECTED":"미채택 / 보류"}
STYLE = {"ETF_ONLY":"ETF 중심","MIXED":"ETF + 개별주 혼합","STOCK_ACTIVE":"개별주 적극 활용"}


def profile_df(p: ClientProfile | None) -> pd.DataFrame:
    if not p or not p.holdings:
        return pd.DataFrame([{"ticker":"","name":"","asset_class":"OTHER","currency":"KRW","weight":0.0}])
    return pd.DataFrame([x.model_dump() for x in p.holdings])


def to_holdings(df: pd.DataFrame) -> list[Holding]:
    out=[]
    for _,r in df.fillna("").iterrows():
        t=str(r.get("ticker","")).strip().upper()
        if not t: continue
        out.append(Holding(ticker=t,name=str(r.get("name","")),asset_class=str(r.get("asset_class","OTHER") or "OTHER").upper(),currency=str(r.get("currency","KRW") or "KRW").upper(),weight=float(r.get("weight",0) or 0)))
    return out


def candidate(record, cid: str):
    return next((c for c in record.candidates.candidates if c.candidate_id==cid),None)


def alloc_df(c) -> pd.DataFrame:
    return pd.DataFrame([a.model_dump() for a in c.allocations]) if c else pd.DataFrame(columns=["ticker","name","asset_class","currency","weight","role"])


def display_alloc(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty: return df
    x=df.copy(); x["자산군"]=x["asset_class"].map(lambda v: ASSET.get(v,v))
    return x[["ticker","name","자산군","currency","weight","role"]].rename(columns={"ticker":"티커","name":"상품/종목","currency":"통화","weight":"비중(%)","role":"역할"})


def portfolio_from_df(df: pd.DataFrame) -> list[dict]:
    out=[]
    for _,r in df.fillna("").iterrows():
        t=str(r.get("ticker","")).strip().upper()
        if not t: continue
        out.append({"ticker":t,"name":str(r.get("name","")),"asset_class":str(r.get("asset_class","OTHER") or "OTHER").upper(),"currency":str(r.get("currency","KRW") or "KRW").upper(),"weight":float(r.get("weight",0) or 0),"role":str(r.get("role","실제 실행 포트폴리오"))})
    return out


def sync_client(record, portfolio: list[dict]) -> None:
    p=db.get_client(record.client_profile.client_code) or record.client_profile.model_copy(deep=True)
    p.holdings=[Holding(ticker=x["ticker"],name=x.get("name","") or "",asset_class=x.get("asset_class","OTHER") or "OTHER",currency=x.get("currency",p.base_currency) or p.base_currency,weight=float(x.get("weight",0) or 0)) for x in portfolio]
    db.upsert_client(p)


def execution_panel(record, analysis_id: int) -> None:
    ex=db.get_execution_for_analysis(analysis_id)
    st.subheader("실제 실행 / 채택 기록")
    st.caption("이 기록이 있어야 이후 재분석과 돌발상황 대응에서 '추천안'이 아니라 고객의 실제 보유 포트폴리오를 기준으로 볼 수 있습니다.")
    if ex:
        st.info(f"현재 기록: **{EXEC.get(ex['status'],ex['status'])}** · 기준 후보 {ex.get('source_candidate_id') or '-'} · {ex['executed_at']}")
        if ex.get("portfolio"):
            actual=pd.DataFrame(ex["portfolio"]); st.dataframe(display_alloc(actual),use_container_width=True,hide_index=True)
            src=candidate(record,ex.get("source_candidate_id") or "")
            if src:
                sm={a.ticker:a.weight for a in src.allocations}; am={str(x.get('ticker')):float(x.get('weight') or 0) for x in ex["portfolio"]}
                d=pd.DataFrame([{"티커":t,"추천 비중(%)":sm.get(t,0),"실제 비중(%)":am.get(t,0),"차이(%p)":round(am.get(t,0)-sm.get(t,0),2)} for t in sorted(set(sm)|set(am))])
                st.markdown("**추천안 대비 실제 실행 차이**"); st.dataframe(d,use_container_width=True,hide_index=True)
    with st.expander("실행 상태 등록 / 수정",expanded=ex is None):
        ids=[c.candidate_id for c in record.candidates.candidates]
        default=record.final.selected_candidate_id if record.final.selected_candidate_id in ids else ("C2" if "C2" in ids else ids[0])
        cid=st.selectbox("기준 후보",ids,index=ids.index(default),key=f"ecid{analysis_id}")
        keys=list(EXEC); cur=ex["status"] if ex and ex["status"] in keys else "NOT_EXECUTED"
        stat=st.radio("실행 상태",keys,index=keys.index(cur),format_func=lambda x:EXEC[x],horizontal=True,key=f"estat{analysis_id}")
        src=candidate(record,cid); portfolio=[]
        if stat=="EXECUTED_AS_RECOMMENDED":
            portfolio=[a.model_dump() for a in src.allocations] if src else []
            st.dataframe(display_alloc(pd.DataFrame(portfolio)),use_container_width=True,hide_index=True)
        elif stat=="EXECUTED_MODIFIED":
            base=pd.DataFrame(ex["portfolio"]) if ex and ex.get("portfolio") and ex.get("source_candidate_id")==cid else alloc_df(src)
            edit=st.data_editor(base,num_rows="dynamic",use_container_width=True,column_config={"weight":st.column_config.NumberColumn("weight",min_value=0.0,max_value=100.0,step=0.5)},key=f"eedit{analysis_id}{cid}")
            portfolio=portfolio_from_df(edit); st.caption(f"비중 합계: {sum(x['weight'] for x in portfolio):.2f}%")
        note=st.text_area("실행 메모",value=ex.get("note","") if ex else "",key=f"enote{analysis_id}")
        if st.button("실행 기록 저장",type="primary",use_container_width=True,key=f"esave{analysis_id}"):
            if stat in {"EXECUTED_AS_RECOMMENDED","EXECUTED_MODIFIED"}:
                total=sum(x["weight"] for x in portfolio)
                if not portfolio or abs(total-100)>0.5:
                    st.error(f"실제 실행 비중 합계를 100%에 맞춰주세요. 현재 {total:.2f}%")
                    return
            else: portfolio=[]
            db.save_execution(analysis_id,record.client_profile.client_code,stat,cid,portfolio,note)
            if stat in {"EXECUTED_AS_RECOMMENDED","EXECUTED_MODIFIED"}:
                sync_client(record,portfolio); st.success("실행 기록과 고객의 현재 보유자산을 함께 갱신했습니다.")
            else: st.success("실행 상태를 저장했습니다.")
            st.rerun()


def render_record(record, analysis_id: int | None=None) -> None:
    st.subheader("CIO 최종판정")
    if record.final.decision=="SELECT": st.success(f"선택: {record.final.selected_candidate_id} · 판단 신뢰도 {record.final.confidence_pct}%")
    else: st.warning(f"사람 검토 필요 · 판단 신뢰도 {record.final.confidence_pct}%")
    for x in record.final.rationale: st.markdown(f"- {x}")

    sel=selected_candidate(record); q=selected_quant(record)
    if sel:
        st.subheader(f"최종 포트폴리오 · {sel.label}"); st.dataframe(display_alloc(alloc_df(sel)),use_container_width=True,hide_index=True)
        st.bar_chart(alloc_df(sel).set_index("ticker")["weight"])
    if q:
        m=q.metrics; c=st.columns(5)
        c[0].metric("과거 연환산수익률","-" if m.annualized_return_pct is None else f"{m.annualized_return_pct:.2f}%")
        c[1].metric("과거 변동성","-" if m.annualized_volatility_pct is None else f"{m.annualized_volatility_pct:.2f}%")
        c[2].metric("Sharpe","-" if m.sharpe_ratio is None else f"{m.sharpe_ratio:.2f}")
        c[3].metric("MDD","-" if m.max_drawdown_pct is None else f"{m.max_drawdown_pct:.2f}%")
        c[4].metric("95% 일간 CVaR","-" if m.cvar_95_daily_pct is None else f"{m.cvar_95_daily_pct:.2f}%")
        st.caption(f"가격데이터 {m.data_start} ~ {m.data_end}, 관측치 {m.observations}. 과거 통계이며 예측값이 아닙니다.")

    with st.expander("3개 후보 비교",expanded=True):
        qm={x.candidate_id:x.metrics for x in record.quant_results}; rows=[]
        for cnd in record.candidates.candidates:
            m=qm.get(cnd.candidate_id); rows.append({"후보":cnd.candidate_id,"성격":cnd.label,"과거수익률%":getattr(m,"annualized_return_pct",None),"변동성%":getattr(m,"annualized_volatility_pct",None),"MDD%":getattr(m,"max_drawdown_pct",None),"Sharpe":getattr(m,"sharpe_ratio",None),"Quant상태":STATUS.get(getattr(m,"status",None),getattr(m,"status",None))})
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)
        for cnd in record.candidates.candidates:
            with st.expander(f"{cnd.candidate_id} · {cnd.label} 구성"):
                st.dataframe(display_alloc(alloc_df(cnd)),use_container_width=True,hide_index=True)

    l,r=st.columns(2)
    with l:
        with st.expander("거시환경 Agent"):
            st.write(record.macro.regime_summary)
            for x in record.macro.key_risks: st.markdown(f"- {x}")
        with st.expander("상품·종목 Agent"):
            st.write(record.product.summary)
            for p in record.product.products: st.markdown(f"- **{p.ticker}** · {p.name} · {_asset_label(p.asset_class)} · {p.why_fit}")
        with st.expander("고객 적합성 Agent"):
            st.write(f"상태: **{STATUS.get(record.suitability.status,record.suitability.status)}**")
            if record.suitability.missing_information: st.write("추가 확인:",record.suitability.missing_information)
            for x in record.suitability.suitability_notes: st.markdown(f"- {x}")
    with r:
        with st.expander("Bear Agent",expanded=True):
            st.write(f"위험: **{RISK.get(record.bear.overall_risk,record.bear.overall_risk)}**")
            for x in record.bear.strongest_objections: st.markdown(f"- {x}")
            if record.bear.failure_scenarios:
                st.markdown("**실패 시나리오**")
                for x in record.bear.failure_scenarios: st.markdown(f"- {x}")
        with st.expander("Fact Checker",expanded=True):
            st.write(f"종합: **{STATUS.get(record.factcheck.overall_status,record.factcheck.overall_status)}**")
            if record.factcheck.items: st.dataframe(pd.DataFrame([x.model_dump() for x in record.factcheck.items]),use_container_width=True,hide_index=True)
        with st.expander("Compliance / Process"):
            st.write(f"상태: **{STATUS.get(record.compliance.status,record.compliance.status)}**")
            for x in record.compliance.issues: st.markdown(f"- {x}")
            if record.compliance.required_human_checks: st.write("사람 확인 항목:",record.compliance.required_human_checks)

    st.subheader("모니터링 규칙")
    for x in record.final.monitoring_triggers: st.markdown(f"- {x}")
    st.write("**리밸런싱:**",record.final.rebalancing_rule)
    h=build_html_report(record); c1,c2=st.columns(2)
    c1.download_button("HTML 투자위원회 보고서",h.encode("utf-8"),file_name=f"IC_{record.client_profile.client_code}_{record.created_at.date()}.html",mime="text/html",use_container_width=True)
    c2.download_button("감사로그 JSON",record.model_dump_json(indent=2).encode("utf-8"),file_name=f"IC_{record.client_profile.client_code}_{record.created_at.date()}.json",mime="application/json",use_container_width=True)
    if analysis_id is not None: execution_panel(record,analysis_id)


def _asset_label(v: str) -> str: return ASSET.get(str(v),str(v))


st.title("📊 Investment Committee Copilot")
st.caption("독립 리서치 → 후보생성 → 로컬 정량검증 → Bear/Fact/Compliance 교차검증 → CIO 선택 → 실제 실행 추적")
st.info("고객 실명·주민번호·계좌번호 대신 Client Code 사용을 권장합니다. 이 앱은 주문을 자동 전송하지 않습니다.")
page=st.sidebar.radio("메뉴",["고객 & 분석","현재 운용","분석 기록","설정","업데이트"])
cfg_side=load_ai_config(); st.sidebar.caption(f"Version: {current_version()}\n\nAI mode: {cfg_side.mode}")

if page=="업데이트":
    st.header("업데이트"); st.write(f"현재 버전: **{current_version()}**")
    uc=load_update_config(); url=st.text_input("업데이트 채널",value=str(uc.get("manifest_url") or ""))
    a,b=st.columns(2)
    if a.button("업데이트 채널 저장",use_container_width=True): save_update_config(url); st.success("저장했습니다.")
    if b.button("새 버전 확인",type="primary",use_container_width=True): st.session_state["ui"]=check_for_update()
    info=st.session_state.get("ui")
    if info:
        if info.error: st.warning(info.error)
        elif not info.available: st.success(f"최신 버전입니다. ({info.current_version})")
        else:
            st.info(f"새 버전 **{info.latest_version}** 사용 가능")
            for n in info.notes or []: st.markdown(f"- {n}")
            if st.button(f"⬆️ {info.latest_version} 지금 업데이트",type="primary",use_container_width=True):
                try:
                    z=download_update(info); stage_update(info,z); launch_updater_and_exit()
                except Exception as e: st.error(f"업데이트 실패: {e}")

elif page=="설정":
    st.header("설정"); c=load_ai_config(); modes=["LOCAL","HYBRID","CLOUD"]
    labels={"LOCAL":"🖥 LOCAL — 로컬 추론, OpenAI 비용 0원","HYBRID":"🔀 HYBRID — 웹 리서치만 OpenAI","CLOUD":"☁ CLOUD — 전체 OpenAI"}
    mode=st.radio("AI 실행 모드",modes,index=modes.index(c.mode),format_func=lambda x:labels[x])
    base=st.text_input("LM Studio 주소",value=c.local_base_url); model=st.text_input("로컬 모델 ID",value=c.local_model)
    a,b=st.columns(2)
    if a.button("🔌 로컬 AI 연결 확인",use_container_width=True):
        try:
            models=list_local_models(base); st.session_state["models"]=models; st.success("로드된 모델: "+", ".join(models) if models else "서버 연결됨 · 로드 모델 없음")
        except Exception as e: st.error(str(e))
    if b.button("🧩 LOCAL AI 설치/준비 도우미",use_container_width=True):
        try:
            if sys.platform.startswith("win"): os.startfile(str(BASE_DIR/"LOCAL_AI_SETUP.bat"))  # type: ignore[attr-defined]
        except Exception as e: st.error(str(e))
    models=st.session_state.get("models") or []
    if models:
        pick=st.selectbox("감지된 모델",models,index=models.index(model) if model in models else 0)
        if st.button("이 모델 사용"): model=pick; st.session_state["picked"]=pick
    if st.session_state.get("picked"): model=st.session_state["picked"]
    avail=psutil.virtual_memory().available/(1024**3); st.caption(f"사용 가능 메모리 약 {avail:.1f}GB")
    if mode in {"LOCAL","HYBRID"} and avail<7: st.warning("로컬 8B 모델용 메모리가 부족할 수 있습니다. 게임 등 대형 앱을 종료하세요.")
    if st.button("💾 AI 엔진 설정 저장",type="primary",use_container_width=True): save_ai_config(AIConfig(mode=mode,local_base_url=base,local_model=model)); st.success("저장했습니다.")
    st.divider(); st.subheader("OpenAI API (HYBRID/CLOUD 전용)")
    st.write("API key:","✅ 저장됨" if get_openai_api_key() else "❌ 미설정"); key=st.text_input("새 API key",type="password")
    if st.button("API key 저장"):
        try: save_openai_api_key(key); st.success("저장했습니다.")
        except Exception as e: st.error(str(e))

elif page=="현재 운용":
    st.header("현재 운용 포트폴리오"); clients=db.list_clients()
    if not clients: st.info("저장된 고객이 없습니다.")
    else:
        code=st.selectbox("Client Code",clients); p=db.get_client(code); ex=db.get_latest_execution(code)
        if ex: st.success(f"최근 실행: {EXEC.get(ex['status'],ex['status'])} · 분석 ID {ex['analysis_id']} · 후보 {ex.get('source_candidate_id') or '-'}")
        else: st.warning("실제 실행 기록이 없습니다. 분석 기록에서 실행 여부를 등록하세요.")
        if p and p.holdings: st.dataframe(display_alloc(pd.DataFrame([h.model_dump() for h in p.holdings])),use_container_width=True,hide_index=True)

elif page=="분석 기록":
    st.header("분석 기록"); clients=db.list_clients(); f=st.selectbox("고객 필터",["전체"]+clients); rows=db.list_analyses(None if f=="전체" else f)
    if not rows: st.info("아직 분석이 없습니다.")
    else:
        em=db.execution_status_map([int(r["id"]) for r in rows])
        table=pd.DataFrame([{"ID":r["id"],"고객":r["client_code"],"분석시각":r["created_at"],"CIO 판단":"후보 선택" if r["record"]["final"]["decision"]=="SELECT" else "사람 검토 필요","선택 후보":r["record"]["final"].get("selected_candidate_id") or "-","신뢰도":r["record"]["final"]["confidence_pct"],"실제 실행":EXEC.get(em.get(int(r["id"]),"NOT_EXECUTED"),"미기록")} for r in rows])
        st.dataframe(table,use_container_width=True,hide_index=True); rid=st.selectbox("상세보기 ID",[r["id"] for r in rows]); rec=db.get_analysis(int(rid))
        if rec: render_record(rec,int(rid))

else:
    st.header("고객 프로필 & 새 투자위원회"); clients=db.list_clients(); pmode=st.radio("프로필",["새 고객","기존 고객"],horizontal=True); e=None
    if pmode=="기존 고객" and clients:
        code=st.selectbox("Client Code",clients); e=db.get_client(code); latest=db.get_latest_execution(code)
        if latest: st.caption(f"실제 실행 포트폴리오 연동됨 · 분석 ID {latest['analysis_id']}")
    c1,c2,c3=st.columns(3)
    with c1:
        cc=st.text_input("Client Code",value=e.client_code if e else "CLIENT_001"); assets=st.number_input("투자가능자산",min_value=1.0,value=float(e.investable_assets) if e else 300_000_000.0,step=10_000_000.0); currs=["KRW","USD","JPY","EUR"]; cur=st.selectbox("기준통화",currs,index=currs.index(e.base_currency) if e and e.base_currency in currs else 0)
    with c2:
        horizon=st.number_input("투자기간(년)",1,60,value=e.horizon_years if e else 5); loss=st.slider("감내 가능한 최대손실(%)",1,80,int(e.max_tolerable_loss_pct) if e else 20); liq=st.slider("최소 현금성 비중(%)",0,100,int(e.minimum_liquidity_pct) if e else 10)
    with c3:
        target=st.number_input("목표 연수익률(%, 0=미지정)",0.0,50.0,value=0.0 if not e or e.target_return_pct is None else float(e.target_return_pct),step=0.5); lv=["low","medium","high"]; exp=st.selectbox("투자경험",lv,index=lv.index(e.experience_level) if e else 1); tax=st.selectbox("세후효율 중요도",lv,index=lv.index(e.tax_priority) if e else 1)
    styles=list(STYLE); curstyle=getattr(e,"product_style","MIXED") if e else "MIXED"; pstyle=st.selectbox("상품 구성 방식",styles,index=styles.index(curstyle) if curstyle in styles else 1,format_func=lambda x:STYLE[x])
    st.caption("혼합/개별주 적극 활용에서는 한국·미국 대형 개별주도 후보에 넣고, 최종 구성 시 개별주 한 종목은 최대 10%로 제한합니다.")
    restr=st.text_area("금지/제약 자산",value=e.restrictions if e else "예: 레버리지 ETF 금지, PTP 금지"); pref=st.text_area("선호",value=e.preferences if e else "예: 한국/미국 상장 상품 선호, 개별주 허용"); notes=st.text_area("기타 고객 메모",value=e.notes if e else "")
    st.subheader("현재 보유자산"); edit=st.data_editor(profile_df(e),num_rows="dynamic",use_container_width=True,column_config={"weight":st.column_config.NumberColumn("weight",min_value=0.0,max_value=100.0,step=0.5)},key=f"hold{cc}")
    p=ClientProfile(client_code=cc.strip(),base_currency=cur,investable_assets=assets,horizon_years=int(horizon),max_tolerable_loss_pct=float(loss),minimum_liquidity_pct=float(liq),target_return_pct=None if target==0 else float(target),experience_level=exp,tax_priority=tax,product_style=pstyle,restrictions=restr,preferences=pref,notes=notes,holdings=to_holdings(edit))
    a,b=st.columns([1,2])
    if a.button("프로필 저장",use_container_width=True): db.upsert_client(p); st.success("저장했습니다.")
    ai=load_ai_config(); can=not(needs_openai_api(ai.mode) and not get_openai_api_key())
    run=b.button(f"🚀 투자위원회 실행 · {ai.mode}",type="primary",use_container_width=True,disabled=not can)
    if run:
        db.upsert_client(p); s=st.status("투자위원회 시작",expanded=True)
        def progress(step:str,detail:str): s.write(f"**{step}** · {detail}")
        try:
            rec=run_investment_committee(p,progress); aid=db.save_analysis(rec); s.update(label=f"완료 · 분석 ID {aid}",state="complete",expanded=False); render_record(rec,aid)
        except Exception as ex:
            s.update(label="분석 실패",state="error",expanded=True); txt=str(ex); low=txt.lower()
            if "credit_balance_exhausted" in low or "no credits remaining" in low: st.error("OpenAI API 크레딧이 없습니다. LOCAL 모드로 바꾸면 크레딧 없이 실행할 수 있습니다.")
            else: st.error(txt); st.info("실패한 실행은 분석 기록에 저장하지 않습니다.")
