"""Couvertures de toutes les vidéos de CAMPAGNE (hashtag contenant « cyclom ») pour le dashboard (vignettes base64 : la page claude.ai ne peut pas charger les images TikTok).

Drive « CLIP tiktok/dashboard/ » :
- clipfrfilm_covers.json  = {"v", "maj", "c": {id: vignette HD}, "mois": {AAAASS: id du fichier Drive}}
  HD (240×427 WebP) : vidéos des 2 derniers jours, celles qui rapportent / montent, les 40 plus vues, les 8 meilleures par campagne.
- clipfrfilm_couv_AAAASS.json = {"c": {id: vignette}} : toutes les autres vidéos de la semaine (160×284 WebP, plus légères).
  Un paquet ne change que quand une vidéo de cette semaine arrive : le dashboard le garde en cache.
Une vignette déjà faite n'est jamais refaite (sauf changement de VERSION)."""
import base64, io, json, re, subprocess, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DOSSIER = 'gdrive:CLIP tiktok/dashboard'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
MAX_NOUVELLES = 450   # par relevé (le reste au relevé suivant, 5 min plus tard)
VERSION = 2


def vignette(url, taille, q):
    from PIL import Image
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': 'https://www.tiktok.com/'})
    im = Image.open(io.BytesIO(urllib.request.urlopen(req, timeout=15).read())).convert('RGB')
    im.thumbnail(taille, Image.LANCZOS)
    b = io.BytesIO(); im.save(b, 'WEBP', quality=q, method=6)
    return 'data:image/webp;base64,' + base64.b64encode(b.getvalue()).decode()


def lire(p):
    try: return json.loads(Path(p).read_text(encoding='utf-8'))
    except Exception: return {}


def maj(out_json, covers_urls, state_dir):
    st = Path(state_dir); loc = st / 'couv'; loc.mkdir(exist_ok=True)
    subprocess.run(['rclone', 'copy', DOSSIER, str(loc), '--include', 'clipfrfilm_covers.json', '--include', 'clipfrfilm_couv_*.json'], capture_output=True)
    main = lire(loc / 'clipfrfilm_covers.json')
    hd = main.get('c', {}) if main.get('v') == VERSION else {}
    paquets = {f.stem.split('_')[-1]: lire(f).get('c', {}) for f in loc.glob('clipfrfilm_couv_*.json')}
    d = json.loads(Path(out_json).read_text(encoding='utf-8'))
    now = time.time()
    # seulement les vidéos de nos campagnes : hashtag avec « cyclom » (#cyclomxdjadelshow…)
    items = d.get('items', {})
    voulu = [k for k, _ in (d.get('top_today') or {}).get('list', [])[:30]] + [k for k, _ in (d.get('rising') or {}).get('list', [])[:30]]
    voulu += sorted((k for k, v in items.items() if now - (v.get('t') or 0) < 2 * 86400), key=lambda k: -items[k].get('t', 0))
    voulu += sorted(items, key=lambda k: -items[k].get('v', 0))[:40]
    camp = {}
    for k, v in items.items():
        for t in set(re.findall(r'#(cyclomx\w+)', (v.get('d') or '').lower())): camp.setdefault(t, []).append(k)
    for ks in camp.values(): voulu += sorted(ks, key=lambda k: -items[k].get('v', 0))[:8]
    voulu = list(dict.fromkeys(voulu))[:380]
    mois = lambda k: time.strftime('%G%V', time.localtime(items[k].get('t') or (int(k) >> 32)))   # paquet par semaine (~1-2 Mo)
    deja_bas = {k for p in paquets.values() for k in p}
    a_faire = [(k, 'hd') for k in voulu if k not in hd and k in covers_urls]
    a_faire += [(k, 'bas') for k in sorted(items, key=lambda k: -items[k].get('t', 0)) if k not in deja_bas and k in covers_urls]
    a_faire = a_faire[:MAX_NOUVELLES]
    def un(x):
        k, q = x
        try: return k, q, vignette(covers_urls[k], (240, 427) if q == 'hd' else (160, 284), 64 if q == 'hd' else 55)
        except Exception: return k, q, None
    changes = set()
    with ThreadPoolExecutor(12) as ex:
        for k, q, v in ex.map(un, a_faire):
            if not v: continue
            if q == 'hd': hd[k] = v
            else: paquets.setdefault(mois(k), {})[k] = v; changes.add(mois(k))
    hd = {k: hd[k] for k in voulu if k in hd}
    for m in changes:
        f = loc / f'clipfrfilm_couv_{m}.json'
        f.write_text(json.dumps({'c': paquets[m]}, separators=(',', ':')), encoding='utf-8')
        subprocess.run(['rclone', 'copyto', str(f), f'{DOSSIER}/{f.name}'])
    # ids Drive des paquets : le dashboard les télécharge directement
    r = subprocess.run(['rclone', 'lsjson', DOSSIER, '--include', 'clipfrfilm_couv_*.json'], capture_output=True, text=True)
    try: ids = {x['Name'].split('_')[-1][:-5]: x['ID'] for x in json.loads(r.stdout or '[]') if x.get('ID')}
    except ValueError: ids = {}
    f = loc / 'clipfrfilm_covers.json'
    f.write_text(json.dumps({'v': VERSION, 'maj': int(now * 1000), 'c': hd, 'mois': ids,
                             'stamp': {**main.get('stamp', {}), **{m: int(now) for m in changes}}},
                            separators=(',', ':')), encoding='utf-8')
    subprocess.run(['rclone', 'copyto', str(f), f'{DOSSIER}/clipfrfilm_covers.json'])
    total = len(hd) + sum(len(p) for p in paquets.values())
    print(f'couvertures : {len(hd)} HD + {sum(len(p) for p in paquets.values())} autres ({total} / {len(items)} vidéos),',
          f'{len(a_faire)} faites ce relevé, paquets changés : {sorted(changes)}')
