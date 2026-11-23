"""Données du dashboard web, CHIFFRÉES avec le mot de passe de Jawed (secret GitHub DASH_MDP), publiées sur la branche « donnees ».

La page (GitHub Pages, dossier docs/) télécharge dash.bin, demande le mot de passe et déchiffre dans le navigateur :
sans le mot de passe, le fichier public est illisible (AES-256-GCM, clé tirée du mot de passe par PBKDF2-SHA256, 310 000 tours).
Contenu : stats @clipfrfilm (clipfrfilm_live.json), classement Cyclom (déjà sans pseudos des autres), clips qui cartonnent, couvertures HD.
Format de dash.bin (texte base64) : iv (12 octets) + données chiffrées (gzip du JSON).
"""
import base64, gzip, hashlib, json, os, subprocess, sys
from pathlib import Path

MDP = os.environ.get('DASH_MDP', '')
SEL = b'cyclom-stats-web-v1'   # fixe : la page peut garder la clé dérivée (pas le mot de passe)
TOURS = 310_000
ST = Path('state')


def lire(p, drive=None):
    if not (ST / p).exists() and drive:
        subprocess.run(['rclone', 'copyto', drive, str(ST / p)], capture_output=True)
    try: return json.loads((ST / p).read_text(encoding='utf-8'))
    except Exception: return None


def main():
    if not MDP: print('dashboard web : pas de mot de passe (secret DASH_MDP), étape sautée'); return
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    live = lire('clipfrfilm_live.json')
    if not live: print('dashboard web : pas de relevé'); return
    D = 'gdrive:CLIP tiktok/dashboard/'
    cov = lire('clipfrfilm_covers.json', D + 'clipfrfilm_covers.json') or {}
    paquet = {'v': 1, 'live': live,
              'classement': lire('cyclom_classement.json', D + 'cyclom_classement.json'),
              'campagnes': lire('cyclom_campagnes.json', D + 'cyclom_campagnes.json'),
              'covers': cov.get('c') or {}}
    brut = gzip.compress(json.dumps(paquet, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), 6)
    cle = hashlib.pbkdf2_hmac('sha256', MDP.encode('utf-8'), SEL, TOURS, 32)
    iv = os.urandom(12)
    out = base64.b64encode(iv + AESGCM(cle).encrypt(iv, brut, None)).decode()
    pub = Path('pub_donnees'); pub.mkdir(exist_ok=True)
    (pub / 'dash.bin').write_text(out)
    print(f'dashboard web : {len(out) // 1024} Ko chiffrés')
    if '--local' in sys.argv: return
    depot, jeton = os.environ.get('GITHUB_REPOSITORY'), os.environ.get('GH_TOKEN')
    cmd = ['git', '-C', str(pub)]
    for c in (['init', '-q'], ['checkout', '-q', '-B', 'donnees'], ['add', 'dash.bin'],
              ['-c', 'user.name=robot', '-c', 'user.email=robot@users.noreply.github.com', 'commit', '-qm', 'donnees chiffrées', '--allow-empty']):
        subprocess.run(cmd + c, capture_output=True)
    r = subprocess.run(cmd + ['push', '-qf', f'https://x-access-token:{jeton}@github.com/{depot}.git', 'donnees'], capture_output=True, text=True)
    if r.returncode: sys.exit('Publication chiffrée échouée')
    print('dashboard web → branche donnees', 'OK' if r.returncode == 0 else 'ÉCHEC')   # (jamais la commande : elle contient le jeton)


if __name__ == '__main__':
    try: main()
    except Exception as e: sys.exit('dashboard web : ' + type(e).__name__)
