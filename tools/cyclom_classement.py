"""Lien permanent cyclom.fr → dashboards : classement des campagnes en cours, NETTOYÉ.

Lit l'espace agence de cyclom.fr avec la clé admin (secret GitHub CYCLOM_ADMIN_CLE, jamais écrite dans le dépôt ni dans les logs),
garde seulement pseudo / comptes / places / vues / clips / meilleure vidéo / prix (jamais téléphone, email, nom, paiement),
puis envoie :
  - Google Drive « CLIP tiktok/dashboard/cyclom_classement.json » (dashboard perso clipfrfilm Live)
  - le serveur Cyclom Stats (POST /api/classement, en-tête x-cle) si CYCLOM_SERVEUR et CYCLOM_CLE sont réglés.
Toutes les 30 min environ (cyclom.fr relève lui-même TikTok toutes les quelques heures : inutile d'aller plus vite).
Usage local de test : python cyclom_classement.py --depuis echantillon.json [--sortie x.json]
"""
import json, os, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path

BASE = os.environ.get('CYCLOM_URL', 'https://cyclom.fr').rstrip('/')
CLE = os.environ.get('CYCLOM_ADMIN_CLE', '')
DRIVE = 'gdrive:CLIP tiktok/dashboard/cyclom_classement.json'
OUT = Path('state') / 'cyclom_classement.json'


