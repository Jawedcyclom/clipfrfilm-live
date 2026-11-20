"""Couvertures des vidéos pour le dashboard (petites vignettes en base64, la page ne peut pas charger les images TikTok).

Garde sur Drive « CLIP tiktok/dashboard/clipfrfilm_covers.json » = {"maj": ms, "c": {id: "data:image/jpeg;base64,..."}}.
Vignettes gardées (600 max) : vidéos des 4 derniers jours, celles qui rapportent aujourd'hui / qui montent, les 40 plus vues
et les 8 meilleures de chaque campagne (#cyclomx…). Une vignette déjà faite n'est pas refaite."""
import base64, io, json, re, subprocess, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REMOTE = 'gdrive:CLIP tiktok/dashboard/clipfrfilm_covers.json'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
MAX_NOUVELLES = 150   # par relevé, pour tenir dans le temps du run


def vignette(url):
    from PIL import Image
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': 'https://www.tiktok.com/'})
    im = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=15).read())).convert('RGB')
    im.thumbnail((108, 192))
    b = io.BytesIO(); im.save(b, 'JPEG', quality=52, optimize=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(b.getvalue()).decode()


def maj(out_json, covers_urls, state_dir):
    """out_json : chemin de clipfrfilm_live.json (sortie du relais) ; covers_urls : {id: lien} lus pendant ce relevé."""
    loc = Path(state_dir) / 'clipfrfilm_covers.json'
    subprocess.run(['rclone', 'copyto', REMOTE, str(loc)], capture_output=True)
    try: cache = json.loads(loc.read_text(encoding='utf-8')).get('c', {})
    except Exception: cache = {}
    d = json.loads(Path(out_json).read_text(encoding='utf-8'))
    items, now = d.get('items', {}), time.time()
    voulu = [k for k, _ in (d.get('top_today') or {}).get('list', [])[:30]] + [k for k, _ in (d.get('rising') or {}).get('list', [])[:30]]
    voulu += sorted((k for k, v in items.items() if now - (v.get('t') or 0) < 4 * 86400), key=lambda k: -items[k].get('t', 0))
    voulu += sorted(items, key=lambda k: -items[k].get('v', 0))[:40]
    camp = {}
    for k, v in items.items():
        for t in set(re.findall(r'#(cyclomx\w+)', (v.get('d') or '').lower())): camp.setdefault(t, []).append(k)
    for ks in camp.values(): voulu += sorted(ks, key=lambda k: -items[k].get('v', 0))[:8]
    voulu = list(dict.fromkeys(voulu))[:600]
    a_faire = [k for k in voulu if k not in cache and k in covers_urls][:MAX_NOUVELLES]
    def un(k):
        try: return k, vignette(covers_urls[k])
        except Exception: return k, None
    with ThreadPoolExecutor(8) as ex:
        for k, v in ex.map(un, a_faire):
            if v: cache[k] = v
    garde = {k: cache[k] for k in voulu if k in cache}
    loc.write_text(json.dumps({'maj': int(now * 1000), 'c': garde}, separators=(',', ':')), encoding='utf-8')
    subprocess.run(['rclone', 'copyto', str(loc), REMOTE])
    print('couvertures :', len(garde), 'gardées,', len([k for k in a_faire if k in cache]), 'nouvelles,',
          round(loc.stat().st_size / 1e6, 2), 'Mo')
