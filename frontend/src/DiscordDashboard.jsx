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
 return <Section title="Sambutan anggota baru"><Toggle label="Aktifkan Welcome" value={v.enabled} onChange={x=>set('enabled',x)}/><Select label="Channel sambutan" value={v.channel} change={x=>set('channel',x)} options={text}/><Text label="Pesan sambutan" value={v.template} change={x=>set('template',x)} max={1500} area/><p className="dd-note">Variabel: {'{member}, {name}, {server}, {count}'}.</p><Toggle label="Ping anggota baru" value={v.ping} onChange={x=>set('ping',x)}/><div className="dd-preview"><strong>Contoh pesan</strong><p>{v.template?.replaceAll('{member}','@Member').replaceAll('{name}','Member').replaceAll('{server}',s.guild.name).replaceAll('{count}','123')}</p></div><div className="dd-actions">{btn('Simpan pengaturan',()=>run('welcome.save',{...bools(v,['enabled','ping']),channel:v.channel||null,template:v.template}))}{btn('Kirim contoh tersimpan (tanpa ping)',()=>run('welcome.test',{},true))}</div></Section>
}
function Tickets({s,run}) {
 const [v,set]=useFields(s.ticket||{enabled:false,category:'',support:'',log:'',title:'Pusat Bantuan Abud',description:'Butuh bantuan? Buka tiket privat bersama tim support.'}), [target,setTarget]=useState(s.ticket?.panel_channel||'');
 const text=s.channels.filter(c=>c.type==='text');
 return <><Section title="Konfigurasi tiket"><Toggle label="Aktifkan Ticket Support" value={v.enabled} onChange={x=>set('enabled',x)}/><Select label="Kategori tiket" value={v.category} change={x=>set('category',x)} options={s.channels.filter(c=>c.type==='category')}/><Select label="Role staf support" value={v.support} change={x=>set('support',x)} options={s.roles}/><Select label="Channel log privat" value={v.log} change={x=>set('log',x)} options={text}/><p className="dd-note">Role staf tidak boleh diberikan melalui panel role publik. Pastikan log hanya dapat dilihat staf.</p><Text label="Judul panel" value={v.title} change={x=>set('title',x)}/><Text label="Deskripsi panel" value={v.description} change={x=>set('description',x)} max={1500} area/><div className="dd-preview"><strong>{v.title}</strong><p>{v.description}</p><span>Buka tiket privat</span></div>{btn('Simpan pengaturan',()=>run('ticket.save',{enabled:!!v.enabled,category:v.category,support:v.support,log:v.log,title:v.title,description:v.description}),!v.category||!v.support||!v.log)}</Section><Section title="Publikasikan panel yang tersimpan"><Select label="Channel panel tiket" value={target} change={setTarget} options={text}/>{btn('Publikasikan panel',()=>run('ticket.publish',{channel:target},true),!target||!s.ticket?.enabled)}</Section></>
}
function Panel({p,s,run}){
 const [emoji,setEmoji]=useState(''),[role,setRole]=useState(''),[target,setTarget]=useState(p.channel||'');
 return <Section title={p.title}><p>{p.description}</p><p className="dd-note">{p.enabled?'Aktif':'Draft / jeda'} · {p.mode==='single'?'Satu pilihan':'Beberapa pilihan'}</p>{p.mappings.map(m=><div key={m.emoji} className="dd-line"><span>{m.display} — {s.roles.find(r=>r.id===m.role)?.name||'Role tidak tersedia'}</span>{btn('Hapus pilihan',()=>run('reaction.unbind',{id:p.id,emoji:m.display},true),!!p.enabled)}</div>)}<Text label="Emoji (mis. 🎮)" value={emoji} change={setEmoji}/><Select label="Role yang diberikan" value={role} change={setRole} options={s.roles}/>{btn('Tambahkan pilihan',()=>run('reaction.bind',{id:p.id,emoji,role}),!emoji||!role||!!p.enabled)}<Select label="Channel panel" value={target} change={setTarget} options={s.channels.filter(c=>c.type==='text')}/><div className="dd-actions">{btn('Publikasikan',()=>run('reaction.publish',{id:p.id,channel:target},true),!target||!p.mappings.length||!!p.enabled)}{btn('Nonaktifkan',()=>run('reaction.disable',{id:p.id},true),!p.enabled)}{btn('Hapus panel',()=>run('reaction.delete',{id:p.id},true),!!p.enabled)}</div><p className="dd-note">Menonaktifkan atau menghapus panel tidak mencabut role lama secara massal.</p></Section>
}
function Reactions({s,run}){
 const [v,set]=useFields({title:'Pilih role kamu',description:'Klik emoji untuk mendapatkan role.',mode:'multiple'});
 return <><Section title="Buat panel role"><Text label="Judul" value={v.title} change={x=>set('title',x)}/><Text label="Deskripsi" value={v.description} change={x=>set('description',x)} max={1500} area/><Select label="Mode pilihan" value={v.mode} change={x=>set('mode',x)} options={choices([['multiple','Boleh beberapa role'],['single','Hanya satu role']])}/><p className="dd-note">Buat draft, tambahkan emoji dan role, lalu publikasikan. Role berizin tinggi akan ditolak oleh bot.</p>{btn('Buat draft panel',()=>run('reaction.create',v),!v.title||!v.mode)}</Section>{s.panels.map(p=><Panel key={p.id} p={p} s={s} run={run}/>)}</>
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
 if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'Permintaan gagal.');
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
   setSnapshot(await load(guild));setVersion(x=>x+1);setNotice(action==='read'?'Data diperbarui.':'Pengaturan berhasil disimpan / tindakan berhasil.');
  }catch(e){setError(e.message+' Muat ulang sebelum mencoba aksi yang sama.');if(action!=='read'){try{setSnapshot(await load(guild));setVersion(x=>x+1)}catch{setSnapshot(null)}}}
  finally{setBusy(false)}
 }
 const current=modules.find(m=>m[0]===tab), available=s?.available[linked[tab]||tab];
 const status=key=>{if(!s.available[linked[key]||key])return 'Tidak tersedia';if(key==='reaction')return s.panels.some(p=>p.enabled)?'Aktif':'Belum ada panel aktif';if(key==='notifications')return s.notifications.some(n=>n.enabled)?'Aktif':'Belum ada langganan aktif';if(key==='voice'||key==='music')return 'Tersedia';return s[key]?.enabled?'Aktif':'Belum aktif'};
 return <main className="dd-page">
  <header className="dd-heading"><div><div className="dd-kicker"><Bot size={18}/> DISCORD BOT</div><h1>Kelola bot Discord</h1><p>Pilih server, pilih fitur, lalu simpan. Tidak perlu menghafal slash command.</p></div></header>
  {error&&<p role="alert" className="dd-alert">{error}</p>}{notice&&<p role="status" className="dd-notice">{notice}</p>}
  {servers===null?<p>Memeriksa server Discord…</p>:!servers.length?<Section title="Belum ada server yang dapat dikelola"><p>Login dengan akun Discord yang menjadi Administrator atau pemilik server tempat ABUD sudah bergabung. Selesaikan profil jika diperlukan.</p><a href="/auth/discord/login">Login Discord</a></Section>:<Section title="Pilih server"><fieldset disabled={busy}><Select label="Server Discord" value={guild} change={id=>{setTab('overview');setGuild(id)}} options={servers}/>{guild&&btn('Muat ulang',()=>run('read'))}</fieldset></Section>}
  {busy&&<p role="status">Memproses…</p>}
  {s&&<><div className="dd-tabs"><button type="button" aria-current={tab==='overview'?'page':undefined} onClick={()=>setTab('overview')} disabled={busy}>Ringkasan</button>{modules.map(([key,title])=><button key={key} type="button" aria-current={tab===key?'page':undefined} disabled={busy} onClick={()=>{setTab(key);setNotice('');setError('')}}>{title}</button>)}</div>
  {tab==='overview'?<div className="dd-grid">{modules.map(([key,title,desc,Icon])=><button key={key} disabled={busy} type="button" className="dd-module" onClick={()=>setTab(key)}><Icon size={25}/><span><strong>{title}</strong><small>{desc}</small><small className="dd-status">{status(key)}</small></span><ChevronRight size={18}/></button>)}</div>:<><h2 className="dd-subheading">{current?.[1]}</h2>{!available?<Section title="Fitur belum tersedia"><p>Hubungi pengelola ABUD untuk mengaktifkan layanan ini.</p></Section>:<fieldset disabled={busy} key={guild+'-'+tab+'-'+version}>
  {tab==='leveling'?<Level s={s} run={run}/>:tab==='welcome'?<Welcome s={s} run={run}/>:tab==='ticket'?<Tickets s={s} run={run}/>:tab==='reaction'?<Reactions s={s} run={run}/>:tab==='notifications'?<Notifications s={s} run={run}/>:<VoiceMusic s={s} kind={tab}/>}
  </fieldset>}</>}
  </>}
 </main>
}
