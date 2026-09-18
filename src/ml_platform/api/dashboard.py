# ruff: noqa: E501
DASHBOARD = r"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ML Platform · Monitor</title>
<style>
:root{color-scheme:dark;font:15px system-ui;color:#e2e8f0;background:#101821}
body{max-width:1160px;margin:40px auto;padding:0 24px}h1{font-size:30px;margin:8px 0}
h2{font-size:18px}header{display:flex;justify-content:space-between;gap:24px;align-items:center}
small,.muted{color:#99aebf}button,select,input{background:#203244;border:1px solid #456077;color:inherit;
padding:10px;border-radius:6px}button{cursor:pointer;background:#165e6e}label{margin-right:14px}
.controls{display:flex;flex-wrap:wrap;gap:12px;margin:28px 0}.cards{display:grid;
grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}.card,section{background:#182532;
border:1px solid #2c4051;border-radius:10px;padding:20px}.card strong{display:block;font-size:26px;
margin-top:8px;overflow-wrap:anywhere}section{margin:18px 0}table{border-collapse:collapse;width:100%}td,th{text-align:left;
padding:10px 8px;border-bottom:1px solid #2c4051}th{font-size:12px;color:#99aebf;text-transform:uppercase}
.stable{color:#74d8b2}.moderate,.drift,.degraded{color:#ffcf70}.severe{color:#ff9189}
#error{color:#ff9189}#quality{overflow:auto}details{margin-top:14px}pre{white-space:pre-wrap;
font-size:12px;max-height:360px;overflow:auto}a{color:#86cced}.grid{display:grid;
grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}.grid section{margin:0}
</style><body><header><div><small>PRODUCTION ML PLATFORM · LOCAL OPERATIONS</small>
<h1>Model monitoring</h1><p class="muted">Versioned predictions, drift signals and delayed outcomes.</p>
</div><a href="/docs">API documentation ↗</a></header>
<div class="controls"><label>API key <input id="api-key" type="password" autocomplete="off" placeholder="Paste ML_API_KEY from .env" spellcheck="false"></label>
<button id="connect">Connect</button><button id="forget">Clear key</button>
<small>Key stays in this tab's memory. Re-enter after reloading.</small></div>
<div class="controls"><label>Cohort <select id="cohort"><option>live</option><option>verification</option>
<option>synthetic-none</option><option>synthetic-mild</option><option>synthetic-moderate</option>
<option>synthetic-severe</option><option>benchmark</option></select></label>
<label>Window <select id="hours"><option value="24">24 hours</option><option value="1">1 hour</option>
<option value="168">7 days</option></select></label><button id="refresh">Refresh report</button>
<small id="updated"></small></div><p id="error" role="alert"></p><div class="cards" id="cards"></div>
<section><h2>Feature drift</h2><p class="muted">Train reference vs this model's predictions. Numeric PSI ≥ 0.20;
repayment-category total variation ≥ 0.15. At least 100 observations required.</p>
<table><thead><tr><th>Feature</th><th>PSI</th><th>Total variation</th><th>Status</th><th>Missing input rate</th>
</tr></thead><tbody id="features"></tbody></table></section>
<div class="grid"><section><h2>Prediction distribution</h2><div id="distribution"></div></section>
<section id="quality"><h2>Delayed-label performance</h2><div id="performance"></div>
<p class="muted">Requires 100 labels, 10 per class and 50% coverage. Observed labels may be biased.
Drift alone does not prove model degradation.</p></section></div>
<section><h2>Saved monitoring windows</h2><p class="muted">Save reports with the monitor CLI or the authenticated
snapshot endpoint. History retains each model version and cohort separately.</p><div id="history"></div>
<details><summary>Current report JSON</summary><pre id="raw"></pre></details></section>
<script>
const $=id=>document.getElementById(id), fmt=x=>x==null?'—':Number(x).toFixed(3);
function table(target, rows){const t=document.createElement('table');for(const row of rows){
const tr=document.createElement('tr');for(const v of row){const td=document.createElement('td');
td.textContent=v;tr.append(td)}t.append(tr)}$(target).replaceChildren(t)}
let apiKey='',generation=0;
function clearReport(){for(const id of ['cards','features','distribution','performance','history','raw','updated'])$(id).replaceChildren()}
function authHeaders(){return apiKey?{'X-API-Key':apiKey}:{}}
async function load(){ const ticket=++generation;$('error').textContent='';$('refresh').disabled=true;try{
const q='cohort='+encodeURIComponent($('cohort').value)+'&hours='+$('hours').value;
const response=await fetch('/api/v1/monitoring?'+q,{headers:authHeaders(),cache:'no-store'});const r=await response.json();if(ticket!==generation)return;
if(!response.ok)throw new Error(response.status===401?'Enter ML_API_KEY from your .env, then click Connect.':r.detail||'Report unavailable');$('cards').replaceChildren();
const o=r.operational;const cards=[['Serving model','v'+r.model_version],['Predictions',r.prediction_count],
['Requests / min',fmt(o.requests_per_minute)],['P95 latency · ms',fmt(o.latency_ms.p95)],
['HTTP error rate',o.error_rate==null?'—':(o.error_rate*100).toFixed(1)+'%'],['Drift',r.drift.status]];
for(const [label,value] of cards){const card=document.createElement('div');card.className='card';
const small=document.createElement('small');small.textContent=label;const strong=document.createElement('strong');
strong.textContent=value;card.append(small,strong);$('cards').append(card)}
$('features').replaceChildren();for(const [name,d] of Object.entries(r.drift.features)){
const tr=document.createElement('tr');for(const value of [name,fmt(d.psi),fmt(d.total_variation),d.status,
fmt(o.missing_feature_rates[name])]){const td=document.createElement('td');td.textContent=value;
if(value===d.status)td.className=d.status;tr.append(td)}$('features').append(tr)}
if(!Object.keys(r.drift.features).length){const tr=document.createElement('tr');const td=document.createElement('td');
td.colSpan=5;td.textContent='Waiting for at least 100 predictions in this cohort.';tr.append(td);$('features').append(tr)}
const d=r.drift.prediction||{};table('distribution',[['Score PSI',fmt(d.psi)],['Mean risk',fmt(d.mean_risk)],
['Mean risk change',fmt(d.mean_risk_delta)],['Positive rate',fmt(d.positive_rate)],
['P50 / P99 latency · ms',fmt(o.latency_ms.p50)+' / '+fmt(o.latency_ms.p99)]]);
const p=r.performance;table('performance',[['Status',p.status],['Labels / coverage',p.labeled+' / '+
(p.coverage*100).toFixed(1)+'%'],...Object.entries(p.metrics||{}).map(([k,v])=>[k,fmt(v)]),['Calibration ECE',fmt(p.ece)]]);
$('raw').textContent=JSON.stringify(r,null,2);$('updated').textContent='Updated '+new Date(r.created_at).toLocaleTimeString();
const history=await fetch('/api/v1/monitoring/history?cohort='+encodeURIComponent(r.cohort),{headers:authHeaders(),cache:'no-store'});
if(history.ok){const h=await history.json();if(ticket!==generation)return;table('history',h.length?h.map(x=>[
new Date(x.window.end).toLocaleString(),'v'+x.model_version,x.prediction_count,x.drift.status,x.performance.status]):
[['No saved windows yet.']])}
}catch(e){if(ticket===generation){clearReport();$('error').textContent=e.message}}finally{if(ticket===generation)$('refresh').disabled=false}}
$('connect').onclick=()=>{apiKey=$('api-key').value.trim();$('api-key').value='';load()};
$('api-key').onkeydown=e=>{if(e.key==='Enter')$('connect').click()};
$('forget').onclick=()=>{generation++;apiKey='';$('refresh').disabled=false;$('api-key').value='';clearReport();$('error').textContent='Key cleared. Enter a key to reconnect.'};
$('refresh').onclick=load;$('cohort').onchange=load;$('hours').onchange=load;load();
</script></body></html>"""
