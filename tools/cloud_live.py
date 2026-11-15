"""Relevé « direct » dans le cloud (GitHub Actions) : marche PC éteint.
Récupère l'historique sur Drive, relit abonnés + vues des vidéos récentes (pages TikTok publiques),
recalcule et renvoie tout sur Drive (le dashboard lit CLIP tiktok/dashboard/clipfrfilm_live.json)."""
import json, os, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_relay as L, tiktok_watch as W

ST = Path('state'); ST.mkdir(exist_ok=True)
L.FULL, L.OUT, L.STUDIO, L.LOG = ST / 'live_full.json', ST / 'clipfrfilm_live.json', ST / 'studio_latest.json', ST / 'log.txt'
REMOTE = 'gdrive:CLIP tiktok/dashboard/state'
INC = ['--include', 'live_full.json', '--include', 'studio_latest.json', '--include', 'seed.json']

subprocess.run(['rclone', 'copy', REMOTE, str(ST), *INC])
# correctif ponctuel déposé sur Drive (state/seed.json) : appliqué une fois puis supprimé
SEED = ST / 'seed.json'
if SEED.exists() and L.FULL.exists():
    full, seed = json.loads(L.FULL.read_text(encoding='utf-8')), json.loads(SEED.read_text(encoding='utf-8'))
    if seed.get('restore'):   # historique écrasé (15/11, relais PC reparti à vide) : on repart de la bonne version
        R, last = seed.pop('restore'), 0
        last = max(s['t'] for s in R['snaps'])
        for x in [full] + full['snaps']:   # vidéos de l'autre compte (extension sur le mauvais compte)
            for k in L.FOREIGN & set(x.get('items' if x is full else 'v') or {}): x['items' if x is full else 'v'].pop(k)
        tot = lambda: {k: sum(x.get(k, 0) for x in R['items'].values()) for k in 'lcs'}
        t1 = tot(); R['items'].update(full['items']); t2 = tot()
        dd = R.get('daily', {}).get(time.strftime('%Y%m%d', time.localtime(last / 1000)), {})
        for k in 'lcs':   # vidéos figées relues d'un coup : pas des likes/partages du jour
            if k + '0' in dd: dd[k + '0'] += t2[k] - t1[k]
        R['hearts'] = full.get('hearts', R.get('hearts'))
        new = sorted((s for s in full['snaps'] if s['t'] > last and 'v' in s), key=lambda s: s['t'])
        # vidéo figée dans l'ancien état puis relue d'un coup (+127 k « en 4 min ») : ce n'est pas un gain du jour
        lv = next((x['v'] for x in reversed(R['snaps']) if 'v' in x), {})
        if new:
            for k, v in new[0]['v'].items():
                if k in lv and v - lv[k] > 5000:
                    for x in R['snaps']:
                        if k in x.get('v', {}): x['v'][k] += v - lv[k]
        for s in new:
            prev = next((x for x in reversed(R['snaps']) if 'v' in x), None)
            ref = next((x for x in R['snaps'] if x['t'] >= L.midnight_ms(s['t']) and 'v' in x), None)
            s['gd'] = (L.gained(s['v'], ref, R['items']) if ref else 0) + L.day_offset(R, s['t'])
            L.track_history(R, s, prev, s['t']); R['snaps'].append(s)
        for d, v in full.get('daily', {}).items():
            dd = R.setdefault('daily', {}).setdefault(d, {})
            for k in ('f', 'h'):
                if k in v: dd[k] = v[k]
        today = time.strftime('%Y%m%d', time.localtime(R['snaps'][-1]['t'] / 1000))
        R['daily'].setdefault(today, {})['g'] = R['snaps'][-1]['gd']
        full = R
    if seed.get('offset'):
        full['offset'] = seed['offset']
        md = L.midnight_ms(full['snaps'][-1]['t']) if full['snaps'] else 0
        for s in full['snaps']:
            if s['t'] >= md and s.get('gd') is not None: s['gd'] += seed['offset']['g']
    for d, v in seed.get('daily', {}).items(): full.setdefault('daily', {}).setdefault(d, {}).update(v)
    full['items'].update(seed.get('items', {}))
    if seed.get('studio'): L.merge_studio(seed['studio'])   # relevé TikTok Studio fait dans le Chrome de Jawed
    if seed.get('backfill_hourly'):   # heures passées reconstruites à partir des relevés déjà faits (cumul du jour 'gd')
        sn = sorted([x for x in full['snaps'] if x.get('gd') is not None], key=lambda x: x['t'])
        hh = full.setdefault('hourly', {})
        for a_, b_ in zip(sn, sn[1:]):
            if L.midnight_ms(a_['t']) != L.midnight_ms(b_['t']) or b_['t'] - a_['t'] > 40 * 60 * 1000: continue
            k = time.strftime('%Y%m%d%H', time.localtime(b_['t'] / 1000)); h = hh.setdefault(k, {'g': 0})
            h['g'] += max(0, b_['gd'] - a_['gd'])
            if b_.get('f'): h['f'] = b_['f']   # vidéos restreintes par TikTok : vues figées au dernier relevé Studio
    L.FULL.write_text(json.dumps(full, separators=(',', ':')), encoding='utf-8')
    subprocess.run(['rclone', 'deletefile', REMOTE + '/seed.json']); SEED.unlink()
    print('correctif appliqué :', seed)
