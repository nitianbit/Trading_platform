"""Open-loop load generator for the owned HTTPS deployment check only."""
import asyncio
from collections import Counter
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import resource
import secrets
import subprocess
import sys
import time
import httpx
from deployment_target import sql


def percentile(values, fraction):
    values=sorted(values)
    return round(values[min(len(values)-1,int((len(values)-1)*fraction))],2) if values else None


def container_resources(prefix):
    result={}
    for service in ("backend","db","redis","web"):
        probe=subprocess.run(prefix+["exec","-T",service,"cat","/sys/fs/cgroup/cpu.stat","/sys/fs/cgroup/memory.peak"],capture_output=True,text=True)
        if probe.returncode: continue
        lines=probe.stdout.splitlines()
        usage=next((int(line.split()[1]) for line in lines if line.startswith("usage_usec ")),None)
        if usage is not None and lines[-1].isdigit():
            result[service]={"cpu_seconds":usage/1e6,"lifetime_peak_bytes":int(lines[-1])}
    return result


async def measure(host, certificate, actors, *, kind, rate, seconds):
    semaphore=asyncio.Semaphore(128)
    pending=set(); statuses=Counter(); latencies=[]; deadlines=0; errors=0; sent=0
    paths=["/web/paper/market"]*4+["/web/dashboard"]*2+["/web/positions"]*2+["/web/orderbook","/web/tradebook"]
    async with httpx.AsyncClient(base_url=host,verify=str(certificate),timeout=10,limits=httpx.Limits(max_connections=128,max_keepalive_connections=64)) as client:
        # Warm the actual auth/pool/fund paths; rate measurements start afterwards.
        for actor in actors:
            response=await client.get("/web/dashboard",headers={"Cookie":"access_token="+actor["cookie"]})
            if response.status_code!=200: raise RuntimeError("Load fixture authentication failed")
        async def send(index,due):
            nonlocal errors,sent
            actor=actors[index%len(actors)]
            async with semaphore:
                try:
                    if kind=="reads":
                        response=await client.get(paths[index%len(paths)],headers={"Cookie":"access_token="+actor["cookie"]})
                    else:
                        response=await client.post("/api/v1/placeorder",json={"apikey":actor["key"],"symbol":"NIFTY-DEMO-FUT","exchange":"NFO","product":"NRML","pricetype":"MARKET","quantity":25,"action":"BUY" if (index//len(actors))%2==0 else "SELL"})
                    statuses[str(response.status_code)]+=1
                    if response.status_code==200 and response.json().get("status")=="error": statuses["application_error"]+=1
                except httpx.HTTPError:
                    errors+=1
                finally:
                    sent+=1; latencies.append((time.perf_counter()-due)*1000)
        start=time.perf_counter()
        for index in range(rate*seconds):
            due=start+index/rate
            await asyncio.sleep(max(0,due-time.perf_counter()))
            if len(pending)>=256:
                deadlines+=1; continue
            task=asyncio.create_task(send(index,due)); pending.add(task); task.add_done_callback(pending.discard)
        if pending: await asyncio.gather(*list(pending))
        elapsed=time.perf_counter()-start
    accepted=statuses["200"]-statuses["application_error"]
    return {"profile":kind,"offered_rps":rate,"scheduled_seconds":seconds,"elapsed_seconds":round(elapsed,3),"scheduled_requests":rate*seconds,"completed_requests":sent,"accepted_rps":round(accepted/elapsed,2),"http_statuses":dict(statuses),"network_errors":errors,"dropped_due_to_backlog":deadlines,"latency_from_scheduled_arrival_ms":{"p50":percentile(latencies,.5),"p95":percentile(latencies,.95),"p99":percentile(latencies,.99),"max":round(max(latencies),2) if latencies else None}}


def run(prefix, config, source, host, certificate, seconds, output):
    project=prefix[prefix.index("-p")+1]
    if not project.startswith("dhk-deploy-test-") or seconds<5 or seconds>120: raise RuntimeError("Owned disposable deployment and bounded duration required")
    nonce=secrets.token_hex(16)
    sql(prefix,"db","INSERT INTO app_settings(key,value) VALUES ('paper_load_test_owner','"+nonce+"'),('paper_platform_policy','{\"public_feed_enabled\":false}') ON CONFLICT (key) DO UPDATE SET value=excluded.value;")
    seed=subprocess.run(prefix+["exec","-T","backend","python","scripts/seed_load_accounts.py",nonce],check=True,capture_output=True,text=True)
    actors=json.loads(seed.stdout)
    profile=subprocess.run(prefix+["exec","-T","backend","python","scripts/profile_orders.py",nonce],check=True,capture_output=True,text=True)
    profile_path=Path(output).with_suffix(".profile.txt"); profile_path.parent.mkdir(parents=True,exist_ok=True)
    with os.fdopen(os.open(profile_path,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600),"w") as file: file.write(profile.stdout)

    report={"date":datetime.now(timezone.utc).isoformat(),"docker_resources":json.loads(subprocess.check_output(["docker","info","--format",'{"cpus":{{.NCPU}},"memory_bytes":{{.MemTotal}},"architecture":"{{.Architecture}}"}'],text=True)),"host_platform":platform.platform(),"machine":platform.machine(),"logical_host_cpus":os.cpu_count(),"topology":"production Caddy HTTPS + one backend worker + dedicated PostgreSQL 17/Redis 7 containers; 64 activated user fixtures; one client IP","profiles":[]}
    for label,kind,duration,api_limit in [("mixed_reads_default","reads",seconds,"50 per second"),("orders_default_limit","orders",min(seconds,15),"50 per second"),("orders_capacity_limit_250","orders",seconds,"250 per second")]:
        if api_limit!="50 per second":
            config["services"]["backend"]["environment"]["API_RATE_LIMIT"]=api_limit
            source.write_text(json.dumps(config)); source.chmod(0o600)
            subprocess.run(prefix+["up","-d","--wait","--force-recreate","backend"],check=True,capture_output=True)
        before=container_resources(prefix)
        client_before=resource.getrusage(resource.RUSAGE_SELF)
        measured=asyncio.run(measure(host,certificate,actors,kind=kind,rate=100,seconds=duration))
        client_after=resource.getrusage(resource.RUSAGE_SELF); after=container_resources(prefix)
        measured.update(label=label,api_limit=api_limit,order_limit="10 per second per user",client_cpu_seconds=round(client_after.ru_utime+client_after.ru_stime-client_before.ru_utime-client_before.ru_stime,3),container_resources={name:{"cpu_seconds":round(after[name]["cpu_seconds"]-values["cpu_seconds"],3),"lifetime_peak_bytes":after[name]["lifetime_peak_bytes"]} for name,values in before.items() if name in after})
        measured["read_slo_p95_500ms_or_order_slo_p95_1000ms_pass"]=(measured["accepted_rps"]>=99 and not measured["network_errors"] and not measured["dropped_due_to_backlog"] and set(measured["http_statuses"])=={"200"} and measured["latency_from_scheduled_arrival_ms"]["p95"]<=(500 if kind=="reads" else 1000))
        measured["expected_throttling_pass"]=(set(measured["http_statuses"])<={"200","429"} and measured["http_statuses"].get("429",0)>0 and not measured["network_errors"] and not measured["dropped_due_to_backlog"]) if label=="orders_default_limit" else None
        gateway=subprocess.run(prefix+["logs","--no-log-prefix","--tail","100","web"],capture_output=True,text=True)
        gateway_errors=[]
        for line in gateway.stdout.splitlines():
            try: entry=json.loads(line)
            except ValueError: continue
            if entry.get("level")=="error":
                gateway_errors.append({key:entry.get(key) for key in ("msg","error","status") if key in entry})
        measured["gateway_error_summaries"]=gateway_errors
        report["profiles"].append(measured)
        print("LOAD: "+label+" "+json.dumps(measured))
        time.sleep(1.1)
    # Validate cash/margin and fee conservation after all accepted executions.
    identity=sql(prefix,"db","SELECT json_build_object('fees',(SELECT count(*) FROM sandbox_brokerage WHERE fee_paise<>broker_paise+admin_paise),'cash',(SELECT count(*) FROM sandbox_funds f JOIN users u ON u.id=f.user_id WHERE u.username LIKE 'load_user_%' AND abs(f.available+f.used_margin-f.starting_capital-f.realized_pnl)>0.011),'counters',(SELECT count(*) FROM sandbox_funds f JOIN users u ON u.id=f.user_id WHERE u.username LIKE 'load_user_%' AND f.brokerage_paise<>(SELECT coalesce(sum(b.fee_paise),0) FROM sandbox_brokerage b WHERE b.user_id=f.user_id)));" )
    report["financial_identity_violations"]=json.loads(identity)
    if any(report["financial_identity_violations"].values()):
        detail=sql(prefix,"db","SELECT coalesce(json_agg(row_to_json(x)),'[]') FROM (SELECT f.user_id, f.available, f.used_margin, f.starting_capital, f.realized_pnl, f.brokerage_paise, f.available+f.used_margin-f.starting_capital-f.realized_pnl AS cash_residual FROM sandbox_funds f JOIN users u ON u.id=f.user_id WHERE u.username LIKE 'load_user_%' AND abs(f.available+f.used_margin-f.starting_capital-f.realized_pnl)>0.011 LIMIT 10) x;")
        report["financial_details"]=json.loads(detail)
    print("FINANCIAL CHECK: "+json.dumps(report["financial_identity_violations"]))
    report["limitations"]=["Local Docker environment; not a target-host capacity certificate","Peak memory is each container's lifetime cgroup peak, not simultaneous family RSS","CPU resource deltas include fixture-path warmup and metrics probes; per-request latency excludes fixture creation","Login/password hashing and public-reference upstream requests are outside the traffic mix","Token/API-model cost is not measured; the load generator makes no model requests"]
    output=Path(output); output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with os.fdopen(os.open(output,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600),"w") as file: json.dump(report,file,indent=2)
    print("Private load report: "+str(output))
    if any(report["financial_identity_violations"].values()): raise RuntimeError("Load run violated financial identities; the report was preserved")
    if not report["profiles"][1]["expected_throttling_pass"] or any(not row["read_slo_p95_500ms_or_order_slo_p95_1000ms_pass"] for row in report["profiles"] if row["label"]!="orders_default_limit"):
        raise RuntimeError("100-RPS acceptance budget was not met; measurements are preserved in the load report")

