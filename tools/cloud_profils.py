"""Profils des clippeurs concurrents (cloud, PC éteint) : 400 dernières vidéos de chaque compte via yt-dlp (vues, likes, partages,
enregistrements, durée, date). Comptes = ceux trouvés sur les hashtags des campagnes (concurrents.json, collecté par l'extension).
Avance un peu à chaque relevé (budget de temps) ; chaque compte est rafraîchi au plus une fois toutes les 20 h.
Sortie : Drive « CLIP tiktok/dashboard/analyse/concurrents_profils.json » {'_fait': {compte: ts}, id: {...}}."""
import json, subprocess, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

A = Path('analyse'); A.mkdir(exist_ok=True)
R = 'gdrive:CLIP tiktok/dashboard/analyse'
BUDGET = float(sys.argv[1]) if len(sys.argv) > 1 else 150
t0 = time.time()
for f in ('concurrents.json', 'concurrents_profils.json'):
    subprocess.run(['rclone', 'copyto', f'{R}/{f}', str(A / f)], capture_output=True)
C = json.loads((A / 'concurrents.json').read_text(encoding='utf-8')) if (A / 'concurrents.json').exists() else {}
P = json.loads((A / 'concurrents_profils.json').read_text(encoding='utf-8')) if (A / 'concurrents_profils.json').exists() else {}
fait = P.setdefault('_fait', {})
cnt = Counter(x['a'] for x in C.values() if x.get('a') and x['a'] != 'clipfrfilm' and any(not t.startswith('compte_') for t in x.get('tags', [])))
todo = [a for a, _ in cnt.most_common(60) if time.time() - fait.get(a, 0) > 20 * 3600]
if not todo: print('profils : tout est à jour'); sys.exit(0)

def one(acc):
    if time.time() - t0 > BUDGET: return acc, None
    try:
        r = subprocess.run([sys.executable, '-m', 'yt_dlp', '--flat-playlist', '--playlist-end', '400', '-J', f'https://www.tiktok.com/@{acc}'],
                           capture_output=True, text=True, timeout=max(20, BUDGET - (time.time() - t0)))
        return acc, json.loads(r.stdout[r.stdout.index('{'):]).get('entries') or []
    except Exception: return acc, None

n = 0
with ThreadPoolExecutor(4) as ex:
    for acc, es in ex.map(one, todo):
        if es is None: continue
        fait[acc] = int(time.time())
        for e in es:
            if not isinstance(e, dict) or not e.get('id'): continue
            P[e['id']] = {'a': acc, 'd': (e.get('description') or e.get('title') or '')[:150], 't': e.get('timestamp') or 0,
                          'v': e.get('view_count') or 0, 'l': e.get('like_count') or 0, 's': e.get('repost_count') or 0,
                          'sv': e.get('save_count') or 0, 'c': e.get('comment_count') or 0, 'du': e.get('duration'), 'vu': int(time.time())}
            n += 1
(A / 'concurrents_profils.json').write_text(json.dumps(P, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
r = subprocess.run(['rclone', 'copyto', str(A / 'concurrents_profils.json'), f'{R}/concurrents_profils.json'], capture_output=True, text=True)
print(f"profils : {n} vidéos de {sum(1 for a in todo if a in fait and time.time() - fait[a] < 600)} comptes ; total {len(P) - 1} ; reste {sum(1 for a in todo if time.time() - fait.get(a, 0) > 20 * 3600)} comptes ; Drive",
      'OK' if r.returncode == 0 else r.stderr[-200:])