known = json.loads(L.FULL.read_text(encoding='utf-8'))['items'] if L.FULL.exists() else {}

# tout le compte : page embed (nouvelles vidéos) + relecture de chaque vidéo connue
# + les 150 dernières via yt-dlp (repère aussi les gros lots postés d'un coup ; si TikTok bloque, on s'en passe)
extra = []
try:
    r = subprocess.run([sys.executable, '-m', 'yt_dlp', '--flat-playlist', '--playlist-end', '150', '--print', 'id',
                        f'https://www.tiktok.com/@{W.ACCOUNT}'], capture_output=True, text=True, timeout=120)
    extra = [x.strip() for x in r.stdout.split() if x.strip().isdigit()]
except Exception as e: print('yt-dlp :', e)
print('yt-dlp :', len(extra), 'vidéos listées,', len([x for x in extra if x not in known]), 'nouvelles')
items, f, nb = W.releve(list(dict.fromkeys(extra + sorted(known, key=lambda k: -known[k]['t']))))
print(len(items), 'vidéos relues,', f, 'abonnés,', nb, 'vidéos sur le compte,', len(known), 'connues')
if not items: sys.exit('aucune vidéo lue')
L.ingest({'items': items, 'followers': f, 'hearts': W.HEARTS, 'source': 'public'})
L.upload()

# analyse du compte (ce qui marche) : une fois par jour après 5h, dans le même run (pas de nouveau workflow)
try:
    if time.localtime().tm_hour >= 5:
        r = subprocess.run(['rclone', 'lsjson', 'gdrive:CLIP tiktok/dashboard/analyse/insights.json'], capture_output=True, text=True)
        info = json.loads(r.stdout or '[]')
        age = time.time() - time.mktime(time.strptime(info[0]['ModTime'][:19], '%Y-%m-%dT%H:%M:%S')) - time.timezone if info else 1e9
        if age > 20 * 3600:
            subprocess.run('sudo apt-get install -y -qq tesseract-ocr tesseract-ocr-fra > /dev/null 2>&1', shell=True, timeout=180)
            subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', 'pillow', 'numpy'], timeout=120)
            reste = 400 - (time.time() - int(os.environ.get('DEBUT', time.time())))   # le run entier doit tenir en 9 min
            if reste > 120: subprocess.run([sys.executable, str(Path(__file__).resolve().parent / 'cloud_analyse.py')], timeout=reste)
except Exception as e: print('analyse :', e)
