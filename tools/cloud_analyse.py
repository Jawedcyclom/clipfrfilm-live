"""Analyse quotidienne du compte (cloud, PC éteint) : ce qui marche sur @clipfrfilm.
Pour chaque TikTok : fiche publique (enregistrements, labels) + titre incrusté lu sur la couverture (OCR) — en cache sur Drive.
Sorties sur Drive « CLIP tiktok/dashboard/analyse/ » : base.json (1 ligne/vidéo), insights.json (chiffres par critère), insights.md (résumé)."""
import json, os, re, subprocess, sys, time, unicodedata, urllib.request, statistics as S
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tiktok_watch as W

A = Path(os.environ.get('ANALYSE_DIR', 'analyse')); A.mkdir(exist_ok=True); (A / 'tmp').mkdir(exist_ok=True)
REMOTE = 'gdrive:CLIP tiktok/dashboard/analyse'
TES = os.environ.get('TESSERACT', 'tesseract')
TESSDATA = os.environ.get('TESSDATA')

def rc(*a): return subprocess.run(['rclone', *a], capture_output=True, text=True)

def load(name, default):
    p = A / name
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else default

# ---------- 1. données ----------
if not os.environ.get('LOCAL'):
    rc('copy', REMOTE, str(A), '--include', 'meta.json', '--include', 'ocr.json')
    rc('copyto', 'gdrive:CLIP tiktok/dashboard/clipfrfilm_live.json', str(A / 'live.json'))
live = load('live.json', {})
L, MS = live['items'], live.get('ms', {})
META, OCR = load('meta.json', {}), load('ocr.json', {})
NOW = live['updated'] / 1000

def ocr_image(path):
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert('RGB').resize((720, 1280))
    a = np.asarray(im).astype(int)
    m = (a.min(axis=2) > 205) & (a.max(axis=2) - a.min(axis=2) < 40)       # texte blanc des titres
    b = Image.fromarray(np.where(m, 0, 255).astype('uint8')); png = path.with_suffix('.png'); b.save(png)
    cmd = [TES, str(png), '-', '-l', 'fra', '--psm', '11'] + (['--tessdata-dir', TESSDATA] if TESSDATA else [])
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8'); png.unlink(missing_ok=True)
    return ' | '.join(l.strip() for l in r.stdout.splitlines() if len(l.strip()) > 2)

def fiche(vid):
    """fiche publique + OCR de la couverture (nouvelle vidéo), ou seulement la fiche (vidéo récente : enregistrements à jour)"""
    for essai in range(3):
        try:
            it = W._ssr(f'https://www.tiktok.com/@{W.ACCOUNT}/video/{vid}').get('webapp.video-detail', {}).get('itemInfo', {}).get('itemStruct')
            if not it or not it.get('id'): return vid, None, None
            v = it.get('video', {})
            keep = {'statsV2': it.get('statsV2'), 'labels': it.get('diversificationLabels'), 'desc': it.get('desc'),
                    'video': {k: v.get(k) for k in ('duration', 'width', 'height')}, 'music': (it.get('music') or {}).get('title'), 'fetched': int(time.time())}
            txt = None
            if vid not in OCR and (v.get('originCover') or v.get('cover')):
                req = urllib.request.Request(v.get('originCover') or v.get('cover'), headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.tiktok.com/'})
                p = A / 'tmp' / f'{vid}.jpg'; p.write_bytes(urllib.request.urlopen(req, timeout=30).read())
                txt = ocr_image(p); p.unlink(missing_ok=True)
            return vid, keep, txt
        except Exception: time.sleep(2 + 2 * essai)
    return vid, None, None

recent = [k for k, x in L.items() if x.get('t') and NOW - x['t'] < 7 * 86400]
todo = list(dict.fromkeys([k for k in L if k not in OCR or k not in META] + recent))
print(len(todo), 'fiches à lire (', len([k for k in L if k not in OCR]), 'nouvelles couvertures )')
with ThreadPoolExecutor(6) as ex:
    for vid, keep, txt in ex.map(fiche, todo):
        if keep: META[vid] = keep
        if txt is not None: OCR[vid] = txt

# ---------- 2. une ligne par vidéo ----------
def norm(s):
    s = unicodedata.normalize('NFKD', s.lower()).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9 ]+', ' ', s)

