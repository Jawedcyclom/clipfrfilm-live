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

# 1) le navigateur, pour découvrir les nouvelles vidéos (TikTok le bloque souvent depuis un serveur : pas grave)
found = []
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw: found, _ = W.grab(pw, want=25)
except Exception as e: print('navigateur :', e)
print('navigateur :', len(found), 'vidéos')
# 2) page par page : les 30 vidéos connues les plus récentes (+ celles trouvées par le navigateur)
ids = list(dict.fromkeys([i['item_id'] for i in found] + sorted(known, key=lambda k: -known[k]['t'])))[:30]
items, f, nb = W.grab_http(ids)
print(len(items), 'vidéos relues,', f, 'abonnés,', nb, 'vidéos sur le compte,', len(known), 'connues')
if not items: sys.exit('aucune vidéo lue')
L.ingest({'items': items, 'followers': f, 'source': 'public'})
L.upload()
