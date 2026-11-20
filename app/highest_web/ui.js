"use strict";
const app=document.getElementById("app");
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n};
const add=(p,...nodes)=>{p.append(...nodes);return p};
const panel=(title)=>add(el("section",null,"panel"),el("h2",title));
const button=(label,fn,secondary=false)=>{let b=el("button",label,secondary?"secondary":"");b.type="button";b.onclick=async()=>{b.disabled=true;try{await fn()}catch(e){showError(e)}finally{b.disabled=false}};return b};
const link=(label,url)=>{let a=el("a",label);a.href=url;a.target="_blank";a.rel="noopener noreferrer";return a};
async function api(path,body,method="POST"){let r=await fetch("/highest/api"+path,{credentials:"same-origin",cache:"no-store",...(body===undefined?{}:{method,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})});let data=await r.json();if(!r.ok){const e=new Error(typeof data.detail==="string"?data.detail:"Invalid request");e.status=r.status;throw e}return data}

async function uploadApi(path,data){
 let response=await fetch("/highest/api"+path,{method:"POST",credentials:"same-origin",cache:"no-store",body:data});
 let result=await response.json();
 if(!response.ok){const error=new Error(typeof result.detail==="string"?result.detail:"Upload failed");error.status=response.status;throw error}
 return result
}
function showError(e){if(streamSafe)return;let p=document.getElementById("notice");if(p)p.textContent=e.message;else app.prepend(el("p",e.message,"error"))}
function form(fields,submit,fn){const f=el("form");const inputs={};for(const [key,label,type,opts,value] of fields){let l=el("label",label);let i=el(type==="select"?"select":(type==="textarea"||type==="optional_textarea")?"textarea":"input");i.name=key;i.required=type!=="optional"&&type!=="optional_textarea"&&key!=="parent"&&!(type==="select"&&opts?.some(x=>x[0]===""));if(type==="select"){for(const [val,txt] of opts){let o=el("option",txt);o.value=val;i.append(o)}}else if(type!=="textarea"&&type!=="optional_textarea"){i.type=type==="password"?"password":type==="number"?"number":type==="datetime-local"?"datetime-local":type==="month"?"month":"text";if(type==="password"){i.minLength=12;i.maxLength=128;i.autocomplete=key==="confirm"?"new-password":"current-password"}if(key==="username")i.autocomplete="username"}if(value!=null)i.value=value;inputs[key]=i;l.append(i);f.append(l)}let b=el("button",submit);b.type="submit";f.append(b);f.onsubmit=async e=>{e.preventDefault();b.disabled=true;try{await fn(Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.value]))); }catch(err){showError(err)}finally{b.disabled=false}};return f}
let streamSafe=false;try{streamSafe=sessionStorage.getItem("highest_stream_safe")==="1"}catch{};
let me=null,view=location.pathname.includes("/internal/")?"internal":location.pathname.includes("/admin/")?"admin":"community";
function auth(register=false){app.replaceChildren();let p=el("section",null,"panel auth");let img=el("img");img.src="/highest/logo.png";img.alt="The Highest";let fields=[["username","Username","text"],["password","Password · minimal 12 karakter","password"]];if(register)fields.unshift(["display_name","Display name","text"]);if(register)fields.push(["confirm","Confirm password","password"]);add(p,img,el("h1",register?"Create your account":"Welcome to Headquarters"),el("p","Independent account · No Discord login","muted"),form(fields,register?"CREATE ACCOUNT":"SIGN IN",async d=>{if(register&&d.password!==d.confirm)throw Error("Password confirmation mismatch");delete d.confirm;await api(register?"/register":"/login",d);await boot()}),button(register?"Already have an account? Sign in":"New here? Create account",()=>auth(!register),true));let notice=el("p",null,"error");notice.id="notice";p.append(notice,link("Back to ABUD","/"));app.append(p)}
function switchView(next){view=next;history.replaceState(null,"","/highest/"+next+"/");render()}
function heading(){let box=el("section",null,"hero");add(box,el("small","THE OFFICIAL HEADQUARTERS"),el("h1",view==="internal"?"Internal HQ":view==="admin"?"Administration Center":"Beyond the hierarchy."),el("p","Welcome, "+me.display_name+" · Membership: "+me.status));let nav=el("nav");nav.append(button("Community Hub",()=>switchView("community"),true));if(me.status==="approved")nav.append(button("Internal HQ",()=>switchView("internal"),true));if(me.admin)nav.append(button("Admin Center",()=>switchView("admin"),true));nav.append(button("Streamer Mode",()=>setStreamSafe(true),true));nav.append(button("Sign out",async()=>{await api("/logout",{});location.href="/highest/"},true));box.append(nav);return box}
async function community(){let [d,social]=await Promise.all([api("/community"),api("/social")]);let root=el("div"),live=panel("Live Stream Center"),cards=el("div",null,"grid");let order={live:0,offline:1,unknown:2};d.streamers.sort((a,b)=>order[a.status]-order[b.status]);for(const s of d.streamers){let t=el("article",null,"tile");add(t,el("small",s.platform.toUpperCase()),el("h3",s.name),el("p",s.status==="unknown"?"● STATUS UNAVAILABLE":"● "+s.status.toUpperCase(),"status "+s.status),link(s.status==="live"?"Watch now ↗":"Open channel ↗",s.url),el("p"),button(social.follows.includes(s.id)?"Following":"Follow",()=>postRefresh("/social/follow/"+s.id,{enabled:!social.follows.includes(s.id)}),true));cards.append(t)}if(!cards.children.length)cards.append(el("p","Streamer directory is waiting for admin setup.","muted"));live.append(cards);root.append(live);
let member=panel("The Highest Membership");member.append(el("p","Status: "+me.status));if(me.status==="pending")member.append(el("p","Waiting for administrator approval. Your account remains community-only.","muted"));else if(me.status!=="approved")member.append(form([["character","Nama karakter IC","text"],["callsign","Callsign (opsional)","optional"],["requested","Jabatan IC (opsional)","optional"]],"Apply as HT Member",async d=>{await api("/apply",d);await boot()}));root.append(member);
let clips=panel("Clip Center");clips.append(form([["title","Clip title","text"],["url","YouTube or TikTok link","text"]],"Submit for review",async d=>{await api("/clip",d);alert("Clip submitted for moderator review.");await render()}));let list=el("div",null,"grid");for(const c of social.clips){let t=el("article",null,"tile");add(t,el("h3",c.title),el("small","By "+c.display_name),el("p"),link("Watch clip ↗",c.url),el("p"),button((c.liked?"Unlike":"Like")+" · "+c.likes,()=>postRefresh("/social/clip/"+c.id+"/like",{enabled:!c.liked}),true),button(c.bookmarked?"Saved":"Bookmark",()=>postRefresh("/social/clip/"+c.id+"/bookmark",{enabled:!c.bookmarked}),true),reportControl("clip",c.id));list.append(t)}if(!list.children.length)list.append(el("p","No published clips yet.","muted"));clips.append(list);root.append(clips,await socialPanel(social));return root}
function tree(ranks,parent=null,seen=new Set()){let t=el("div",null,"tree");for(const r of ranks.filter(r=>r.parent===parent)){if(seen.has(r.id))continue;seen.add(r.id);t.append(el("p",r.name+" · "+r.position),tree(ranks,r.id,seen))}return t}
let notificationPoller=null;
async function notificationPanel(){
 let d=await api("/notifications"),p=panel("HQ Notification Center");
 let summary=el("p",d.unread_count+" unread · live inbox refreshes every 30 seconds while this page is open","muted");
 summary.id="hq-notification-summary";p.append(summary);
 const controls=el("div",null,"row");
 controls.append(button("Refresh inbox",async()=>await render(),true));
 if(d.unread_count)controls.append(button("Mark all as read",async()=>{await api("/notifications/read-all",{});await render()},true));
 p.append(controls);
 const list=el("div",null,"grid");
 for(const item of d.items){
  const card=el("article",null,"tile");
  add(card,el("h3",item.title),el("small",item.kind.replaceAll("_"," ")+" · "+dateFormat(item.created)),el("p",item.body||""));
  if(!item.read_at)card.append(button("Mark as read",async()=>{await api("/notifications/"+item.id+"/read",{});await render()},true));
  list.append(card);
 }
 if(!d.items.length)list.append(el("p","You're all caught up. No notifications yet.","muted"));
 p.append(list);
 if(notificationPoller)clearInterval(notificationPoller);
 notificationPoller=setInterval(async()=>{
  if(view!=="internal"||document.hidden)return;
  try{
   const fresh=await api("/notifications?limit=1");
   if(fresh.unread_count!==d.unread_count||((fresh.items[0]?.id||0)!==(d.items[0]?.id||0)))await render();
  }catch(e){}
 },30000);
 return p;
}

async function executiveDashboard(){
 const d=await api("/ops/executive"),sections=d.sections||{},p=panel("Executive Intelligence Dashboard");
 const heading=el("div",null,"row");add(heading,el("div","Organization-wide snapshot · live database figures · permission-scoped","muted"),button("Refresh dashboard",async()=>await render(),true));p.append(heading);
 const grid=el("div",null,"grid");
 const metric=(label,value,sub)=>{const t=el("article",null,"tile");add(t,el("small",label),el("h2",String(value)),el("p",sub||""));grid.append(t)};
 metric("Approved members",d.membership.active,"Across all approved ranks");
 metric("Pending membership",d.membership.pending,"Awaiting membership review");
 if(sections.approvals)metric("Pending approvals",sections.approvals.pending,"Within modules you can access");
 if(sections.treasury){const x=sections.treasury;metric("Treasury balance",moneyFormat(x.balance),x.accounts+" active accounts");metric("Pending transactions",x.pending_transactions,"Awaiting Treasury review");}
 if(sections.inventory){const x=sections.inventory;metric("Inventory stock",x.stock_units.toLocaleString("id-ID")+" units",x.items+" item types · "+x.vaults+" stash locations");metric("Inventory valuation",moneyFormat(x.stock_value),x.unvalued_units+" units without recorded cost");metric("Low-stock alerts",x.low_stock,"Items below minimum stock");}
 if(sections.assets){const x=sections.assets;metric("Registered assets",x.total,x.available+" available · "+x.assigned+" assigned");metric("Asset acquisition value",moneyFormat(x.acquisition_cost),x.maintenance+" under maintenance · "+x.retired+" retired");}
 if(sections.operations){const x=sections.operations;metric("Upcoming operations",x.upcoming,"Planned or in progress");metric("Operations in progress",x.in_progress,x.completed+" completed records");}
 if(sections.cases){const x=sections.cases;metric("Registered cases",x.total,x.open+" open · "+x.review+" under review · "+x.closed+" closed");metric("Evidence files",x.evidence_files,x.evidence_events+" custody and access events");metric("Integrity failures",x.integrity_failures,"Recorded evidence integrity failures");}
 if(sections.security){metric("Audit events · 7 days",sections.security.audit_events_7d,"Organization-wide audit activity");metric("Flagged security events",sections.security.flagged_events_7d,"Integrity, denied or failed action markers");}
 p.append(grid);
 const links=el("nav");
 const navItems=[["treasury","Treasury"],["inventory","Vault & Inventory"],["assets","Assets"],["operations","Operations Calendar"],["cases","Case Files"],["financial_reports","Financial Reporting"]];
 for(const [key,label] of navItems){if(d.permissions.includes(key))links.append(button("Open "+label,async()=>{opsTab=key;await render()},true))}
 if(links.childElementCount){p.append(el("h3","Open operational modules"),links)}
 if(sections.operations&&sections.operations.recent?.length){
  p.append(el("h3","Recent operational schedule"));
  for(const x of sections.operations.recent){const card=el("article",null,"tile");add(card,el("h3",x.title),el("p",x.category+" · "+(x.division||"Unassigned division")+" · "+(x.owner||"No owner")),el("small",new Date(x.starts_at).toLocaleString("id-ID",{timeZone:"Asia/Jakarta"})+" WIB · "+x.status.replace("_"," ").toUpperCase()));p.append(card)}
 }
 if(sections.security&&sections.security.recent?.length){
  p.append(el("h3","Recent audit activity · administrator only"));
  for(const x of sections.security.recent){p.append(el("p",dateFormat(x.created)+" · "+(x.username||"System")+" · "+x.action+" · #"+x.target))}
 }
 p.append(el("small","Dashboard data is read-only. Each section is included only when your current rank has permission for its source module.","muted"));
 return p
}
async function internal(){let d=await api("/internal"),root=el("div");root.append(await executiveDashboard());root.append(await notificationPanel());let h=panel("Organizational hierarchy");h.append(tree(d.ranks));root.append(h);let members=panel("Personnel roster");for(const m of d.members){let rank=d.ranks.find(r=>r.id===m.rank);members.append(el("p",m.character+" · "+(m.callsign||"—")+" · "+(rank?.name||"—")+" · "+m.position))}root.append(members);root.append(await opsPanel());return root}
async function businessProfileAdmin(){
let data=await api("/admin/business-profiles"),p=panel("Business profile & document branding");
p.append(el("p","Create one profile for each business unit. Every new order stores a permanent snapshot of the selected identity, document numbering, logo and visual style. Existing invoices and receipts are not rewritten when a profile changes.","muted"));
const templates=[["classic","Classic · Black & gold"],["executive","Executive · Dark header"],["minimal","Minimal · Clean layout"]];
const yesNo=[["true","Yes"],["false","No"]];
const fields=x=>[
 field("code","Unit code (2–20 letters/numbers)","text",null,x?.code??""),
 field("name","Business name","text",null,x?.name??""),
 field("description","Business description","optional",null,x?.description??""),
 field("organization_name","Organization identity","optional",null,x?.organization_name??"THE HIGHEST"),
 field("contact_name","IC contact name","optional",null,x?.contact_name??""),
 field("contact_details","IC contact details","optional",null,x?.contact_details??""),
 field("logo_url","Public HTTPS logo URL","optional",null,x?.logo_url??""),
 field("invoice_prefix","Invoice number prefix","text",null,x?.invoice_prefix??"INV"),
 field("receipt_prefix","Receipt number prefix","text",null,x?.receipt_prefix??"RCT"),
 field("template","Document template","select",templates,x?.template??"classic"),
 field("accent_color","Accent color · HEX","text",null,x?.accent_color??"#b58b4a"),
 field("footer","Custom document footer","optional",null,x?.footer??""),
 field("active","Business unit status","select",yesNo,String(Boolean(x?.active??true))),
 field("is_default","Default for new orders","select",yesNo,String(Boolean(x?.is_default??false)))
];
const save=async(v,id)=>{
 const payload={...v,active:v.active==="true",is_default:v.is_default==="true"};
 if(id!=null)payload.id=id;
 await api("/admin/business-profiles",payload);
 await render();
};
p.append(el("h3","Add business unit"),form(fields(null),"Create business profile",v=>save(v,null)));
p.append(el("h3","Existing business units"));
for(const profile of data.profiles){
 let card=el("article",null,"tile");
 add(card,el("h3",profile.name),el("small",profile.code+" · "+(profile.is_default?"DEFAULT FOR NEW ORDERS · ":"")+(profile.active?"ACTIVE":"INACTIVE")));
 card.append(form(fields(profile),"Save business profile",v=>save(v,profile.id)));
 p.append(card);
}
return p
}

