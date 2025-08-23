const cards = document.getElementById("cards");
const statusEl = document.getElementById("status");
const beep = document.getElementById("beep");
document.getElementById("analyze").addEventListener("click", analyze);

function fmt(n, d=5){ return (n===null||n===undefined) ? "—" : Number(n).toFixed(d); }

function card(symbol){
  return `
  <section class="card" id="card-${symbol.replace(/[^\w]/g,'_')}">
    <div class="head">
      <h2>${symbol}</h2>
      <span class="sig" id="sig-${symbol}">—</span>
    </div>
    <div class="row">
      <div class="kv"><span>Trend</span><b id="trend-${symbol}">—</b></div>
      <div class="kv"><span>POC</span><b id="poc-${symbol}">—</b></div>
      <div class="kv"><span>VAH</span><b id="vah-${symbol}">—</b></div>
      <div class="kv"><span>VAL</span><b id="val-${symbol}">—</b></div>
    </div>
    <div class="candle"><img id="img-${symbol}" src="" alt="candle"></div>
    <div class="reason" id="reason-${symbol}">—</div>
  </section>`;
}

async function loadResults(){
  const res = await fetch("/results");
  const data = await res.json();
  if(!data.ok){ statusEl.textContent = "Error loading"; return; }
  cards.innerHTML = "";
  const pairs = Object.keys(data.results);
  pairs.forEach(p => { cards.insertAdjacentHTML("beforeend", card(p)); });
  updateCards(data.results, "Loaded");
}

function updateCards(results, label){
  let tradeable = false;
  Object.entries(results).forEach(([sym, r]) => {
    const sig = document.getElementById(`sig-${sym}`);
    const trend = document.getElementById(`trend-${sym}`);
    const poc = document.getElementById(`poc-${sym}`);
    const vah = document.getElementById(`vah-${sym}`);
    const val = document.getElementById(`val-${sym}`);
    const img = document.getElementById(`img-${sym}`);
    const reason = document.getElementById(`reason-${sym}`);
    sig.textContent = r.signal || "—";
    sig.className = "sig " + (r.signal || "").toLowerCase();
    trend.textContent = r.trend || "—";
    poc.textContent = fmt(r.poc);
    vah.textContent = fmt(r.vah);
    val.textContent = fmt(r.val);
    img.src = r.svg || "";
    reason.textContent = r.reason || "—";
    if (r.signal === "CALL" || r.signal === "PUT") tradeable = true;
  });
  statusEl.textContent = label + " @ " + new Date().toLocaleTimeString();
  if (tradeable){ try { beep.play(); } catch(e){} }
}

async function analyze(){
  try{
    const res = await fetch("/analyze", {method:"POST"});
    const data = await res.json();
    if(!data.ok){ statusEl.textContent = "Error: " + (data.error||""); return; }
    updateCards(data.results, "Analyzed");
  }catch(e){
    statusEl.textContent = "Analyze failed";
  }
}

loadResults();
setInterval(loadResults, 15000);
