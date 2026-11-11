"""Relevé « direct » dans le cloud (GitHub Actions) : marche PC éteint.
Récupère l'historique sur Drive, relit abonnés + vues des vidéos récentes (pages TikTok publiques),
recalcule et renvoie tout sur Drive (le dashboard lit CLIP tiktok/dashboard/clipfrfilm_live.json)."""
import json, subprocess, sys
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
    if seed.get('offset'):
        full['offset'] = seed['offset']
        md = L.midnight_ms(full['snaps'][-1]['t']) if full['snaps'] else 0
        for s in full['snaps']:
            if s['t'] >= md and s.get('gd') is not None: s['gd'] += seed['offset']['g']
    for d, v in seed.get('daily', {}).items(): full.setdefault('daily', {}).setdefault(d, {}).update(v)
    for k in [k for k, v in full['items'].items() if not v.get('t')]: del full['items'][k]
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
L.ingest({'items': items, 'followers': f, 'source': 'public'})
L.upload()
