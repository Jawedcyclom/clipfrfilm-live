"""Relais « vues en direct » pour le dashboard clipfrfilm Live.

L'onglet TikTok Studio ouvert dans Chrome (déjà connecté) envoie toutes les 5 min les vues à jour
des 100 dernières vidéos + les abonnés à ce petit serveur local (http://127.0.0.1:8766/snap).
Le serveur garde l'historique, calcule les vues gagnées et envoie un fichier compact sur Google Drive
(CLIP tiktok/dashboard/clipfrfilm_live.json) que le dashboard lit depuis le téléphone.

  python tools/live_relay.py          # à laisser tourner (PC allumé)
Les relevés viennent de l'extension Chrome tools/extension_live (vidéos toutes les 5 min, stats Studio complètes toutes les heures).
"""
import glob, json, os, subprocess, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FULL = ROOT / 'travail' / 'live_full.json'
OUT = ROOT / 'travail' / 'clipfrfilm_live.json'
LOG = ROOT / 'travail' / 'live_relay.log'
STUDIO = ROOT / 'travail' / 'studio_latest.json'   # dernier relevé TikTok Studio complet (+ jours archivés)
DRIVE = 'gdrive:CLIP tiktok/dashboard/clipfrfilm_live.json'
DRIVE_STATE = 'gdrive:CLIP tiktok/dashboard/state/'
HIST_KEYS = ('vv', 'pv', 'like', 'comment', 'share', 'followers', 'reached', 'newv', 'returning')
lock = threading.Lock()
DAILY = {}   # jours relevés par nous : {AAAAMMJJ: {'f': abonnés en fin de jour, 'g': vues gagnées ce jour-là}}


def log(*a):
    line = time.strftime('%Y-%m-%d %H:%M:%S ') + ' '.join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f: f.write(line + '\n')


def rclone():
    hits = glob.glob(os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\WinGet\Packages\Rclone.Rclone_*\rclone-*\rclone.exe'))
    return hits[0] if hits else 'rclone'


def midnight_ms(t):
    lt = time.localtime(t / 1000)
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)) * 1000)


def gained(now_v, ref, items=None):
    """vues gagnées depuis un relevé de référence. Une vidéo absente de la référence ne compte en entier
    que si elle a été postée après (sinon c'est juste une vieille vidéo qu'on ne suivait pas encore)."""
    ref_v, g = ref['v'], 0
    for k, v in now_v.items():
        if k in ref_v: g += max(0, v - ref_v[k])
        elif items is None or (items.get(k, {}).get('t', 0) * 1000 >= ref['t'] - 15 * 60 * 1000): g += v
    return g


def day_str(start, i):
    t = time.mktime((int(start[:4]), int(start[4:6]), int(start[6:8]) + i, 12, 0, 0, 0, 0, -1))
    return time.strftime('%Y%m%d', time.localtime(t))


