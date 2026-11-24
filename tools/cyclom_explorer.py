"""EXPLORATION UNIQUE de l'espace agence cyclom.fr (clé admin) : quels champs existent (historique, gains, paiements) ?

Écrit sur le Drive PRIVÉ « CLIP tiktok/dashboard/state/cyclom_explore.json » :
  - schema : chaque chemin de champ (ex. campagnes[].classement.vues) avec son type et combien de fois il apparaît —
    AUCUNE valeur, sauf pour les champs sans risque (statuts, dates, montants) ;
  - moi : MES lignes complètes (comptes MOI_COMPTES), campagne par campagne, terminées comprises.
Rien de personnel sur les autres clippeurs (téléphone, email, nom, pseudo) n'est écrit nulle part.
Le dépôt est PUBLIC : le journal n'affiche que des compteurs.
"""
import json, os, subprocess, sys, urllib.parse, urllib.request
from pathlib import Path

BASE = os.environ.get('CYCLOM_URL', 'https://cyclom.fr').rstrip('/')
CLE = os.environ.get('CYCLOM_ADMIN_CLE', '')
MOI = {x.strip().lower() for x in os.environ.get('MOI_COMPTES', 'clipfrfilm').split(',') if x.strip()}
SURS = ('statut', 'status', 'terminee', 'commencee', 'publiee', 'fin', 'debut', 'date', 'cree', 'maj', 'paye', 'payé', 'paiement',
        'gain', 'montant', 'prix', 'total', 'solde', 'rang', 'type', 'devise', 'methode', 'etat')


def lire(chemin):
    sep = '&' if '?' in chemin else '?'
    req = urllib.request.Request(f'{BASE}{chemin}{sep}cle={urllib.parse.quote(CLE)}', headers={'User-Agent': 'cyclom-stats-releve/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read().decode('utf-8'))
    except Exception as e:
        return {'__erreur': f'{type(e).__name__} {getattr(e, "code", "")}'.strip()}


def schema(o, chemin, S):
    if isinstance(o, dict):
        for k, v in o.items(): schema(v, f'{chemin}.{k}' if chemin else k, S)
    elif isinstance(o, list):
        for v in o[:400]: schema(v, chemin + '[]', S)
        if not o: S.setdefault(chemin + '[]', {'type': 'vide', 'n': 0})
    else:
        e = S.setdefault(chemin, {'type': type(o).__name__, 'n': 0}); e['n'] += 1
        cle = chemin.split('.')[-1].lower()
        if any(m in cle for m in SURS) and not isinstance(o, str) or (isinstance(o, str) and any(m in cle for m in SURS) and len(o) < 40):
            ex = e.setdefault('exemples', [])
            if o not in ex and len(ex) < 6: ex.append(o)


def est_moi(x):
    if not isinstance(x, dict): return False
    L = lambda v: v if isinstance(v, list) else []
    noms = [x.get('pseudo'), *L(x.get('pseudosComptes')), *L(x.get('comptes'))]
    return any(isinstance(n, str) and n.lower() in MOI for n in noms)


def main():
    if not CLE: print('exploration : pas de clé'); return
    out = {'schema': {}, 'moi': {}, 'erreurs': {}}
    z = lire('/api/central')
    if '__erreur' in z: out['erreurs']['/api/central'] = z['__erreur']
    schema(z, 'central', out['schema'])
    out['moi']['clippeur'] = [c for c in z.get('clippeurs', []) if est_moi(c)]
    # toutes les autres listes de premier niveau : mes lignes seulement
    for k, v in z.items():
        if isinstance(v, list) and k not in ('clippeurs', 'campagnes'):
            out['moi'][k] = [x for x in v if est_moi(x)]
    camps = z.get('campagnes', []) or []
    out['moi']['campagnes'] = []
    for c in camps:
        a = lire('/api/central/activite/' + urllib.parse.quote(str(c.get('id'))))
        if '__erreur' in a: out['erreurs'][str(c.get('id'))] = a['__erreur']; continue
        schema(a, 'activite', out['schema'])
        mes = [i for i in a.get('inscrits', []) if est_moi(i)]
        info = {k: c.get(k) for k in ('id', 'nom', 'hashtagCyclom', 'debut', 'fin', 'terminee', 'commencee', 'publiee', 'classement')}
        autres = {k: v for k, v in a.items() if k != 'inscrits' and not isinstance(v, (list, dict))}
        out['moi']['campagnes'].append({**info, 'activite_champs_simples': autres, 'mes_lignes': mes})
    # quelques adresses de l'espace agence à essayer (paiements / historique) : on note seulement si elles répondent
    for chemin in ('/api/central/paiements', '/api/central/historique', '/api/central/gains', '/api/central/virements', '/api/central/factures'):
        r = lire(chemin)
        out['erreurs' if '__erreur' in r else 'schema'][chemin] = r.get('__erreur') if '__erreur' in r else 'répond'
        if '__erreur' not in r:
            schema(r, chemin, out['schema'])
            out['moi'][chemin] = [x for x in (r if isinstance(r, list) else next((v for v in r.values() if isinstance(v, list)), [])) if est_moi(x)]
    Path('state').mkdir(exist_ok=True)
    Path('state/cyclom_explore.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    r = subprocess.run(['rclone', 'copyto', 'state/cyclom_explore.json', 'gdrive:CLIP tiktok/dashboard/state/cyclom_explore.json'], capture_output=True)
    print(f"exploration : {len(camps)} campagnes, {len(out['schema'])} champs, {len(out['moi']['campagnes'])} campagnes lues, "
          f"{len(out['erreurs'])} erreurs → Drive {'OK' if r.returncode == 0 else 'ÉCHEC'}")


if __name__ == '__main__':
    main()