async function admin(){let d=await api("/admin"),root=el("div"),ranks=panel("Rank & hierarchy editor");let opts=[["","No parent"],...d.ranks.map(r=>[String(r.id),r.name])],rankOpts=d.ranks.map(r=>[String(r.id),r.name]);const rankFields=r=>[["name","Rank name","text",null,r?.name],["position","Order (0 = highest)","number",null,r?.position??0],["parent","Reports to","select",opts,r?.parent??""]];const saveRank=async(values,id)=>{await api("/admin/rank",{id,name:values.name,position:Number(values.position),parent:values.parent?Number(values.parent):null});await render()};ranks.append(form(rankFields(),"Add rank",d=>saveRank(d,null)));for(const r of d.ranks){let t=el("div",null,"tile");t.append(el("h3",r.name),form(rankFields(r),"Save rank",v=>saveRank(v,r.id)),button("Delete rank",async()=>{if(confirm("Delete rank?")){await api("/admin/rank/delete/"+r.id,{});await render()}},true));ranks.append(t)}root.append(ranks);
let review=panel("Membership approvals");for(const m of d.members){let t=el("article",null,"tile");add(t,el("h3",m.character+" / "+m.username),el("p","Status: "+m.status+" · Requested: "+(m.requested||"—")+" · Callsign: "+(m.callsign||"—")));if(["pending","approved"].includes(m.status)&&rankOpts.length){t.append(form([["rank","Rank","select",rankOpts,m.rank??rankOpts[0][0]],["position","Position / title","text",null,m.position||""]],m.status==="pending"?"Approve membership":"Save assignment",async v=>{await api(m.status==="pending"?"/admin/review/"+m.uid:"/admin/assign/"+m.uid,{approve:true,rank:Number(v.rank),position:v.position});await render()}))}if(m.status==="pending")t.append(form([["reason","Reason for rejection","text"]],"Reject",async v=>{await api("/admin/review/"+m.uid,{approve:false,reason:v.reason});await render()}));if(m.status==="approved")t.append(button("Revoke membership",async()=>{if(confirm("Revoke internal access?")){await api("/admin/revoke/"+m.uid,{});await render()}},true));review.append(t)}root.append(review);
root.append(await businessProfileAdmin());
let streams=panel("Streamer directory management");streams.append(form([["name","Streamer name","text"],["platform","Platform","select",[["youtube","YouTube"],["tiktok","TikTok"]]],["channel","YouTube channel ID (UC...) or TikTok username","text"]],"Save streamer",async v=>{await api("/admin/streamer",v);await render()}));root.append(streams);let clips=panel("Pending clips");for(const c of d.clips){let t=el("div",null,"tile");add(t,el("h3",c.title),link("Review clip",c.url),el("p"),button("Publish",async()=>{await api("/admin/clip/"+c.id+"/published",{});await render()}),button("Reject",async()=>{await api("/admin/clip/"+c.id+"/rejected",{});await render()},true));clips.append(t)}root.append(clips);root.append(await discountPolicyPanel(d.ranks),await grantPanel(d.ranks),await socialAdmin());return root}
let generation=0;
async function render(){if(streamSafe){safeScreen();return}const g=++generation;if(view==="internal"&&me.status!=="approved")view="community";if(view==="admin"&&!me.admin)view="community";let notice=el("p",null,"error");notice.id="notice";app.replaceChildren(heading(),notice);try{let content=await (view==="internal"?internal():view==="admin"?admin():community());if(g===generation)app.append(content)}catch(e){if(g===generation)showError(e)}}
async function boot(){if(streamSafe){safeScreen();return}try{me=await api("/me");await render()}catch(e){if(streamSafe)return;if(e.status===401)auth();else{app.replaceChildren(el("p",e.message,"error"),button("Retry",boot))}}}
boot();
setInterval(async()=>{if(streamSafe||!me||view!=="community"||document.hidden)return;let focused=document.activeElement;if(focused&&["INPUT","SELECT","BUTTON"].includes(focused.tagName))return;try{let fresh=await api("/me");me=fresh;await render()}catch(e){if(e.status===401&&!streamSafe){me=null;auth()}}},60000);

const opsNames={treasury:"Treasury",inventory:"Vault & Inventory",crafting:"Crafting & Production",cases:"Intelligence & Case Files",syndicates:"Syndicate Directory",operations:"Operations Calendar",assets:"Assets & Vehicles",documents:"Documents & SOP",business:"Business Orders & POS",business_prices:"Business Price Catalog",business_analytics:"Business Intelligence & Analytics",business_discounts:"Discount Approval",financial_reports:"Financial Reporting"};
let opsTab="";
const options=(rows,label="name")=>rows.map(x=>[String(x.id),x[label]]);
const n=x=>Number(x);
const moneyFormat=x=>"$"+Number(x).toLocaleString("en-US");
const dateFormat=x=>new Date(x*1000).toLocaleString("id-ID",{timeZone:"Asia/Jakarta"});
const field=(key,label,type="text",opts=null,value=null)=>[key,label,type,opts,value];
const postRefresh=async(path,data)=>{await api(path,data);await render()};
function lines(rows,format){const v=el("div");for(const r of rows)v.append(el("p",format(r)));if(!rows.length)v.append(el("p","No entries yet.","muted"));return v}
async function grantPanel(ranks){let p=panel("Rank permissions · internal modules");p.append(el("p","Default access is denied. All Access grants view, write and approve on all current and future internal modules; it does not grant website administrator rights.","muted"));let grants=await api("/admin/grants");for(const rank of ranks){let enabled=grants.some(g=>g.rank_id===rank.id&&g.module==="*"&&g.level==="approve");let row=el("div",null,"row");add(row,el("strong",rank.name+" · "+(enabled?"ALL ACCESS":"Custom permissions")),button(enabled?"Disable All Access":"Enable All Access",async()=>{if(!confirm(enabled?"Disable All Access? Existing custom permissions will apply again.":"Grant all internal modules and approval rights to every approved member of this rank, including future modules?"))return;await postRefresh("/admin/grants",{rank:rank.id,module:"*",level:enabled?"none":"approve"})},!enabled));p.append(row)}if(ranks.length)p.append(form([field("rank","Rank","select",options(ranks)),field("module","Module","select",Object.entries(opsNames)),field("level","Permission","select",[["none","No access"],["view","View"],["write","Write"],["approve","Approve (includes write)"]])],"Save permission",v=>postRefresh("/admin/grants",{...v,rank:n(v.rank)})));p.append(lines(grants,g=>(ranks.find(r=>r.id===g.rank_id)?.name||g.rank_id)+" · "+(g.module==="*"?"All Access":opsNames[g.module])+" · "+g.level));let a=panel("Audit log · recent activity");let logs=await api("/admin/ops-audit");a.append(lines(logs,l=>dateFormat(l.created)+" · "+(l.username||"System")+" · "+l.action+" · "+(l.target??"—")));p.append(a);return p}
async function assetsUI(write,level){
 const d=await api("/ops/assets"),p=panel("Asset & Property Management");
 p.append(el("p","Central register for organizational vehicles, property and equipment. Acquisition and disposal require independent approval; assignments, maintenance and every lifecycle change are recorded.","muted"));
 const counts={};for(const a of d.assets)counts[a.status]=(counts[a.status]||0)+1;
 const summary=el("div",null,"grid");
 for(const [key,label] of [["available","Available"],["assigned","Assigned"],["maintenance","Maintenance"],["retired","Retired"]]){
  const tile=el("article",null,"tile");tile.append(el("small",label),el("h2",String(counts[key]||0)));summary.append(tile);
 }
 p.append(summary);
 const active=d.assets.filter(a=>a.status!=="retired"),assetOptions=options(active.map(a=>({id:a.id,name:a.asset_tag+" · "+a.name})));
 if(write){
  p.append(form([
   field("asset_tag","Asset tag / registration ID"),field("asset_type","Asset type","select",[["vehicle","Vehicle"],["property","Property"],["equipment","Equipment"],["other","Other"]]),
   field("name","Asset name"),field("description","Description","textarea"),field("make_model","Make / model"),field("serial_number","Serial number"),
   field("plate_number","Plate / registration number"),field("location","Current location"),field("condition","Condition","select",[["new","New"],["excellent","Excellent"],["good","Good"],["fair","Fair"],["poor","Poor"]]),
   field("purchase_cost","Acquisition cost","number",null,0),field("purchase_date","Acquisition date"),field("account_id","Treasury account · required when cost is above zero","select",options(d.accounts)),
   field("inventory_item_id","Related inventory item · optional","select",options(d.inventory_items)),field("case_id","Related case · optional","select",options(d.cases)),field("note","Acquisition justification / reference","textarea")
  ],"Request asset acquisition",v=>postRefresh("/ops/assets/requests",{request_type:"acquisition",acquisition:{...v,purchase_cost:n(v.purchase_cost),account_id:v.account_id? n(v.account_id):null,inventory_item_id:v.inventory_item_id?n(v.inventory_item_id):null,case_id:v.case_id?n(v.case_id):null}})));
  if(active.length)p.append(form([field("asset_id","Asset to dispose","select",assetOptions),field("note","Disposal justification / reference","textarea")],"Request asset disposal",v=>postRefresh("/ops/assets/requests",{request_type:"disposal",disposal:{asset_id:n(v.asset_id),note:v.note}})));
 }
 p.append(el("h3","Asset register"));
 for(const a of d.assets){
  const card=el("article",null,"tile"),details=el("div");
  add(card,el("h3",a.asset_tag+" · "+a.name),el("small",a.asset_type.toUpperCase()+" · "+a.status.toUpperCase()+" · "+a.condition),el("p",a.description||"No description"),el("p",(a.make_model||"—")+" · Serial "+(a.serial_number||"—")+" · Plate "+(a.plate_number||"—")),el("p","Location: "+(a.location||"—")+" · Assigned: "+(a.assigned_to||"Unassigned")),el("p","Acquisition: "+moneyFormat(a.purchase_cost)+" · "+(a.purchase_date||"Date not recorded")),el("p","Inventory: "+(a.inventory_item_name||"—")+" · Case: "+(a.case_title||"—")));
  if(write&&a.status!=="retired"){
   const controls=el("details");controls.append(el("summary","Manage asset"));
   controls.append(form([field("assigned_to","Assigned character / custodian","text",null,a.assigned_to),field("location","Current location","text",null,a.location),field("note","Assignment / return reason")],"Save assignment / return",v=>postRefresh("/ops/assets/"+a.id+"/assignment",v)));
   if(a.status!=="maintenance")controls.append(form([field("title","Maintenance task"),field("description","Work required","textarea"),field("vendor","Workshop / provider"),field("cost","Estimated cost","number",null,0)],"Open maintenance record",v=>postRefresh("/ops/assets/"+a.id+"/maintenance",{...v,cost:n(v.cost)})));
   card.append(controls);
  }
  if(a.status==="maintenance"){
   const open=d.maintenance.filter(m=>m.asset_id===a.id&&m.status==="open");
   for(const m of open)card.append(el("p","Open maintenance: "+m.title+" · "+moneyFormat(m.cost)+" · "+(m.vendor||"No provider")),write?button("Mark maintenance completed",()=>postRefresh("/ops/assets/"+a.id+"/maintenance/"+m.id+"/complete",{})):el("small","Maintenance in progress"));
  }
  card.append(button("View lifecycle history",()=>{details.replaceChildren(lines(d.history.filter(h=>h.asset_id===a.id),h=>dateFormat(h.created)+" · "+h.event+" · "+(h.from_value||"—")+" → "+(h.to_value||"—")+" · "+h.note));},true),details);
  p.append(card);
 }
 p.append(el("h3","Acquisition & disposal approval queue"));
 for(const q of d.requests){
  const card=el("article",null,"tile");
  add(card,el("h3","#"+q.id+" · "+q.request_type.toUpperCase()+" · "+q.status.toUpperCase()),el("p",(q.asset_name||q.asset_tag||JSON.parse(q.payload||"{}").name||"Asset request")+" · "+q.note),el("small",q.username+" · "+dateFormat(q.created)+(q.reviewer_name?" · reviewed by "+q.reviewer_name:"")));
  if(level==="approve"&&q.status==="pending"&&q.actor!==me.id)card.append(el("div",null,"row"),button("Approve",()=>postRefresh("/ops/assets/requests/"+q.id+"/review",{approve:true})),button("Reject",()=>postRefresh("/ops/assets/requests/"+q.id+"/review",{approve:false}),true));
  p.append(card);
 }
 p.append(el("h3","Maintenance history"),lines(d.maintenance,m=>m.asset_tag+" · "+m.title+" · "+m.status+" · "+moneyFormat(m.cost)+" · "+dateFormat(m.created)));
 return p
}

async function financialReportsUI(write){
 const p=panel("Advanced Financial Reporting");
 p.append(el("p","Consolidated management reporting from posted Treasury transactions. Pending entries and internal account transfers are excluded.","muted"));
 const controls=el("div",null,"row"),from=el("input"),to=el("input"),apply=button("Generate report",load,true);
 from.type="month";to.type="month";
 const today=new Date(),prior=new Date(today.getFullYear(),today.getMonth()-2,1);
 const monthValue=d=>d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0");
 from.value=monthValue(prior);to.value=monthValue(today);
 controls.append(el("label","From month"),from,el("label","To month"),to,apply);p.append(controls);
 const exports=el("div",null,"row"),content=el("div"),tabs=el("nav");p.append(exports,tabs,content);
 let data=null,tab="summary";
 const fmt=x=>moneyFormat(x||0);
 function metric(label,value,sub){let card=el("article",null,"tile");add(card,el("small",label),el("h2",String(value)),el("p",sub||""));return card}
 function draw(){
  content.replaceChildren();tabs.replaceChildren();
  for(const [key,label] of [["summary","Executive summary"],["monthly","Monthly cash flow"],["divisions","By division"],["categories","By category"],["business","Business POS"],["budgets","Budget plan"]]){
   tabs.append(button(label,()=>{tab=key;draw()},key!==tab));
  }
  if(tab==="summary"){
   let g=el("div",null,"grid"),s=data.summary,c=data.comparison;
   g.append(metric("Opening balance",fmt(s.opening_balance),"Posted ledger balance before selected period"),
    metric("Total income",fmt(s.income),"Posted cash-in transactions"),
    metric("Total expenses",fmt(s.expense),"Posted cash-out transactions"),
    metric("Net cash flow",fmt(s.net_cash_flow),"Income less expenses"),
    metric("Closing balance",fmt(s.closing_balance),"Opening balance plus period net flow"),
    metric("Budget allocation",fmt(s.budget_total),"Actual expense is compared against each budget scope below"));
   if(data.business?.available){g.append(metric("Completed POS sales",fmt(data.business.sales_revenue),data.business.completed_orders+" completed POS orders"),metric("POS purchase spend",fmt(data.business.purchase_spend),"Operational purchase orders"),metric("Estimated POS gross profit",fmt(data.business.estimated_gross_profit),"Sales less estimated cost of goods"));}content.append(g,el("h3","Comparison with previous period"),el("p",c.previous_start+" to "+c.previous_end+" · Income "+fmt(c.income)+" · Expenses "+fmt(c.expense)+" · Net "+fmt(c.net_cash_flow)),el("p","Change · Income "+fmt(c.income_change)+" · Expenses "+fmt(c.expense_change)+" · Net "+fmt(c.net_change)),el("p",data.budget_note,"muted"));
  }else if(tab==="monthly"){
   content.append(el("h3","Monthly cash flow"));
   for(const x of data.monthly)content.append(el("p",x.period+" · Income "+fmt(x.income)+" · Expenses "+fmt(x.expense)+" · Net "+fmt(x.net)+" · "+x.transactions+" posted transactions"));
  }else if(tab==="divisions"){
   content.append(el("h3","Financial performance by division"));
   for(const x of data.divisions)content.append(el("p",x.division+" · Income "+fmt(x.income)+" · Expenses "+fmt(x.expense)+" · Net "+fmt(x.income-x.expense)+" · "+x.transactions+" transactions"));
  }else if(tab==="categories"){
   content.append(el("h3","Financial performance by category"));
   for(const x of data.categories)content.append(el("p",x.category+" · Income "+fmt(x.income)+" · Expenses "+fmt(x.expense)+" · Net "+fmt(x.income-x.expense)+" · "+x.transactions+" transactions"));
  }else if(tab==="business"){
   const b=data.business;content.append(el("h3","Completed business POS activity"));
   if(!b.available)content.append(el("p","Business POS schema is not initialized yet.","muted"));
   else{content.append(el("p","Sales "+fmt(b.sales_revenue)+" · Purchases "+fmt(b.purchase_spend)+" · Estimated gross profit "+fmt(b.estimated_gross_profit)+" · "+b.completed_orders+" completed orders"));
    for(const x of b.divisions)content.append(el("p",x.division+" · Sales "+fmt(x.sales_revenue)+" · Purchases "+fmt(x.purchase_spend)+" · "+x.completed_orders+" completed orders"));
   }
  }else{
   content.append(el("h3","Monthly budget plan"),el("p","Budgets are set by month, division and optional category. Actuals are compared against posted expenses.","muted"));
   if(write)content.append(form([field("period","Budget month","month"),field("division","Division / rank","select",[["","Organization-wide"],...data.available_divisions.map(x=>[x.name,x.name])]),field("category","Expense category (optional)","optional"),field("amount","Budget amount","number")],"Save monthly budget",v=>postRefresh("/ops/financial-reports/budgets",{...v,amount:n(v.amount)})));
   for(const x of data.budgets)content.append(el("p",x.period+" · "+(x.division||"All divisions")+" · "+(x.category||"All categories")+" · Budget "+fmt(x.amount)+" · Actual "+fmt(x.actual_expense)+" · Variance "+fmt(x.variance)+" · "+(x.utilization_pct==null?"—":x.utilization_pct+"% utilized")));
   if(!data.budgets.length)content.append(el("p","No budgets configured for this reporting period.","muted"));
  }
 }
 async function load(){
  if(!from.value||!to.value)throw Error("Choose both reporting months");
  if(to.value<from.value)throw Error("End month must not precede start month");
  data=await api("/ops/financial-reports?start="+encodeURIComponent(from.value)+"&end="+encodeURIComponent(to.value),undefined,"GET");
  exports.replaceChildren();
  for(const format of ["pdf","xlsx","csv"])exports.append(link("Export "+format.toUpperCase(),"/highest/api/ops/financial-reports/export?start="+encodeURIComponent(from.value)+"&end="+encodeURIComponent(to.value)+"&format="+format));
  draw();
 }
 await load();return p
}
async function opsPanel(){let rights=await api("/ops/access"),p=panel("Internal operations");let mods=Object.keys(opsNames).filter(k=>rights[k]);if(!mods.length){p.append(el("p","No module permissions assigned. Contact an administrator.","muted"));return p}if(!mods.includes(opsTab))opsTab=mods[0];let nav=el("nav");for(const k of mods)nav.append(button(opsNames[k],async()=>{opsTab=k;await render()},k!==opsTab));p.append(nav);let canWrite=rights[opsTab]!=="view";let handler={treasury:treasuryUI,inventory:inventoryUI,crafting:craftingUI,cases:casesUI,operations:operationsCalendarUI,business:businessUI,business_prices:pricesUI,business_analytics:businessAnalyticsUI,business_discounts:discountApprovalUI,financial_reports:financialReportsUI,assets:assetsUI}[opsTab];p.append(handler?await handler(canWrite,rights[opsTab],rights):await recordUI(opsTab,canWrite,rights[opsTab]));p.append(await approvalUI());return p}