def merge_studio(new):
    """garde tous les jours déjà vus (TikTok ne donne que 60 j) et reconstruit hist depuis le 1er jour archivé"""
    old = json.loads(STUDIO.read_text(encoding='utf-8')) if STUDIO.exists() else {}
    days = old.get('days', {})
    for i in range(len(new['hist']['vv'])):
        days[day_str(new['start'], i)] = {k: (new['hist'].get(k) or [0] * 999)[i] for k in HIST_KEYS}
    keys = sorted(days)
    start = keys[0]
    span = []
    while not span or span[-1] < keys[-1]: span.append(day_str(start, len(span)))
    st = dict(new, start=start, days=days, hist={k: [days.get(d, {}).get(k, 0) for d in span] for k in HIST_KEYS})
    STUDIO.write_text(json.dumps(st, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return st


def followers_day(last, ref_day):
    """abonnés gagnés aujourd'hui : par rapport au total de fin d'hier donné par TikTok Studio (sinon 1er relevé du jour)"""
    f = last.get('f')
    if not f: return None
    yd = time.strftime('%Y%m%d', time.localtime(last['t'] / 1000 - 86400))
    try:   # TikTok Studio = total exact de fin de journée, prioritaire quand il couvre hier
        st = json.loads(STUDIO.read_text(encoding='utf-8'))
        if day_str(st['start'], len(st['hist']['followers']) - 1) == yd: return f - st['hist']['followers'][-1]
    except Exception:
        pass
    if DAILY.get(yd, {}).get('f'): return f - DAILY[yd]['f']
    try:
        st = json.loads(STUDIO.read_text(encoding='utf-8'))
        if day_str(st['start'], len(st['hist']['followers']) - 1) == time.strftime('%Y%m%d', time.localtime(time.time() - 86400)):
            return f - st['hist']['followers'][-1]
    except Exception:
        pass
    return f - ref_day['f'] if ref_day and ref_day.get('f') else None


def day_offset(full, t):
    o = full.get('offset') or {}
    return o.get('g', 0) if o.get('day') == time.strftime('%Y%m%d', time.localtime(t / 1000)) else 0


def build(full):
    it = full['items']
    DAILY.clear(); DAILY.update(full.get('daily', {}))
    sn = [s for s in full['snaps'] if 'v' in s]          # relevés complets (les vieux sont allégés)
    last = sn[-1]; t = last['t']; now_v = last['v']
    md = midnight_ms(t)
    ref_day = next((s for s in sn if s['t'] >= md), None)
    # après une coupure (PC éteint) on ne compare pas à un relevé trop vieux : ça ferait un faux « +180 000 en 1 h »
    ref_h = next((s for s in reversed(sn) if t - 120 * 60 * 1000 <= s['t'] <= t - 55 * 60 * 1000), None)
    ref_30 = next((s for s in reversed(sn) if t - 60 * 60 * 1000 <= s['t'] <= t - 25 * 60 * 1000), None)
    # courbe : vues gagnées depuis minuit à chaque relevé du jour (valeur calculée et gardée à chaque relevé)
    off = day_offset(full, t)
    curve = [[s['t'], s['gd']] for s in full['snaps'] if s['t'] >= md and s.get('gd') is not None]
    if off and curve: curve.insert(0, [md, 0])
    hist = [[s['t'], s.get('f'), s.get('tot', 0)] for s in full['snaps']]
    ref = ref_h or ref_30 or (sn[-2] if len(sn) > 1 and t - sn[-2]['t'] <= 30 * 60 * 1000 else None)
    rising = []
    if ref:
        for k, v in now_v.items():
            if k in ref['v'] and v > ref['v'][k]: rising.append([k, v - ref['v'][k]])
        rising.sort(key=lambda x: -x[1])
    return {
        'source': 'Pages TikTok publiques (relevé toutes les 5 min)' if full.get('src') == 'public' else 'TikTok Studio (onglet Chrome du PC)',
        'updated': t, 'followers': last.get('f'), 'hearts': full.get('hearts'),
        'tracked': len(now_v), 'total': sum(now_v.values()),
        'today': {'since': md if off else ref_day['t'], 'gained': gained(now_v, ref_day, it) + off} if ref_day else None,
        'daily': dict(sorted(full.get('daily', {}).items())[-90:]),
        'hourly': dict(sorted(full.get('hourly', {}).items())[-72:]),
        'vh': {k: [p for p in v if p[0] >= t - 48 * 3600 * 1000] for k, v in sorted(full.get('vh', {}).items(), key=lambda kv: -(kv[1][-1][1] - kv[1][0][1]))[:150]},
        'ms': full.get('ms', {}),
        'hour': {'since': ref_h['t'], 'gained': gained(now_v, ref_h, it)} if ref_h else None,
        'rising': {'since': ref['t'], 'list': rising[:15]} if ref else None,
        # vues gagnées aujourd'hui, vidéo par vidéo (depuis le 1er relevé complet du jour)
        'top_today': ({'since': ref_day['t'], 'list': sorted(([k, v - ref_day['v'][k]] for k, v in now_v.items()
                       if k in ref_day['v'] and v > ref_day['v'][k]), key=lambda x: -x[1])[:60]} if ref_day else None),
        'followers_day': followers_day(last, ref_day),
        'curve': curve[-300:], 'hist': hist[-300:],
        'items': it,
        'studio': ({k: v for k, v in json.loads(STUDIO.read_text(encoding='utf-8')).items() if k != 'days'} if STUDIO.exists() else None),
    }


def slim(full, now):
    """garde le détail par vidéo seulement pour les 2 dernières heures + le 1er relevé du jour (référence de minuit) ;
    les autres relevés ne gardent que l'heure, les abonnés et les totaux (fichier léger même avec tout le compte)."""
    md = midnight_ms(now)
    first_today = next((s['t'] for s in full['snaps'] if s['t'] >= md and 'v' in s), None)
    for s in full['snaps']:
        if 'v' in s and s['t'] < now - 125 * 60 * 1000 and s['t'] != first_today:
            s.setdefault('tot', sum(s['v'].values())); del s['v']


MILESTONES = (1, 3, 6, 12, 24)


def track_history(full, snap, prev, now):
    """Garde ce qui permet de comparer : vues et abonnés heure par heure (15 j), courbe horaire des vidéos qui bougent (72 h),
    et les vues de chaque vidéo 1 h, 3 h, 6 h, 12 h, 24 h après sa publication (30 j)."""
    items, lt = full['items'], time.localtime(now / 1000)
    hk = time.strftime('%Y%m%d%H', lt)
    hr = full.setdefault('hourly', {}).setdefault(hk, {'g': 0})
    if prev and now - prev['t'] < 40 * 60 * 1000:     # pas de rattrapage après une coupure : ce serait faux pour cette heure
        hr['g'] += gained(snap['v'], prev, items)
    if snap.get('f'): hr['f'] = snap['f']
    cut = time.strftime('%Y%m%d%H', time.localtime(now / 1000 - 15 * 86400))
    for k in [k for k in full['hourly'] if k < cut]: del full['hourly'][k]
    # vidéos suivies heure par heure : celles qui prennent le plus de vues + celles postées depuis moins de 48 h
    mv = {}
    if prev: mv = {k: v - prev['v'].get(k, v) for k, v in snap['v'].items()}
    movers = sorted((k for k in mv if mv[k] > 0), key=lambda k: -mv[k])[:60]
    fresh = [k for k, x in items.items() if x.get('t') and now - x['t'] * 1000 < 48 * 3600 * 1000]
    vh, hb = full.setdefault('vh', {}), now // 3600000 * 3600000
    for k in set(movers) | set(fresh) | set(vh):
        if k not in snap['v']: continue
        pts = vh.setdefault(k, [])
        if pts and pts[-1][0] == hb: pts[-1][1] = snap['v'][k]
        elif k in movers or k in fresh or (pts and snap['v'][k] > pts[-1][1]): pts.append([hb, snap['v'][k]])
        vh[k] = [p for p in pts if p[0] >= hb - 72 * 3600 * 1000]
        if not vh[k]: del vh[k]
    # jalons des premières heures (relevés seulement quand on passe le jalon, pas reconstruits)
    ms = full.setdefault('ms', {})
    for k in fresh:
        age = (now - items[k]['t'] * 1000) / 3600000
        for m in MILESTONES:
            if m <= age < m + 1.5 and str(m) not in ms.get(k, {}): ms.setdefault(k, {})[str(m)] = snap['v'][k]
    old = time.time() - 30 * 86400
    for k in [k for k in ms if items.get(k, {}).get('t', 0) < old]: del ms[k]


def known_ids():
    """toutes les vidéos déjà connues, les plus récentes d'abord"""
    try: it = json.loads(FULL.read_text(encoding='utf-8'))['items']
    except Exception: return []
    return sorted(it, key=lambda k: -it[k]['t'])


def ingest(body):
    """Fusionne un relevé (vidéos + abonnés [+ studio]) dans l'historique et réécrit le fichier du dashboard."""
    items = {str(i['item_id']): i for i in body.get('items', []) if i.get('item_id')}
    if not items: raise ValueError('aucune vidéo')
    now = int(time.time() * 1000)
    with lock:
        full = json.loads(FULL.read_text(encoding='utf-8')) if FULL.exists() else {'snaps': [], 'items': {}}
        # on garde toutes les vidéos déjà vues (les relevés rapides ne renvoient que les 100 dernières)
        pub = body.get('source') == 'public'
        for k, i in items.items():
            if not int(i.get('create_time') or 0): continue
            v = int(i.get('play_count') or 0)
            if pub: v = max(v, full['items'].get(k, {}).get('v', 0))   # compteur public arrondi : ne jamais redescendre
            full['items'][k] = {'v': v, 'l': int(i.get('like_count') or 0), 'c': int(i.get('comment_count') or 0),
                                's': int(i.get('share_count') or 0), 't': int(i.get('create_time') or 0), 'd': (i.get('desc') or '')[:120],
                                'du': int(i.get('duration') or 0) // 1000}
        # direct : on suit TOUTES les vidéos du compte
        full['snaps'] = [s for s in full['snaps'] if s['t'] > now - 30 * 3600 * 1000]
        full['src'] = 'public' if pub else 'studio'
        snap = {'t': now, 'f': body.get('followers'), 'v': {k: x['v'] for k, x in full['items'].items()}}
        snap['tot'] = sum(snap['v'].values())
        ref_day = next((s for s in full['snaps'] if s['t'] >= midnight_ms(now) and 'v' in s), None)
        snap['gd'] = (gained(snap['v'], ref_day, full['items']) if ref_day else 0) + day_offset(full, now)
        prev = next((x for x in reversed(full['snaps']) if 'v' in x), None)
        full['snaps'].append(snap)
        track_history(full, snap, prev, now)
        dd = full.setdefault('daily', {}).setdefault(time.strftime('%Y%m%d', time.localtime(now / 1000)), {})
        if snap['f']: dd['f'] = snap['f']
        # likes / commentaires / partages : somme sur toutes les vidéos ; le 1er relevé du jour sert de point de départ
        it = full['items'].values()
        tot = {'l': sum(x.get('l', 0) for x in it), 'c': sum(x.get('c', 0) for x in it), 's': sum(x.get('s', 0) for x in it)}
        if 'l0' not in dd:
            prevd = full['daily'].get(time.strftime('%Y%m%d', time.localtime(now / 1000 - 86400)), {})
            # si la veille a été relevée jusqu'au bout, on part de sa fin (≈ minuit), sinon de maintenant
            src = prevd if prevd.get('lt') and now - prevd['lt'] < 30 * 60 * 1000 + (now - midnight_ms(now)) and now - midnight_ms(now) < 30 * 60 * 1000 else tot
            dd.update(l0=src.get('l', tot['l']), c0=src.get('c', tot['c']), s0=src.get('s', tot['s']), t0=now if src is tot else midnight_ms(now))
        dd.update(l=tot['l'], c=tot['c'], s=tot['s'], lt=now)
        if body.get('hearts'): dd['h'] = full['hearts'] = int(body['hearts'])
        dd['g'] = snap['gd']
        slim(full, now)
        if body.get('studio') and body['studio'].get('hist', {}).get('vv'):
            merge_studio(body['studio']); log('stats TikTok Studio complètes reçues')
        FULL.write_text(json.dumps(full, separators=(',', ':')), encoding='utf-8')
        OUT.write_text(json.dumps(build(full), ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    log(f'relevé : {len(items)} vidéos, {body.get("followers")} abonnés, {sum(full["snaps"][-1]["v"].values())} vues suivies')


up_lock = threading.Lock()


def upload():
    # un seul envoi à la fois (deux envois simultanés créent des dossiers en double sur Drive)
    with up_lock:
        r = subprocess.run([rclone(), 'copyto', str(OUT), DRIVE], capture_output=True, text=True)
        # historique partagé avec le relevé cloud (GitHub) qui prend le relais quand le PC est éteint
        for f in (FULL, STUDIO):
            if f.exists(): subprocess.run([rclone(), 'copyto', str(f), DRIVE_STATE + f.name], capture_output=True)
    err = r.stderr.strip()[-300:]
    if r.returncode != 0 and ('invalid_grant' in err or 'token' in err.lower()):
        err = "accès Google expiré : lance « rclone config reconnect gdrive: » et clique Autoriser (ou demande à Claude)"
    log('Drive', 'OK' if r.returncode == 0 else 'ERREUR ' + err)


class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', 'https://www.tiktok.com')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Private-Network', 'true')

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        if self.path.startswith('/recv'):
            # petite fenêtre ouverte par l'onglet TikTok Studio : reçoit les relevés par postMessage et les poste ici
            html = """<!doctype html><meta charset=utf-8><title>Relais direct clipfrfilm</title>
<body style="font:14px system-ui;background:#0b0b0d;color:#ededed;padding:16px">
<b>Relais « vues en direct » actif</b><p id=s>En attente du premier relevé…</p><p style="color:#85858b">Laisse cette petite fenêtre ouverte (tu peux la réduire).</p>
<script>
addEventListener('message', async e => {
  if (e.origin !== 'https://www.tiktok.com') return;
  try { const r = await fetch('/snap', {method:'POST', headers:{'Content-Type':'application/json'}, body: e.data});
        document.getElementById('s').textContent = 'Dernier relevé : ' + new Date().toLocaleTimeString() + ' (' + r.status + ')';
        e.source && e.source.postMessage('ok ' + r.status, e.origin); }
  catch (x) { document.getElementById('s').textContent = 'Erreur : ' + x; }
});
</script>"""
            self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(html.encode('utf-8')); return
        self.send_response(200); self._cors(); self.send_header('Content-Type', 'application/json'); self.end_headers()
        self.wfile.write(OUT.read_bytes() if OUT.exists() else b'{}')

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
            ingest(body)
            threading.Thread(target=upload, daemon=True).start()
            self.send_response(200); self._cors(); self.end_headers(); self.wfile.write(b'ok')
        except Exception as e:
            log('erreur', e); self.send_response(400); self._cors(); self.end_headers(); self.wfile.write(str(e).encode())

    def log_message(self, *a): pass


if __name__ == '__main__':
    log('relais démarré sur http://127.0.0.1:8766')
    import sys
    if '--sans-watch' not in sys.argv:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import tiktok_watch
        def _w():
            time.sleep(3)
            while True:
                try: tiktok_watch.loop(log=log, known=known_ids)
                except Exception as e: log('watch planté, relance dans 60 s :', e); time.sleep(60)
        threading.Thread(target=_w, daemon=True).start()
        log('relevé auto de la page TikTok publique : toutes les 5 min')
    ThreadingHTTPServer(('127.0.0.1', 8766), H).serve_forever()
