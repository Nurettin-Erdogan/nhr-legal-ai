#!/bin/bash
# Azure bekcisi: collect_bedesten (yalniz yargitay), collect_emsal (<=2022), worker.verify_loop
# Kanal paylasimi: Azure=Yargitay, PC=Danistay+Emsal(yeni aylar). Her makinenin kendi IP'si kendi
# Bedesten sirasini (reserve_slot) kullandigindan her kanal ~700/sa alir.
# olduren surecleri 5 dk'da bir kontrol edip yeniden baslatir. PC'deki
# overnight_watchdog.ps1 ile ayni amaca hizmet eder, Azure/Linux tarafi icin.
cd ~/nhr-legal-ai || exit 1
LOG=data/logs/azure-watchdog.log
mkdir -p data/logs
log() { echo "$(date -Iseconds) $1" >> "$LOG"; }
log "bekci basladi"
while true; do
  if ! pgrep -f "collect_bedesten.py --source yargitay" > /dev/null; then
    log "bedesten-yargitay yoktu, baslatiliyor"
    nohup .venv/bin/python -X utf8 -u scripts/collect_bedesten.py --source yargitay > data/logs/bedesten-yargitay.out.log 2> data/logs/bedesten-yargitay.err.log < /dev/null &
    disown
  fi
  if ! pgrep -f "collect_emsal.py" > /dev/null; then
    log "emsal yoktu, baslatiliyor"
    nohup .venv/bin/python -X utf8 -u scripts/collect_emsal.py --delay 3.0 --cooldown 300 --to 2022-12-31 > data/logs/emsal.out.log 2> data/logs/emsal.err.log < /dev/null &
    disown
  fi
  if ! pgrep -f "worker.verify_loop" > /dev/null; then
    log "verify_loop yoktu, baslatiliyor"
    nohup .venv/bin/python -u -m worker.verify_loop > data/logs/verify_loop.out.log 2> data/logs/verify_loop.err.log < /dev/null &
    disown
  fi
  if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q nhr-legal-ai-db; then
    log "docker/db yok, docker compose up deneniyor"
    docker compose up -d db 2>>"$LOG"
  fi
  sleep 300
done
