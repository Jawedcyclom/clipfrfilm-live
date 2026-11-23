"""Ce qui marche sur chaque campagne Cyclom en cours, à partir de la page PUBLIQUE de la campagne (cyclom.fr/api/campagne/<id>,
auteurs déjà anonymisés par cyclom.fr : « Clippeur 1 »…). Aucune clé, aucune donnée personnelle.

Sortie : Drive « CLIP tiktok/dashboard/cyclom_campagnes.json » (+ serveur Cyclom Stats si configuré) :
  - les clips qui cartonnent (top 12 : titre, vues, gain 24 h, date, lien)
  - ce que font les 10 meilleurs (clips par jour, vues par clip, heures de post, part de clips avec un vrai titre) contre tout le monde
  - les vues de la campagne jour par jour
Liste des campagnes en cours : celle du classement (state/cyclom_classement.json) ; sinon CYCLOM_CAMPAGNES="id1,id2".
"""
import json, os, re, statistics as S, subprocess, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import datetime

BASE = os.environ.get('CYCLOM_URL', 'https://cyclom.fr').rstrip('/')
OUT = 'state/cyclom_campagnes.json'
DRIVE = 'gdrive:CLIP tiktok/dashboard/cyclom_campagnes.json'


def lire(id_):
    req = urllib.request.Request(f'{BASE}/api/campagne/{urllib.parse.quote(id_)}', headers={'User-Agent': 'cyclom-stats-releve/1.0'})
    with urllib.request.urlopen(req, timeout=40) as r: return json.loads(r.read().decode('utf-8'))


def med(a):
    a = [x for x in a if x is not None]
    return S.median(a) if a else None


def titre_ecrit(desc):
    return bool(re.sub(r'#[\w.]+', '', desc or '').strip())


def analyser(id_, c):
    vids = c.get('videos') or []
    if not vids: return None
    for v in vids:
        lt = time.localtime(datetime.fromisoformat(v['publieLe'].replace('Z', '+00:00')).timestamp())   # heure de Paris (TZ=Europe/Paris dans le robot)
        v['_jour'], v['_h'] = time.strftime('%Y%m%d', lt), lt.tm_hour
    par = defaultdict(list)
    for v in vids: par[v.get('a') or '?'].append(v)
    auteurs = sorted(par.items(), key=lambda kv: -sum(x.get('p') or 0 for x in kv[1]))

    def profil(groupes):
        clips = [v for _, vs in groupes for v in vs]
        par_jour = [len(vs) / max(1, len({v['_jour'] for v in vs})) for _, vs in groupes]
        heures = Counter(v['_h'] for v in clips)
        tot = sum(heures.values()) or 1
        return {'auteurs': len(groupes), 'clips': len(clips),
                'clips_par_jour': round(med(par_jour) or 0, 1),
                'vues_par_clip': round(med([v.get('p') or 0 for v in clips]) or 0),
                'partages_pour_mille': round(1000 * sum(v.get('s') or 0 for v in clips) / max(1, sum(v.get('p') or 0 for v in clips)), 2),
                'titre_ecrit': round(100 * sum(titre_ecrit(v.get('description')) for v in clips) / max(1, len(clips))),
                'heures': {str(h): round(100 * n / tot) for h, n in sorted(heures.items())}}

    top = sorted(vids, key=lambda v: -(v.get('p') or 0))[:12]
    fiche = c.get('fiche') or {}
    return {'id': id_, 'nom': fiche.get('nom') or id_, 'tag': (c.get('hashtag') or '').lstrip('#'), 'fin': fiche.get('fin'), 'debut': fiche.get('debut'),
            'vues': sum(v.get('p') or 0 for v in vids), 'clips': len(vids), 'clippeurs': len(par),
            'aujourdhui': (c.get('vuesAujourdhui') or {}).get('vues'),
            'meilleurs': profil(auteurs[:10]), 'tous': profil(auteurs),
            'cartons': [{'titre': re.sub(r'\s+', ' ', v.get('description') or '').strip()[:140], 'vues': v.get('p') or 0, 'gain24': ((v.get('progression') or {}).get('24h') or {}).get('gain'),
                         'partages': v.get('s') or 0, 'publie': v.get('publieLe'), 'lien': v.get('lectureUrl'), 'img': v.get('img')} for v in top],
            'jours': [[h['t'][:10], h['vues']] for h in (c.get('historique') or [])][-400:]}


def main():
    ids = [x for x in os.environ.get('CYCLOM_CAMPAGNES', '').split(',') if x]
    if not ids and os.path.exists('state/cyclom_classement.json'):
        ids = [c['id'] for c in json.load(open('state/cyclom_classement.json', encoding='utf-8')).get('campagnes', [])]
    if not ids: print('campagnes Cyclom : aucune campagne en cours connue'); return
    out = {'maj': time.strftime('%Y-%m-%dT%H:%M:%S'), 'campagnes': []}
    for i in ids:
        try:
            r = analyser(i, lire(i))
            if r: out['campagnes'].append(r)
        except Exception as e: print('campagne', i, ':', type(e).__name__)
    os.makedirs('state', exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print(f"campagnes Cyclom : {len(out['campagnes'])} analysée(s)")
    if '--local' in sys.argv: return
    r = subprocess.run(['rclone', 'copyto', OUT, DRIVE], capture_output=True, text=True)
    print('campagnes Cyclom → Drive', 'OK' if r.returncode == 0 else 'ÉCHEC')
    srv, cle = os.environ.get('CYCLOM_SERVEUR', '').rstrip('/'), os.environ.get('CYCLOM_CLE', '')
    if srv and cle:
        try:
            urllib.request.urlopen(urllib.request.Request(srv + '/api/campagnes-info', data=json.dumps(out).encode(), method='POST',
                                                          headers={'content-type': 'application/json', 'x-cle': cle}), timeout=30).read()
        except Exception as e: print('campagnes Cyclom → serveur :', type(e).__name__)


if __name__ == '__main__':
    try: main()
    except Exception as e: print('campagnes Cyclom :', e)
