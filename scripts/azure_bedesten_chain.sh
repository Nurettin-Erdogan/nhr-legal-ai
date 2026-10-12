#!/bin/bash
# Azure Bedesten kotasını hiç boşta bırakmaz: Yargıtay (2022-2012, sonra 2009-2000; 2011-2010 PC'de bitti, PC duraklatıldı) eksikleri bitince Danıştay eksiklerine geçer,
# o da bitince başa döner (biten aylar tek istekle atlanır, yeni kararlar yakalanır). Bekçi bu betiği canlı tutar.
cd "$HOME/nhr-legal-ai" || exit 1
PY=.venv/bin/python
while true; do
  $PY -X utf8 -u scripts/collect_bedesten.py --source yargitay --known-file "$HOME/yargitay-known.tsv.gz" \
    --from-year 2022 --to-year 2012 >> data/logs/bedesten-yargitay.out.log 2>> data/logs/bedesten-yargitay.err.log < /dev/null
  # PC duraklatıldığı (kullanıcı kararı, 2026-10-12) için PC payı olan 2009-2000 de burada taranır; 2011-2010 PC'de bitti.
  $PY -X utf8 -u scripts/collect_bedesten.py --source yargitay --known-file "$HOME/yargitay-known.tsv.gz"     --from-year 2009 --to-year 2000 >> data/logs/bedesten-yargitay.out.log 2>> data/logs/bedesten-yargitay.err.log < /dev/null
  $PY -X utf8 -u scripts/collect_bedesten.py --source danistay --known-file "$HOME/danistay-known.tsv.gz" \
    --from-year 2026 --to-year 1982 >> data/logs/bedesten-danistay.out.log 2>> data/logs/bedesten-danistay.err.log < /dev/null
  sleep 30
done
