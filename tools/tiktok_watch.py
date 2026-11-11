"""Relevé « direct » SANS extension : un Chrome invisible ouvre la page publique TikTok du compte
toutes les 5 min, lit les abonnés (exacts) + les vues des dernières vidéos, et les envoie au relais
(http://127.0.0.1:8766/snap). Aucune connexion TikTok nécessaire.

Limite TikTok public : au-delà de 10 000 vues, le compteur est arrondi (ex. 32 300). Le relais ne fait
jamais baisser une vidéo, donc les « vues gagnées » restent justes, juste par paliers sur les grosses vidéos.

  python tools/tiktok_watch.py           # boucle toutes les 5 min (lancé automatiquement par live_relay.py)
  python tools/tiktok_watch.py --once    # un seul relevé (test)
"""
import json, os, sys, time, urllib.request

ACCOUNT = 'clipfrfilm'
EVERY = 5 * 60
RELAY = 'http://127.0.0.1:8766/snap'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'


def grab(pw, want=60):
    items, followers = {}, None
    b = pw.chromium.launch(headless=True, channel=os.environ.get('TT_CHANNEL') or None, args=['--disable-blink-features=AutomationControlled'])
    try:
        c = b.new_context(locale='fr-FR', user_agent=UA, viewport={'width': 1280, 'height': 900})
        pg = c.new_page()

        def on(r):
            if '/api/post/item_list' in r.url:
                try:
                    for i in r.json().get('itemList') or []: items[i['id']] = i
                except Exception: pass
        pg.on('response', on)
        pg.goto(f'https://www.tiktok.com/@{ACCOUNT}', wait_until='domcontentloaded', timeout=60000)
        pg.wait_for_timeout(5000)
        try:
            d = json.loads(pg.locator('#__UNIVERSAL_DATA_FOR_REHYDRATION__').text_content(timeout=5000))
            ui = d['__DEFAULT_SCOPE__']['webapp.user-detail']['userInfo']
            followers = int((ui.get('statsV2') or ui['stats'])['followerCount'])
        except Exception: pass
        # on fait défiler doucement pour charger plus de vidéos (TikTok en donne 25 par page)
        for _ in range(12):
            if len(items) >= want: break
            n = len(items)
            pg.mouse.wheel(0, 2500); pg.wait_for_timeout(2500)
            if len(items) == n: pg.wait_for_timeout(2000)
    finally:
        b.close()
    out = []
    for i in items.values():
        st = i.get('statsV2') or i.get('stats') or {}
        out.append({'item_id': i['id'], 'play_count': int(st.get('playCount') or 0), 'like_count': int(st.get('diggCount') or 0),
                    'comment_count': int(st.get('commentCount') or 0), 'share_count': int(st.get('shareCount') or 0),
                    'create_time': int(i.get('createTime') or 0), 'desc': i.get('desc') or '',
                    'duration': int((i.get('video') or {}).get('duration') or 0) * 1000})
    return out, followers


def send(items, followers):
    body = json.dumps({'items': items, 'followers': followers, 'source': 'public'}).encode()
    req = urllib.request.Request(RELAY, data=body, headers={'Content-Type': 'application/json'})
    return urllib.request.urlopen(req, timeout=60).read().decode()


def loop(log=print, once=False):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        while True:
            t0 = time.time()
            try:
                items, f = grab(pw)
                if items: send(items, f)
                else: log('page TikTok : aucune vidéo lue (réessai au prochain tour)')
                if once: print(len(items), 'vidéos,', f, 'abonnés'); return
            except Exception as e:
                log('relevé public échoué :', e)
                if once: raise
            time.sleep(max(30, EVERY - (time.time() - t0)))


if __name__ == '__main__':
    loop(once='--once' in sys.argv)
