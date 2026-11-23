"""Alertes sur le téléphone (appli gratuite ntfy, sans compte) pour @clipfrfilm.

Chaque relevé (≈ 5 min) regarde state/clipfrfilm_live.json (+ le classement Cyclom s'il existe) et envoie au plus quelques alertes utiles :
  🚀 une vidéo décolle (top 10 % de tes vidéos au même âge, entre 1 h et 6 h)        → la décliner vite
  ⚠️ une vidéo semble bloquée (moins de 15 % des vues habituelles à cet âge)         → vérifier dans TikTok Studio
  🏁 classement : quelqu'un te passe devant / le suivant revient / fin de campagne dans 6 h
  ⏰ c'est le moment de poster (heure forte de ton public, rien posté depuis 3 h)
Jamais entre 1 h et 8 h du matin. Chaque alerte n'est envoyée qu'une fois (mémoire : Drive state/alertes.json).
Réglage : secret GitHub NTFY_TOPIC = nom de sujet long et secret (ex. clipfrfilm-8f3k2…), à suivre dans l'appli ntfy.
Lien ouvert au toucher : DASHBOARD_URL. Test local : python alertes.py --essai (affiche sans envoyer).
"""
import json, os, statistics as S, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path

TOPIC = os.environ.get('NTFY_TOPIC', '').strip()
LIEN = os.environ.get('DASHBOARD_URL', 'https://claude.ai/artifact/AsJqn1GqFWdKQqqz4X3vY6')
ST = Path('state')
MEM_DRIVE = 'gdrive:CLIP tiktok/dashboard/state/alertes.json'
JAL = ['1', '3', '6', '12', '24']


def med(a):
    a = [x for x in a if x]
    return S.median(a) if a else None


def k(n):
    n = float(n)
    return f"{n / 1e6:.2f} M".replace('.', ',') if n >= 1e6 else f"{n / 1e3:.1f} k".replace('.', ',') if n >= 1e4 else f"{int(n):,}".replace(',', ' ')


def calculer(live, cl, mem, now):
    out, items, ms = [], live.get('items', {}), live.get('ms', {})
    # vidéos récentes : décolle / bloquée (comparées à toutes tes vidéos au même âge)
    for vid, it in items.items():
        if it.get('r'): continue
        age = (now - it.get('t', 0)) / 3600
        if not (1 <= age <= 24): continue
        m = None
        for x in JAL:
            if float(x) <= age and (ms.get(vid) or {}).get(x) is not None: m = x
        val = (ms.get(vid) or {}).get(m) if m else it.get('v')
        autres = [d[m] for k_, d in ms.items() if k_ != vid and m and d.get(m)]
        if not m or len(autres) < 15 or val is None: continue
        top = round(100 * sum(1 for a in autres if a > val) / len(autres))
        if age <= 6 and top <= 10 and val >= 1000:
            out.append(('decolle:' + vid, '🚀 Ta vidéo décolle', f"Top {max(1, top)} % de tes vidéos à {m} h ({k(val)} vues). Décline ce moment maintenant : même extrait, autre accroche.", 'rocket'))
        attendu = med(autres)
        if age >= 2 and attendu and attendu >= 500 and val < attendu * .15:
            out.append(('bloquee:' + vid, '⚠️ Vidéo peut-être bloquée', f"{k(val)} vues à {m} h, d'habitude ≈ {k(attendu)}. Vérifie dans TikTok Studio ; si elle est restreinte, reposte une version modifiée.", 'warning'))
    # classement Cyclom
    for c in (cl or {}).get('campagnes', []):
        # place = ordre des vues (même règle que la page et le serveur)
        L = sorted([l for l in c.get('lignes', []) if l.get('vues')], key=lambda l: -l['vues'])
        for i_, l in enumerate(L): l['rv'] = i_ + 1
        moi = next((l for l in L if 'clipfrfilm' in [x.lower() for x in (l.get('comptes') or [])]), None)
        if not moi: continue
        prix = (c.get('prix') or {}).get('vues') or []
        avant = (mem.get('rangs') or {}).get(c['id'])
        if avant and moi['rv'] > avant:
            devant = next((l for l in L if l['rv'] == moi['rv'] - 1), None)
            perte = (prix[avant - 1] if avant <= len(prix) else 0) - (prix[moi['rv'] - 1] if moi['rv'] <= len(prix) else 0)
            out.append((f"passe:{c['id']}:{moi['rv']}:{now // 3600}", '🏁 On t’est passé devant', f"{c['nom']} : tu es maintenant {moi['rv']}e" + (f" (−{perte} €)" if perte > 0 else '') + ". Il reste du temps pour reprendre ta place.", 'checkered_flag'))
        i = L.index(moi)
        if i + 1 < len(L) and moi['vues'] and (moi['vues'] - L[i + 1]['vues']) / moi['vues'] < .1:
            out.append((f"revient:{c['id']}:{now // (6 * 3600)}", '🏁 Le suivant revient', f"{c['nom']} : le {L[i + 1]['rv']}e n’est plus qu’à {k(moi['vues'] - L[i + 1]['vues'])} vues de toi.", 'checkered_flag'))
        mem.setdefault('rangs', {})[c['id']] = moi['rv']
        if c.get('fin'):
            fin = time.mktime(time.strptime(c['fin'] + ' 23:59', '%Y-%m-%d %H:%M'))
            if 0 < fin - now <= 6 * 3600:
                out.append((f"fin:{c['id']}", '⏳ Fin de campagne dans moins de 6 h', f"{c['nom']} : tu es {moi['rv']}e. Dernière ligne droite : poste tes meilleurs extraits.", 'hourglass'))
    # moment de poster : heure forte du public, rien posté depuis 3 h (au plus une fois toutes les 4 h)
    h_now = time.localtime(now).tm_hour
    par_h = {}
    for kk, x in (live.get('hourly') or {}).items(): par_h.setdefault(int(kk[8:10]), []).append(x.get('g') or 0)
    moy = {h: sum(v) / len(v) for h, v in par_h.items() if len(v) >= 3}
    fortes = sorted(moy, key=lambda h: -moy[h])[:6] if len(moy) >= 18 else []
    dern = max((it.get('t', 0) for it in items.values()), default=0)
    if h_now in fortes and now - dern > 3 * 3600:
        out.append((f"poste:{now // (4 * 3600)}", '⏰ C’est le moment de poster', f"Ton public est le plus actif en ce moment. Dernière vidéo il y a {int((now - dern) / 3600)} h.", 'alarm_clock'))
    return out