let calendarMode="month",calendarAnchor=new Date(),calendarSelected=new Date(),calendarDivisions=[];
const calDate=d=>[d.getFullYear(),String(d.getMonth()+1).padStart(2,"0"),String(d.getDate()).padStart(2,"0")].join("-");
const calIso=d=>calDate(d)+"T00:00:00+07:00";
const calLabel=value=>new Date(value).toLocaleString("id-ID",{timeZone:"Asia/Jakarta",dateStyle:"medium",timeStyle:"short"});
function calendarEventForm(entry=null,level="write"){
 const initial=entry||{},local=value=>value?new Date(value).toLocaleString("sv-SE",{timeZone:"Asia/Jakarta"}).replace(" ","T").slice(0,16):"";
 return form([
  field("title","Activity title","text",null,initial.title||""),
  field("category","Category","text",null,initial.category||"Briefing"),
  field("division","Organizational unit / rank","select",[["","Unassigned"],...calendarDivisions.map(x=>[x,x])],initial.division||""),
  field("owner","Person responsible","text",null,initial.owner||""),
  field("location","Location","text",null,initial.location||""),
  field("starts_at","Start · WIB","datetime-local",null,local(initial.starts_at)),
  field("ends_at","End · WIB","datetime-local",null,local(initial.ends_at)),
  field("detail","Agenda / description","textarea",null,initial.detail||""),
  field("status","Status","select",[["planned","Planned"],["in_progress","In progress"],["completed","Completed"],["cancelled","Cancelled"],...(level==="approve"||initial.status==="archived"?[["archived","Archived"]]:[])],initial.status||"planned"),
  field("reminder_minutes","Reminder","select",[[0,"No reminder"],[5,"5 minutes before"],[15,"15 minutes before"],[30,"30 minutes before"],[60,"1 hour before"],[1440,"1 day before"]],initial.reminder_minutes??0)
 ],entry?"Save schedule revision":"Create activity",async v=>{
  if(!v.starts_at||!v.ends_at)throw Error("Start and end time are required");
  const payload={...v,reminder_minutes:n(v.reminder_minutes)};
  await api("/ops/calendar"+(entry?"/"+entry.id:""),payload,entry?"PUT":"POST");
  await render();
 });
}
async function operationsCalendarUI(write,level){
 const p=panel("Visual Operations Calendar");
 p.append(el("p","Central operational schedule · all dates and times are stored in WIB (Asia/Jakarta). Changes are versioned and audited.","muted"));
 const toolbar=el("div",null,"row"),filters=el("div",null,"document-filters"),content=el("div"),selectedPanel=el("div");
 const modeButton=(label,value)=>button(label,async()=>{calendarMode=value;await load()},calendarMode!==value);
 const previous=button("← Previous",async()=>{calendarAnchor.setDate(1);calendarAnchor.setMonth(calendarAnchor.getMonth()+(calendarMode==="week"?0:-1));if(calendarMode==="week")calendarAnchor.setDate(calendarAnchor.getDate()-7);await load()},true);
 const next=button("Next →",async()=>{calendarAnchor.setDate(1);calendarAnchor.setMonth(calendarAnchor.getMonth()+(calendarMode==="week"?0:1));if(calendarMode==="week")calendarAnchor.setDate(calendarAnchor.getDate()+7);await load()},true);
 const today=button("Today",async()=>{calendarAnchor=new Date();calendarSelected=new Date();await load()},true);
 const month=modeButton("Month","month"),week=modeButton("Week","week"),list=modeButton("List","list");
 const division=el("select"),category=el("select"),status=el("select");
 const addFilter=(label,input,items)=>{const wrap=el("label",label);for(const [v,t] of items){const o=el("option",t);o.value=v;input.append(o)}wrap.append(input);filters.append(wrap)};
 addFilter("Division",division,[["","All divisions"]]);addFilter("Category",category,[["","All categories"]]);
 addFilter("Status",status,[["","All statuses"],["planned","Planned"],["in_progress","In progress"],["completed","Completed"],["cancelled","Cancelled"],["archived","Archived"]]);
 const header=el("div",null,"row"),grid=el("div",null,"calendar-grid");
 const heading=el("h2"),details=el("div");
 const fmtDay=d=>d.toLocaleDateString("en-CA",{timeZone:"Asia/Jakarta"});
 const makeDay=(d,events,muted=false)=>{
  const key=calDate(d),cell=el("button",null,"calendar-day"+(key===calDate(calendarSelected)?" selected":"")+(muted?" outside":""));
  cell.type="button";cell.append(el("strong",String(d.getDate())));
  for(const event of events.filter(e=>e.starts_at.slice(0,10)===key).slice(0,3))cell.append(el("small",event.title));
  cell.onclick=async()=>{calendarSelected=new Date(d);await load()};return cell
 };
 let latest=[];
 const renderEvents=(events)=>{
  latest=events;content.replaceChildren();details.replaceChildren();
  const selectedKey=calDate(calendarSelected),onDay=events.filter(e=>e.starts_at.slice(0,10)===selectedKey);
  heading.textContent=calendarMode==="month"?calendarAnchor.toLocaleDateString("id-ID",{month:"long",year:"numeric"}):calendarMode==="week"?"Week of "+calendarAnchor.toLocaleDateString("id-ID"):"All scheduled activities";
  if(calendarMode==="month"){
   grid.replaceChildren();for(const day of ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"])grid.append(el("div",day,"calendar-weekday"));
   const first=new Date(calendarAnchor.getFullYear(),calendarAnchor.getMonth(),1),offset=(first.getDay()+6)%7;
   const start=new Date(first);start.setDate(first.getDate()-offset);
   for(let i=0;i<42;i++){const d=new Date(start);d.setDate(start.getDate()+i);grid.append(makeDay(d,events,d.getMonth()!==calendarAnchor.getMonth()))}
   content.append(grid);
  }else if(calendarMode==="week"){
   grid.replaceChildren();for(let i=0;i<7;i++){const d=new Date(calendarAnchor);d.setDate(d.getDate()-((d.getDay()+6)%7)+i);grid.append(makeDay(d,events))}
   content.append(grid);
  }else{
   const ordered=events.slice().sort((a,b)=>a.starts_at.localeCompare(b.starts_at));
   if(!ordered.length)content.append(el("p","No activities match these filters.","muted"));
   for(const event of ordered)content.append(calendarCard(event));
  }
  details.append(el("h3",calendarSelected.toLocaleDateString("id-ID",{dateStyle:"full"})));
  if(!onDay.length)details.append(el("p","No activities scheduled for this date.","muted"));
  for(const event of onDay)details.append(calendarCard(event));
  if(write)details.append(el("h3","Schedule an activity"),calendarEventForm(null,level));
 };
 function calendarCard(event){
  const card=el("article",null,"tile");
  add(card,el("h3",event.title),el("small",calLabel(event.starts_at)+" – "+calLabel(event.ends_at)+" WIB"),
   el("p",event.category+" · "+(event.division||"No division")+" · "+event.status.replaceAll("_"," ")),
   el("p",(event.owner||"No owner assigned")+" · "+(event.location||"Location not set")),
   el("p",event.detail||"No agenda details"),el("small","Reminder: "+(event.reminder_minutes?event.reminder_minutes+" minutes before":"Off")+" · v"+event.version+" · "+(event.creator_name||"Unknown")));
  if(write){const actions=el("div",null,"row");actions.append(button("Edit",()=>{const editor=el("details");editor.open=true;editor.append(el("summary","Edit activity"),calendarEventForm(event,level));card.append(editor)},true),
   button("Change history",async()=>{const history=await api("/ops/calendar/"+event.id+"/history");const box=el("div",null,"custody-trail");for(const rev of history)box.append(el("p","v"+rev.version+" · "+calLabel(new Date(rev.created*1000).toISOString())+" · "+(rev.actor_name||"Unknown")+" · "+rev.status));card.append(box)},true));card.append(actions)}
  return card
 }
 async function load(){
  const start=new Date(calendarAnchor),end=new Date(calendarAnchor);
  if(calendarMode==="month"){start.setDate(1);start.setDate(start.getDate()-((start.getDay()+6)%7));end.setDate(1);end.setMonth(end.getMonth()+1);end.setDate(end.getDate()+6)}
  else if(calendarMode==="week"){start.setDate(start.getDate()-((start.getDay()+6)%7));end.setDate(start.getDate()+6)}
  else {start.setDate(start.getDate()-180);end.setDate(end.getDate()+365)}
  if(calendarMode==="month")end.setDate(start.getDate()+41);
  const endBoundary=new Date(end);endBoundary.setHours(23,59,59,999);
  const params=new URLSearchParams({start:calIso(start),end:calDate(endBoundary)+"T23:59:59+07:00"});
  if(division.value)params.set("division",division.value);if(category.value)params.set("category",category.value);if(status.value)params.set("status",status.value);
  const data=await api("/ops/calendar?"+params.toString());
  const oldDivision=division.value,oldCategory=category.value;
  calendarDivisions=Array.from(new Set([...(data.organizational_units||[]),...data.divisions]));
  division.replaceChildren();category.replaceChildren();
  for(const [v,t] of [["","All divisions"],...calendarDivisions.map(x=>[x,x])]){const o=el("option",t);o.value=v;division.append(o)}
  for(const [v,t] of [["","All categories"],...data.categories.map(x=>[x,x])]){const o=el("option",t);o.value=v;category.append(o)}
  division.value=oldDivision;category.value=oldCategory;
  renderEvents(data.events);
 }
 toolbar.append(previous,next,today,month,week,list);
 if(write)toolbar.append(button("＋ New activity",()=>{calendarSelected=new Date();calendarMode="list";load()},true));
 p.append(toolbar,filters,heading,content,details);await load();
 for(const control of [division,category,status])control.onchange=load;
 return p
}

async function treasuryUI(write,level){
 let d=await api("/ops/treasury"),p=panel("Financial Control & Treasury");
 p.append(el("h1",moneyFormat(d.balance)),el("p","Consolidated posted balance · no shifts, work hours or time-based restrictions.","muted"));
 p.append(el("h3","Treasury accounts"),lines(d.accounts,a=>a.name+" · "+moneyFormat(a.balance)+(a.description?" · "+a.description:"")));
 const accountOptions=d.accounts.map(a=>[a.id,a.name+" · "+moneyFormat(a.balance)]);
 if(write){
  p.append(form([field("name","Account name"),field("description","Description")],"Create treasury account",v=>postRefresh("/ops/treasury/accounts",v)));
  p.append(form([field("account_id","Account","select",accountOptions),field("direction","Transaction type","select",[["income","Cash in / income"],["expense","Cash out / expense"]]),field("amount","Amount (whole in-game dollars)","number"),field("category","Category"),field("note","Transaction purpose / reference")],"Submit cash transaction",v=>postRefresh("/ops/treasury",{...v,account_id:n(v.account_id),amount:n(v.amount)})));
  if(d.accounts.length>1)p.append(form([field("source_account","From account","select",accountOptions),field("destination_account","To account","select",accountOptions),field("amount","Transfer amount","number"),field("note","Transfer purpose / reference")],"Request internal account transfer",v=>postRefresh("/ops/treasury/transfers",{...v,source_account:n(v.source_account),destination_account:n(v.destination_account),amount:n(v.amount)})));
  if(d.accounts.length)p.append(form([field("account_id","Account to reconcile","select",accountOptions),field("counted_balance","Physically counted balance","number"),field("note","Counting basis / discrepancy explanation")],"Submit balance reconciliation",v=>postRefresh("/ops/treasury/reconciliations",{...v,account_id:n(v.account_id),counted_balance:n(v.counted_balance)})));
 }
 p.append(el("h3","Cash transaction ledger"));
 for(const r of d.entries){let t=el("article",null,"tile");add(t,el("h3",moneyFormat(r.amount)+" · "+r.state.toUpperCase()),el("p",(r.account_name||"General Treasury")+" · "+r.category+" · "+r.note),el("small",r.username+" · "+dateFormat(r.created)));if(level==="approve"&&r.state==="pending"&&r.actor!==me.id)t.append(el("div",null,"row"),button("Approve",()=>postRefresh("/ops/treasury/"+r.id+"/review",{approve:true})),button("Reject",()=>postRefresh("/ops/treasury/"+r.id+"/review",{approve:false}),true));p.append(t)}
 p.append(el("h3","Internal account transfers"));
 for(const x of d.transfers){let t=el("article",null,"tile");add(t,el("h3",x.source_name+" → "+x.destination_name+" · "+moneyFormat(x.amount)),el("p",x.note+" · "+x.status.toUpperCase()),el("small",x.username+" · "+dateFormat(x.created)+" · "+x.transfer_ref));if(level==="approve"&&x.status==="pending"&&x.actor!==me.id)t.append(el("div",null,"row"),button("Approve transfer",()=>postRefresh("/ops/treasury/transfers/"+x.id+"/review",{approve:true})),button("Reject",()=>postRefresh("/ops/treasury/transfers/"+x.id+"/review",{approve:false}),true));p.append(t)}
 p.append(el("h3","Balance reconciliation history"));
 for(const x of d.reconciliations){let t=el("article",null,"tile");add(t,el("h3",x.account_name+" · "+x.status.toUpperCase()),el("p","Expected "+moneyFormat(x.expected_balance)+" · Counted "+moneyFormat(x.counted_balance)+" · Variance "+moneyFormat(x.difference)),el("small",x.note+" · "+x.username+" · "+dateFormat(x.created)));if(level==="approve"&&x.status==="pending"&&x.actor!==me.id)t.append(el("div",null,"row"),button("Approve record",()=>postRefresh("/ops/treasury/reconciliations/"+x.id+"/review",{approve:true})),button("Reject",()=>postRefresh("/ops/treasury/reconciliations/"+x.id+"/review",{approve:false}),true));p.append(t)}
 return p
}
async function inventoryUI(write){
 let d=await api("/ops/inventory"),p=panel("Inventory & multi-stash management");
 p.append(el("p","Manage multiple independent vaults / stashes, transfer stock between locations, and preserve a complete cost and movement trail.","muted"));
 p.append(el("h3","Storage locations"),lines(d.vaults,v=>v.name+" · Vault #"+v.id));
 if(write)p.append(form([field("name","New vault / stash name")],"Create storage location",v=>postRefresh("/ops/vault",v)));
 p.append(el("h3","Stock by vault"),lines(d.stock,s=>s.vault_name+" · "+s.item_name+" · "+s.qty+" units · "+s.costing_method.toUpperCase()));
 p.append(el("h3","Low stock"),lines(d.low,s=>s.name+" · "+s.total+" / minimum "+s.min_stock));
 if(write){
  p.append(form([field("name","Item name"),field("category","Category"),field("min_stock","Minimum stock","number",null,0)],"Add inventory item",v=>postRefresh("/ops/item",{...v,min_stock:n(v.min_stock)})));
  if(d.vaults.length&&d.items.length)p.append(form([
   field("kind","Movement type","select",[["deposit","Receive / deposit"],["withdraw","Issue / withdraw"],["transfer","Transfer between stashes"]]),
   field("vault","Source / target stash","select",options(d.vaults)),
   field("destination","Destination stash · transfers only","select",options(d.vaults)),
   field("item","Item","select",options(d.items)),
   field("qty","Quantity","number"),
   field("unit_cost","Unit acquisition cost · deposits only","number",null,0),
   field("note","Reason / IC reference")
  ],"Record inventory movement",v=>postRefresh("/ops/move",{...v,vault:n(v.vault),destination:v.kind==="transfer"?n(v.destination):null,item:n(v.item),qty:n(v.qty),unit_cost:v.kind==="deposit"?n(v.unit_cost):null})));
  if(d.vaults.length&&d.items.length)p.append(form([
   field("vault","Storage location","select",options(d.vaults)),
   field("item","Item","select",options(d.items)),
   field("counted_qty","Physical counted quantity","number"),
   field("unit_cost","Unit cost · required only when increasing stock","number",null,0),
   field("note","Stocktake / adjustment reason")
  ],"Reconcile stocktake",v=>postRefresh("/ops/inventory/adjust",{...v,vault:n(v.vault),item:n(v.item),counted_qty:n(v.counted_qty),unit_cost:v.unit_cost===""?null:n(v.unit_cost)})));
  if(d.items.length)p.append(el("h3","Costing method per item"),form([
   field("item","Inventory item","select",options(d.items)),
   field("method","Costing method","select",[["fifo","FIFO · first in, first out"],["weighted_average","Moving weighted average"]])
  ],"Update costing method",v=>postRefresh("/ops/item/"+v.item+"/costing",{method:v.method})));
  if(d.vaults.length&&d.items.length)p.append(form([
   field("vault","Legacy stash","select",options(d.vaults)),
   field("item","Inventory item","select",options(d.items)),
   field("unit_cost","Opening unit cost","number",null,0),
   field("note","Valuation basis / note")
  ],"Value legacy opening stock",v=>postRefresh("/ops/inventory/opening-valuation",{...v,vault:n(v.vault),item:n(v.item),unit_cost:n(v.unit_cost)})));
 }
 p.append(el("h3","Inventory valuation by stash"),lines(d.valuation,v=>v.vault_name+" · "+v.item_name+" · "+v.qty+" units · "+moneyFormat(v.value)+" · avg "+moneyFormat(Math.round(v.average_unit_cost))+" / unit · "+v.costing_method.toUpperCase()+(v.unvalued_qty?" · "+v.unvalued_qty+" unvalued":"")));
 p.append(el("h3","FIFO / weighted-average cost layers"),lines(d.cost_layers,l=>l.vault_name+" · "+l.item_name+" · "+l.qty_remaining+" units · "+moneyFormat(l.value_remaining)+" · "+l.source+" · "+l.reference));
 p.append(el("h3","Complete movement & transfer history"),lines(d.movements,m=>dateFormat(m.created)+" · "+m.username+" · "+m.kind+" · "+m.vault_name+(m.counterparty_vault_name?" ⇄ "+m.counterparty_vault_name:"")+" / "+m.item_name+" · "+(m.delta>0?"+":"")+m.delta+" · cost "+moneyFormat(m.value||0)+" · ref "+m.ref+" · "+m.note));
 return p
}
async function craftingUI(write){let d=await api("/ops/crafting"),p=panel("Crafting & production");p.append(el("p","Record completed in-game crafting only. Stock consumption and production are recorded in one transaction.","muted"));for(const r of d.recipes)p.append(el("p",r.name+" → "+r.output_qty+" × "+r.output_name+" ("+r.ingredients.map(i=>i.qty+" × "+i.name).join(", ")+")"));if(write&&d.items.length>=2){let box=panel("New recipe (IC game items)");box.append(form([field("name","Recipe name"),field("output","Output item","select",options(d.items)),field("output_qty","Output per batch","number",null,1),field("ingredients","Ingredients: item ID:quantity, comma-separated")],"Add recipe",v=>{const ingredients=v.ingredients.split(",").map(s=>{const a=s.trim().split(":");return {item:n(a[0]),qty:n(a[1])}});if(ingredients.some(i=>!Number.isSafeInteger(i.item)||!Number.isSafeInteger(i.qty)||i.qty<=0))throw Error("Use item ID:quantity");return postRefresh("/ops/recipe",{name:v.name,output:n(v.output),output_qty:n(v.output_qty),ingredients})}),el("small",d.items.map(i=>i.id+" = "+i.name).join(" · ")));p.append(box)}if(write&&d.vaults.length&&d.recipes.length)p.append(form([field("recipe","Recipe","select",options(d.recipes)),field("vault","Vault","select",options(d.vaults)),field("batches","Completed batches","number",null,1),field("note","Production notes")],"Confirm completed crafting",v=>postRefresh("/ops/craft",{...v,recipe:n(v.recipe),vault:n(v.vault),batches:n(v.batches)})));p.append(el("h3","Production history"),lines(d.batches,b=>dateFormat(b.created)+" · "+b.recipe_name+" × "+b.batches+" · "+b.vault_name+" · "+b.username));return p}

function intelligenceAnalyticsPanel(data){
 const p=panel("Advanced Intelligence Analytics");
 p.append(el("p",data.scope,"muted"));
 const g=el("div",null,"grid");
 const metric=(label,value,note)=>{const t=el("article",null,"tile");add(t,el("small",label),el("h2",String(value)),el("p",note||""));g.append(t)};
 metric("Total IC cases",data.cases.total,"Open "+data.cases.open+" · Review "+data.cases.review+" · Closed "+data.cases.closed);
 metric("Tracked entities",data.graph.total_nodes,"Characters "+data.graph.characters+" · Vehicles "+data.graph.vehicles+" · Organizations "+data.graph.organizations);
 metric("Relationships",data.graph.relationships,"Case-scoped graph connections");
 metric("Evidence files",data.graph.evidence_files,"Custody events "+data.graph.custody_events);
 metric("Integrity failures",data.graph.integrity_failures,"Recorded failed integrity checks");
 metric("Case-linked assets",data.graph.case_linked_assets,"Assets associated with IC cases");
 p.append(g);
 const recurring=el("section",null,"tile");add(recurring,el("h3","Recurring entities across cases"),el("p","Exact normalized name matches only. These are candidate overlaps for investigator review, not confirmed identities.","muted"));
 recurring.append(lines(data.recurring_entities,x=>x.entity_type.toUpperCase()+" · "+x.entity_name+" · "+x.case_count+" cases · "+x.cases.map(c=>"TH-"+String(c.id).padStart(4,"0")+" "+c.title).join(" / ")));
 p.append(recurring);
 const overlaps=el("section",null,"tile");add(overlaps,el("h3","Potential case connections"),el("p","Cases sharing an entity name are grouped as review leads. No cross-case relationship is created automatically.","muted"));
 overlaps.append(lines(data.candidate_case_overlaps,x=>"TH-"+String(x.left_case_id).padStart(4,"0")+" "+x.left_case+" ↔ TH-"+String(x.right_case_id).padStart(4,"0")+" "+x.right_case+" · "+x.entity_type+" · "+x.matched_name));
 p.append(overlaps);
 const cols=el("div",null,"grid");
 const connected=el("section",null,"tile");add(connected,el("h3","Most connected entities"));
 connected.append(lines(data.most_connected_entities,x=>x.name+" · "+x.entity_type+" · "+x.degree+" links · TH-"+String(x.case_id).padStart(4,"0")+" "+x.case_title));
 cols.append(connected);
 const patterns=el("section",null,"tile");add(patterns,el("h3","Relationship patterns"));
 patterns.append(lines(data.relationship_patterns,x=>x.label+" · "+x.relationship_count+" links across "+x.case_count+" cases"));
 cols.append(patterns);p.append(cols);
 const active=el("section",null,"tile");add(active,el("h3","Most active case files"));
 active.append(lines(data.most_active_cases,x=>"TH-"+String(x.case_id).padStart(4,"0")+" · "+x.title+" · "+x.status+" · "+x.entity_count+" entities · "+x.relationship_count+" links · "+x.evidence_count+" files · "+x.update_count+" updates"));
 p.append(active);
 const timeline=el("section",null,"tile");add(timeline,el("h3","IC activity timeline · WIB"),el("p","Daily case, graph, evidence and custody activity. This is a record of logged events, not an inferred event chronology.","muted"));
 timeline.append(lines(data.activity_timeline.slice(0,30),x=>x.day+" · Cases opened "+x.cases_opened+" · Updates "+x.case_updates+" · Entities "+x.nodes_added+" · Links "+x.relationships_added+" · Evidence "+x.evidence_uploaded+" · Custody "+x.custody_events));
 p.append(timeline);
 const integrity=el("section",null,"tile");add(integrity,el("h3","Recorded evidence integrity incidents"));
 integrity.append(lines(data.recorded_integrity_failures_by_case,x=>"TH-"+String(x.case_id).padStart(4,"0")+" · "+x.title+" · "+x.integrity_failures+" recorded failures"));
 p.append(integrity);
 p.append(el("small","Generated "+dateFormat(data.generated_at),"muted"));
 return p
}
async function casesUI(write){let d=await api("/ops/cases"),intelligence=await api("/case-intelligence/analytics"),p=panel("Roleplay intelligence & cases");p.append(el("p","IC fictional character information only. Never enter real-world private information.","muted"),intelligenceAnalyticsPanel(intelligence));if(write)p.append(form([field("name","Case title"),field("summary","IC case summary")],"Open case",v=>postRefresh("/ops/cases",v)));for(const c of d){let t=el("article",null,"tile"),details=el("div");add(t,el("h3","TH-"+String(c.id).padStart(4,"0")+" · "+c.title),el("small",c.status+" · "+dateFormat(c.updated)),el("p",c.summary),button("Open timeline",async()=>{let data=await api("/ops/cases/"+c.id);details.replaceChildren(lines(data.notes,n=>dateFormat(n.created)+" · "+n.username+" · "+n.note),await caseExtras(c.id,write));if(write)details.append(form([field("note","IC update / evidence reference"),field("status","Status","select",[["open","Open"],["review","Under review"],["closed","Closed"]],c.status)],"Save case update",v=>postRefresh("/ops/cases/"+c.id,v)))}),details);p.append(t)}return p}

let socialTab="moments";
const socialTabs={moments:"Multi-POV Moments",studio:"Creator Studio",wiki:"Lore & Character Wiki",feed:"Community Feed",leaders:"Leaderboard"};
const spoilerChoices=[["false","No"],["true","Yes — spoiler"]];
const bool=v=>v==="true";
function spoilerBlock(hidden,content){if(!hidden)return content;let box=el("div");let detail=el("details");detail.append(el("summary","Spoiler — click to reveal"),content);box.append(detail);return box}
async function socialPanel(d){let p=panel("Community & Creator Ecosystem"),nav=el("nav");for(const [k,name] of Object.entries(socialTabs))nav.append(button(name,async()=>{socialTab=k;await render()},k!==socialTab));p.append(nav);
if(socialTab==="moments"){
p.append(form([field("title","Moment title"),field("summary","Published RP event summary"),field("spoiler","Contains story spoilers?","select",spoilerChoices)],"Submit moment for review",async v=>{await api("/social/moment",{...v,spoiler:bool(v.spoiler)});alert("Submitted for review. Add POVs from Creator Studio.");await render()}));
for(const m of d.moments){let t=el("article",null,"tile"),c=el("div");t.append(el("h3",m.spoiler?"Spoiler moment":m.title));add(c,el("h3",m.title),el("p",m.summary),el("small","By "+m.display_name+" · "+dateFormat(m.created)));for(const pov of m.povs){let item=el("div",null,"community-content-item");add(item,el("p",pov.label+" · submitted by "+pov.display_name+" · clip by "+pov.clip_owner),link(pov.title+" ↗",pov.url),reportControl("pov",pov.id));c.append(item)}c.append(reportControl("moment",m.id));if(d.clips.length)c.append(povForm(m.id,d.clips));t.append(spoilerBlock(m.spoiler,c));p.append(t)}
}else if(socialTab==="studio"){p.append(await studioUI(d))}
else if(socialTab==="wiki"){p.append(form([field("kind","Type","select",[["lore","Lore"],["character","Character profile"],["recap","Weekly recap"]]),field("title","Title"),field("body","Public story / biography"),field("spoiler","Spoiler?","select",spoilerChoices)],"Submit article",v=>postRefresh("/social/wiki",{...v,spoiler:bool(v.spoiler)})));for(const w of d.wiki){let c=el("article",null,"tile");add(c,el("small",w.kind.toUpperCase()),el("h3",w.title),el("p",w.body),el("small","By "+w.display_name+" · "+dateFormat(w.created)));c.append(reportControl("wiki",w.id));p.append(spoilerBlock(w.spoiler,c))}}
else if(socialTab==="feed"){p.append(form([field("category","Category","select",[["general","General"],["storyline","Storyline"],["fan_art","Fan art discussion"],["clips","Clips"],["memes","Memes"]]),field("body","Post"),field("spoiler","Spoiler?","select",spoilerChoices)],"Submit post",v=>postRefresh("/social/post",{...v,spoiler:bool(v.spoiler)})));for(const post of d.posts){let c=el("article",null,"tile");add(c,el("h3",post.display_name),el("small",post.category+" · "+dateFormat(post.created)),el("p",post.body),reportControl("post",post.id));p.append(spoilerBlock(post.spoiler,c))}}
else{p.append(el("h3","Top Clippers · Website likes"),lines(d.leaderboard,(r)=>r.display_name+" · "+r.clips+" approved clips · "+r.likes+" likes"),el("h3","Verified creators"));for(const creator of d.creators)p.append(el("p",creator.display_name+" · Verified "+creator.kind),link("Creator channel ↗",creator.url))}
return p}
function reportControl(kind,id){
 const details=el("details",null,"community-report");
 details.append(el("summary","Report content"));
 details.append(form([
  field("reason","Reason","select",[
   ["harassment","Harassment / hate"],
   ["personal_info","Personal information"],
   ["spam","Spam / scam"],
   ["inappropriate","Inappropriate content"],
   ["copyright","Copyright concern"],
   ["other","Other"]
  ]),
  field("details","Additional context (optional)","optional_textarea")
 ],"Send report",async values=>{
  await api("/social/report",{content_type:kind,content_id:id,reason:values.reason,details:values.details});
  details.replaceChildren(el("small","Report submitted. Moderators will review it."));
 }));
 return details;
}
function povForm(id,clips){return form([field("clip","Published clip","select",options(clips,"title")),field("label","POV label / character")],"Submit POV for review",v=>postRefresh("/social/moment/"+id+"/pov",{clip:n(v.clip),label:v.label}))}
async function studioUI(d){let [s,reportData]=await Promise.all([api("/social/studio"),api("/social/reports")]),p=panel("Your creator dashboard");let approved=s.clips.filter(c=>c.state==="published");p.append(el("h3",approved.length+" published clips · "+approved.reduce((x,c)=>x+c.likes,0)+" website likes"),el("p","External platform view counts are not included.","muted"),lines(s.clips,c=>c.title+" · "+c.state+" · "+c.likes+" likes"),el("h3","Creator verification"),lines(s.verification,v=>v.kind+" · "+v.status),form([field("kind","Verify as","select",[["clipper","Clipper"],["streamer","Streamer"]]),field("url","YouTube / TikTok profile link"),field("note","Verification note","optional")],"Request verification",v=>postRefresh("/social/creator",v)),el("h3","Your moments"));for(const m of s.moments){p.append(el("p",m.title+" · "+m.state));if(d.clips.length&&["pending","published"].includes(m.state))p.append(povForm(m.id,d.clips))}p.append(el("h3","Your submitted articles"),lines(s.wiki,w=>w.title+" · "+w.state),el("h3","Your feed submissions"),lines(s.posts,x=>x.category+" · "+x.state),el("h3","Saved clips"));for(const b of s.bookmarks)p.append(el("p"),link(b.title+" ↗",b.url));p.append(el("h3","Your content reports"));for(const r of reportData.reports){let t=el("article",null,"tile");add(t,el("strong",r.content_type+" #"+r.content_id+" · "+r.reason.replaceAll("_"," ")),el("small","Status: "+r.status+" · "+dateFormat(r.created)),el("p",r.review_note||"No moderator note yet"));p.append(t)}if(!reportData.reports.length)p.append(el("p","You have not submitted any reports.","muted"));return p}
async function socialAdmin(){let [d,reportData]=await Promise.all([api("/admin/social"),api("/admin/social/reports")]),p=panel("Community moderation");p.append(el("p","Review only already-public roleplay content. Do not publish restricted IC material or personal information.","muted"));p.append(el("h3","Trust & Safety · Report queue ("+reportData.reports.length+")"));for(const r of reportData.reports){let t=el("article",null,"tile"),content=r.content||{};add(t,el("h3",r.content_type.toUpperCase()+" #"+r.content_id+" · "+(content.title||content.body||"Reported content")),el("small","Reported by "+r.reporter_username+" · "+r.reason.replaceAll("_"," ")+" · "+dateFormat(r.created)),el("p",r.details||"No additional context"),el("p","Content author: "+(content.author_username||"Unknown")),el("p",content.body||""),el("small",r.review_note||""));if(content.url)t.append(link("Open reported content ↗",content.url));t.append(button("Remove content",async()=>{if(confirm("Hide this content from the community?")){await api("/admin/social/report/"+r.id,{action:"remove",note:"Removed after community report"});await render()} }),button("Dismiss report",async()=>{await api("/admin/social/report/"+r.id,{action:"dismiss",note:"No policy violation found"});await render()},true));p.append(t)}if(!reportData.reports.length)p.append(el("p","No open reports.","muted"));p.append(el("h3","Removed content · Restore"));for(const item of reportData.removed){let t=el("article",null,"tile");add(t,el("h3",item.kind.toUpperCase()+" · "+(item.title||item.body||"Content #"+item.id)),el("small","Author: "+item.username+" · #"+item.id));t.append(button("Restore publication",async()=>{if(confirm("Restore this content to the community?")){await api("/admin/social/content/"+item.kind+"/"+item.id+"/restore",{action:"restore"});await render()} }));p.append(t)}if(!reportData.removed.length)p.append(el("p","No removed content.","muted"));for(const c of d.creators){let t=el("article",null,"tile");add(t,el("h3",c.username+" · "+c.kind),el("p",c.note),link("Review creator link ↗",c.url),el("p"),button("Verify",()=>postRefresh("/admin/social/creator/"+c.uid+"/"+c.kind,{approve:true})),button("Reject",()=>postRefresh("/admin/social/creator/"+c.uid+"/"+c.kind,{approve:false}),true));p.append(t)}for(const [kind,items] of [["moment",d.moments],["pov",d.povs],["wiki",d.wiki],["post",d.posts]]){p.append(el("h3",kind+" queue ("+items.length+")"));for(const item of items){let t=el("article",null,"tile");add(t,el("h3",item.title||item.label||item.category),el("small","Submitted by "+(item.display_name||item.username||"Unknown")+(item.created?" · "+dateFormat(item.created):"")),el("p",item.summary||item.body||[item.moment_title,item.clip_title].filter(Boolean).join(" · ")));if(item.url)t.append(link("Review clip ↗",item.url),el("p"));t.append(button("Publish",()=>postRefresh("/admin/social/"+kind+"/"+item.id,{approve:true})),button("Reject",()=>postRefresh("/admin/social/"+kind+"/"+item.id,{approve:false}),true));p.append(t)}}return p}

const recordLabels={
syndicates:["Organization name","Organization category","Public/IC RP history and agreements","IC contact / representative","Reference / meeting date",["active","inactive","archived"]],
operations:["Activity title","Activity type","RP session agenda and after-action notes","IC coordinator","Schedule (date/time WIB)",["planned","in_progress","completed","cancelled","archived"]],
assets:["Asset name","Vehicle / property / other","IC asset details and condition","Assigned character","In-game asset ID or plate",["available","assigned","maintenance","retired","archived"]],
documents:["Document title","SOP / policy / meeting minutes","Document text","Responsible division","Document reference",["draft","active","archived"]]};
function recordForm(module,entry,level){let [title,category,detail,owner,reference,statuses]=recordLabels[module];let options=statuses.filter(s=>s!=="archived"||level==="approve"||entry?.status==="archived").map(s=>[s,s.replaceAll("_"," ")]);return form([field("title",title,"text",null,entry?.title),field("category",category,"text",null,entry?.category),field("detail",detail,"textarea",null,entry?.detail),field("owner",owner,"optional",null,entry?.owner),field("reference",reference,"optional",null,entry?.reference),field("status","Status","select",options,entry?.status)],entry?"Save new revision":"Create record",v=>postRefresh("/records/"+module+(entry?"/"+entry.id:""),{...v,version:entry?.version??null}))}
async function recordUI(module,write,level){let d=await api("/records/"+module),p=panel(opsNames[module]);p.append(el("p","Fictional FiveM records only. Do not enter real-world private information.","muted"));if(write)p.append(recordForm(module,null,level));for(const r of d){let t=el("article",null,"tile"),details=el("div");add(t,el("h3",r.title),el("small",r.category+" · "+r.status+" · v"+r.version),el("p",r.detail),el("p","Owner: "+(r.owner||"—")+" · Reference: "+(r.reference||"—")),button("Revision history",async()=>{let data=await api("/records/"+module+"/"+r.id);details.replaceChildren();for(const old of data.revisions){let rev=el("section",null,"tile");add(rev,el("h3","Version "+old.version+" · "+dateFormat(old.created)),el("p",old.title+" · "+old.category+" · "+old.status),el("p",old.detail),el("small",(old.owner||"—")+" / "+(old.reference||"—")));details.append(rev)}},true),details);if(module==="documents"&&r.status==="active"){t.append(el("p","Acknowledged by "+r.ack_count+" members"));if(!r.acknowledged)t.append(button("Acknowledge this version",()=>postRefresh("/records/documents/"+r.id+"/ack",{})));else t.append(el("p","You have acknowledged this version.","muted"))}if(write&&(r.status!=="archived"||level==="approve")){let edit=el("details");edit.append(el("summary","Edit record"),recordForm(module,r,level));t.append(edit)}p.append(t)}return p}
async function caseExtras(id,write){
 const p=panel("IC case workspace · Evidence & relationships");
 const body=el("div");p.append(body);
 const fileUrl=eid=>"/highest/api/case-extras/evidence/"+eid+"/file";
 const refresh=async()=>{
  const data=await api("/case-extras/"+id);body.replaceChildren();
  const graphPanel=el("section",null,"case-graph-panel");
  add(graphPanel,el("h3","Relationship intelligence map"),el("p","Case entities, vehicles, organizations and evidence are connected in one case-scoped graph. Drag nodes to arrange the map; positions are saved for the next visit.","muted"));
  const graphWrap=el("div",null,"relationship-scroll"),canvas=el("div",null,"relationship-canvas");
  const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
  svg.setAttribute("viewBox","0 0 1000 520");svg.setAttribute("preserveAspectRatio","none");svg.classList.add("relationship-edges");
  canvas.append(svg);graphWrap.append(canvas);graphPanel.append(graphWrap);
  const nodes=new Map(data.nodes.map(node=>[node.id,node])),edgeShapes=[];
  const updateEdges=()=>{
   for(const shape of edgeShapes){
    const a=nodes.get(shape.link.source_id),b=nodes.get(shape.link.target_id);if(!a||!b)continue;
    shape.line.setAttribute("x1",a.x);shape.line.setAttribute("y1",a.y);
    shape.line.setAttribute("x2",b.x);shape.line.setAttribute("y2",b.y);
    shape.label.setAttribute("x",(a.x+b.x)/2);shape.label.setAttribute("y",(a.y+b.y)/2-8);
   }
  };
  for(const link of data.links){
   const line=document.createElementNS("http://www.w3.org/2000/svg","line");
   line.setAttribute("stroke","#b9975b");line.setAttribute("stroke-width","2");line.setAttribute("opacity","0.8");
   const label=document.createElementNS("http://www.w3.org/2000/svg","text");
   label.textContent=link.label;label.setAttribute("text-anchor","middle");label.setAttribute("font-size","12");label.setAttribute("fill","#e8d5ad");
   svg.append(line,label);edgeShapes.push({link,line,label});
  }
  for(const node of data.nodes){
   const card=el("div",node.name,"graph-node graph-node-"+node.entity_type);
   card.style.left=(Number(node.x)/1000*100)+"%";card.style.top=Number(node.y)+"px";
   add(card,el("small",node.entity_type.toUpperCase()),el("p",node.description||node.reference||"No additional details"));
   if(node.reference&&node.description)card.append(el("small",node.reference));
   if(write){
    card.title="Drag to arrange this node";
    let drag=null;card.style.touchAction="none";
    card.onpointerdown=e=>{
     if(e.button!==0)return;
     drag={x:e.clientX,y:e.clientY,originX:Number(node.x),originY:Number(node.y)};
     card.setPointerCapture(e.pointerId);e.preventDefault();
    };
    card.onpointermove=e=>{
     if(!drag)return;
     const rect=canvas.getBoundingClientRect();
     node.x=Math.max(85,Math.min(915,drag.originX+(e.clientX-drag.x)/rect.width*1000));
     node.y=Math.max(90,Math.min(475,drag.originY+(e.clientY-drag.y)));
     card.style.left=(node.x/1000*100)+"%";card.style.top=node.y+"px";updateEdges();
    };
    card.onpointerup=async()=>{
     if(!drag)return;drag=null;
     try{await api("/case-extras/"+id+"/nodes/"+node.id+"/position",{x:Math.round(node.x),y:Math.round(node.y)})}
     catch(error){showError(error)}
    };
    card.onpointercancel=()=>{drag=null};
   }
   canvas.append(card);
  }
  updateEdges();
  if(!data.links.length)graphPanel.append(el("p","No entity relationships yet. Add nodes and connect them below.","muted"));
  const legend=el("div",null,"graph-legend");
  for(const type of [["case","Case"],["character","Character"],["vehicle","Vehicle"],["organization","Organization"],["evidence","Evidence"]])legend.append(el("span",type[1],"legend-"+type[0]));
  graphPanel.append(legend);
  if(write){
   graphPanel.append(el("h3","Add case entity"));
   graphPanel.append(form([
    field("entity_type","Entity type","select",[["character","Character"],["vehicle","Vehicle"],["organization","Organization"]]),
    field("name","Entity name"),field("description","IC description","textarea"),field("reference","In-game reference / identifier","optional")
   ],"Add node",async values=>{await api("/case-extras/"+id+"/nodes",values);await refresh()}));
   if(data.nodes.length>=2){
    graphPanel.append(el("h3","Connect entities"));
    const nodeOptions=data.nodes.map(node=>[String(node.id),node.entity_type.toUpperCase()+" · "+node.name]);
    graphPanel.append(form([
     field("source_id","From entity","select",nodeOptions),field("target_id","To entity","select",nodeOptions),field("label","Relationship / connection")
    ],"Create relationship",async values=>{
     if(values.source_id===values.target_id)throw Error("Choose two different entities");
     await api("/case-extras/"+id+"/links",{source_id:n(values.source_id),target_id:n(values.target_id),label:values.label});
     await refresh();
    }));
   }
  }
  body.append(graphPanel);
  const evidencePanel=panel("Evidence Vault");
  evidencePanel.append(el("p","Secure case-scoped storage for PDF and image evidence. Files are limited to 15 MB. Each upload receives a SHA-256 fingerprint; every upload, preview, download and integrity failure is recorded in a hash-linked custody trail.","muted"));
  if(write){
   const uploadForm=el("form",null,"evidence-upload-form");
   const addField=(label,control)=>{const wrap=el("label",label);wrap.append(control);uploadForm.append(wrap);return control};
   const title=addField("Evidence title",el("input"));
   title.name="title";title.required=true;title.maxLength=120;title.placeholder="e.g. Vehicle photo — east entrance";
   const category=el("select");category.name="category";
   for(const pair of [["document","Document / PDF"],["photo","Photo / image"],["other","Other supported file"]]){const option=el("option",pair[1]);option.value=pair[0];category.append(option)}
   addField("Evidence category",category);
   const related=el("select");related.name="related_entity_id";
   const empty=el("option","No related entity");empty.value="";related.append(empty);
   for(const node of data.nodes.filter(x=>x.entity_type!=="case"&&x.entity_type!=="evidence")){
    const option=el("option",node.entity_type.toUpperCase()+" · "+node.name);option.value=String(node.id);related.append(option);
   }
   addField("Link evidence to an entity (optional)",related);
   const detail=el("textarea");detail.name="detail";detail.maxLength=2000;detail.rows=3;detail.placeholder="Source, context and IC notes";
   addField("Evidence notes",detail);
   const file=el("input");file.type="file";file.name="file";file.required=true;file.accept=".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/png,image/jpeg,image/webp";
   addField("File · PDF / PNG / JPG / WEBP · max 15 MB",file);
   const submit=el("button","Upload evidence");submit.type="submit";uploadForm.append(submit);
   uploadForm.onsubmit=async event=>{
    event.preventDefault();submit.disabled=true;
    try{
     if(!file.files||!file.files[0])throw Error("Choose an evidence file first");
     if(file.files[0].size>15*1024*1024)throw Error("Evidence files are limited to 15 MB");
     const payload=new FormData();payload.append("title",title.value);payload.append("category",category.value);
     payload.append("related_entity_id",related.value);payload.append("detail",detail.value);payload.append("file",file.files[0]);
     await uploadApi("/case-extras/"+id+"/files",payload);await refresh();
    }catch(error){showError(error)}finally{submit.disabled=false}
   };
   evidencePanel.append(uploadForm);
  }
  if(!data.files.length)evidencePanel.append(el("p","No uploaded evidence files yet.","muted"));
  for(const file of data.files){
   const card=el("article",null,"tile"),size=(file.size/1024/1024).toFixed(2)+" MB";
   add(card,el("h3",file.title),el("small",file.original_filename+" · "+file.category.toUpperCase()+" · "+size),
    el("p","Uploaded by "+(file.uploader||"Unknown")+" · "+dateFormat(file.created)),
    el("p",file.detail||"No additional notes"),el("small","SHA-256 · "+file.sha256),
    el("small","Linked entity · "+(file.related_name||"Not linked")+" · "+file.event_count+" custody events"));
   if(file.content_type.startsWith("image/")){
    const image=el("img");image.src=fileUrl(file.id);image.alt=file.title;image.loading="lazy";image.className="evidence-preview";card.append(image);
   }
   const actions=el("div",null,"row");
   const download=el("a","Download original");download.href=fileUrl(file.id)+"?download=true";download.download=file.original_filename;download.className="button";
   actions.append(download,button("Chain of custody",async()=>{
    const trail=await api("/case-extras/evidence/"+file.id+"/custody");
    const details=el("div",null,"custody-trail");
    add(details,el("strong",trail.chain_valid?"Custody log hash chain valid":"WARNING · Custody log hash chain invalid"),el("p",trail.events.length+" recorded events"));
    for(const item of trail.events)add(details,el("p",dateFormat(item.created)+" · "+item.actor_name+" · "+item.action.toUpperCase()),el("small","Event hash · "+item.event_hash));
    card.append(details);
   },true));
   card.append(actions);evidencePanel.append(card);
  }
  body.append(evidencePanel);
  const refs=panel("Legacy evidence references");refs.append(lines(data.evidence,e=>e.title+" · "+e.reference+" · "+e.detail));body.append(refs);
  const oldRelations=panel("Legacy relationship notes");oldRelations.append(lines(data.relations,r=>r.left_name+" — "+r.label+" → "+r.right_name));body.append(oldRelations);
 };
 await refresh();return p;
}

async function approvalUI(){
 const d=await api("/approval-center"),p=panel("Approval Center");
 p.append(el("h3","Treasury requests awaiting your review"));
 for(const r of d.treasury){let t=el("article",null,"tile");add(t,el("h3",moneyFormat(r.amount)+" · "+r.category),el("p",r.note),button("Approve",()=>postRefresh("/ops/treasury/"+r.id+"/review",{approve:true})),button("Reject",()=>postRefresh("/ops/treasury/"+r.id+"/review",{approve:false}),true));p.append(t)}
 if(!d.treasury.length)p.append(el("p","No treasury requests available for your review.","muted"));
 if(me.admin)p.append(el("p",d.membership.length+" membership requests · "+d.clips.length+" clips awaiting moderation"),lines(Object.entries(d.community),x=>x[0]+": "+x[1]),button("Open admin queues",()=>switchView("admin"),true));
 const rights=await api("/ops/access"),modules=Object.keys(opsNames).filter(k=>rights[k]&&rights[k]!=="view");
 const all=await api("/ops/approvals?scope=all"),box=panel("Full Approval Workflow");
 box.append(el("p","Rank-routed, sequential decisions with independent reviewers, delegation and a permanent action history. Existing treasury and discount approvals remain in their dedicated workflows.","muted"));
 if(modules.length)box.append(form([field("module","Approval module","select",modules.map(x=>[x,opsNames[x]])),field("reference_type","Reference type · optional","optional"),field("reference_id","Reference ID · optional","optional"),field("title","Request title"),field("description","Justification / details","textarea")],"Submit approval request",async v=>{await api("/ops/approvals",v);await render()}));
 else box.append(el("p","You need write access to at least one module to submit an approval request.","muted"));
 const list=el("div");
 for(const item of all){
  const card=el("article",null,"tile"),status=item.status.toUpperCase(),meta=item.module+" · "+status+" · Step "+item.current_step+"/"+item.total_steps;
  add(card,el("h3",item.title),el("small",meta),el("p",item.description||"No additional details"),el("p","Submitted by "+item.requester_name+" · "+dateFormat(item.created)+(item.reference_type?" · "+item.reference_type+" #"+item.reference_id:"")));
  const actions=el("div",null,"row");
  if(item.status==="pending"&&item.requester===me.id)actions.append(button("Cancel request",()=>postRefresh("/ops/approvals/"+item.id+"/cancel",{}),true));
  if(item.status==="pending"&&item.requester!==me.id&&rights[item.module]==="approve"){
   actions.append(button("Approve current step",async()=>{const note=prompt("Decision note (optional):")||"";await api("/ops/approvals/"+item.id+"/review",{approve:true,note});await render()}),button("Reject request",async()=>{const note=prompt("Reason for rejection:");if(note===null||!note.trim())return;await api("/ops/approvals/"+item.id+"/review",{approve:false,note});await render()},true));
  }
  actions.append(button("View history",async()=>{const h=await api("/ops/approvals/"+item.id+"/history"),trail=el("div",null,"custody-trail");for(const a of h.actions)trail.append(el("p","Step "+a.step+" · "+a.decision.toUpperCase()+" · "+a.actor_name+(a.delegated_from_name?" (delegated by "+a.delegated_from_name+")":"")+" · "+dateFormat(a.created)+(a.note?" · "+a.note:"")));if(!h.actions.length)trail.append(el("p","No decisions recorded yet.","muted"));card.append(trail)},true));
  card.append(actions);list.append(card);
 }
 if(!all.length)list.append(el("p","No approval requests to display.","muted"));box.append(el("h3","Requests & review inbox"),list);
 if(modules.length){
  const delegates=await api("/ops/approvals/delegations");
  box.append(el("h3","Delegation"),el("p","Delegate a module approval task to another approved member who already has approve permission for that module. Use their HQ user ID.","muted"));
  box.append(form([field("module","Module","select",modules.map(x=>[x,opsNames[x]])),field("delegate_user_id","Delegate user ID","number"),field("active","Delegation","select",[["true","Active"],["false","Revoke"]],"true")],"Save delegation",async v=>{await api("/ops/approvals/delegations",{module:v.module,delegate_user_id:n(v.delegate_user_id),active:v.active==="true"});await render()}));
  box.append(lines(delegates,x=>x.module+" · "+x.delegator_name+" → "+x.delegate_name+" · "+(x.active?"ACTIVE":"REVOKED")));
 }
 if(me.admin){
  const config=await api("/admin/approval-policies");
  box.append(el("h3","Approval route configuration · administrator"),el("p","Enter rank IDs in approval order, separated by commas. Every selected rank must already have Approve permission for that module. Leave a module unconfigured to allow any member with that module's Approve permission to act as the single-step reviewer.","muted"));
  box.append(form([field("module","Module","select",Object.keys(opsNames).map(x=>[x,opsNames[x]])),field("ranks","Sequential rank IDs","text",null,"")],"Save approval route",async v=>{const ranks=v.ranks.split(",").map(x=>Number(x.trim())).filter(Boolean);if(!ranks.length)throw Error("Enter at least one rank ID");await api("/admin/approval-policies",{module:v.module,ranks});await render()}));
  box.append(lines(config.policies,x=>x.module+" · Step "+x.step+" → "+x.rank_name+" (rank "+x.rank_id+")"));
  box.append(form([field("module","Clear route","select",Object.keys(opsNames).map(x=>[x,opsNames[x]]))],"Remove route · use single-step approval",async v=>{await api("/admin/approval-policies/"+v.module,{},"DELETE");await render()}));
 }
 p.append(box);return p
}
function safeScreen(){generation++;me=null;let p=panel("STREAMER MODE");add(p,el("h1","THE HIGHEST HQ"),el("p","Protected display · Internal workspace hidden"),el("p","No HQ records are loaded into this screen. This does not control OBS or other browser tabs.","muted"),button("Exit Streamer Mode",()=>{if(confirm("Private HQ information may become visible. Exit safe display?"))setStreamSafe(false)},true));app.replaceChildren(p)}
function setStreamSafe(enabled){streamSafe=enabled;try{sessionStorage.setItem("highest_stream_safe",enabled?"1":"0")}catch{};if(enabled)safeScreen();else{view="community";history.replaceState(null,"","/highest/community/");boot()}}

async function discountPolicyPanel(ranks){
let p=panel("Business discount policy · per rank");
p.append(el("p","Each rank has allowed discount scopes and direct-approval limits. Discounts above either limit enter the approval queue and cannot move to Ready until approved. Fixed limit is the maximum total discount per order; selected-item fixed discounts are per unit.","muted"));
let policies=await api("/admin/discount-policies");
for(const rank of ranks){
 let current=policies.find(x=>x.rank_id===rank.id)||{scope:"none",max_percent:0,max_fixed:0};
 let card=el("article",null,"tile");
 add(card,el("h3",rank.name),el("p","Current: "+current.scope+" · Up to "+current.max_percent+"% · "+moneyFormat(current.max_fixed)+" fixed per order"));
 card.append(form([
  field("scope","Allowed discount scope","select",[["none","No discounts"],["all","All items only"],["items","Selected items only"],["both","All items and selected items"]],current.scope),
  field("max_percent","Maximum direct percentage (%)","number",null,current.max_percent),
  field("max_fixed","Maximum direct fixed discount per order ($)","number",null,current.max_fixed)
 ],"Save discount policy",async v=>{
  const pct=n(v.max_percent),fixed=n(v.max_fixed);
  if(!Number.isInteger(pct)||pct<0||pct>100)throw Error("Percentage must be between 0 and 100");
  if(!Number.isSafeInteger(fixed)||fixed<0||fixed>1000000000000)throw Error("Fixed limit must be a whole number within the supported range");
  await postRefresh("/admin/discount-policies",{rank:rank.id,scope:v.scope,max_percent:pct,max_fixed:fixed});
 }));
 p.append(card);
}
return p
}
async function discountApprovalUI(write,level){
let data=await api("/business/discount-requests"),p=panel("Discount approval queue");
p.append(el("p","Review requests that exceed the creator's rank discount limits. Approving activates the requested discount; rejecting removes the discount and lets the order continue at its undiscounted total.","muted"));
if(!data.requests.length)p.append(el("p","No discount requests awaiting approval.","muted"));
for(const o of data.requests){
 let card=el("article",null,"tile"),hist=el("div");
 add(card,el("h3","TH-BIZ-"+String(o.id).padStart(5,"0")+" · "+o.group_name),
 el("small",o.direction.toUpperCase()+" · "+o.creator+" · "+dateFormat(o.created)),
 lines(o.lines,l=>l.name+" × "+l.qty+" · Requested discount "+moneyFormat(l.requested_discount_amount)),
 el("p","Subtotal "+moneyFormat(o.subtotal)+" · Requested discount "+moneyFormat(o.requested_discount_amount)+" · Proposed total "+moneyFormat(o.subtotal-o.requested_discount_amount)),
 el("p","Discount method: "+(o.discount_scope==="all"?"All items · "+(o.discount_type==="percent"?o.discount_value+"%":moneyFormat(o.discount_value)+" fixed"): "Selected items")),
 el("p","Reason: "+o.discount_reason));
 if(level==="approve"&&o.actor!==me.id){
  card.append(form([field("note","Approval note (optional)","optional")],"Approve discount",v=>postRefresh("/business/orders/"+o.id+"/discount-review",{approve:true,note:v.note})));
  card.append(form([field("note","Reason for rejection")],"Reject discount",v=>postRefresh("/business/orders/"+o.id+"/discount-review",{approve:false,note:v.note})));
 }else if(o.actor===me.id)card.append(el("small","You cannot approve your own request.","muted"));
 p.append(card);
}
return p
}
async function pricesUI(write){let data=await api("/business/prices"),p=panel("Item buy & sell price catalog");p.append(el("p","Whole in-game dollars. Create master items in Inventory first. Changes affect future orders only.","muted"));if(!data.length)p.append(el("p","No inventory items yet."));for(const i of data){let t=el("article",null,"tile");add(t,el("h3",i.name),el("small",i.category),el("p",i.buy===null?"Price not set":"Buy "+moneyFormat(i.buy)+" · Sell "+moneyFormat(i.sell)+" · Unit margin "+moneyFormat(i.sell-i.buy)));if(write)t.append(form([field("buy","Purchase / input unit price","number",null,i.buy??0),field("sell","Sale / output unit price","number",null,i.sell??0)],"Save prices",v=>postRefresh("/business/prices",{item:i.id,buy:n(v.buy),sell:n(v.sell)})));p.append(t)}return p}
const businessTransitions={pending:["ready"],ready:["completed"],completed:[]};
function posUI(data,rights){
let p=panel("New order · POS"),cart=new Map(),lineDiscounts=new Map(),nonce=crypto.randomUUID();let f=el("form");
let policy=data.discount_policy||{scope:"none",max_percent:0,max_fixed:0};
function control(label,tag,type,choices){let l=el("label",label),x=el(tag);if(tag==="input")x.type=type;for(const [v,t] of choices||[]){let q=el("option",t);q.value=v;x.append(q)}l.append(x);f.append(l);return x}
function discountFor(base,type,value,qty=1){if(!base||!value)return 0;if(type==="percent")return Math.min(base,Math.floor((base*value+50)/100));if(type==="fixed")return Math.min(base,value*qty);return 0}
function allocateDiscount(amount,bases){let total=bases.reduce((a,b)=>a+b,0),shares=bases.map(x=>0);if(!total||!amount)return shares;let remainder=[];for(let i=0;i<bases.length;i++){let product=bases[i]*amount;shares[i]=Math.floor(product/total);remainder.push([i,product%total])}let left=amount-shares.reduce((a,b)=>a+b,0);remainder.sort((a,b)=>b[1]-a[1]||a[0]-b[0]);for(let i=0;i<left;i++)shares[remainder[i][0]]++;return shares}
let group=control("Customer / supplier group (IC)","input","text");group.required=true;group.maxLength=100;
let profile=control("Business unit / issuing identity","select",null,(data.profiles||[]).map(x=>[String(x.id),x.name+" · "+x.code+(x.is_default?" · Default":"")]));
let direction=control("Transaction type","select",null,[["sell","Sale / output"],["buy","Purchase / input"]]);
let select=control("Item","select",null,data.prices.map(i=>[String(i.id),i.name]));let qty=control("Quantity","input","number");qty.min="1";qty.max="100000";qty.value="1";
let discountOptions=[["none","No discount"]];
if(["all","both"].includes(policy.scope))discountOptions.push(["all","All items in cart"]);
if(["items","both"].includes(policy.scope))discountOptions.push(["items","Selected items only"]);
let discountScope=control("Discount scope","select",null,discountOptions);
let discountType=control("All-items discount method","select",null,[["percent","Percentage (%)"],["fixed","Nominal amount ($)"]]);
let discountValue=control("All-items discount value","input","number");discountValue.min="0";discountValue.max="1000000000000";discountValue.step="1";discountValue.value="0";
let typeWrap=discountType.parentElement,valueWrap=discountValue.parentElement;
let discountReason=control("Reason for discount","input","text");discountReason.maxLength=500;
let reasonWrap=discountReason.parentElement;reasonWrap.hidden=true;
let list=el("div"),totals=el("div",null,"tile");
function redraw(){
let rows=[],buy=0,sell=0;
for(const [id,q] of cart){let i=data.prices.find(x=>x.id===id),base=(direction.value==="buy"?i.buy:i.sell)*q;buy+=i.buy*q;sell+=i.sell*q;let d=lineDiscounts.get(id)||{type:"none",value:0};rows.push({id,q,item:i,base,discount:discountScope.value==="items"?discountFor(base,d.type,d.value,q):0,discountType:d.type,discountValue:d.value})}
let subtotal=direction.value==="buy"?buy:sell,discount=0;
if(discountScope.value==="all")discount=discountFor(subtotal,discountType.value,n(discountValue.value));
if(discountScope.value==="all"){let shares=allocateDiscount(discount,rows.map(x=>x.base));rows.forEach((x,i)=>x.discount=shares[i])}
discount=rows.reduce((a,x)=>a+x.discount,0);
let approvalRequired=false;
if(discountScope.value==="all"){
 if(discountType.value==="percent"&&n(discountValue.value)>policy.max_percent)approvalRequired=true;
 if(discount>policy.max_fixed)approvalRequired=true;
}else if(discountScope.value==="items"){
 if(Array.from(lineDiscounts.values()).some(x=>x.type==="percent"&&x.value>policy.max_percent))approvalRequired=true;
 if(discount>policy.max_fixed)approvalRequired=true;
}
reasonWrap.hidden=discount===0;discountReason.required=discount>0;if(discount===0)discountReason.value="";
list.replaceChildren();
for(const x of rows){
let row=el("article",null,"tile");
add(row,el("strong",x.item.name+" × "+x.q),el("p","Subtotal "+moneyFormat(x.base)+(x.discount?" · Discount −"+moneyFormat(x.discount):"")+" · Net "+moneyFormat(x.base-x.discount)));
if(discountScope.value==="items"){
let controls=el("div",null,"row"),type=el("select"),value=el("input"),label=el("label","Discount value");
for(const [v,t] of [["none","No discount"],["percent","Percentage (%)"],["fixed","Nominal per unit ($)"]]){let option=el("option",t);option.value=v;type.append(option)}
let current=lineDiscounts.get(x.id)||{type:"none",value:0};type.value=current.type;value.type="number";value.min="0";value.max=current.type==="percent"?"100":"1000000000";value.step="1";value.value=String(current.value||0);label.append(value);
type.onchange=()=>{value.value="0";value.max=type.value==="percent"?"100":"1000000000";lineDiscounts.set(x.id,{type:type.value,value:0});redraw()};
value.onchange=()=>{let v=n(value.value);if(!Number.isInteger(v)||v<0||(type.value==="percent"&&v>100)){showError(new Error("Discount must be a whole number; percentage is 0–100"));value.value=String(current.value||0);return}lineDiscounts.set(x.id,{type:type.value,value:v});redraw()};
controls.append(type,label);row.append(controls)
}
row.append(button("Remove",()=>{cart.delete(x.id);lineDiscounts.delete(x.id);redraw()},true));list.append(row)
}
let total=subtotal-discount;
totals.replaceChildren(el("h3","Subtotal "+moneyFormat(subtotal)),el("p","Total discount −"+moneyFormat(discount)),el("h2","Total after discount "+moneyFormat(total)),el("p","Direct discount limit: "+policy.max_percent+"% or "+moneyFormat(policy.max_fixed)+" per order"),el("p",discount===0?"No discount selected.":approvalRequired?"Approval required · reason is mandatory; the order cannot advance until approved.":"Within rank's direct discount limit · reason is mandatory."),el("p","Estimated purchase cost "+moneyFormat(buy)),...(direction.value==="sell"?[el("p","Estimated gross margin after discount "+moneyFormat(total-buy))]:[]));
typeWrap.hidden=discountScope.value!=="all";valueWrap.hidden=discountScope.value!=="all";
discountValue.max=discountType.value==="percent"?"100":"1000000000000";
}
f.append(button("Add item to cart",()=>{let id=n(select.value),q=n(qty.value);if(!data.prices.some(i=>i.id===id)||!Number.isInteger(q)||q<1||q+(cart.get(id)||0)>100000)throw Error("Invalid item or quantity");if(!cart.has(id)&&cart.size>=50)throw Error("Maximum 50 distinct items");cart.set(id,q+(cart.get(id)||0));redraw()}),list,totals);
direction.onchange=redraw;discountScope.onchange=redraw;discountType.onchange=()=>{if(discountType.value==="percent"&&n(discountValue.value)>100)discountValue.value="0";redraw()};discountValue.onchange=()=>{let v=n(discountValue.value);if(!Number.isInteger(v)||v<0||(discountType.value==="percent"&&v>100)){showError(new Error("Discount must be a whole number; percentage is 0–100"));discountValue.value="0"}redraw()};redraw();
let vault=control("Inventory settlement","select",null,[["","Record only — no stock change"],...((rights.inventory&&rights.inventory!=="view")?options(data.vaults):[])]);let money=control("Treasury settlement","select",null,[["false","Record only — no ledger request"],...((rights.treasury&&rights.treasury!=="view")?[["true","Create pending treasury request on completion"]]:[])]);let notes=control("Notes","textarea");notes.maxLength=1000;let submit=el("button","Create pending order");submit.type="submit";f.append(submit);f.onsubmit=async e=>{e.preventDefault();submit.disabled=true;try{if(!cart.size)throw Error("Add at least one item");let scope=discountScope.value;let lines=Array.from(cart,([item,qty])=>{let d=scope==="items"?(lineDiscounts.get(item)||{type:"none",value:0}):{type:"none",value:0};return {item,qty,discount_type:d.type,discount_value:d.value}});await api("/business/orders",{nonce,group_name:group.value,business_profile_id:n(profile.value),direction:direction.value,lines,notes:notes.value,vault:vault.value?n(vault.value):null,treasury:money.value==="true",discount_scope:scope,discount_type:scope==="all"?discountType.value:"none",discount_value:scope==="all"?n(discountValue.value):0,discount_reason:discountReason.value});await render()}catch(e){showError(e)}finally{submit.disabled=false}};
p.append(f,el("small","Discount permissions and approval limits are enforced by the server using your rank policy. All-items nominal discount is one amount for the cart; item-specific nominal discount is per unit. Discounts cannot be stacked. No stock is reserved before completion."));return p
}
function documentEscape(value){return String(value??"").replace(/[&<>"']/g,ch=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]))}
function businessDocumentHTML(o,kind){
const receipt=kind==="receipt",number=receipt?o.receipt_no:o.invoice_no,issued=receipt?o.receipt_issued_at:o.invoice_issued_at;
const brand=o.business_profile||{};
const accent=/^#[0-9a-f]{6}$/i.test(brand.accent_color||"")?brand.accent_color:"#b58b4a";
const template=["classic","executive","minimal"].includes(brand.template)?brand.template:"classic";
const brandName=documentEscape(brand.name||"THE HIGHEST HQ");
const initials=(brand.name||"THE HIGHEST HQ").trim().split(/\s+/).slice(0,2).map(x=>x.charAt(0)).join("").toUpperCase();
const logo=brand.logo_url?'<img class="brand-logo" src="'+documentEscape(brand.logo_url)+'" alt="" referrerpolicy="no-referrer">':'<div class="brand-monogram">'+documentEscape(initials||"TH")+'</div>';
const contact=[brand.organization_name,brand.contact_name,brand.contact_details].filter(Boolean).map(documentEscape).join(" · ");
const description=documentEscape(brand.description||"");
const groupLabel=o.direction==="sell"?"Customer / group":"Supplier / group";
const statusLabel=o.status==="ready"?"Ready · Butuh pengantaran":o.status==="completed"?"Completed":"Pending";
const settlement=o.money_state==="posted"?"Posted to treasury ledger":o.money_state==="pending"?"Pending treasury approval":o.money_state==="rejected"?"Rejected by treasury reviewer":"No treasury settlement requested";
const moneyState=documentEscape(settlement);
const itemRows=(o.lines||[]).map((line,index)=>'<tr><td>'+(index+1)+'</td><td>'+documentEscape(line.name)+'</td><td class="num">'+Number(line.qty).toLocaleString("id-ID")+'</td><td class="num">'+documentEscape(moneyFormat(o.direction==="buy"?line.buy:line.sell))+'</td><td class="num">'+documentEscape(moneyFormat(line.subtotal))+'</td><td class="num">'+documentEscape(moneyFormat(line.discount_amount))+'</td><td class="num">'+documentEscape(moneyFormat(line.total))+'</td></tr>').join("");
const discountNote=o.discount_state==="pending"?"Discount request pending approval; the displayed total excludes the requested discount.":o.discount_state==="rejected"?"Discount request rejected; the displayed total uses full price.":o.discount_state==="approved"?"Discount approved and applied.":"No discount applied.";
const settlementNote=receipt?"This document confirms the order was marked Completed in The Highest HQ. Treasury settlement is shown separately and may still require approval.":"Invoice for an in-game order. Final discounts are subject to the rank-based approval policy.";
const notes=[o.notes?("Order notes: "+o.notes):"",o.delivery_note?("Delivery: "+o.delivery_note):"",o.discount_reason?("Discount reason: "+o.discount_reason):""].filter(Boolean).map(x=>'<p>'+documentEscape(x)+'</p>').join("");
const footer=documentEscape(brand.footer||"Generated by The Highest HQ · All values are in-game currency (IC). This is an internal roleplay record, not a real-world invoice, receipt, or proof of payment.");
return '<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+documentEscape(number)+' · '+brandName+'</title><link rel="stylesheet" href="/highest/document.css"><style>:root{--brand-accent:'+accent+'}</style></head><body><div class="print-actions"><button id="print-document" type="button">Print / Save as PDF</button></div><main class="sheet">'
+'<header class="top template-'+template+'"><div class="identity">'+logo+'<div class="identity-copy"><div class="eyebrow">'+documentEscape(brand.code||"BUSINESS DIVISION")+'</div><div class="brand">'+brandName+'</div>'+(description?'<div class="brand-description">'+description+'</div>':"")+'<div class="organization">'+contact+'</div></div></div>'
+'<div class="doc-title"><div class="eyebrow">'+(receipt?"Transaction receipt":"Sales / purchase invoice")+'</div><h1>'+(receipt?"BUKTI PENYELESAIAN TRANSAKSI":"INVOICE")+'</h1><div class="doc-number">'+documentEscape(number||"Not issued")+'</div></div></header>'
+'<section class="meta"><div><label>Order reference</label><strong>TH-BIZ-'+String(o.id).padStart(5,"0")+'</strong></div><div><label>'+(receipt?"Receipt issued":"Invoice issued")+'</label><strong>'+documentEscape(dateFormat(issued))+'</strong></div><div><label>Issuing business unit</label><strong>'+brandName+'</strong></div><div><label>'+groupLabel+'</label><strong>'+documentEscape(o.group_name)+'</strong></div><div><label>Transaction type</label><strong>'+(o.direction==="sell"?"Sale / output":"Purchase / input")+'</strong></div><div><label>Created by</label><strong>'+documentEscape(o.invoice_creator_name||o.creator)+'</strong></div><div><label>Order status</label><strong>'+statusLabel+'</strong></div>'+(receipt?'<div><label>Completed at</label><strong>'+documentEscape(dateFormat(o.completed_at))+'</strong></div><div><label>Completed by</label><strong>'+documentEscape(o.receipt_completed_by||"—")+'</strong></div>':"")+'</section>'
+'<div class="table-wrap"><table><thead><tr><th>#</th><th>Item</th><th class="num">Qty</th><th class="num">Unit price</th><th class="num">Subtotal</th><th class="num">Discount</th><th class="num">Net total</th></tr></thead><tbody>'+itemRows+'</tbody></table></div>'
+'<section class="totals"><div><span>Subtotal</span><strong>'+documentEscape(moneyFormat(o.subtotal))+'</strong></div><div><span>Discount applied</span><strong>− '+documentEscape(moneyFormat(o.discount_amount))+'</strong></div>'+(o.discount_state==="pending"?'<div><span>Discount requested (pending)</span><strong>'+documentEscape(moneyFormat(o.requested_discount_amount))+'</strong></div>':"")+'<div class="grand"><span>Grand total</span><strong>'+documentEscape(moneyFormat(o.total))+'</strong></div></section>'
+'<section class="note"><strong>'+(receipt?"Treasury settlement":"Discount & order notes")+'</strong>'+(receipt?'<p>'+moneyState+'</p>':'<p>'+documentEscape(discountNote)+'</p>')+notes+(receipt?'<p>Invoice reference: '+documentEscape(o.invoice_no)+'</p>':"")+'<p>'+documentEscape(settlementNote)+'</p></section>'
+'<footer class="footer">'+footer+'<br>Generated by The Highest HQ · Internal FiveM roleplay economy record.</footer>'
+'</main></body></html>';
}
async function printBusinessDocument(orderId,kind){
const win=window.open("about:blank","_blank");
if(!win)throw Error("Pop-up diblokir browser. Izinkan pop-up untuk mencetak dokumen.");
win.opener=null;
try{
const result=await api("/business/orders/"+orderId),o=result.order;
if(kind==="receipt"&&(o.status!=="completed"||!o.receipt_no))throw Error("Receipt tersedia setelah order berstatus Completed.");
if(kind==="invoice"&&!o.invoice_no)throw Error("Invoice belum tersedia untuk order ini.");
win.document.open();win.document.write(businessDocumentHTML(o,kind));win.document.close();win.document.getElementById("print-document").addEventListener("click",()=>win.print());win.focus();
}catch(error){win.close();throw error}
}
async function businessDocumentCenter(){
const p=panel("Business Document Center");
let data=await api("/business/documents");
p.append(el("p","A searchable archive of issued invoices and completed-order receipts. Documents are retained by issue period; download a PDF directly or reopen the original branded print view.","muted"));
const filters=el("div",null,"document-filters");
const control=(label,type,items,placeholder)=>{
 const wrap=el("label",label),input=el(type==="select"?"select":"input");
 if(type==="date")input.type="date";else if(type==="search"){input.type="search";input.placeholder=placeholder||""}
 if(items){for(const [value,name] of items){let option=el("option",name);option.value=value;input.append(option)}}
 wrap.append(input);filters.append(wrap);return input
};
const search=control("Search document number / group","search",null,"e.g. INV-20261120-000001");
const kind=control("Document type","select",[["all","All documents"],["invoice","Invoices"],["receipt","Receipts"]]);
const profile=control("Business unit","select",[["all","All business units"],...data.profiles.map(x=>[String(x.id),x.name+" · "+x.code])]);
const creator=control("Created by","select",[["all","All creators"],...data.creators.map(x=>[String(x.id),x.name])]);
const period=control("Archive period","select",[["all","All periods"],...data.archive_periods.map(x=>[x.period,x.period+" · "+x.document_count+" documents"])]);
const from=control("Issued from","date"),to=control("Issued to","date");
const actions=el("div",null,"row"),summary=el("div",null,"document-summary"),archive=el("div"),results=el("div"),pagination=el("div",null,"row");
const addSummary=(label,value,detail)=>{let tile=el("article",null,"tile");add(tile,el("small",label),el("h2",String(value)),el("small",detail||""));summary.append(tile)};
const draw=(d)=>{
 data=d;summary.replaceChildren();
 addSummary("Documents",d.summary.document_count,"Across "+d.summary.order_count+" orders");
 addSummary("Invoices",d.summary.invoice_count,"Issued documents");
 addSummary("Receipts",d.summary.receipt_count,"Completed orders");
 addSummary("Invoiced value",moneyFormat(d.summary.invoiced_value),"Invoice value counted once");
 archive.replaceChildren();archive.append(el("h3","Monthly archive"));
 if(!d.archive_periods.length)archive.append(el("p","No archived periods yet.","muted"));
 else{
  const periodNav=el("nav");
  periodNav.append(button("All periods",()=>{period.value="all";from.value="";to.value="";load(1)},period.value!=="all"));
  for(const x of d.archive_periods.slice(0,12))periodNav.append(button(x.period+" · "+x.document_count,()=>{period.value=x.period;from.value="";to.value="";load(1)},period.value!==x.period));
  archive.append(periodNav);
 }
 results.replaceChildren();
 if(!d.documents.length)results.append(el("p","No documents match these filters.","muted"));
 for(const doc of d.documents){
  const card=el("article",null,"tile"),typeLabel=doc.document_type==="invoice"?"INVOICE":"RECEIPT";
  add(card,el("h3",typeLabel+" · "+doc.document_number),
   el("small",doc.business_name+" · "+doc.business_code+" · "+dateFormat(doc.issued_at)),
   el("p","Order TH-BIZ-"+String(doc.order_id).padStart(5,"0")+" · "+doc.group_name+" · "+(doc.direction==="sell"?"Sale / output":"Purchase / input")),
   el("p","Created by "+(doc.creator_name||"—")+(doc.completed_by?" · Completed by "+doc.completed_by:"")),
   el("h3",moneyFormat(doc.total)),
   el("small","Order status: "+(doc.status==="ready"?"Ready · Butuh pengantaran":doc.status==="completed"?"Completed":"Pending")));
  const row=el("div",null,"row"),download=el("a","Download PDF");
  download.href="/highest/api/business/documents/"+doc.order_id+"/"+doc.document_type+"/pdf";
  download.download=doc.document_number+".pdf";download.className="button";
  row.append(download,button("Open / Print",()=>printBusinessDocument(doc.order_id,doc.document_type),true));
  card.append(row);results.append(card);
 }
 pagination.replaceChildren();
 pagination.append(el("small","Showing "+(d.documents.length?((d.page-1)*d.page_size+1):0)+"–"+((d.page-1)*d.page_size+d.documents.length)+" of "+d.total+" documents"));
 if(d.pages>1){
  if(d.page>1)pagination.append(button("Previous",()=>load(d.page-1),true));
  if(d.page<d.pages)pagination.append(button("Next",()=>load(d.page+1),true));
 }
};
const load=async(page=1)=>{
 const params=new URLSearchParams({page:String(page),page_size:"50"});
 if(search.value.trim())params.set("q",search.value.trim());
 if(kind.value!=="all")params.set("kind",kind.value);
 if(profile.value!=="all")params.set("profile_id",profile.value);
 if(creator.value!=="all")params.set("creator_id",creator.value);
 if(period.value!=="all")params.set("period",period.value);
 if(from.value)params.set("from_date",from.value);
 if(to.value)params.set("to_date",to.value);
 draw(await api("/business/documents?"+params.toString()));
};
actions.append(button("Search / Apply filters",()=>load(1)),button("Reset filters",()=>{search.value="";kind.value="all";profile.value="all";creator.value="all";period.value="all";from.value="";to.value="";load(1)},true));
p.append(filters,actions,summary,archive,results,pagination);
draw(data);
return p
}

let businessSubtab="orders";
async function businessUI(write,level,rights){let data=await api("/business/orders"),p=panel("Business operations"),tabs=el("nav");tabs.append(button("Orders & POS",async()=>{businessSubtab="orders";await render()},businessSubtab!=="orders"),button("Document Center",async()=>{businessSubtab="documents";await render()},businessSubtab!=="documents"));p.append(tabs);if(businessSubtab==="documents"){p.append(await businessDocumentCenter());return p}p.append(el("p","Fictional FiveM economy · Every transaction is permanently attributed to the account that created it. Status changes are separately attributed to the acting account. Completed orders are retained in the analytics archive. Only three statuses are used: Pending, Ready (Butuh pengantaran), and Completed.","muted"));if(write&&data.prices.length)p.append(posUI(data,rights));else if(write)p.append(el("p","Configure item prices in Business Price Catalog first.","muted"));let filters=el("nav"),results=el("div"),memberFilter=el("select");let selected="all",selectedMember="all";for(const [value,label] of [["all","All members"],...Array.from(new Map(data.orders.map(o=>[String(o.actor),o.creator||("Member #"+o.actor)])).entries()).sort((a,b)=>a[1].localeCompare(b[1])).map(([id,name])=>[id,name])]){let option=el("option",label);option.value=value;memberFilter.append(option)}memberFilter.onchange=()=>{selectedMember=memberFilter.value;draw()};function draw(){results.replaceChildren();let orders=data.orders.filter(o=>(selected==="all"||o.status===selected)&&(selectedMember==="all"||String(o.actor)===selectedMember));if(!orders.length)results.append(el("p","No orders in this status.","muted"));for(const o of orders){let t=el("article",null,"tile"),hist=el("div");let label=o.status==="ready"?"READY · BUTUH PENGANTARAN":o.status==="completed"?"COMPLETED · ANALYTICS ARCHIVE":"PENDING";let discountLabel=o.discount_state==="pending"?"DISCOUNT APPROVAL PENDING":o.discount_state==="rejected"?"DISCOUNT REJECTED · FULL PRICE":o.discount_state==="approved"?"DISCOUNT APPROVED":"NO DISCOUNT";add(t,el("h3","TH-BIZ-"+String(o.id).padStart(5,"0")+" · "+o.group_name),el("small",o.direction.toUpperCase()+" · "+label+" · By "+(o.creator||("Member #"+o.actor))+" · "+dateFormat(o.created)),lines(o.lines,l=>l.name+" × "+l.qty+" @ "+moneyFormat(o.direction==="buy"?l.buy:l.sell)+" = "+moneyFormat(l.subtotal)+(l.discount_amount?" · Discount −"+moneyFormat(l.discount_amount)+(l.discount_type==="percent"?" ("+l.discount_value+"%)":l.discount_type==="fixed"?" ("+moneyFormat(l.discount_value)+" / unit)":""):"")+" · Net "+moneyFormat(l.total)),el("p",discountLabel+" · "+(o.discount_state==="pending"?"Requested "+moneyFormat(o.requested_discount_amount):o.discount_state==="rejected"?"Requested "+moneyFormat(o.requested_discount_amount)+" · "+o.discount_review_note:"Applied "+moneyFormat(o.discount_amount))),el("p",o.discount_reason?"Discount reason: "+o.discount_reason:""),el("p",o.discount_scope==="all"?"Discount: All items · "+(o.discount_type==="percent"?o.discount_value+"%":moneyFormat(o.discount_value)+" fixed total"):(o.discount_scope==="items"?"Discount: Selected items":"No discount")),el("p","Subtotal "+moneyFormat(o.subtotal)+" · Total discount −"+moneyFormat(o.discount_amount)),el("h3","Total "+moneyFormat(o.total)),el("p",o.estimated_margin===null?"Purchase order":"Estimated gross profit "+moneyFormat(o.estimated_margin)),el("p",o.delivery_note||""),el("p",o.notes),el("small","Vault: "+(data.vaults.find(v=>v.id===o.vault)?.name||"record only")+" · Treasury: "+(o.treasury?(o.money_state||"not submitted"):"record only")),el("p"),button("Status history",async()=>{let d=await api("/business/orders/"+o.id);hist.replaceChildren(lines(d.history,h=>dateFormat(h.created)+" · "+h.display_name+" · "+h.status+" · "+h.note))},true),hist);t.append(el("small","Business unit: "+(o.business_profile?.name||"Legacy profile")+" · Invoice: "+(o.invoice_no||"Not issued")));t.append(button("Open / Print invoice · Save PDF",()=>printBusinessDocument(o.id,"invoice"),true));if(o.status==="completed"&&o.receipt_no)t.append(button("Open / Print receipt · Save PDF",()=>printBusinessDocument(o.id,"receipt"),true));let allowed=(businessTransitions[o.status]||[]).filter(s=>write&&o.discount_state!=="pending"&&(s!=="completed"||level==="approve"));if(allowed.length)t.append(form([field("status","Next status","select",allowed.map(s=>[s,s==="ready"?"Ready · Butuh pengantaran":"Completed"])),field("note",o.status==="pending"?"Delivery instruction (optional)":"Completion note (optional)","optional")],"Update order status",v=>postRefresh("/business/orders/"+o.id+"/status",{...v,version:o.version})));if(o.status==="completed")t.append(el("small","Completed at: "+dateFormat(o.completed_at)+" · Retained for analytics"));results.append(t)}}for(const [status,label] of [["all","All orders"],["pending","Pending"],["ready","Ready · Delivery"],["completed","Completed archive"]])filters.append(button(label,()=>{selected=status;draw()},true));p.append(filters,memberFilter,results);draw();return p}

let businessAnalyticsTab="overview";
async function businessAnalyticsUI(){let p=panel("Business Intelligence & Analytics"),start=new Date(),end=new Date();start.setDate(start.getDate()-29);const iso=d=>{let x=new Date(d.getTime()-d.getTimezoneOffset()*60000);return x.toISOString().slice(0,10)};let from=el("input"),to=el("input");from.type="date";to.type="date";from.value=iso(start);to.value=iso(end);let controls=el("div",null,"row"),tabs=el("nav"),content=el("div");const localEpoch=(v,addDays=0)=>{let [y,m,d]=v.split("-").map(Number);return Math.floor(new Date(y,m-1,d+addDays).getTime()/1000)};let data=null;
function metric(label,value,sub){let card=el("article",null,"tile");add(card,el("small",label),el("h2",value),el("p",sub||""));return card}
function barList(rows,label,value){let box=el("div");let max=Math.max(1,...rows.map(value));for(const row of rows){let card=el("div",null,"tile"),top=el("div",null,"row");add(top,el("strong",label(row)),el("span",moneyFormat(value(row))));let track=el("div"),fill=el("div");track.style.height="9px";track.style.background="#292929";track.style.borderRadius="9px";track.style.overflow="hidden";fill.style.height="9px";fill.style.width=(Math.max(0,value(row))/max*100)+"%";fill.style.background="#c9a86a";track.append(fill);card.append(top,track);box.append(card)}if(!rows.length)box.append(el("p","No completed activity in this period.","muted"));return box}
function overview(){let s=data.summary,box=el("div");let kpis=el("div",null,"grid");kpis.append(metric("Sales revenue",moneyFormat(s.sales_revenue),s.sales_orders+" completed sales orders"),metric("Purchase spend",moneyFormat(s.purchase_spend),s.purchase_orders+" completed purchase orders"),metric("Gross profit",moneyFormat(s.estimated_gross_profit),(s.cogs_basis||"catalog_buy_price_estimate")+" · "+s.gross_margin_pct+"% gross margin"),metric("Net order value",moneyFormat(s.net_order_value),"Sales value less purchase-order value"),metric("Total discounts",moneyFormat(s.total_discounts),"Sales "+moneyFormat(s.sales_discounts)+" · Purchases "+moneyFormat(s.purchase_discounts)),metric("Pending treasury settlement",moneyFormat(s.pending_settlement_value),s.pending_settlements+" pending settlement requests"),metric("Inventory carrying value",moneyFormat(s.stock_value_estimate),s.unpriced_stock_qty+" units still unvalued"));box.append(kpis);let pipeline=el("div",null,"grid");pipeline.append(metric("Pending orders",String(s.pending_orders),"Awaiting preparation"),metric("Ready · delivery required",String(s.ready_orders),"Delivery backlog"),metric("Completed orders",String(s.completed_orders),s.units_sold+" units sold"),metric("Average sales order",moneyFormat(s.average_sales_order),"Completed sales only"));box.append(el("h3","Order & Financial Performance"),pipeline,el("h3","Completed order trend"));let trend=data.trend.slice(-14);box.append(el("h4","Daily sales revenue"),barList(trend,x=>x.day,x=>x.sales_revenue),el("h4","Daily purchase spend"),barList(trend,x=>x.day,x=>x.purchase_spend));box.append(el("h3","Top customer / supplier groups"),lines(data.groups.slice(0,8),x=>x.group_name+" · "+x.completed_orders+" orders · Sales "+moneyFormat(x.sales_revenue)+" · Purchases "+moneyFormat(x.purchase_spend)));return box}
function groupView(){let box=el("div");box.append(el("h3","Group performance · completed orders"),lines(data.groups,x=>x.group_name+" · "+x.completed_orders+" orders · Sales "+moneyFormat(x.sales_revenue)+" (discount "+moneyFormat(x.sales_discounts)+") · Purchases "+moneyFormat(x.purchase_spend)+" (discount "+moneyFormat(x.purchase_discounts)+") · Gross profit "+moneyFormat(x.estimated_gross_profit)));return box}
function productView(){let box=el("div");box.append(el("h3","Product performance · completed orders"),lines(data.products,x=>x.item_name+" · Sold "+x.units_sold+" · Revenue "+moneyFormat(x.sales_revenue)+" · Discount "+moneyFormat(x.sales_discounts)+" · Gross profit "+moneyFormat(x.estimated_gross_profit)+" · Purchased "+x.units_purchased+" ("+moneyFormat(x.purchase_spend)+", discount "+moneyFormat(x.purchase_discounts)+")"));return box}
function flowView(){let f=data.flow,box=el("div"),kpis=el("div",null,"grid");kpis.append(metric("Goods input",f.input_qty.toLocaleString("id-ID")+" units","Valued "+moneyFormat(f.valued_input)),metric("Goods output",f.output_qty.toLocaleString("id-ID")+" units","Valued "+moneyFormat(f.valued_output)),metric("Transfer in",f.transfer_in_qty.toLocaleString("id-ID")+" units","Internal warehouse movement"),metric("Transfer out",f.transfer_out_qty.toLocaleString("id-ID")+" units","Excluded from external net flow"));box.append(kpis,el("h3","Movement by transaction type"),lines(f.by_type,x=>x.kind+" · In "+x.input_qty+" / Out "+x.output_qty+" · Transfer in/out "+x.transfer_in_qty+"/"+x.transfer_out_qty+" · Valued in/out "+moneyFormat(x.input_value)+"/"+moneyFormat(x.output_value)),el("h3","Item flow"),lines(f.by_item,x=>x.item_name+" · Input "+x.input_qty+" / Output "+x.output_qty+" · Transfer "+x.transfer_in_qty+"/"+x.transfer_out_qty),el("h3","Current stock by vault"),lines(data.stock,x=>x.vault_name+" · "+x.item_name+" · "+x.qty+" units"+(x.low_stock?" · LOW STOCK":"")),el("h3","Data quality"));box.append(el("p",f.unvalued_movement_qty+" units of stock movement are still unvalued. Quantities remain visible, but unknown costs are excluded from monetary totals.","muted"),el("p",data.data_quality.gross_profit_basis,"muted"));if(data.low_stock.length)box.append(el("h3","Low stock alerts"),lines(data.low_stock,x=>x.item_name+" · "+x.total_qty+" / minimum "+x.min_stock+" units across all vaults"));return box}
function memberView(){let box=el("div"),rows=data.members||[];box.append(el("h3","Member transaction performance"),el("p","Transactions created are attributed to the account that submitted the order. Sales and purchase values include completed orders in the selected period, attributed to the original creator—not the member who later changes its status.","muted"));box.append(lines(rows,x=>x.display_name+" · Created "+x.transactions_created+" orders (Pending "+x.pending_orders+" / Ready "+x.ready_orders+" / Completed "+x.completed_orders_created+") · Completed sales "+x.completed_sales_orders+" · Revenue "+moneyFormat(x.sales_revenue)+" · Sales discount "+moneyFormat(x.sales_discounts)+" · Completed purchases "+x.completed_purchase_orders+" · Spend "+moneyFormat(x.purchase_spend)+" · Purchase discount "+moneyFormat(x.purchase_discounts)+" · Gross profit "+moneyFormat(x.estimated_gross_profit)));return box}
function draw(){content.replaceChildren();tabs.replaceChildren();for(const [k,label] of [["overview","Executive Overview"],["groups","Group Analysis"],["products","Product Performance"],["flow","Inventory Input / Output"],["members","Member Performance"]])tabs.appendChild(button(label,()=>{businessAnalyticsTab=k;draw()},k!==businessAnalyticsTab));content.append(businessAnalyticsTab==="overview"?overview():businessAnalyticsTab==="groups"?groupView():businessAnalyticsTab==="products"?productView():businessAnalyticsTab==="members"?memberView():flowView())}
async function load(){if(!from.value||!to.value)throw Error("Select both dates");let a=localEpoch(from.value),b=localEpoch(to.value,1);if(b<=a)throw Error("End date must not precede start date");data=await api("/business/analytics?start="+a+"&end="+b);exportButton.disabled=false;draw()}
let apply=button("Apply date range",async()=>{try{await load()}catch(e){showError(e)}});
function exportCsv(){if(!data)return;const rowsOut=[["THE HIGHEST HQ — BUSINESS INTELLIGENCE"],["Period",from.value,to.value],[],["EXECUTIVE SUMMARY"],["Metric","Value"],...Object.entries(data.summary).map(([k,v])=>[k,v]),[],["GROUP PERFORMANCE"],["Group","Completed Orders","Sales Revenue","Sales Discounts","Purchase Spend","Purchase Discounts","Estimated Gross Profit"],...data.groups.map(x=>[x.group_name,x.completed_orders,x.sales_revenue,x.sales_discounts,x.purchase_spend,x.purchase_discounts,x.estimated_gross_profit]),[],["PRODUCT PERFORMANCE"],["Item","Units Sold","Sales Revenue","Sales Discounts","Estimated COGS","Gross Profit","Units Purchased","Purchase Spend","Purchase Discounts"],...data.products.map(x=>[x.item_name,x.units_sold,x.sales_revenue,x.sales_discounts,x.estimated_cogs,x.estimated_gross_profit,x.units_purchased,x.purchase_spend,x.purchase_discounts]),[],["MEMBER PERFORMANCE"],["Account","Transactions Created","Pending","Ready","Completed Created","Completed Sales Orders","Sales Revenue","Sales Discounts","Completed Purchase Orders","Purchase Spend","Purchase Discounts","Estimated Gross Profit"],...(data.members||[]).map(x=>[x.display_name,x.transactions_created,x.pending_orders,x.ready_orders,x.completed_orders_created,x.completed_sales_orders,x.sales_revenue,x.sales_discounts,x.completed_purchase_orders,x.purchase_spend,x.purchase_discounts,x.estimated_gross_profit]),[],["INVENTORY MOVEMENT BY TYPE"],["Movement","Movements","Input Qty","Output Qty","Transfer In","Transfer Out","Input Value","Output Value"],...data.flow.by_type.map(x=>[x.kind,x.movements,x.input_qty,x.output_qty,x.transfer_in_qty,x.transfer_out_qty,x.input_value,x.output_value]),[],["INVENTORY MOVEMENT BY ITEM"],["Item","Input Qty","Output Qty","Transfer In","Transfer Out","Input Value","Output Value"],...data.flow.by_item.map(x=>[x.item_name,x.input_qty,x.output_qty,x.transfer_in_qty,x.transfer_out_qty,x.input_value,x.output_value]),[],["CURRENT STOCK"],["Vault","Item","Quantity","Minimum Stock","Low Stock"],...data.stock.map(x=>[x.vault_name,x.item_name,x.qty,x.min_stock,x.low_stock])];const cell=v=>{let s=String(v??"");if(/^[=+@-]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"'};const csv="\uFEFF"+rowsOut.map(row=>row.map(cell).join(",")).join("\r\n");const url=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"}));const a=el("a");a.href=url;a.download="highest-business-report-"+from.value+"-to-"+to.value+".csv";document.body.append(a);a.click();a.remove();URL.revokeObjectURL(url)}
let exportButton=button("Export CSV",exportCsv,true);exportButton.disabled=true;
for(const days of [7,30,90])controls.append(button("Last "+days+" days",async()=>{let d=new Date();to.value=iso(d);d.setDate(d.getDate()-(days-1));from.value=iso(d);try{await load()}catch(e){showError(e)}},true));
controls.append(from,to,apply,exportButton);p.append(el("p","Enterprise-style management reporting · Completed orders only for sales, purchases and gross-profit analytics. Inventory movement is reported separately.","muted"),controls,tabs,content);load().catch(showError);return p}
