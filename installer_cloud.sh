#!/bin/bash
# Crée le dépôt GitHub public clipfrfilm-live, met l'accès Drive dans le coffre (secret chiffré) et lance un 1er relevé.
set -e
cd "$(dirname "$0")"
GH="/c/Program Files/GitHub CLI/gh.exe"
[ -d .git ] || { git init -q -b main; git add -A; git -c user.name=Jawedcyclom -c user.email=Jawedcyclom@users.noreply.github.com commit -qm "Relevé TikTok public toutes les 5 min"; }
"$GH" repo view clipfrfilm-live >/dev/null 2>&1 || "$GH" repo create clipfrfilm-live --public --source . --push
"$GH" secret set RCLONE_CONF < "$APPDATA/rclone/rclone.conf"
"$GH" workflow run releve-live
echo "OK : dépôt créé, 1er relevé lancé."