def envoyer(titre, texte, tag):
    # titre et options dans l'adresse (encodées) : les en-têtes HTTP n'acceptent pas les emojis
    q = urllib.parse.urlencode({'title': titre, 'tags': tag, 'click': LIEN, 'priority': '4' if tag in ('rocket', 'checkered_flag') else '3'})
    urllib.request.urlopen(urllib.request.Request(f'https://ntfy.sh/{TOPIC}?{q}', data=texte.encode('utf-8'), method='POST'), timeout=20).read()


def main():
    essai = '--essai' in sys.argv
    if not TOPIC and not essai: return
    now = int(time.time())
    if 1 <= time.localtime(now).tm_hour < 8 and not essai: return   # on ne réveille personne
    live = json.loads((ST / 'clipfrfilm_live.json').read_text(encoding='utf-8'))
    cl = json.loads((ST / 'cyclom_classement.json').read_text(encoding='utf-8')) if (ST / 'cyclom_classement.json').exists() else None
    if not cl and not essai:
        subprocess.run(['rclone', 'copyto', 'gdrive:CLIP tiktok/dashboard/cyclom_classement.json', str(ST / 'cyclom_classement.json')], capture_output=True)
        if (ST / 'cyclom_classement.json').exists(): cl = json.loads((ST / 'cyclom_classement.json').read_text(encoding='utf-8'))
    if not essai: subprocess.run(['rclone', 'copyto', MEM_DRIVE, str(ST / 'alertes.json')], capture_output=True)
    mem = json.loads((ST / 'alertes.json').read_text(encoding='utf-8')) if (ST / 'alertes.json').exists() else {}
    deja = set(mem.get('envoyees', []))
    nouvelles = [a for a in calculer(live, cl, mem, now) if a[0] not in deja][:3]   # 3 alertes max par relevé
    for cle, titre, texte, tag in nouvelles:
        if essai: print('ALERTE', titre, '|', texte); continue
        try: envoyer(titre, texte, tag); deja.add(cle)
        except Exception as e: print('alerte non envoyée :', type(e).__name__)
    mem['envoyees'] = sorted(deja)[-500:]
    (ST / 'alertes.json').write_text(json.dumps(mem), encoding='utf-8')
    if not essai: subprocess.run(['rclone', 'copyto', str(ST / 'alertes.json'), MEM_DRIVE], capture_output=True)
    print(f'alertes : {len(nouvelles)} nouvelle(s)')


if __name__ == '__main__':
    try: main()
    except Exception as e: print('alertes :', e)