def lire(chemin):
    """GET sur l'espace agence. Les erreurs ne montrent jamais l'adresse (elle contient la clé)."""
    sep = '&' if '?' in chemin else '?'
    req = urllib.request.Request(f'{BASE}{chemin}{sep}cle={urllib.parse.quote(CLE)}', headers={'User-Agent': 'cyclom-stats-releve/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=40) as r: return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        raise RuntimeError(f'cyclom.fr {chemin.split("?")[0]} : {type(e).__name__}') from None


def nettoyer_brut():
    """Interroge cyclom.fr et renvoie le format brut compact (même format que l'échantillon de test)."""
    z = lire('/api/central')
    comptes = {p.get('pseudo'): [x for x in (p.get('pseudosComptes') or []) if isinstance(x, str)] for p in z.get('clippeurs', [])}
    out = {'maj': time.strftime('%Y-%m-%dT%H:%M:%S'), 'campagnes': []}
    for c in z.get('campagnes', []):
        if not c.get('commencee') or not c.get('publiee', True): continue
        # campagnes terminées : TOUTES gardées (historique du clippeur, Jawed 24/11) ; la page n'en montre aucune dans le Direct
        a = lire('/api/central/activite/' + urllib.parse.quote(c['id']))
        cl = c.get('classement') or {}
        out['campagnes'].append({'id': c['id'], 'nom': c.get('nom'), 'tag': c.get('hashtagCyclom'), 'fin': c.get('fin'), 'terminee': bool(c.get('terminee')),
            'prix': {'vues': cl.get('vues') or [], 'posts': cl.get('posts') or [], 'bonus': cl.get('bonus') or 0},
            'inscrits': [[i.get('pseudo'), i.get('rangVues') or 0, i.get('rangPosts') or 0, i.get('vues') or 0, i.get('clips') or 0,
                          i.get('meilleur') or 0, i.get('gain') or 0, '|'.join(comptes.get(i.get('pseudo')) or [i.get('pseudo')])]
                         for i in a.get('inscrits', []) if i.get('statut') == 'actif' and i.get('pseudo')]})
    out['soldes'] = soldes(z.get('clippeurs', []))
    return out


def soldes(clippeurs):
    """Ce que Cyclom a calculé et versé à chaque clippeur (une personne = tous ses comptes réunis).
    Seulement des NOMBRES officiels (gagné, versé, date du dernier versement, par campagne) : jamais RIB, téléphone, email, nom."""
    par = {}
    for p in clippeurs:
        comptes = [x for x in (p.get('pseudosComptes') or []) if isinstance(x, str)] or [p.get('pseudo')]
        cle = tuple(sorted({str(x).lower() for x in comptes if x}))
        if not cle: continue
        s = par.setdefault(cle, {'comptes': list(cle), 'gagne': 0.0, 'verse': 0.0, 'paye_le': None, 'campagnes': {}})
        num = lambda v: float(v) if isinstance(v, (int, float)) else 0.0
        s['gagne'] += num(p.get('duCumule', p.get('du'))); s['verse'] += num(p.get('verse'))
        if p.get('payeLe') and (not s['paye_le'] or p['payeLe'] > s['paye_le']): s['paye_le'] = p['payeLe']
        for cid, c in (p.get('campagnes') or {}).items():
            if isinstance(c, dict): s['campagnes'].setdefault(cid, {'gain': 0.0, 'verse': 0.0})['gain'] += num(c.get('gain'))
        for cid, c in (p.get('paiementsCampagnes') or {}).items():
            if isinstance(c, dict): s['campagnes'].setdefault(cid, {'gain': 0.0, 'verse': 0.0})['verse'] += num(c.get('verse'))
    out = []
    for s in par.values():
        if not (s['gagne'] or s['verse']): continue
        s['gagne'], s['verse'] = round(s['gagne'], 2), round(s['verse'], 2)
        s['campagnes'] = {k: {'gain': round(v['gain'], 2), 'verse': round(v['verse'], 2)} for k, v in s['campagnes'].items() if v['gain'] or v['verse']}
        out.append(s)
    return out


def verifier(final, prec):
    """Contrôles avant envoi : nombres valides, pas de campagne vide, pas d'effondrement suspect des vues (relevé cyclom.fr incomplet)."""
    ok = []
    anciens = {c['id']: c for c in (prec or {}).get('campagnes', [])}
    for c in final['campagnes']:
        c['lignes'] = [l for l in c['lignes'] if isinstance(l.get('vues'), int) and l['vues'] >= 0 and isinstance(l.get('clips'), int)]
        tot = sum(l['vues'] for l in c['lignes'])
        if not tot: print('classement : campagne', c['id'], 'sans vues, ignorée'); continue
        a = anciens.get(c['id'])
        if a and tot < .5 * sum(l['vues'] for l in a['lignes']):
            print('classement : campagne', c['id'], 'vues divisées par 2 depuis le dernier relevé, on garde l’ancien'); ok.append(a); continue
        ok.append(c)
    final['campagnes'] = ok
    return final


def rythmes(final, prec):
    """Vues gagnées par heure depuis le relevé précédent, par personne (même liste de comptes)."""
    if not prec: return
    dt = (time.time() - time.mktime(time.strptime(prec['maj'][:19], '%Y-%m-%dT%H:%M:%S'))) / 3600
    if not (0.3 <= dt <= 12): return
    for c in final['campagnes']:
        a = {tuple(l['comptes']): l for c2 in prec['campagnes'] if c2['id'] == c['id'] for l in c2['lignes']}
        for l in c['lignes']:
            p = a.get(tuple(l['comptes']))
            if p and l['vues'] >= p['vues']: l['vh'] = round((l['vues'] - p['vues']) / dt)


def mettre_en_forme(brut):
    """Format final : une ligne par personne (comptes secondaires réunis), triée par vues."""
    camps = []
    for c in brut['campagnes']:
        par_personne = {}
        for pseudo, rv, rp, vues, clips, meilleur, gain, comptes in c['inscrits']:
            cle = tuple(sorted(x.lower() for x in (comptes or pseudo).split('|') if x))
            ligne = {'pseudo': pseudo, 'comptes': list(cle), 'rv': rv or None, 'rp': rp or None, 'vues': vues, 'clips': clips, 'meilleur': meilleur, 'gain': gain}
            # une personne inscrite avec plusieurs comptes = ADDITION de tous ses comptes (Jawed 25/11 : « campagne ça réunit tout »)
            p = par_personne.get(cle)
            if not p: par_personne[cle] = ligne; continue
            if vues > p['vues']: p['pseudo'] = pseudo
            p['vues'] += vues; p['clips'] += clips; p['gain'] += gain; p['meilleur'] = max(p['meilleur'], meilleur)
            p['rv'] = min([x for x in (p['rv'], rv or None) if x] or [None]); p['rp'] = min([x for x in (p['rp'], rp or None) if x] or [None])
        lignes = sorted(par_personne.values(), key=lambda x: (-x['vues'], -x['clips']))
        camps.append({k: c[k] for k in ('id', 'nom', 'tag', 'fin', 'terminee', 'prix')} | {'lignes': lignes})
    return {'maj': brut['maj'], 'source': 'cyclom.fr', 'campagnes': camps, 'soldes': brut.get('soldes') or []}


def main():
    a = sys.argv[1:]
    if '--depuis' in a:
        brut = json.loads(Path(a[a.index('--depuis') + 1]).read_text(encoding='utf-8'))
    else:
        if not CLE: print('classement Cyclom : pas de clé (secret CYCLOM_ADMIN_CLE), étape sautée'); return
        if time.localtime().tm_min % 30 >= 6 and not os.environ.get('CYCLOM_FORCER'): return   # ~ toutes les 30 min
        brut = nettoyer_brut()
    final = mettre_en_forme(brut)
    prec = None
    if '--depuis' not in a:   # version complète précédente (privée, dossier state du Drive) pour le rythme et les contrôles
        subprocess.run(['rclone', 'copyto', 'gdrive:CLIP tiktok/dashboard/state/cyclom_classement_complet.json', 'state/cyclom_classement_complet.json'], capture_output=True)
        try: prec = json.loads(Path('state/cyclom_classement_complet.json').read_text(encoding='utf-8'))
        except Exception: prec = None
    final = verifier(final, prec)
    rythmes(final, prec)
    if '--depuis' not in a:
        Path('state/cyclom_classement_complet.json').write_text(json.dumps(final, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        subprocess.run(['rclone', 'copyto', 'state/cyclom_classement_complet.json', 'gdrive:CLIP tiktok/dashboard/state/cyclom_classement_complet.json'], capture_output=True)
    # le classement est PRIVÉ : vers le Drive, seuls MES comptes gardent leur pseudo ; les autres deviennent anonymes
    # (le serveur reçoit la version complète pour reconnaître chaque clippeur, et anonymise lui-même avant d'envoyer)
    moi = {x.strip().lower() for x in os.environ.get('MOI_COMPTES', 'clipfrfilm').split(',') if x.strip()}
    # sous : vers le Drive, seulement MON solde (le serveur reçoit tout et ne donne à chacun que le sien)
    prive = {**final, 'soldes': [x for x in final.get('soldes') or [] if moi & set(x['comptes'])], 'campagnes': [{**c, 'lignes': [l if moi & set(l['comptes']) else {**l, 'pseudo': None, 'comptes': []} for l in c['lignes']]} for c in final['campagnes']]}
    sortie = Path(a[a.index('--sortie') + 1]) if '--sortie' in a else OUT
    sortie.parent.mkdir(exist_ok=True); sortie.write_text(json.dumps(prive, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f"classement Cyclom : {len(final['campagnes'])} campagne(s), {len(final.get('soldes') or [])} soldes, {sum(len(c['lignes']) for c in final['campagnes'])} clippeurs")
    if '--depuis' in a: return
    r = subprocess.run(['rclone', 'copyto', str(sortie), DRIVE], capture_output=True, text=True)
    print('classement Cyclom → Drive', 'OK' if r.returncode == 0 else 'ÉCHEC')
    srv, cle_srv = os.environ.get('CYCLOM_SERVEUR', '').rstrip('/'), os.environ.get('CYCLOM_CLE', '')
    if srv and cle_srv:
        try:
            req = urllib.request.Request(srv + '/api/classement', data=json.dumps(final).encode(), method='POST',
                                         headers={'content-type': 'application/json', 'x-cle': cle_srv})
            urllib.request.urlopen(req, timeout=30).read(); print('classement Cyclom → serveur OK')
        except Exception as e: print('classement Cyclom → serveur :', type(e).__name__)


if __name__ == '__main__':
    try: main()
    except Exception as e: print('classement Cyclom :', e)   # ne casse jamais le relevé des vues
