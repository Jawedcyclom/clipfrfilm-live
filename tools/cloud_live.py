"""Relevé « direct » dans le cloud (GitHub Actions) : marche PC éteint.
Récupère l'historique sur Drive, lit la page TikTok publique, recalcule, renvoie tout sur Drive."""
import os, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import live_relay as L, tiktok_watch as W
from playwright.sync_api import sync_playwright

ST = Path('state'); ST.mkdir(exist_ok=True)
L.FULL, L.OUT, L.STUDIO, L.LOG = ST / 'live_full.json', ST / 'clipfrfilm_live.json', ST / 'studio_latest.json', ST / 'log.txt'
REMOTE = 'gdrive:CLIP tiktok/dashboard/state'

subprocess.run(['rclone', 'copy', REMOTE, str(ST), '--include', 'live_full.json', '--include', 'studio_latest.json'])
with sync_playwright() as pw:
    items, f = W.grab(pw)
print(len(items), 'vidéos,', f, 'abonnés')
if not items: sys.exit('TikTok n\'a renvoyé aucune vidéo')
L.ingest({'items': items, 'followers': f, 'source': 'public'})
L.upload()
subprocess.run(['rclone', 'copy', str(ST), REMOTE, '--include', 'live_full.json', '--include', 'studio_latest.json'], check=True)
