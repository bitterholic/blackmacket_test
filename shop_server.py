#!/usr/bin/env python3
"""온라인 상점 서버 (표준 라이브러리만 사용).

실행:  python shop_server.py [포트]
- 손님 페이지 : http://localhost:8080/
- 상점주 페이지: http://localhost:8080/admin?key=<서버 시작 시 출력되는 키>
환경변수 ADMIN_KEY 로 상점주 키를 고정할 수 있음.
상품 풀은 같은 폴더의 items.json 을 수정.
"""
import json
import os
import random
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
ITEMS_FILE = os.path.join(BASE, "items.json")
STATE_FILE = os.path.join(BASE, "state.json")
ADMIN_KEY = os.environ.get("ADMIN_KEY") or secrets.token_urlsafe(8)

LOCK = threading.Lock()
STATE = {"open": False, "round": 0, "shelf": [], "orders": [], "next_id": 1}


def load_pool():
    with open(ITEMS_FILE, encoding="utf-8") as f:
        return {it["id"]: it for it in json.load(f)}


def save_state():
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(STATE, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            STATE.update(json.load(f))


SHOP_NAME = os.environ.get("SHOP_NAME", "이탈리아 지방 상점")
SHOP_URL = os.environ.get("SHOP_URL", "")  # 터널 주소. 비우면 접속 주소로 대체


def build_shop_announcement(shelf, shop_url, shop_name=SHOP_NAME):
    """밴드 등에 올릴 상점 개방 공지문 (weather_broadcast_dashboard.build_band_announcement와 같은 형식)."""
    def one(it):
        return it["name"] + (f" {it['price']}G" if it.get("price") is not None else "")
    items = " · ".join(one(it) for it in shelf) if shelf else "(진열 없음)"
    return (
        f"{shop_name} 오늘의 진열대\n"
        f"{items}\n"
        f"주문은 여기서 해주세요\n"
        f"{shop_url}"
    )


def public_view():
    return {"open": STATE["open"], "round": STATE["round"], "shelf": STATE["shelf"]}


GUEST_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>상점</title>
<style>
body{font-family:system-ui,sans-serif;max-width:560px;margin:0 auto;padding:16px;background:#faf7f2;color:#222}
h1{font-size:1.4rem}.card{background:#fff;border:1px solid #e3dccf;border-radius:10px;padding:12px;margin:10px 0;display:flex;align-items:center;gap:10px}
.info{flex:1}.name{font-weight:600}.desc{font-size:.85rem;color:#666}.price{font-size:.85rem;color:#a60}
.qty{display:flex;align-items:center;gap:8px}.qty button{width:38px;height:38px;font-size:1.3rem;border-radius:8px;border:1px solid #ccc;background:#f4efe6;cursor:pointer}
.qty span{min-width:28px;text-align:center;font-size:1.1rem}
input[type=text]{width:100%;box-sizing:border-box;padding:10px;font-size:1rem;border:1px solid #ccc;border-radius:8px}
#send{width:100%;padding:14px;font-size:1.1rem;border:0;border-radius:10px;background:#2b6;color:#fff;cursor:pointer;margin-top:8px}
#send:disabled{background:#aaa}#msg{margin-top:10px;font-weight:600}.closed{text-align:center;padding:40px 0;color:#888}
</style></head><body>
<h1>🛒 상점</h1>
<div id="closed" class="closed" style="display:none">지금은 상점이 닫혀 있어요.<br>상점주가 열면 자동으로 나타납니다.</div>
<div id="shop" style="display:none">
<input type="text" id="nick" maxlength="20" placeholder="닉네임을 입력하세요">
<div id="list"></div>
<div id="total"></div>
<button id="send">주문 보내기</button>
<div id="msg"></div>
</div>
<script>
let round=-1, shelf=[], qty={};
const $=id=>document.getElementById(id);
function render(){
  const list=$('list'); list.innerHTML='';
  shelf.forEach(it=>{
    const d=document.createElement('div'); d.className='card';
    const info=document.createElement('div'); info.className='info';
    const n=document.createElement('div'); n.className='name'; n.textContent=it.name;
    const ds=document.createElement('div'); ds.className='desc'; ds.textContent=it.desc||'';
    info.append(n,ds);
    if(it.price!=null){const p=document.createElement('div'); p.className='price'; p.textContent=it.price+'G'; info.append(p);}
    const q=document.createElement('div'); q.className='qty';
    const m=document.createElement('button'); m.textContent='−';
    const c=document.createElement('span'); c.textContent=qty[it.id]||0;
    const pl=document.createElement('button'); pl.textContent='+';
    m.onclick=()=>{qty[it.id]=Math.max(0,(qty[it.id]||0)-1); c.textContent=qty[it.id]; upd();};
    pl.onclick=()=>{qty[it.id]=Math.min(99,(qty[it.id]||0)+1); c.textContent=qty[it.id]; upd();};
    q.append(m,c,pl); d.append(info,q); list.append(d);
  });
  upd();
}
function upd(){
  let cnt=0,sum=0,hasPrice=false;
  shelf.forEach(it=>{const k=qty[it.id]||0; cnt+=k; if(it.price!=null){sum+=k*it.price;hasPrice=true;}});
  $('total').textContent=cnt?('선택 '+cnt+'개'+(hasPrice?' / 합계 '+sum+'G':'')):'';
  $('send').disabled=cnt===0;
}
async function poll(){
  try{
    const r=await (await fetch('/api/shop')).json();
    $('closed').style.display=r.open?'none':'block';
    $('shop').style.display=r.open?'block':'none';
    if(r.round!==round){round=r.round; shelf=r.shelf; qty={}; $('msg').textContent=''; render();}
  }catch(e){}
}
$('send').onclick=async()=>{
  const nick=$('nick').value.trim();
  if(!nick){$('msg').textContent='닉네임을 입력해주세요.';return;}
  const items={}; for(const k in qty) if(qty[k]>0) items[k]=qty[k];
  $('send').disabled=true;
  try{
    const r=await fetch('/api/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nick,items,round})});
    const j=await r.json();
    if(r.ok){$('msg').textContent='✅ 주문이 전달되었습니다!'; qty={}; render();}
    else{$('msg').textContent='⚠️ '+(j.error||'실패'); upd();}
  }catch(e){$('msg').textContent='⚠️ 네트워크 오류'; upd();}
};
poll(); setInterval(poll,4000);
</script></body></html>"""

ADMIN_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>상점주</title>
<style>
body{font-family:system-ui,sans-serif;max-width:760px;margin:0 auto;padding:16px;background:#f2f5fa;color:#222}
.box{background:#fff;border:1px solid #d9e0ec;border-radius:10px;padding:12px;margin:10px 0}
button{padding:10px 16px;font-size:1rem;border-radius:8px;border:1px solid #99a;background:#eef;cursor:pointer;margin:2px}
button.go{background:#2b6;color:#fff;border:0}button.stop{background:#c44;color:#fff;border:0}
input[type=number]{width:70px;padding:8px;font-size:1rem}
.shelf span{display:inline-block;background:#eef;border-radius:6px;padding:4px 8px;margin:3px}
.order{border-bottom:1px solid #eee;padding:8px 0}.order.done{opacity:.45}.nick{font-weight:700}
table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 10px}
</style></head><body>
<h1>🧑‍🍳 상점주 페이지</h1>
<div class="box">
  <div>진열 개수 <input type="number" id="cnt" value="5" min="1" max="30">
  <button id="reroll">🎲 리롤</button></div>
  <div class="shelf" id="shelf" style="margin-top:8px"></div>
  <div style="margin-top:8px"><button class="go" id="open">상점 개방</button><button class="stop" id="close">상점 닫기</button>
  <b id="status"></b></div>
</div>
<div class="box"><b>공지문</b> <button id="copy">복사</button> <span id="copied"></span>
  <textarea id="ann" rows="5" style="width:100%;box-sizing:border-box;margin-top:6px;font-size:1rem" readonly></textarea></div>
<div class="box"><b>이번 회차 집계</b><div id="agg"></div></div>
<div class="box"><b>주문 목록</b> <button id="clear">전체 비우기</button><div id="orders"></div></div>
<script>
const KEY=new URLSearchParams(location.search).get('key')||'';
const $=id=>document.getElementById(id);
async function api(path,body){
  const r=await fetch(path+'?key='+encodeURIComponent(KEY),{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
  return r.json();
}
$('copy').onclick=async()=>{
  const t=$('ann'); t.select();
  try{await navigator.clipboard.writeText(t.value);}catch(e){document.execCommand('copy');}
  $('copied').textContent='복사됨'; setTimeout(()=>$('copied').textContent='',1500);
};
function render(s){
  if(document.activeElement!==$('ann')) $('ann').value=s.announcement||'';
  $('status').textContent=s.open?' 🟢 개방 중':' 🔴 닫힘';
  const sh=$('shelf'); sh.innerHTML=''; s.shelf.forEach(it=>{const e=document.createElement('span'); e.textContent=it.name; sh.append(e);});
  const agg={}; s.orders.forEach(o=>{ if(o.round!==s.round) return; for(const k in o.items){agg[k]=agg[k]||{name:o.items[k].name,q:0}; agg[k].q+=o.items[k].qty;}});
  const a=$('agg'); a.innerHTML=''; const t=document.createElement('table');
  Object.values(agg).forEach(v=>{const tr=document.createElement('tr'); const c1=document.createElement('td'); c1.textContent=v.name; const c2=document.createElement('td'); c2.textContent=v.q; tr.append(c1,c2); t.append(tr);});
  a.append(Object.keys(agg).length?t:document.createTextNode('아직 없음'));
  const ol=$('orders'); ol.innerHTML='';
  s.orders.slice().reverse().forEach(o=>{
    const d=document.createElement('div'); d.className='order'+(o.done?' done':'');
    const n=document.createElement('span'); n.className='nick'; n.textContent=o.nick;
    const tx=document.createElement('span'); tx.textContent=' — '+Object.values(o.items).map(i=>i.name+' ×'+i.qty).join(', ')+'  (회차 '+o.round+')';
    const b=document.createElement('button'); b.textContent=o.done?'되돌리기':'처리 완료';
    b.onclick=async()=>{await api('/api/admin/done',{id:o.id}); load();};
    d.append(n,tx,b); ol.append(d);
  });
}
async function load(){ try{ const s=await api('/api/admin/state'); if(!s.error) render(s); }catch(e){} }
$('reroll').onclick=async()=>{await api('/api/admin/reroll',{count:parseInt($('cnt').value)||5}); load();};
$('open').onclick=async()=>{await api('/api/admin/open',{open:true}); load();};
$('close').onclick=async()=>{await api('/api/admin/open',{open:false}); load();};
$('clear').onclick=async()=>{ if(confirm('주문 목록을 모두 비울까요?')){await api('/api/admin/clear',{}); load();} };
load(); setInterval(load,3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else (
            body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode("utf-8"))
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _is_admin(self):
        q = parse_qs(urlparse(self.path).query)
        return secrets.compare_digest(q.get("key", [""])[0], ADMIN_KEY)

    def _body(self):
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 20000)
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return None

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self._send(200, GUEST_HTML, "text/html; charset=utf-8")
        if path == "/admin":
            if not self._is_admin():
                return self._send(403, "키가 올바르지 않습니다.", "text/plain; charset=utf-8")
            return self._send(200, ADMIN_HTML, "text/html; charset=utf-8")
        if path == "/api/shop":
            with LOCK:
                return self._send(200, public_view())
        if path == "/api/admin/state":
            if not self._is_admin():
                return self._send(403, {"error": "forbidden"})
            with LOCK:
                url = SHOP_URL or f"http://{self.headers.get('Host', 'localhost')}/"
                out = dict(STATE)
                out["announcement"] = build_shop_announcement(STATE["shelf"], url)
                return self._send(200, out)
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        data = self._body()
        if data is None:
            return self._send(400, {"error": "잘못된 요청"})
        if path == "/api/order":
            return self._order(data)
        if not path.startswith("/api/admin/"):
            return self._send(404, {"error": "not found"})
        if not self._is_admin():
            return self._send(403, {"error": "forbidden"})
        with LOCK:
            if path == "/api/admin/reroll":
                pool = list(load_pool().values())
                cnt = max(1, min(int(data.get("count", 5)), len(pool)))
                STATE["shelf"] = random.sample(pool, cnt)
                STATE["round"] += 1
            elif path == "/api/admin/open":
                STATE["open"] = bool(data.get("open")) and bool(STATE["shelf"])
            elif path == "/api/admin/done":
                for o in STATE["orders"]:
                    if o["id"] == data.get("id"):
                        o["done"] = not o["done"]
            elif path == "/api/admin/clear":
                STATE["orders"] = []
            else:
                return self._send(404, {"error": "not found"})
            save_state()
            return self._send(200, {"ok": True})

    def _order(self, data):
        nick = str(data.get("nick", "")).strip()[:20]
        if not nick:
            return self._send(400, {"error": "닉네임을 입력해주세요."})
        with LOCK:
            if not STATE["open"]:
                return self._send(400, {"error": "상점이 닫혀 있습니다."})
            if data.get("round") != STATE["round"]:
                return self._send(409, {"error": "상품이 갱신되었습니다. 새로 고침 후 다시 선택해주세요."})
            shelf = {it["id"]: it for it in STATE["shelf"]}
            items = {}
            for k, v in (data.get("items") or {}).items():
                if k in shelf and isinstance(v, int) and 1 <= v <= 99:
                    items[k] = {"name": shelf[k]["name"], "qty": v}
            if not items:
                return self._send(400, {"error": "선택한 상품이 없습니다."})
            STATE["orders"].append({"id": STATE["next_id"], "nick": nick, "items": items,
                                    "round": STATE["round"], "ts": int(time.time()), "done": False})
            STATE["next_id"] += 1
            save_state()
        self._send(200, {"ok": True})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    load_state()
    print(f"손님 페이지 : http://localhost:{port}/")
    print(f"상점주 페이지: http://localhost:{port}/admin?key={ADMIN_KEY}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