CAMP = [('djadelshow', 'Djadel Show S2'), ('deja', 'Djadel (#deja)'), ('mdr', 'La Maison de nos rêves'), ('redouane', 'Redouane'), ('kraken', 'Kraken')]
SUJETS = {
    'invité : Naza': ['naza'], 'invité : Gradur': ['gradur'], 'DJ Khaled / grec': ['khaled', 'grec'],
    'communautés': ['arabe', 'noir', 'blanc', 'renoi', 'rebeu', 'africain', 'algerien', 'marocain', 'tunisien', 'senegal', 'congo', 'chinois', 'asiat', 'juif', 'portugais', 'gitan', 'francais'],
    'religion': ['religion', 'musulman', 'chretien', 'islam', 'priere', 'ramadan', 'mosquee', 'eglise', 'dieu', 'allah', 'voilee', 'halal', 'judaisme', 'bouddh'],
    'famille': ['mere', 'pere', 'soeur', 'frere', 'daronne', 'daron', 'maman', 'papa', 'femme', 'mari', 'enfant', 'fils', 'fille', 'bebe', 'enceinte'],
    'public / premier rang': ['public', 'rang', 'spectat', 'la dame', 'le monsieur'],
    'argent / travail': ['pauvre', 'riche', 'argent', 'salaire', 'smic', 'caf', 'chomage', 'travail', 'patron', 'carrefour', 'chauffeur'],
    'physique / roast': ['tete', 'gros', 'moche', 'chauve', 'nez', 'dents', 'taille', 'petit', 'roast', 'detrui', 'cheveux', 'barbe', 'nain'],
    'sexe / couple': ['nude', 'sexe', 'coucher', 'meuf', 'copine', 'couple', 'mariage', 'divorce', 'tromp'],
    'police / justice': ['police', 'prison', 'flic', 'garde a vue', 'avocat', 'juge', 'cavale', 'tribunal'],
    'Mbappé': ['mbappe'],
}
PROMO = r'a partir du|saison 2|le plus fou|retourne|dans tous les sens|20 octobre|actuellement au cinema'

rows = []
for k, x in L.items():
    if not x.get('t'): continue
    m = META.get(k, {}); st = m.get('statsV2') or {}
    d = (x.get('d') or '').lower(); txt = OCR.get(k, ''); n = norm(txt)
    camp = next((nm for t, nm in CAMP if '#cyclomx' + t in d), 'autre')
    fmt = ('TOP 5' if re.search(r'\btop\s*[5s]\b', n) else 'Essaie de ne pas rire' if 'essaie' in n or 'pas rire' in n else
           'Partie' if re.search(r'\bpartie\s*\d', n) else 'POV' if re.search(r'\bpov\b', n) else
           'Duel' if 'qui est le plus' in n or 'qui s est fait' in n else 'Replay' if 'spectacle dispo' in n or 'replay' in n else 'Titre simple')
    lt = time.localtime(x['t'])
    rows.append({'id': k, 'camp': camp, 'fmt': fmt, 'titre': txt, 'v': x['v'], 'l': x.get('l', 0), 'c': x.get('c', 0), 's': x.get('s', 0),
                 'save': int(st.get('collectCount') or 0), 'du': x.get('du', 0), 't': x['t'], 'jour': time.strftime('%Y-%m-%d', lt),
                 'heure': lt.tm_hour, 'wd': lt.tm_wday, 'age_j': round((NOW - x['t']) / 86400, 1), 'r': x.get('r', 0),
                 'label': ((m.get('labels') or ['?'])[0]), 'v24': (MS.get(k) or {}).get('24'),
                 'citation': '«' in txt or '»' in txt, 'promo': bool(re.search(PROMO, n)),
                 'sujets': [s for s, kw in SUJETS.items() if any(w in n for w in kw)], 'n': n})
per_day = Counter(r['jour'] for r in rows)
seen = []
for r in sorted(rows, key=lambda r: r['t']):
    r['posts_jour'] = per_day[r['jour']]
    key = re.sub(r'\b(djadel|disponible|sur|netflix|show|spectacle|dispo|youtube)\b', '', r['n'])
    key = ' '.join(w for w in key.split() if len(w) > 2)[:90]
    r['rep'] = 0
    if len(key) > 15:
        for kk, rr in seen[-1500:]:
            if SequenceMatcher(None, key, kk).ratio() > 0.8: r['rep'] = rr['rep'] + 1; break
    seen.append((key, r))

# ---------- 3. chiffres par critère ----------
mature = [r for r in rows if r['age_j'] >= 2 and not r['r']]
def groups(key, min_n=6, rs=mature):
    g = defaultdict(list)
    for r in rs:
        ks = key(r)
        for kk in (ks if isinstance(ks, list) else [ks]): g[kk].append(r['v'])
    return sorted(({'cle': kk, 'n': len(vs), 'med': S.median(vs), 'hit10k': round(sum(v >= 1e4 for v in vs) / len(vs), 3),
                    'hit100k': round(sum(v >= 1e5 for v in vs) / len(vs), 3), 'total': sum(vs)} for kk, vs in g.items() if len(vs) >= min_n),
                  key=lambda x: -x['hit10k'])
