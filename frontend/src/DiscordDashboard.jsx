import React, {useEffect, useState} from 'react';
import {Bot, Trophy, Ticket, Hand, Users, Bell, Mic, Music, RefreshCw, ChevronRight} from 'lucide-react';
import './discord-dashboard.css';

const modules = [
 ['leveling', 'Leveling', 'XP, rank dan pengumuman level', Trophy],
 ['ticket', 'Ticket Support', 'Pusat bantuan privat', Ticket],
 ['welcome', 'Welcome', 'Sambut anggota baru', Hand],
 ['reaction', 'Reaction Roles', 'Role pilihan melalui emoji', Users],
 ['notifications', 'Notifikasi kreator', 'YouTube dan TikTok', Bell],
 ['voice', 'AI Voice', 'Percakapan di voice channel', Mic],
 ['music', 'Music Player', 'Putar musik di Discord', Music]
];
const linked = {welcome:'onboarding',reaction:'onboarding'};
const btn = (text, fn, disabled=false) => <button type="button" disabled={disabled} onClick={fn}>{text}</button>;
function Field({label,children,note}) {return <label className="dd-field"><span>{label}</span>{children}{note && <small>{note}</small>}</label>}
function Toggle({label,value,onChange}) {return <label className="dd-toggle"><span>{label}</span><input type="checkbox" checked={!!value} onChange={e=>onChange(e.target.checked)}/></label>}
function Text({label,value,change,max=100,area=false}) {const props={value:value??'',maxLength:max,onChange:e=>change(e.target.value)};return <Field label={label}>{area?<textarea {...props} rows={4}/>:<input {...props}/>}</Field>}
function Select({label,value,change,options,optional=false}) {return <Field label={label}><select value={value??''} onChange={e=>change(e.target.value)}><option value="">{optional?'Tidak dipilih':'Pilih…'}</option>{options.map(o=><option key={o.id} value={o.id}>{o.name}</option>)}</select></Field>}
const choices=(rows)=>rows.map(([id,name])=>({id,name}));
const bools=(value,keys)=>Object.fromEntries(keys.map(k=>[k,!!value[k]]));
function useFields(initial){const [v,set]=useState(initial);return [v,(k,x)=>set(old=>({...old,[k]:x}))]}
function Section({title,children}){return <section className="dd-card"><h2>{title}</h2>{children}</section>}
function Level({s,run}) {
 const [v,set]=useFields(s.leveling), [channel,setChannel]=useState('');
 const all=s.channels.filter(c=>c.type!=='category'), text=all.filter(c=>c.type==='text');
 return <><Section title="Pengaturan XP"><Toggle label="Aktifkan Leveling" value={v.enabled} onChange={x=>set('enabled',x)}/><Toggle label="XP dari chat" value={v.chat} onChange={x=>set('chat',x)}/><Toggle label="XP dari voice channel" value={v.voice} onChange={x=>set('voice',x)}/><Select label="Channel pengumuman level-up (opsional)" value={v.announcement} change={x=>set('announcement',x)} options={text} optional/><p className="dd-note">Anti-spam dan batas XP sudah ditentukan oleh bot. Tidak ada role hadiah otomatis.</p>{btn('Simpan pengaturan',()=>run('leveling.save',{...bools(v,['enabled','chat','voice']),announcement:v.announcement||null}))}</Section><Section title="Channel yang tidak mendapatkan XP"><Select label="Pilih channel" value={channel} change={setChannel} options={all}/>{btn('Kecualikan channel',()=>run('leveling.exclude',{channel,excluded:true}),!channel)}{v.excluded.map(id=><div className="dd-line" key={id}><span>{all.find(c=>c.id===id)?.name||'Channel '+id}</span>{btn('Izinkan XP',()=>run('leveling.exclude',{channel:id,excluded:false}))}</div>)}</Section></>
}
function Welcome({s,run}) {
 const [v,set]=useFields(s.welcome), text=s.channels.filter(c=>c.type==='text');
 return <Section title="Sambutan anggota baru"><Toggle label="Aktifkan Welcome" value={v.enabled} onChange={x=>set('enabled',x)}/><Select label="Channel sambutan" value={v.channel} change={x=>set('channel',x)} options={text}/><Text label="Pesan sambutan" value={v.template} change={x=>set('template',x)} max={1500} area/><p className="dd-note">Variabel: {'{member}, {name}, {server}, {count}'}.</p><Toggle label="Ping anggota baru" value={v.ping} onChange={x=>set('ping',x)}/><div className="dd-preview"><strong>Contoh pesan</strong><p>{v.template?.replaceAll('{member}','@Member').replaceAll('{name}','Member').replaceAll('{server}',s.guild.name).replaceAll('{count}','123')}</p></div><div className="dd-actions">{btn('Simpan pengaturan',()=>run('welcome.save',{...bools(v,['enabled','ping']),channel:v.channel||null,template:v.template}))}{btn('Kirim contoh tersimpan (tanpa ping)',()=>run('welcome.test',{},true),!s.welcome.enabled)}</div></Section>
}
function Tickets({s,run}) {
 const [v,set]=useFields(s.ticket||{enabled:false,category:'',support:'',log:'',title:'Pusat Bantuan Abud',description:'Butuh bantuan? Buka tiket privat bersama tim support.'}), [target,setTarget]=useState(s.ticket?.panel_channel||'');
 const text=s.channels.filter(c=>c.type==='text');
 return <><Section title="Konfigurasi tiket"><Toggle label="Aktifkan Ticket Support" value={v.enabled} onChange={x=>set('enabled',x)}/><Select label="Kategori tiket" value={v.category} change={x=>set('category',x)} options={s.channels.filter(c=>c.type==='category')}/><Select label="Role staf support" value={v.support} change={x=>set('support',x)} options={s.roles}/><Select label="Channel log privat" value={v.log} change={x=>set('log',x)} options={text}/><p className="dd-note">Role staf tidak boleh diberikan melalui panel role publik. Pastikan log hanya dapat dilihat staf.</p><Text label="Judul panel" value={v.title} change={x=>set('title',x)}/><Text label="Deskripsi panel" value={v.description} change={x=>set('description',x)} max={1500} area/><div className="dd-preview"><strong>{v.title}</strong><p>{v.description}</p><span>Buka tiket privat</span></div>{btn('Simpan pengaturan',()=>run('ticket.save',{enabled:!!v.enabled,category:v.category,support:v.support,log:v.log,title:v.title,description:v.description}),!v.category||!v.support||!v.log)}</Section><Section title="Publikasikan panel yang tersimpan"><Select label="Channel panel tiket" value={target} change={setTarget} options={text}/>{btn('Publikasikan panel',()=>run('ticket.publish',{channel:target},true),!target||!s.ticket?.enabled)}</Section></>
}
const commonEmoji = ['🎮','✅','❤️','🔥','🎵','🎨','🤖','💎','⭐','🎉','👋','📚','⚔️','🏆','💬','🔔','🎬','🌟','🟢','🔴','🔵','🟣','🇮🇩','1️⃣'];
function EmojiPicker({value,change,emojis,disabled}){
 return <div className="dd-emoji-picker">
  <div className="dd-field"><span>Pilih emoji umum</span><div className="dd-emoji-grid">{commonEmoji.map(emoji=><button type="button" key={emoji} aria-label={'Pilih emoji '+emoji} aria-pressed={value===emoji} disabled={disabled} onClick={()=>change(emoji)}>{emoji}</button>)}</div></div>
  <Field label="Custom emoji server"><select value={emojis.some(e=>e.value===value)?value:''} onChange={e=>{if(e.target.value)change(e.target.value)}} disabled={disabled||!emojis.length}><option value="">{emojis.length?'Pilih custom emoji…':'Tidak ada custom emoji yang bisa digunakan'}</option>{emojis.map(e=><option key={e.id} value={e.value}>:{e.name}: ({e.id})</option>)}</select></Field>
  <Field label="Emoji yang dipilih / tempel emoji lain" note="Pilih di atas atau tempel satu emoji asli. Nama :emoji: hanya untuk custom emoji server ini."><input value={value} maxLength={100} disabled={disabled} onChange={e=>change(e.target.value)} placeholder="🎮"/></Field>
 </div>
}
function ReactionEmoji({value}){
 const custom=/^<a?:([A-Za-z0-9_]+):(\d+)>$/.exec(value||'');
 return custom?<span role="img" aria-label={custom[1]}>:{custom[1]}:</span>:<span>{value||'—'}</span>;
}
function Panel({p,s,run}){
 const [emoji,setEmoji]=useState(''),[role,setRole]=useState(''),[target,setTarget]=useState(p.channel||'');
 const checks=s.reaction_roles||{}, roleInfo=checks[role], eligible=s.roles.filter(r=>checks[r.id]?.allowed&&!p.mappings.some(m=>m.role===r.id)), blocked=s.roles.filter(r=>checks[r.id]&&!checks[r.id].allowed);
 const channels=s.channels.filter(c=>c.type==='text'&&(!p.channel||c.id===p.channel)), chosen=channels.find(c=>c.id===target);
 return <div className="dd-reaction-editor">
 <div className="dd-panel-head"><div><h2>{p.title}</h2><p>{p.description}</p></div><span className={'dd-state '+(p.enabled?'is-live':'')}>{p.enabled?'Aktif di Discord':p.message?'Dijeda':'Draft · belum terbit'}</span></div>
 <div className="dd-steps" aria-label="Progres konfigurasi"><span className="done">1. Panel dibuat</span><span className={p.mappings.length?'done':''}>2. Pilihan role</span><span className={p.enabled?'done':''}>3. Publikasi</span></div>
 <div className="dd-panel-columns"><div>
 <Section title="2. Pilih emoji & role">
 <p className="dd-note">{p.enabled?'Jeda panel sebelum mengubah pilihan.':'Tambahkan satu pasangan emoji dan role untuk setiap pilihan anggota.'}</p>
 {p.mappings.length?<div className="dd-mapping-list">{p.mappings.map(m=><div className="dd-mapping" key={m.emoji}><div className="dd-mapping-emoji"><ReactionEmoji value={m.display}/></div><div><strong>{s.roles.find(r=>r.id===m.role)?.name||'Role tidak tersedia'}</strong><small>{checks[m.role]?.allowed?'Siap digunakan':checks[m.role]?.reason||'Periksa role di Discord'}</small></div>{!p.enabled&&btn('Hapus',()=>run('reaction.unbind',{id:p.id,emoji:m.display},true))}</div>)}</div>:<p className="dd-empty">Belum ada pilihan. Tambahkan pilihan pertama di bawah.</p>}
 {!p.enabled&&<><EmojiPicker value={emoji} change={setEmoji} emojis={s.emojis||[]}/><Select label="Role yang akan diterima anggota" value={role} change={setRole} options={eligible}/>{!eligible.length&&<p className="dd-note">Tidak ada role tambahan yang memenuhi syarat. Periksa izin dan hierarki role di Discord, lalu muat ulang.</p>}
 <button className="dd-primary" type="button" disabled={!emoji.trim()||!roleInfo?.allowed||!eligible.some(r=>r.id===role)} onClick={()=>run('reaction.bind',{id:p.id,emoji:emoji.trim(),role})}>+ Simpan pilihan</button>
 {blocked.length>0&&<details className="dd-role-help"><summary>{blocked.length} role tidak dapat dipilih — lihat alasan</summary>{blocked.map(r=><div key={r.id}><strong>{r.name}</strong><small>{checks[r.id].reason}</small></div>)}<p className="dd-note">Perbaiki di Server Settings → Roles, lalu gunakan Muat ulang. Jangan menghapus izin staff hanya agar role bisa dipilih.</p></details>}
 </>}</Section></div>
 <div><Section title="Preview pesan Discord"><div className="dd-discord-preview"><small>ABUD BOT</small><strong>{p.title}</strong><p>{p.description}</p>{p.mappings.map(m=><div key={m.emoji}><ReactionEmoji value={m.display}/> → @{s.roles.find(r=>r.id===m.role)?.name||'Role tidak tersedia'}</div>)}{!p.mappings.length&&<small>Belum ada pilihan tersimpan.</small>}<small>{p.mode==='single'?'Hanya satu pilihan role':'Boleh memilih beberapa role'}</small></div><p className="dd-note">Preview dari pilihan yang sudah disimpan, bukan pesan yang sudah dikirim.</p></Section>
 <Section title="3. Publikasikan ke Discord">
 {p.enabled?<><p>Panel aktif di #{s.channels.find(c=>c.id===p.channel)?.name||'channel tersimpan'}.</p>{btn('Jeda panel untuk mengedit',()=>run('reaction.disable',{id:p.id},true))}</>:<><Select label="Channel tujuan" value={target} change={setTarget} options={channels}/>{p.channel&&<p className="dd-note">Panel yang pernah terbit harus tetap di channel asal.</p>}<button className="dd-primary" type="button" disabled={!chosen||!p.mappings.length||p.mappings.some(m=>!checks[m.role]?.allowed)} onClick={()=>run('reaction.publish',{id:p.id,channel:target},true)}>{p.message?'Aktifkan kembali':'Publikasikan panel'}</button><p className="dd-note">{!p.mappings.length?'Tambahkan minimal satu pilihan dulu.':p.mappings.some(m=>!checks[m.role]?.allowed)?'Perbaiki atau hapus pilihan role yang tidak valid.':!chosen?'Pilih channel tujuan.':'Siap dikirim ke Discord.'}</p></>}
 <details className="dd-role-help"><summary>Pengaturan lanjutan</summary><p className="dd-note">Menjeda atau menghapus panel tidak mencabut role lama secara massal.</p>{btn('Hapus panel',()=>run('reaction.delete',{id:p.id},true),!!p.enabled)}</details></Section></div></div></div>
}
function Reactions({s,run}){
 const [v,set]=useFields({title:'Pilih role kamu',description:'Klik emoji untuk mendapatkan role.',mode:'multiple'});
 const [selected,setSelected]=useState(null),[creating,setCreating]=useState(false);
 const panel=s.panels.find(p=>p.id===selected)||s.panels[0];
 return <div className="dd-reaction">
 <p className="dd-note">Anggota klik emoji di Discord untuk mengambil role sendiri. Kelola panel yang sudah ada atau buat panel baru.</p>
 <div className="dd-panel-head"><h2>Panel role ({s.panels.length})</h2><button className="dd-primary" type="button" onClick={()=>setCreating(x=>!x)}>{creating?'Tutup form':'+ Buat panel'}</button></div>
 {(creating||!s.panels.length)&&<Section title="1. Buat panel baru"><Text label="Judul pesan" value={v.title} change={x=>set('title',x)}/><Text label="Petunjuk untuk anggota" value={v.description} change={x=>set('description',x)} max={1500} area/><Select label="Berapa role boleh dipilih?" value={v.mode} change={x=>set('mode',x)} options={choices([['multiple','Boleh beberapa role'],['single','Hanya satu role']])}/><button className="dd-primary" type="button" disabled={!v.title.trim()||!v.mode} onClick={async()=>{const result=await run('reaction.create',v);if(result){setSelected(result.panels.find(p=>!s.panels.some(old=>old.id===p.id))?.id||null);setCreating(false)}}}>Buat panel & lanjutkan</button></Section>}
 {s.panels.length>0&&<><div className="dd-panel-list" aria-label="Pilih panel">{s.panels.map(p=><button aria-pressed={panel?.id===p.id} key={p.id} type="button" onClick={()=>{setSelected(p.id);setCreating(false)}}><strong>{p.title}</strong><small>{p.enabled?'Aktif':p.message?'Dijeda':'Draft'} · {p.mappings.length} pilihan</small></button>)}</div>{panel&&<Panel key={panel.id+':'+s.revision} p={panel} s={s} run={run}/>}</>}
 </div>
}
function NotifyFields({v,set,text}){return <><Select label="Channel tujuan" value={v.destination} change={x=>set('destination',x)} options={text}/><Select label="Jenis notifikasi" value={v.events} change={x=>set('events',x)} options={choices([['both','Live dan video baru'],['live','Live saja'],['post','Video baru saja']])}/><Select label="Ping anggota" value={v.ping} change={x=>set('ping',x)} options={choices([['none','Tanpa ping'],['here','@here'],['everyone','@everyone']])}/></>}
function Subscription({row,s,run}){const [v,set]=useFields(row);return <Section title={row.title}><p className="dd-note">{row.platform} · {row.account}</p><Toggle label="Aktifkan notifikasi" value={v.enabled} onChange={x=>set('enabled',x)}/><NotifyFields v={v} set={set} text={s.channels.filter(c=>c.type==='text')}/><div className="dd-actions">{btn('Simpan',()=>run('notify.edit',{id:row.id,destination:v.destination,ping:v.ping,events:v.events,enabled:!!v.enabled},v.ping!=='none'))}{btn('Kirim contoh (tanpa ping)',()=>run('notify.test',{id:row.id},true))}{btn('Hapus langganan',()=>run('notify.remove',{id:row.id},true))}</div></Section>}
function Notifications({s,run}){
 const [v,set]=useFields({url:'',destination:'',events:'both',ping:'none'});
 return <><Section title="Tambahkan kreator YouTube"><p className="dd-note">YouTube: {s.providers.youtube?'API key dikonfigurasi':'belum dikonfigurasi'}. TikTok: {s.providers.tiktok?'webhook dikonfigurasi; gunakan /notify add untuk pendaftaran':'provider belum terhubung'}.</p><Text label="Link channel atau @handle YouTube" value={v.url} change={x=>set('url',x)} max={500}/><NotifyFields v={v} set={set} text={s.channels.filter(c=>c.type==='text')}/>{btn('Tambahkan langganan',()=>run('notify.add',v,v.ping!=='none'),!v.url||!v.destination||!s.providers.youtube)}</Section>{s.notifications.map(row=><Subscription row={row} key={row.id} s={s} run={run}/>)}</>
}
function VoiceMusic({s,kind}){return <Section title={kind==='voice'?'AI Voice':'Music Player'}><p>{s.sessions[kind]?'Sesi sedang aktif di server ini.':'Tidak ada sesi aktif di server ini.'}</p><p className="dd-note">Fitur ini diaktifkan secara global oleh pengelola ABUD. Tidak ada pengaturan permanen per server saat ini. Kontrol sesi tetap melalui Discord.</p><div className="dd-preview">{kind==='voice'?<><p><code>/join</code> — masuk voice channel</p><p><code>/listen</code> — atur persetujuan audio sendiri</p><p><code>/voice-status</code> — status sesi</p><p><code>/leave</code> — keluar</p></>:<><p><code>/play query:judul lagu</code> — putar lagu</p><p><code>/music queue</code> — antrean</p><p><code>/music volume</code> — volume</p><p><code>/music leave</code> — keluar</p></>}</div><p>AI Voice dan Music tidak dapat aktif dalam voice channel server yang sama secara bersamaan.</p></Section>}
async function request(path, data) {
 const response=await fetch(path,{credentials:'same-origin',...(data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{})});
 let body;try{body=await response.json()}catch{throw new Error('Server tidak dapat memberikan respons. Muat ulang.')}
 if(!response.ok){const error=new Error(typeof body.detail==='string'?body.detail:'Permintaan gagal.');error.status=response.status;throw error;}
 return body;
}
export default function DiscordDashboard(){
 const [servers,setServers]=useState(null),[guild,setGuild]=useState(''),[s,setSnapshot]=useState(null),[tab,setTab]=useState('overview'),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState(''),[version,setVersion]=useState(0);
 const load=async id=>request('/dashboard/discord/action',{guild_id:id,action:'read',data:{}});
 useEffect(()=>{let alive=true;request('/dashboard/discord/servers').then(x=>{if(alive){setServers(x.servers);if(x.servers.length===1)setGuild(x.servers[0].id)}}).catch(e=>{if(alive){setServers([]);setError(e.message)}});return()=>{alive=false}},[]);
 useEffect(()=>{let alive=true;setSnapshot(null);setError('');setNotice('');if(guild){setBusy(true);load(guild).then(x=>{if(alive)setSnapshot(x)}).catch(e=>{if(alive)setError(e.message)}).finally(()=>{if(alive)setBusy(false)})}return()=>{alive=false}},[guild]);
 async function run(action,data={},confirm=false){
  if(busy||!guild)return;
  if(confirm&&!window.confirm('Lanjutkan tindakan ini pada server '+s.guild.name+'?'))return;
  setBusy(true);setError('');setNotice('');
  try{
   if(action!=='read')await request('/dashboard/discord/action',{guild_id:guild,action,data});
   const fresh=await load(guild);setSnapshot(fresh);setVersion(x=>x+1);setNotice(action==='read'?'Data diperbarui.':action==='reaction.bind'?'Pilihan emoji dan role tersimpan.':action==='reaction.publish'?'Panel berhasil dipublikasikan ke Discord.':'Pengaturan berhasil disimpan.');return fresh;
  }catch(e){setError(e.message+(e.status===400?' Periksa pilihan dan izin di Discord.':' Muat ulang sebelum mencoba aksi yang sama.'));if(action!=='read'){try{setSnapshot(await load(guild));if(e.status!==400)setVersion(x=>x+1)}catch{setSnapshot(null)}}return null;}
  finally{setBusy(false)}
 }
 const current=modules.find(m=>m[0]===tab), available=s?.available[linked[tab]||tab];
 const status=key=>{if(!s.available[linked[key]||key])return 'Tidak tersedia';if(key==='reaction')return s.panels.some(p=>p.enabled)?'Aktif':'Belum ada panel aktif';if(key==='notifications')return s.notifications.some(n=>n.enabled)?'Aktif':'Belum ada langganan aktif';if(key==='voice'||key==='music')return 'Tersedia';return s[key]?.enabled?'Aktif':'Belum aktif'};
 return <main className="dd-page">
  <header className="dd-heading"><div><div className="dd-kicker"><Bot size={18}/> DISCORD BOT</div><h1>Kelola bot Discord</h1><p>Pilih server, pilih fitur, lalu simpan. Tidak perlu menghafal slash command.</p></div></header>
  <section className="dd-invite"><div><h2>Tambahkan ABUD ke server kamu</h2><p>Pilih server di Discord, izinkan akses, lalu kembali ke sini untuk mengatur bot.</p></div><div className="dd-actions"><a className="dd-invite-link" href="/discord/invite" target="_blank" rel="noopener noreferrer"><Bot size={18}/> Invite ABUD to your server</a>{btn('Segarkan daftar server',()=>window.location.reload(),busy)}</div></section>
  {error&&<p role="alert" className="dd-alert">{error}</p>}{notice&&<p role="status" className="dd-notice">{notice}</p>}
  {servers===null?<p>Memeriksa server Discord…</p>:!servers.length?<Section title="Belum ada server yang dapat dikelola"><p>Undang ABUD menggunakan tombol di atas, lalu segarkan daftar server. Login dengan akun Discord yang menjadi Administrator atau pemilik server. Selesaikan profil jika diperlukan.</p><a href="/auth/discord/login">Login Discord</a></Section>:<Section title="Pilih server"><fieldset disabled={busy}><Select label="Server Discord" value={guild} change={id=>{setTab('overview');setGuild(id)}} options={servers}/>{guild&&btn('Muat ulang',()=>run('read'))}</fieldset></Section>}
  {busy&&<p role="status">Memproses…</p>}
  {s&&<><div className="dd-tabs"><button type="button" aria-current={tab==='overview'?'page':undefined} onClick={()=>setTab('overview')} disabled={busy}>Ringkasan</button>{modules.map(([key,title])=><button key={key} type="button" aria-current={tab===key?'page':undefined} disabled={busy} onClick={()=>{setTab(key);setNotice('');setError('')}}>{title}</button>)}</div>
  {tab==='overview'?<div className="dd-grid">{modules.map(([key,title,desc,Icon])=><button key={key} disabled={busy} type="button" className="dd-module" onClick={()=>setTab(key)}><Icon size={25}/><span><strong>{title}</strong><small>{desc}</small><small className="dd-status">{status(key)}</small></span><ChevronRight size={18}/></button>)}</div>:<><h2 className="dd-subheading">{current?.[1]}</h2>{!available?<Section title="Fitur belum tersedia"><p>Hubungi pengelola ABUD untuk mengaktifkan layanan ini.</p></Section>:<fieldset disabled={busy} key={guild+'-'+tab+(tab==='reaction'?'':'-'+version)}>
  {tab==='leveling'?<Level s={s} run={run}/>:tab==='welcome'?<Welcome s={s} run={run}/>:tab==='ticket'?<Tickets s={s} run={run}/>:tab==='reaction'?<Reactions s={{...s,revision:version}} run={run}/>:tab==='notifications'?<Notifications s={s} run={run}/>:<VoiceMusic s={s} kind={tab}/>}
  </fieldset>}</>}
  </>}
 </main>
}
