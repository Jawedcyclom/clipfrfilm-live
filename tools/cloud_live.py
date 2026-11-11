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
INC = ['--include', 'live_full.json', '--include', 'studio_latest.json']

subprocess.run(['rclone', 'copy', REMOTE, str(ST), *INC])
known = json.loads(L.FULL.read_text(encoding='utf-8'))['items'] if L.FULL.exists() else {}

# tout le compte : page embed (nouvelles vidéos) + relecture de chaque vidéo connue
items, f, nb = W.releve(sorted(known, key=lambda k: -known[k]['t']))
print(len(items), 'vidéos relues,', f, 'abonnés,', nb, 'vidéos sur le compte,', len(known), 'connues')
if not items: sys.exit('aucune vidéo lue')
L.ingest({'items': items, 'followers': f, 'source': 'public'})
L.upload()
