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
HIST_KEYS = ('vv', 'pv', 'like', 'comment', 'share', 'followers', 'reached', 'newv', 'returning')
lock = threading.Lock()


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


def gained(now_v, ref_v):
    """vues gagnées depuis un relevé de référence (une vidéo absente du relevé = nouvelle, compte en entier)"""
    return sum(v - ref_v.get(k, 0) for k, v in now_v.items() if v >= ref_v.get(k, 0))


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
    try:
        st = json.loads(STUDIO.read_text(encoding='utf-8'))
        if day_str(st['start'], len(st['hist']['followers']) - 1) == time.strftime('%Y%m%d', time.localtime(time.time() - 86400)):
            return f - st['hist']['followers'][-1]
    except Exception:
        pass
    return f - ref_day['f'] if ref_day and ref_day.get('f') else None


def build(full):
    # un relevé avec presque aucune vidéo (test, onglet pas prêt) fausserait toutes les vues gagnées : on l'ignore
    sn = [s for s in full['snaps'] if len(s['v']) >= 20] or full['snaps'][-1:]
    last = sn[-1]; t = last['t']; now_v = last['v']
    md = midnight_ms(t)
    day = [s for s in sn if s['t'] >= md]
    ref_day = day[0] if day else None
    # après une coupure (PC éteint) on ne compare pas à un relevé trop vieux : ça ferait un faux « +180 000 en 1 h »
    ref_h = next((s for s in reversed(sn) if t - 120 * 60 * 1000 <= s['t'] <= t - 55 * 60 * 1000), None)
    ref_30 = next((s for s in reversed(sn) if t - 60 * 60 * 1000 <= s['t'] <= t - 25 * 60 * 1000), None)
    # courbe : vues gagnées depuis minuit à chaque relevé du jour
    curve = [[s['t'], gained(s['v'], ref_day['v'])] for s in day] if ref_day else []
    hist = [[s['t'], s.get('f'), sum(s['v'].values())] for s in sn]
    ref = ref_h or ref_30 or (sn[-2] if len(sn) > 1 and t - sn[-2]['t'] <= 30 * 60 * 1000 else None)
    rising = []
    if ref:
        for k, v in now_v.items():
            g = v - ref['v'].get(k, 0)
            if g > 0: rising.append([k, g])
        rising.sort(key=lambda x: -x[1])
    return {
        'source': 'Page TikTok publique (PC)' if full.get('src') == 'public' else 'TikTok Studio (onglet Chrome du PC)', 'updated': t, 'followers': last.get('f'),
        'tracked': len(now_v), 'total': sum(now_v.values()),
        'today': {'since': ref_day['t'], 'gained': gained(now_v, ref_day['v'])} if ref_day else None,
        'hour': {'since': ref_h['t'], 'gained': gained(now_v, ref_h['v'])} if ref_h else None,
        'rising': {'since': ref['t'], 'list': rising[:15]} if ref else None,
        'followers_day': followers_day(last, ref_day),
        'curve': curve[-200:], 'hist': hist[-300:],
        'items': full['items'],
        'studio': ({k: v for k, v in json.loads(STUDIO.read_text(encoding='utf-8')).items() if k != 'days'} if STUDIO.exists() else None),
    }


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
            v = int(i.get('play_count') or 0)
            if pub: v = max(v, full['items'].get(k, {}).get('v', 0))   # compteur public arrondi : ne jamais redescendre
            full['items'][k] = {'v': v, 'l': int(i.get('like_count') or 0), 'c': int(i.get('comment_count') or 0),
                                's': int(i.get('share_count') or 0), 't': int(i.get('create_time') or 0), 'd': (i.get('desc') or '')[:120],
                                'du': int(i.get('duration') or 0) // 1000}
        # direct : on suit les 100 vidéos les plus récentes
        recent = sorted(full['items'], key=lambda k: -full['items'][k]['t'])[:100]
        full['snaps'] = [s for s in full['snaps'] if s['t'] > now - 30 * 3600 * 1000]
        full['src'] = 'public' if pub else 'studio'
        full['snaps'].append({'t': now, 'f': body.get('followers'), 'v': {k: full['items'][k]['v'] for k in recent}})
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
                try: tiktok_watch.loop(log=log)
                except Exception as e: log('watch planté, relance dans 60 s :', e); time.sleep(60)
        threading.Thread(target=_w, daemon=True).start()
        log('relevé auto de la page TikTok publique : toutes les 5 min')
    ThreadingHTTPServer(('127.0.0.1', 8766), H).serve_forever()