dur = lambda r: '<30 s' if r['du'] < 30 else '30-60 s' if r['du'] < 60 else '60-90 s' if r['du'] < 90 else '90 s +'
tot = sorted((r['v'] for r in mature), reverse=True); T = sum(tot) or 1
v24 = defaultdict(list)
for r in rows:
    if r['v24'] is not None: v24[r['jour']].append(r['v24'])
ins = {
    'maj': int(time.time()), 'videos': len(rows), 'matures': len(mature),
    'concentration': {p: round(sum(tot[:max(1, int(len(tot) * p / 100))]) / T, 3) for p in (1, 5, 10)},
    'campagne': groups(lambda r: r['camp']), 'format': groups(lambda r: r['fmt'], 5),
    'format_campagne': groups(lambda r: r['camp'] + ' / ' + r['fmt'], 5),
    'citation': groups(lambda r: 'citation « »' if r['citation'] else 'sans citation'),
    'promo': groups(lambda r: 'titre promo' if r['promo'] else 'titre vanne'),
    'duree': groups(dur), 'heure': groups(lambda r: f"{r['heure']:02d}h", 5),
    'jour': groups(lambda r: 'lun mar mer jeu ven sam dim'.split()[r['wd']]),
    'reprise': groups(lambda r: ['original', '1re reprise', '2e reprise +'][min(r['rep'], 2)], 5),
    'sujet': groups(lambda r: r['sujets'] or ['(aucun)'], 5), 'label': groups(lambda r: r['label'], 5),
    'v24_par_jour': {d: {'n': len(v), 'med': S.median(v), 'hit10k': sum(x >= 1e4 for x in v)} for d, v in sorted(v24.items())},
    'top_recents': [{k: r[k] for k in ('id', 'v', 'v24', 'fmt', 'camp', 'du', 'heure', 'titre')} for r in sorted((r for r in rows if r['age_j'] < 7), key=lambda r: -r['v'])[:15]],
}
for r in rows: r.pop('n', None)
(A / 'base.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
(A / 'insights.json').write_text(json.dumps(ins, ensure_ascii=False), encoding='utf-8')
(A / 'meta.json').write_text(json.dumps(META, ensure_ascii=False), encoding='utf-8')
(A / 'ocr.json').write_text(json.dumps(OCR, ensure_ascii=False), encoding='utf-8')

def md():
    out = [f"# Analyse @clipfrfilm — {time.strftime('%d/%m/%Y %H:%M')}", f"{len(rows)} vidéos, {len(mature)} de ≥ 2 jours. "
           f"Top 1 % = {ins['concentration'][1]:.0%} des vues, top 10 % = {ins['concentration'][10]:.0%}.", '']
    for k, t in (('format', 'Format'), ('citation', 'Titre en citation'), ('promo', 'Titre promo'), ('duree', 'Durée'), ('heure', 'Heure'),
                 ('reprise', 'Reprise du même titre'), ('sujet', 'Sujet'), ('campagne', 'Campagne')):
        out.append(f'## {t} (classé par % ≥ 10 k vues)')
        out += [f"- {g['cle']} : {g['hit10k']:.0%} ≥ 10 k, {g['hit100k']:.0%} ≥ 100 k, médiane {g['med']:.0f} (n={g['n']})" for g in ins[k][:12]]
        out.append('')
    out.append('## Vues à 24 h par jour de post'); out += [f"- {d} : médiane {x['med']:.0f}, {x['hit10k']} vidéos ≥ 10 k (n={x['n']})" for d, x in ins['v24_par_jour'].items()]
    out.append(''); out.append('## Meilleures vidéos des 7 derniers jours')
    out += [f"- {r['v']} vues ({r['fmt']}, {r['du']} s, {r['heure']}h) : {r['titre'][:90]}" for r in ins['top_recents']]
    return '\n'.join(out)
(A / 'insights.md').write_text(md(), encoding='utf-8')

if not os.environ.get('LOCAL'):
    for f in ('base.json', 'insights.json', 'insights.md', 'meta.json', 'ocr.json'):
        r = rc('copyto', str(A / f), f'{REMOTE}/{f}')
        print(f, 'Drive', 'OK' if r.returncode == 0 else r.stderr[-200:])
print('analyse OK :', len(rows), 'vidéos')
