/* RexStüdyo ortak katman: ayarlar, tam ekran, sesli asistan (tüm sayfalarda aynı) */
(function(){"use strict";
const D={q:"4k",user:"",diaGoal:10000,likeGoal:5000,barColor:"#38e8ff",barH:14,shake:true,smoke:true,galaxy:true,feed:true,beltSpeed:7,fx:1,likeLife:10,giftLife:60,minWall:1,likeCool:20,fps:true,joinShow:true,sfx:true,
 voiceOn:true,voiceName:"",persona:"cilveli",pitch:1,rate:1,vol:1,minDia:1,readNames:true,
 vEv:{join:false,gift:true,follow:true,share:true,like:false,comment:false,goal:true},
 tpl:{gift:"{isim}, {hediye} gönderdi. Çok teşekkürler!",follow:"{isim} takip etti, hoş geldin!",share:"{isim} yayını paylaştı, sağ ol!",join:"{isim}, hoş geldin!",like:"{isim}, kalpler için teşekkürler!",comment:"{isim} diyor ki: {yorum}",goal:"Hedef tamamlandı! Hepinize teşekkürler!"},
vt:{name:"Mira",hair:"#8a6bff",eyes:"#3ec9ff",outfit:"#ff5c9a",energy:1,read:true,greet:true,chatter:true,react:true,ask:true,poll:true,draw:true},lazer:{ev:{join:"tam",like:"tam",follow:"tam",share:"tam"}},mode:"lazer",scene:"night",showGifts:true,showGiftFeed:true,showGoals:true,showDiaGoal:true,showLikeGoal:true,showLb:true,showHud:true,showCard:true,showCaps:false,argo:true,giftIcons:true,autoActs:true,
 pos:{legL:true,legR:true,lgN:4,goals:true,lb:true,lbN:5,shake:true,fps:false,persist:true,tips:true,level:true,rc:{likes:true,gifts:true,dia:true,cm:true,lvl:true,rank:true},copies:5,bigGift:5,likeBig:10,giftSec:5,bigGiftSec:12,voice:true,gifts:null,ev:{join:"fis",like:"buyuk",follow:"fis",share:"fis",comment:"fis",gift:"hepsi"}},
 karpuz:{min:15,max:60,gap:350,fruit:"karpuz",zoom:.6,orbit:.3,dist:25,pr:2,likes:10,joinC:true,ev:{like:"band",comment:"band",follow:"band",share:"band",join:"yok"},spk:true,safe:true,showLb:true,showFeed:true,legend:true,slowmo:true,shadows:true,persist:true,perf:"auto",fps:60,tips:true,gmap:""},
 mc:{likes:10,cap:60,pr:2,fps:60,persist:true,base:1,nameTag:true,pname:"Usta",ev:{like:"block1",comment:"block1",follow:"build",share:"speed",join:"none"},legend:true,tips:true,shake:true,lb:true,feed:true,spk:true,ai:true,chatter:true,gifts:null},
 cip:{legend:true,lgSize:90,lgOp:90,lgMax:4,lgSide:"both",lgY:14,lgDesc:false,gameTop:0,hudY:0,hudB:0,zoom:100,mapAuto:true,show:{dist:true,win:true,score:true,gauges:true,labels:true,top:true,name:false,banner:true,last:true,queue:true},tx:{a:{on:false,t:"BEĞENİ = İLERİ|TAKİP = GERİ",x:50,y:92,sz:16,c:"#ffffff"},b:{on:false,t:"",x:50,y:30,sz:22,c:"#ffd36a"},c:{on:false,t:"",x:50,y:60,sz:22,c:"#6df0ff"}},goal:5000,car:"supra",map:"green",autoSpd:2.2,winGoal:1000,likeEvery:20,spk:true,coins:true,fuel:true,ev:{like:"fwd10",follow:"back10",share:"turbo",join:"boost1",comment:"none"},gifts:null},
 ai:{on:true,rewrite:true,reply:true,idle:true,style:"samimi"},
 slime:{spk:true,aggro:2,guard:30,legend:true,tips:true,chat:true,likes:10,safe:true,gifts:null,pr:3,perf:"auto",fps:60,shadows:true,dist:1,ev:{like:"knead",follow:"glitter",share:"dye"}},
 arena:{ev:{join:"katil",like:"begeni",follow:"takip",share:"paylasim",gift:"hediye"},spk:true,autoVoice:true,spkPersona:"spiker",spkRate:1.05,spkPitch:1,spkVol:1,spkJoin:true,spkKill:true,spkGift:true,spkLike:true,spkFollow:true,spkLevel:true,spkLead:true,spkLeave:true,leaveSec:10,idleLeave:120,spkLeadSec:60,maxPlayers:100,food:120,likeMul:1,giftMul:1,shake:true,joinOnComment:true,showTop:true,showTicker:true,showLb:true,showFeed:true,showKill:true,showGrowth:true,showSpeakerLine:true,showGoals:true,showTest:false}};
const merge=(a,b)=>{for(const k in b){if(b[k]&&typeof b[k]==="object"&&!Array.isArray(b[k]))merge(a[k]=a[k]||{},b[k]);else a[k]=b[k]}return a};
const Rex=window.Rex={D,cfg:merge(JSON.parse(JSON.stringify(D)),(()=>{try{return JSON.parse(localStorage.getItem("rex_cfg"))||{}}catch(e){return{}}})()),
 save(){localStorage.setItem("rex_cfg",JSON.stringify(Rex.cfg))},
 get(p){return p.split(".").reduce((o,k)=>o&&o[k],Rex.cfg)},
 set(p,v){const a=p.split("."),l=a.pop();let o=Rex.cfg;a.forEach(k=>o=o[k]=o[k]||{});o[l]=v;Rex.save()},
 reset(){Rex.cfg=JSON.parse(JSON.stringify(D));Rex.save()},
 fmt:n=>Math.round(n).toLocaleString("tr-TR")};
/* ---------- ayar senkronu: stüdyo değiştirince açık tüm sayfalar anında günceller ---------- */
addEventListener("storage",e=>{if(e.key!=="rex_cfg"&&e.key!==null)return;try{const nc=merge(JSON.parse(JSON.stringify(D)),JSON.parse(e.newValue||localStorage.getItem("rex_cfg")||"{}"));for(const k in Rex.cfg)delete Rex.cfg[k];Object.assign(Rex.cfg,nc);}catch(x){}});
/* ---------- hediye kataloğu + ikon + ekran kartı (tüm modlar) ---------- */
Rex.GIFTCAT=[["Rose,Gül","🌹"],["Heart,Kalp","❤️"],["Finger Heart,Parmak Kalbi","🫰"],["Hand Hearts,El Kalpleri","🤲"],["Doughnut,Donut","🍩"],["GG,GG","🎮"],["TikTok,TikTok","🎵"],["Corgi,Corgi","🐶"],["Lion,Aslan","🦁"],["Panda,Panda","🐼"],["Galaxy,Galaksi","🌌"],["Interstellar,Yıldızlararası","🚀"],["Sunglasses,Güneş Gözlüğü","🕶️"],["Confetti,Konfeti","🎉"],["Money Gun,Para Tabancası","💸"],["Perfume,Parfüm","🧴"],["Cap,Şapka","🧢"],["Ice Cream Cone,Dondurma","🍦"],["Paper Crane,Kağıt Turna","🕊️"],["Swan,Kuğu","🦢"],["Coin,Jeton","🪙"],["Water Drop,Su Damlası","💧"],["Water,Su","💧"],["Bucket,Kova","🪣"],["Glue,Tutkal","🧴"],["Egg,Yumurta","🥚"],["Blue Heart,Mavi Kalp","💙"],["Red Cup,Kırmızı Bardak","🥤"],["Blue Star,Mavi Yıldız","⭐"],["Trophy,Kupa","🏆"],["Fireworks,Havai Fişek","🎆"],["Rocket,Roket","🚀"],["Crown,Taç","👑"],["Castle,Kale","🏰"],["Diamond,Elmas","💎"]].map(([n,i])=>({n,i}));
Rex.giftIcon=u=>{u=String(u||"");if(!u)return "";if(/^https?:/.test(u))return '<img src="/img?u='+encodeURIComponent(u)+'" alt="">';if(/^data:/.test(u))return '<img src="'+u.replace(/"/g,"")+'" alt="">';return '<span class="emo">'+u.replace(/[<>&"]/g,"")+'</span>';};
Rex.giftRow=(mode,name)=>{const rows=(Rex.cfg[mode]||{}).gifts;if(!Array.isArray(rows))return null;const n=String(name||"").toLowerCase().trim();return rows.find(r=>String(r.n||"").toLowerCase().split(",").map(x=>x.trim()).includes(n))||null;};
let _gcHost=null;
function gcHost(){if(_gcHost&&document.body.contains(_gcHost))return _gcHost;const st=document.createElement("style");st.textContent=".rgc{position:relative;display:flex;align-items:center;gap:12px;padding:10px 20px 10px 10px;border-radius:18px;background:linear-gradient(135deg,rgba(18,20,28,.94),rgba(44,30,18,.92));border:1px solid rgba(255,190,110,.38);box-shadow:0 12px 34px rgba(0,0,0,.45);color:#fff;font-family:system-ui,sans-serif;animation:rgcIn .45s cubic-bezier(.2,.9,.3,1.2) both}.rgc.out{animation:rgcOut .42s ease forwards}.rgi{width:60px;height:60px;border-radius:14px;background:rgba(255,255,255,.08);display:flex;align-items:center;justify-content:center;flex:none}.rgi img{width:52px;height:52px;object-fit:contain}.rgt small{display:block;font-size:13px;color:#cfd6e4}.rgt strong{display:block;font-size:22px;font-weight:800;color:#ffd58a}.rgn{position:absolute;right:14px;top:8px;font-size:18px;color:#7ff0ff}#rexGC{position:fixed;top:4%;left:50%;transform:translateX(-50%);display:flex;flex-direction:column;gap:8px;align-items:center;z-index:9999;pointer-events:none;width:min(92vw,520px)}@keyframes rgcIn{from{opacity:0;transform:translateY(-16px) scale(.92)}to{opacity:1;transform:none}}@keyframes rgcOut{to{opacity:0;transform:translateY(-10px) scale(.96)}}.emo{display:inline-block;font-size:1.1em;line-height:1;font-family:\"Apple Color Emoji\",\"Segoe UI Emoji\",\"Noto Color Emoji\",sans-serif}.rgi .emo{font-size:40px}";
  document.head.appendChild(st);_gcHost=document.createElement("div");_gcHost.id="rexGC";document.body.appendChild(_gcHost);return _gcHost;}
// Hediye geldiğinde ekranda kısa kart: seçilen hediyenin adı ve ikonu (satırdaki Türkçe ad + ikon öncelikli)
Rex.giftCard=(user,gift,icon,count,mode)=>{try{const r=mode?Rex.giftRow(mode,gift):null;const ic=(r&&r.i)||icon||"";const al=r?String(r.n).split(",").map(x=>x.trim()).filter(Boolean):[];
  const name=al.length?al[al.length-1]:String(gift||"Hediye");const c=String(count||1);const e=s=>String(s==null?"":s).replace(/[<>&"]/g,"");
  const h=gcHost(),card=document.createElement("div");card.className="rgc";
  card.innerHTML='<div class="rgi">'+(Rex.giftIcon(ic)||'<span class="emo">🎁</span>')+'</div><div class="rgt"><small>'+e(user||"izleyici")+' gönderdi</small><strong>'+e(name)+'</strong></div>'+(+c>1?'<b class="rgn">×'+e(c)+'</b>':'');
  h.appendChild(card);while(h.children.length>3)h.firstChild.remove();
  setTimeout(()=>{card.classList.add("out");setTimeout(()=>card.remove(),450);},3800);}catch(err){}};
/* ---------- tam ekran (her sayfada sağ altta) ---------- */
function fs(){const d=document,el=d.documentElement;if(!(d.fullscreenEnabled||d.webkitFullscreenEnabled))return;
 let b=d.getElementById("fs");
 if(!b){const st=d.createElement("style");st.textContent="#fs{position:fixed;right:12px;bottom:var(--fsb,14px);width:42px;height:42px;border-radius:50%;border:1px solid rgba(255,255,255,.2);background:rgba(14,15,19,.78);backdrop-filter:blur(8px);color:#fff;display:grid;place-items:center;cursor:pointer;z-index:9999;padding:0;transition:transform .2s,background .3s}#fs:hover{background:rgba(255,106,43,.55)}#fs:active{transform:scale(.88)}#fs svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}#fs .c,#fs.on .e{display:none}#fs.on .c{display:block}";d.head.appendChild(st);
  b=d.createElement("button");b.id="fs";b.setAttribute("aria-label","Tam ekran");b.innerHTML='<svg viewBox="0 0 24 24"><path class="e" d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/><path class="c" d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5"/></svg>';
  d.body.style.setProperty("--fsb",d.body.dataset.fsBottom||"14px");d.body.appendChild(b)}
 const cur=()=>d.fullscreenElement||d.webkitFullscreenElement,tog=()=>cur()?(d.exitFullscreen||d.webkitExitFullscreen).call(d):(el.requestFullscreen||el.webkitRequestFullscreen).call(el);
 b.onclick=tog;const upd=()=>b.classList.toggle("on",!!cur());d.addEventListener("fullscreenchange",upd);d.addEventListener("webkitfullscreenchange",upd);
 addEventListener("keydown",e=>{if((e.key==="f"||e.key==="F")&&!/INPUT|TEXTAREA|SELECT/.test((e.target||{}).tagName||""))tog()})}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",fs);else fs();
/* ---------- sesli asistan ---------- */
const PERS=[{id:"cilveli",n:"Cilveli genç kız",p:1.2,r:.96},{id:"dogal",n:"Doğal",p:1,r:1},{id:"spiker",n:"Haber spikeri",p:.9,r:1.08},{id:"derin",n:"Derin ve gizemli",p:.62,r:.86},{id:"fisilti",n:"Fısıltı",p:1.15,r:.82,v:.55},{id:"enerjik",n:"Enerjik sunucu",p:1.3,r:1.18},{id:"sevimli",n:"Sevimli asistan",p:1.5,r:1.1},{id:"robot",n:"Robot",p:.3,r:.95},{id:"cocuk",n:"Çocuk",p:1.9,r:1.05},{id:"bilge",n:"Yaşlı bilge",p:.5,r:.78},{id:"epik",n:"Epik anons",p:.55,r:.9}];

/* ---------- izleyici etkileşimi eşlemesi (tüm modlar) ---------- */
const EVOPT={
 karpuz:[["yok","Hiçbir şey"],["band","Lastik tak (+1)"],["thick","Kalın lastik"],["rain","Lastik yağmuru (5)"],["scissor","Lastik çıkar / makas"],["kolibandi","Kolibandı (+3 dayanım)"],["gold","Altın lastik (3 güç)"],["hammer","Dev çekiç (anında patlat)"]],
 lazer:[["yok","Hiçbir şey"],["tam","Tam tepki (puan, kalp, havai, konuşma)"],["puan","Sadece puan"],["kalp","Kalp yağmuru"],["patlama","Havai fişek"],["konus","Sesli tepki"]],
 arena:[["yok","Hiçbir şey"],["katil","Arenaya katıl"],["begeni","Beğeni puanı"],["takip","Takip bonusu"],["paylasim","Paylaşım bonusu"],["hediye","Hediye ödülü"]],
 slime:[["yok","Hiçbir şey"],["knead","Yoğur"],["glitter","Sim dök"],["foam","Köpük dök"],["ketchup","Ketçap dök"],["borax","Boraks dök"],["water1","1 litre su dök"],["glue","Tutkal dök"],["dye","Rastgele boya dök"]],
 minecraft:[["none","Hiçbir şey"],["block1","+1 blok"],["build","Blok yağmuru (+10 blok)"],["rain","Mega blok yağmuru (+25 blok)"],["diamond","Elmas bloklar (+5)"],["bomb","Bomba"],["tnt","TNT"],["light","Şimşek"],["storm","Fırtına (3 şimşek)"],["speed","Hız (8 sn)"],["nuke","Nükleer TNT (4 TNT)"],["fireworks","Havai fişek"],["jump","Karakter zıplasın"],["gold","Altın bloklar (+8)"],["emerald","Zümrüt bloklar (+8)"],["obsidian","Obsidyen (+6)"],["creeper","Creeper saldırısı"]]
};
const EVKEYS={karpuz:[["like","Beğeni"],["comment","Yorum"],["follow","Takip"],["share","Paylaşım"],["join","Katılım"]],lazer:[["join","Katılım"],["like","Beğeni"],["follow","Takip"],["share","Paylaşım"]],arena:[["join","Katılım"],["like","Beğeni"],["follow","Takip"],["share","Paylaşım"],["gift","Hediye"]],slime:[["like","Beğeni"],["follow","Takip"],["share","Paylaşım"]],minecraft:[["like","Beğeni"],["comment","Yorum"],["follow","Takip"],["share","Paylaşım"],["join","Katılım"]]};
EVOPT.cip=[["yok","Hiçbir şey"],["boost1","Küçük hızlanma"],["boost2","Büyük hızlanma"],["turbo","Turbo (8 sn süper hız)"],["fwd10","10 m ileri"],["fwd25","25 m ileri"],["back10","10 m geri"],["back25","25 m geri"],["win","WIN +1"],["coin","Altın yağmuru"],["arrow","Alevli ok"],["bolt","Yıldırım"],["jail","Hapis (8 sn)"]];
EVKEYS.cip=[["like","Beğeni"],["follow","Takip"],["share","Paylaşım"],["join","Katılım"],["comment","Yorum"]];
EVOPT.pos=[["yok","Hiçbir şey"],["fis","Fişe bas"],["buyuk","Büyük fiş (profil büyük)"],["ekran","POS ekranında göster"],["hepsi","Ekran + fiş + sesli okuma"]];
EVKEYS.pos=[["join","Katılım"],["like","Beğeni"],["follow","Takip"],["share","Paylaşım"],["comment","Yorum"],["gift","Hediye"]];
Rex.EVOPT=EVOPT;Rex.EVKEYS=EVKEYS;
Rex.evAct=(mode,type)=>{const e=(Rex.cfg[mode]||{}).ev;return (e&&e[type])||"yok"};
const V=Rex.voice={personas:PERS,muted:localStorage.getItem("rex_muted")==="1",q:[],busy:false,tok:0,
 list(){try{return speechSynthesis.getVoices()}catch(e){return[]}},
 pick(){const vs=V.list(),c=Rex.cfg;return vs.find(v=>v.name===c.voiceName)||vs.find(v=>/^tr/i.test(v.lang)&&/emel|yelda|female/i.test(v.name))||vs.find(v=>/^tr/i.test(v.lang))||null},
 params(){const c=Rex.cfg,p=PERS.find(x=>x.id===c.persona)||PERS[0];return{pitch:Math.min(2,Math.max(0,p.p*c.pitch)),rate:Math.min(2,Math.max(.5,p.r*c.rate)),vol:Math.min(1,Math.max(0,(p.v||1)*c.vol))}},
 make(text){const u=new SpeechSynthesisUtterance(text),q=V.params(),v=V.pick();u.lang="tr-TR";u.pitch=q.pitch;u.rate=q.rate;u.volume=q.vol;if(v){u.voice=v;u.lang=v.lang}return u},
 can(){return Rex.cfg.voiceOn&&!V.muted&&"speechSynthesis" in window},
 allow(ev,dia){const c=Rex.cfg;return V.can()&&c.vEv[ev]&&(ev!=="gift"||(dia||0)>=c.minDia)},
 name(n){return Rex.cfg.readNames?String(n||"").replace(/[_.\d]+/g," ").replace(/\s+/g," ").trim().slice(0,22)||"dostum":"dostum"},
 fill(k,o){return(Rex.cfg.tpl[k]||"").replace(/\{(\w+)\}/g,(_,x)=>o[x]!=null?o[x]:"")},
 say(text,o){o=o||{};if(!V.can())return false;if(o.pr>=2){V.q.length=0;try{speechSynthesis.cancel()}catch(e){}V.busy=false}else if(V.q.length>2)V.q.shift();V.q.push({text,o});if(!V.busy)V.next();return true},
 next(){const it=V.q.shift(),my=++V.tok;if(!it){V.busy=false;return}V.busy=true;const done=()=>{if(my!==V.tok)return;it.o.onend&&it.o.onend();setTimeout(V.next,250)};
  try{const u=V.make(it.text);u.onstart=()=>it.o.onstart&&it.o.onstart();u.onboundary=()=>it.o.onboundary&&it.o.onboundary();u.onend=u.onerror=done;speechSynthesis.speak(u);setTimeout(done,9000+it.text.length*90)}catch(e){done()}},
 stop(){V.q.length=0;V.busy=false;V.tok++;try{speechSynthesis.cancel()}catch(e){}},
 mute(m){V.muted=m;localStorage.setItem("rex_muted",m?"1":"0");if(m)V.stop()},
 test(t){V.say(t||"Merhaba, ben yayın asistanınız. Sesim böyle duyuluyor.",{pr:2})}};
V.best=()=>{const vs=V.list().filter(v=>/^tr/i.test(v.lang));return vs.find(v=>v.name===Rex.cfg.voiceName)||vs.find(v=>/natural|neural|online/i.test(v.name))||vs.find(v=>/google|emel|yelda/i.test(v.name))||vs[0]||null};
V.speaker=(text,o)=>{o=o||{};const A=Rex.cfg.arena,p=PERS.find(x=>x.id===(o.persona||A.spkPersona))||PERS[2],u=new SpeechSynthesisUtterance(text),v=V.best();u.lang="tr-TR";u.pitch=Math.min(2,p.p*(A.spkPitch||1));u.rate=Math.min(2,Math.max(.5,p.r*(A.spkRate||1)));u.volume=Math.min(1,(p.v||1)*(A.spkVol==null?1:A.spkVol)*(Rex.cfg.vol==null?1:Rex.cfg.vol));if(v){u.voice=v;u.lang=v.lang}return u};
try{speechSynthesis.getVoices();speechSynthesis.onvoiceschanged=()=>document.dispatchEvent(new Event("rexvoices"))}catch(e){}
/* ---------- YAPAY ZEKA SES: tüm modlarda konuşulan her cümle, modun durumuyla gerçek yapay zekadan geçer ---------- */
const MD={"/lazer":"Yayıncı 1: anime sanal yayıncı","/arena":"Neon Arena: izleyiciler karakter büyütür","/karpuz":"Karpuz Patlat: lastikle karpuz patlatma","/slime":"Slime Atölyesi: slime yapımı","/minecraft":"Minecraft blok kulesi","/cip":"Cip Parkuru: araç yavaş gider, hediye ve beğeni hızlandırır"};
const ST={samimi:"samimi, sıcak, cilveli",hype:"çok enerjik, coşkulu sunucu",komik:"esprili ve komik",sakin:"sakin ve nazik",agresif:"iddialı, kafa bulan ama kibar"};
const AI=Rex.ai={ctx:()=>"",off:0,done:new Set(),gen:0,lastSay:Date.now(),
 on(){const a=Rex.cfg.ai||{};return a.on!==false&&a.rewrite!==false&&Date.now()>AI.off},
 sys(){const a=Rex.cfg.ai||{};let c="";try{c=AI.ctx()||""}catch(e){}return "Sen bir TikTok canlı yayınında sesli yapay zeka asistansın. Yayın modu: "+(MD[location.pathname]||"canlı yayın")+". Durum: "+c+". Tarz: "+(ST[a.style]||ST.samimi)+". Türkçe konuş, en fazla 1-2 kısa cümle, emoji ve tırnak kullanma, küfür ve hakaret etme. Sadece söylenecek metni yaz."},
 async ask(user,sys,ms){const c=new AbortController(),t=setTimeout(()=>c.abort(),ms||4000);try{const r=await fetch("/ai",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({system:sys||AI.sys(),user,max_tokens:90}),signal:c.signal}),j=await r.json();if(j.ok&&j.text)return String(j.text).replace(/["*#]/g,"").trim().slice(0,220);if(j.err==="nokey")AI.off=Date.now()+90000;return ""}catch(e){return ""}finally{clearTimeout(t)}},
 say(t){AI.done.add(t);V.say(t,{pr:1})}};
try{const _sp=speechSynthesis.speak.bind(speechSynthesis),_cn=speechSynthesis.cancel.bind(speechSynthesis);
 speechSynthesis.cancel=function(){AI.gen++;return _cn()};
 speechSynthesis.speak=function(u){AI.lastSay=Date.now();if(u._ai||!u.text||u.text.length<4||AI.done.has(u.text)||!AI.on()||!MD[location.pathname])return _sp(u);const g=AI.gen,o=u.text;
  AI.ask("Şu cümleyi anlamını, isimleri ve sayıları koruyarak kendi ağzınla canlı söyle: "+o,AI.sys(),3500).then(t=>{if(g!==AI.gen)return;let x=u;if(t){x=new SpeechSynthesisUtterance(t);["lang","voice","pitch","rate","volume","onstart","onend","onerror","onboundary"].forEach(k=>{try{x[k]=u[k]}catch(e){}})}x._ai=1;_sp(x)})}}catch(e){}
if(MD[location.pathname]&&window.EventSource){let lr=0;const es=new EventSource("/events");es.onmessage=e=>{try{const d=JSON.parse(e.data),a=Rex.cfg.ai||{};if(d.type!=="comment"||!d.text||a.on===false||a.reply===false||!V.can()||Date.now()<AI.off||Date.now()-lr<9000)return;lr=Date.now();
  AI.ask((d.nickname||"izleyici")+" yayında şunu yazdı: "+d.text,AI.sys()+" Yoruma yayıncı asistan olarak kısa cevap ver; siyaset, küfür veya kişisel bilgi varsa kibarca geç ve oyuna dön.",5000).then(t=>t&&AI.say(t))}catch(x){}};
 setInterval(()=>{const a=Rex.cfg.ai||{};if(a.on===false||a.idle===false||!V.can()||Date.now()<AI.off||Date.now()-AI.lastSay<60000)return;AI.ask("Yayında sessizlik oldu. İzleyicileri hediye, beğeni ve takip ile oyuna katılmaya çağıran kısa bir cümle söyle.",AI.sys(),5000).then(t=>t&&AI.say(t))},20000)}

})();
