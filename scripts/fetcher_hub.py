"""PC (ana veritabanı) tarafı: çekici düğümlere (AWS, Azure) iş gönderir, sonuçları alır ve seed'leri doğrular.

PC portala hiç istek atmaz. Her çağrıda (Görev Zamanlayıcı günde bir `run`):
  1. collect: düğümlerdeki biten sonuç parçalarını (out/*.jsonl.gz) scp ile alır, düğümden siler.
  2. apply  : her sonucu ilgili seed ile `verify_seeds.compare_texts` kuralıyla karşılaştırır:
              eşleşen → resmî (ready) + resmî metin; harf/rakam farkı → korpustan çıkarılır (deleted_at);
              portalda yok → verify_status=unavailable; ağ hatası → atıf kuyruğuna (sonra yeniden).
  3. dispatch: düğümdeki bekleyen işi 8 dosyaya (8 x 5000 kimlik, ~2,5 günlük) tamamlar. Öncelik: atıf kuyruğu
              (seed_verification_queue: asistanın atıf yaptığı seed'ler), sonra en yeniden eskiye. Seed daire etiketleri
              güvenilmez (570 bin "Büyük Genel Kurulu" yanlış etiketi), bu yüzden daireye göre öncelik verilmez.
              İmleç data/campaign/fetcher-hub.json.

  python scripts/fetcher_hub.py run
  python scripts/fetcher_hub.py status
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
load_dotenv(ROOT / ".env")

NODES = {
    # Emsal şeridi yalnız aws2 ve aws3'te (kullanıcı 2026-10-16: "Emsal'i 2 sunucuyla çekelim"; aws ve azure IP'leri CAPTCHA'ya en çok takılanlar).
    "aws": {"host": "ubuntu@16.170.253.173", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "azure": {"host": "nhr@20.91.186.253", "key": None, "dir": "fetcher"},
    # azure2/azure3 (2026-10-17): Azure for Students bölge kotası 6 vCPU; yalnız Yargıtay/Danıştay.
    "azure2": {"host": "nhr@4.223.86.140", "key": None, "dir": "fetcher"},
    "azure3": {"host": "nhr@20.240.91.189", "key": None, "dir": "fetcher"},
    # azure4-azure6: BAE Kuzey (uaenorth; Students politikası yalnız 5 bölgeye izin veriyor, diğerlerinde B2ts_v2 kapasite yok); yalnız Yargıtay/Danıştay.
    "azure4": {"host": "nhr@20.74.232.206", "key": None, "dir": "fetcher", "lanes": ("bedesten",)},
    "azure5": {"host": "nhr@40.123.217.211", "key": None, "dir": "fetcher", "lanes": ("bedesten",)},
    "azure6": {"host": "nhr@20.196.2.219", "key": None, "dir": "fetcher", "lanes": ("bedesten",)},
    # İkinci AWS sunucusu (2026-10-16, PC'nin yerine; makine sayısı artmadı): aynı hesap/anahtar, farklı IP.
    "aws2": {"host": "ubuntu@16.170.226.173", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    # Dördüncü sunucu (2026-10-16, kullanıcı: "bir sunucu daha açayım"); Azure 22 Ekim civarı kapanınca yerine yenisi AÇILMAZ (3'e iner).
    "aws3": {"host": "ubuntu@56.228.29.154", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    # aws4-aws7 yalnız Yargıtay/Danıştay (2026-10-16, kullanıcı: "2-3 sunucu daha, onlar sadece Yargıtay/Danıştay çeksin").
    "aws4": {"host": "ubuntu@13.53.69.118", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws5": {"host": "ubuntu@13.61.9.191", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws6": {"host": "ubuntu@16.171.42.20", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws7": {"host": "ubuntu@13.53.41.188", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    # aws8-aws19 yalnız Yargıtay/Danıştay (2026-10-17, kullanıcı: toplam 20 sunucu; Emsal yalnız aws2/aws3).
    "aws8": {"host": "ubuntu@13.48.46.100", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws9": {"host": "ubuntu@13.60.63.116", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws10": {"host": "ubuntu@13.61.173.65", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws11": {"host": "ubuntu@56.228.35.44", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws12": {"host": "ubuntu@16.171.193.27", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws13": {"host": "ubuntu@16.171.165.80", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws14": {"host": "ubuntu@16.171.132.24", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws15": {"host": "ubuntu@51.21.180.168", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws16": {"host": "ubuntu@16.171.195.3", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws17": {"host": "ubuntu@13.51.201.139", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws18": {"host": "ubuntu@51.20.6.240", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws19": {"host": "ubuntu@13.63.237.229", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    # aws20-aws30 yalnız Yargıtay/Danıştay (2026-10-17, kullanıcı: 10 sunucu daha; aws20 önceki turdan kalan tek sunucu).
    "aws20": {"host": "ubuntu@16.171.208.208", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws21": {"host": "ubuntu@13.60.20.192", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws22": {"host": "ubuntu@13.60.249.128", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws23": {"host": "ubuntu@16.192.78.188", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws24": {"host": "ubuntu@13.62.105.113", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws25": {"host": "ubuntu@51.21.195.191", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws26": {"host": "ubuntu@13.48.193.17", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws27": {"host": "ubuntu@13.51.197.133", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws28": {"host": "ubuntu@13.60.221.4", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws29": {"host": "ubuntu@16.171.40.27", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "aws30": {"host": "ubuntu@13.53.212.232", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    # aws31-aws38: ikinci AWS hesabı (nhr-bm-aws1-8), anahtar jurisai-aws.pem; yalnız Yargıtay/Danıştay (2026-10-18).
    "aws31": {"host": "ubuntu@51.20.3.50", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "aws32": {"host": "ubuntu@16.171.21.85", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "aws33": {"host": "ubuntu@16.171.171.239", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "aws34": {"host": "ubuntu@13.60.29.138", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "aws35": {"host": "ubuntu@13.53.174.254", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "aws36": {"host": "ubuntu@51.20.54.167", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "aws37": {"host": "ubuntu@16.171.175.34", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "aws38": {"host": "ubuntu@16.170.224.128", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    # n31-n50: birinci AWS hesabında nhr-aws31..nhr-aws50 (2026-10-18); yalnız Yargıtay/Danıştay. (Ad çakışmasın diye 'n' öneki.)
    "n31": {"host": "ubuntu@13.60.87.239", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n32": {"host": "ubuntu@13.62.102.43", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n33": {"host": "ubuntu@16.171.26.221", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n34": {"host": "ubuntu@16.171.38.198", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n35": {"host": "ubuntu@51.20.193.7", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n36": {"host": "ubuntu@13.60.13.154", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n37": {"host": "ubuntu@16.171.17.218", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n38": {"host": "ubuntu@13.62.102.78", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n39": {"host": "ubuntu@13.60.167.90", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n40": {"host": "ubuntu@13.60.87.70", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n41": {"host": "ubuntu@13.60.236.2", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n42": {"host": "ubuntu@13.60.255.165", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n43": {"host": "ubuntu@13.62.103.42", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n44": {"host": "ubuntu@13.51.160.80", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n45": {"host": "ubuntu@13.53.101.133", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n46": {"host": "ubuntu@16.171.140.135", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n47": {"host": "ubuntu@56.228.28.194", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n48": {"host": "ubuntu@13.63.237.213", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n49": {"host": "ubuntu@13.60.233.38", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n50": {"host": "ubuntu@13.48.27.146", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    # n51-n60: nhr-aws51..60 (2026-10-19, birinci hesap 100 sunucuya tamamlandı); Yargıtay/Danıştay + Emsal.
    "n51": {"host": "ubuntu@13.60.22.198", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n52": {"host": "ubuntu@51.20.191.222", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n53": {"host": "ubuntu@51.20.31.199", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n54": {"host": "ubuntu@51.20.53.201", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n55": {"host": "ubuntu@16.171.41.172", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n56": {"host": "ubuntu@16.170.232.96", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n57": {"host": "ubuntu@13.60.247.202", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n58": {"host": "ubuntu@51.21.200.69", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n59": {"host": "ubuntu@13.61.8.88", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "n60": {"host": "ubuntu@16.171.160.34", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    # b9-b50: ikinci AWS hesabı (Building Momentum) nhr-bm-aws9..50 (2026-10-19), anahtar jurisai-aws.pem; Yargıtay/Danıştay + Emsal.
    "b9": {"host": "ubuntu@16.171.5.89", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b10": {"host": "ubuntu@51.21.169.79", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b11": {"host": "ubuntu@13.48.59.185", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b12": {"host": "ubuntu@13.60.20.235", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b13": {"host": "ubuntu@16.171.4.85", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b14": {"host": "ubuntu@13.60.249.138", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b15": {"host": "ubuntu@13.60.248.228", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b16": {"host": "ubuntu@51.20.64.107", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b17": {"host": "ubuntu@51.20.193.180", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b18": {"host": "ubuntu@13.49.244.210", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b19": {"host": "ubuntu@13.60.84.126", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b20": {"host": "ubuntu@56.228.35.147", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b21": {"host": "ubuntu@13.48.25.26", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b22": {"host": "ubuntu@13.49.230.35", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b23": {"host": "ubuntu@13.49.230.91", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b24": {"host": "ubuntu@13.60.28.79", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b25": {"host": "ubuntu@13.48.147.119", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b26": {"host": "ubuntu@16.171.147.64", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b27": {"host": "ubuntu@13.60.229.5", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b28": {"host": "ubuntu@13.60.40.63", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b29": {"host": "ubuntu@13.53.99.130", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b30": {"host": "ubuntu@13.61.33.209", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b31": {"host": "ubuntu@56.228.35.31", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b32": {"host": "ubuntu@51.21.192.178", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b33": {"host": "ubuntu@13.60.82.253", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b34": {"host": "ubuntu@13.60.233.31", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b35": {"host": "ubuntu@16.171.44.182", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b36": {"host": "ubuntu@16.171.198.129", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b37": {"host": "ubuntu@13.49.68.66", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b38": {"host": "ubuntu@13.60.74.212", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b39": {"host": "ubuntu@16.170.201.226", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b40": {"host": "ubuntu@13.48.147.129", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b41": {"host": "ubuntu@13.49.238.181", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b42": {"host": "ubuntu@13.60.28.117", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b43": {"host": "ubuntu@13.60.34.188", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b44": {"host": "ubuntu@51.20.7.179", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b45": {"host": "ubuntu@16.171.30.255", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b46": {"host": "ubuntu@13.62.103.74", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b47": {"host": "ubuntu@13.61.24.156", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b48": {"host": "ubuntu@51.21.197.30", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b49": {"host": "ubuntu@51.20.2.235", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "b50": {"host": "ubuntu@51.20.9.103", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm51": {"host": "ubuntu@16.171.32.110", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm52": {"host": "ubuntu@13.60.66.207", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm53": {"host": "ubuntu@13.53.174.155", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm54": {"host": "ubuntu@51.21.199.197", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm55": {"host": "ubuntu@13.61.176.241", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm56": {"host": "ubuntu@13.51.163.141", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm57": {"host": "ubuntu@16.171.33.36", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm58": {"host": "ubuntu@51.21.170.55", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm59": {"host": "ubuntu@51.20.18.128", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm60": {"host": "ubuntu@16.171.148.244", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm61": {"host": "ubuntu@51.20.54.58", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm62": {"host": "ubuntu@13.49.243.206", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm63": {"host": "ubuntu@13.60.187.142", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm64": {"host": "ubuntu@16.192.93.128", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm65": {"host": "ubuntu@13.61.104.27", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm66": {"host": "ubuntu@16.171.198.149", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm67": {"host": "ubuntu@13.60.163.46", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm68": {"host": "ubuntu@13.49.44.133", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm69": {"host": "ubuntu@56.228.31.167", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm70": {"host": "ubuntu@16.170.225.206", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm71": {"host": "ubuntu@13.60.20.165", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm72": {"host": "ubuntu@13.60.214.19", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm73": {"host": "ubuntu@16.171.155.215", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm74": {"host": "ubuntu@51.20.191.194", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm75": {"host": "ubuntu@13.60.82.200", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm76": {"host": "ubuntu@13.51.72.159", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm77": {"host": "ubuntu@13.51.70.19", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm78": {"host": "ubuntu@16.171.226.129", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm79": {"host": "ubuntu@13.48.147.199", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm80": {"host": "ubuntu@13.60.47.98", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm81": {"host": "ubuntu@13.61.21.93", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm82": {"host": "ubuntu@16.170.201.254", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm83": {"host": "ubuntu@13.60.80.245", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm84": {"host": "ubuntu@16.170.215.205", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm85": {"host": "ubuntu@51.20.54.10", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm86": {"host": "ubuntu@16.192.94.249", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm87": {"host": "ubuntu@16.171.150.246", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm88": {"host": "ubuntu@16.171.153.1", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm89": {"host": "ubuntu@16.171.25.90", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm90": {"host": "ubuntu@16.192.77.206", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm91": {"host": "ubuntu@51.21.196.96", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm92": {"host": "ubuntu@16.170.242.148", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm93": {"host": "ubuntu@16.171.23.78", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm94": {"host": "ubuntu@13.48.249.236", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm95": {"host": "ubuntu@16.170.228.95", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm96": {"host": "ubuntu@13.60.230.157", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm97": {"host": "ubuntu@51.21.161.173", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm98": {"host": "ubuntu@16.171.17.132", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm99": {"host": "ubuntu@13.60.77.26", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    "bm100": {"host": "ubuntu@13.60.94.45", "key": str(Path.home() / ".ssh" / "id_rsa"), "dir": "fetcher"},
    # m11-m50: eski embedding sunucuları t3.micro'ya küçültülüp çekiciye çevrildi (2026-10-19); Yargıtay/Danıştay + Emsal.
    "m11": {"host": "ubuntu@13.48.13.190", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m12": {"host": "ubuntu@13.48.178.234", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m13": {"host": "ubuntu@16.171.225.38", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m14": {"host": "ubuntu@51.20.119.169", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m15": {"host": "ubuntu@13.49.64.108", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m16": {"host": "ubuntu@51.21.252.232", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m17": {"host": "ubuntu@51.20.69.48", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m18": {"host": "ubuntu@56.228.10.188", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m19": {"host": "ubuntu@13.61.155.12", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m20": {"host": "ubuntu@51.20.63.70", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m21": {"host": "ubuntu@13.48.177.141", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m22": {"host": "ubuntu@13.62.18.2", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m23": {"host": "ubuntu@13.61.152.196", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m24": {"host": "ubuntu@16.170.140.75", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m25": {"host": "ubuntu@16.171.112.63", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m26": {"host": "ubuntu@13.61.143.212", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m27": {"host": "ubuntu@13.60.75.96", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m28": {"host": "ubuntu@16.16.28.87", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m29": {"host": "ubuntu@51.20.130.193", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m30": {"host": "ubuntu@16.171.236.229", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m31": {"host": "ubuntu@51.20.81.181", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m32": {"host": "ubuntu@13.61.17.36", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m33": {"host": "ubuntu@51.20.105.157", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m34": {"host": "ubuntu@13.51.108.235", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m35": {"host": "ubuntu@13.50.16.207", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m36": {"host": "ubuntu@56.228.2.27", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m37": {"host": "ubuntu@13.62.222.142", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m38": {"host": "ubuntu@13.53.122.255", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m39": {"host": "ubuntu@16.170.141.32", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m40": {"host": "ubuntu@13.48.177.19", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m41": {"host": "ubuntu@13.61.144.172", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m42": {"host": "ubuntu@16.171.58.137", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m43": {"host": "ubuntu@13.53.160.38", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m44": {"host": "ubuntu@56.228.14.105", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m45": {"host": "ubuntu@51.20.107.89", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m46": {"host": "ubuntu@51.20.249.29", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m47": {"host": "ubuntu@51.20.70.40", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m48": {"host": "ubuntu@13.61.146.103", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m49": {"host": "ubuntu@13.62.19.197", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
    "m50": {"host": "ubuntu@51.20.253.114", "key": str(Path.home() / ".ssh" / "nhr-aws.pem"), "dir": "fetcher"},
}

# Üçüncü AWS hesabı (nhr-sl-aws1-150, 2026-10-23): düğümler `data/campaign/extra-nodes.json` içinde ({ad: {"host", "key", "dir"}}).
_EXTRA = Path(__file__).resolve().parents[1] / "data" / "campaign" / "extra-nodes.json"
if _EXTRA.exists():
    try:
        NODES.update(json.loads(_EXTRA.read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
# Daytona sandbox'ı (kullanıcı 2026-10-16: "PC'yi bırakırız olmazsa bunu da ekle"): API anahtarı .env'de DAYTONA_API_KEY varsa eklenir.
# KAPALI: Daytona ücretsiz seviyesi portallara çıkışa izin vermiyor (Tier 3+ gerekir, ölçüldü 2026-10-16); FETCHER_USE_DAYTONA=1 ile açılır.
if os.getenv("DAYTONA_API_KEY") and os.getenv("FETCHER_USE_DAYTONA") == "1":
    NODES["daytona"] = {"host": None, "key": None, "dir": "fetcher", "kind": "daytona"}
# PC günde bir kez çalışır (kullanıcı 2026-10-14): düğümde ~2,5 günlük iş (8 x 5000; düğüm ~16 bin/gün) hazır tutulur ki
# PC bir gün çalışmasa bile düğüm boş kalmasın.
STATE = ROOT / "data" / "campaign" / "fetcher-hub.json"
INBOX = ROOT / "data" / "fetcher" / "inbox"
APPLIED = ROOT / "data" / "fetcher" / "applied"
LOG = ROOT / "data" / "logs" / "fetcher-hub.log"

_SEED = """
  AND ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending' AND ls.is_current
  AND ls.deleted_at IS NULL AND ls.source_type = 'court_decision'
  AND ls.metadata->>'verify_status' IS NULL
  AND (ls.external_id LIKE 'yargitay:%%' OR ls.external_id LIKE 'danistay:%%')
"""
_SELECT = """
SELECT ls.id, ls.external_id, d.decision_date
FROM court_decision_details d JOIN legal_sources ls ON ls.id = d.legal_source_id
WHERE d.decision_date IS NOT NULL
  AND (%(cdate)s::date IS NULL OR (d.decision_date, d.legal_source_id) < (%(cdate)s::date, %(cid)s::uuid))
""" + _SEED + """
ORDER BY d.decision_date DESC, d.legal_source_id DESC
LIMIT %(n)s
"""
_QUEUE = """
SELECT ls.id, ls.external_id
FROM seed_verification_queue q JOIN legal_sources ls ON ls.id = q.legal_source_id
WHERE q.picked_at IS NULL
""" + _SEED + """
ORDER BY q.request_count DESC, q.requested_at
LIMIT %(n)s
"""
_SEED_EMSAL = """
  AND ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending' AND ls.is_current
  AND ls.deleted_at IS NULL AND ls.source_type = 'court_decision'
  AND ls.metadata->>'verify_status' IS NULL
  AND ls.external_id LIKE 'emsal:%%'
"""
# Emsal şeridi EN ESKİDEN yeniye gider: PC'deki `verify_seeds.py --source emsal` en yeniden eskiye gittiği için ikisi
# aynı kaydı çekmez, ortada buluşur (çakışan az sayıda kayıt işlemede zaten doğrulanmış olarak atlanır).
_SELECT_EMSAL = """
SELECT ls.id, ls.external_id, d.decision_date
FROM court_decision_details d JOIN legal_sources ls ON ls.id = d.legal_source_id
WHERE d.decision_date IS NOT NULL
  AND (%(cdate)s::date IS NULL OR (d.decision_date, d.legal_source_id) > (%(cdate)s::date, %(cid)s::uuid))
""" + _SEED_EMSAL + """
ORDER BY d.decision_date ASC, d.legal_source_id ASC
LIMIT %(n)s
"""
LANES = {
    # şerit: (düğümdeki iş dizini, iş boyutu, düğümde tutulacak iş sayısı)
    # ~6 günlük iş: PC birkaç gün açılmasa bile sunucular boş kalmaz (kullanıcı 2026-10-15: "hiçbir zaman boşta kalmasın").
    "bedesten": ("jobs", 5000, 20),
    "emsal": ("jobs-emsal", 1500, 4),  # 2026-10-18: 61 sunucu x ~95/sa; sunucuda 4 iş (~63 saat) yeter, imleç boşa ilerlemesin
}
_PICKED = "UPDATE seed_verification_queue SET picked_at = NOW() WHERE legal_source_id = ANY(%s)"
_ROW = """
SELECT ls.id, ls.raw_text FROM legal_sources ls
WHERE ls.external_id = %s AND ls.source_type = 'court_decision' AND ls.is_current AND ls.deleted_at IS NULL
  AND ls.ingestion_method = 'bulk_seed' AND ls.ingest_status = 'pending'
"""
_REQUEUE = """
INSERT INTO seed_verification_queue (legal_source_id, request_count) VALUES (%s, 1)
ON CONFLICT (legal_source_id) DO UPDATE SET picked_at = NULL
"""


def _log(message: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _ssh_args(node: dict) -> list[str]:
    # ServerAlive: Azure'da oturumun bağlandıktan sonra asılı kaldığı görüldü (2026-10-14); 30 sn yanıtsızsa kopar.
    args = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3",
            "-o", "StrictHostKeyChecking=accept-new"]  # yeniden başlatılan düğümlerin yeni IP'leri ilk bağlantıda kabul edilir
    if node["key"]:
        args += ["-i", node["key"]]
    return args


def ssh(node: dict, command: str, timeout: int = 120) -> str:
    # stdin=DEVNULL: Start-Process ile başlatılan hub'da ssh'lar ortak konsol girdisini okumaya çalışıp topluca takılıyordu (2026-10-23).
    result = subprocess.run(["ssh", *_ssh_args(node), node["host"], command], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=timeout, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"ssh {node['host']}: {result.stderr.strip()[:200]}")
    return result.stdout


def scp(node: dict, source: str, target: str, timeout: int = 600) -> None:
    result = subprocess.run(["scp", "-q", *_ssh_args(node), source, target], stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=timeout, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"scp {source} → {target}: {result.stderr.strip()[:200]}")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# -- collect -------------------------------------------------------------------------------------
def _collect_local(name: str, node: dict) -> int:
    out = Path(node["dir"]) / "out"
    target = INBOX / name
    target.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in sorted(out.glob("*.jsonl.gz")) if out.exists() else []:
        os.replace(path, target / path.name)
        moved += 1
    return moved


def _collect_daytona(name: str, node: dict) -> int:
    import fetcher_daytona as fd

    fd.ensure_running()
    sandbox = fd.get_sandbox()
    target = INBOX / name
    target.mkdir(parents=True, exist_ok=True)
    got = []
    for fname in fd.ls(sandbox, "out"):
        fd.get(sandbox, "out", fname, str(target / fname) + ".part")
        os.replace(str(target / fname) + ".part", target / fname)
        got.append(fname)
    if got:
        fd.rm(sandbox, "out", got)
    return len(got)


def collect(name: str, node: dict) -> int:
    """Biten parçaları kopyalar; düğümden toplu siler. Silme başarısız olursa parça bir sonraki turda yeniden
    kopyalanır, işleme zararsızdır (zaten doğrulanmış kayıt atlanır)."""
    if node.get("kind") == "daytona":
        return _collect_daytona(name, node)
    if node["host"] is None:
        return _collect_local(name, node)
    # Listeleme kısa zaman aşımı + yeniden deneme: PC'den çıkan ssh'lar zaman zaman 60 sn'lik topluca takılıyordu (2026-10-22: tur başına
    # düğümlerin yarısı "zaman aşımı"); ikinci/üçüncü deneme çoğunlukla hemen geçer, tur 10 dk yerine 1-2 dk sürer.
    listing = None
    for attempt in range(2):   # 2026-10-23 gece: disk doygunken ssh başlatma 30+ sn sürdü; zaman aşımı 25 -> 75 sn, deneme 3 -> 2
        try:
            listing = ssh(node, f"cd {node['dir']}/out 2>/dev/null && ls -1 *.jsonl.gz 2>/dev/null || true", timeout=75).split()
            break
        except Exception:  # noqa: BLE001
            if attempt == 1:
                raise
    target = INBOX / name
    target.mkdir(parents=True, exist_ok=True)
    copied = []
    # Her dosya için ayrı scp (bağlantı kurulumu ~1-2 sn) yerine 100'lük gruplar tek ssh+tar akışıyla alınır (2026-10-20:
    # PC uyurken düğüm başına yüzlerce dosya birikti, tek tek kopyalama saatler sürdü).
    import tarfile

    for start in range(0, len(listing), 100):
        batch = listing[start:start + 100]
        try:
            proc = subprocess.Popen(["ssh", *_ssh_args(node), node["host"], f"cd {node['dir']}/out && tar cf - " + " ".join(batch)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
            with tarfile.open(fileobj=proc.stdout, mode="r|") as archive:
                for member in archive:
                    if not member.isfile() or "/" in member.name or not member.name.endswith(".jsonl.gz"):
                        continue
                    data = archive.extractfile(member)
                    part = target / (member.name + ".part")
                    with part.open("wb") as handle:
                        handle.write(data.read())
                    os.replace(part, target / member.name)
                    copied.append(member.name)
            proc.wait(timeout=60)
        except Exception as exc:  # noqa: BLE001
            _log(f"{name}: tar akışı hatası ({len(batch)} dosya): {exc}")
            break
    if copied:
        try:
            ssh(node, "cd " + node["dir"] + "/out && rm -f " + " ".join(copied), timeout=60)
        except Exception as exc:  # noqa: BLE001
            _log(f"{name}: düğümde silme başarısız (sonraki turda tekrar kopyalanır): {exc}")
    return len(copied)


# -- apply ---------------------------------------------------------------------------------------
def _apply_file(path: Path) -> dict[str, int]:
    """Tek sonuç dosyasını kendi bağlantısıyla işler (dosyalar birbirinden bağımsız; paralel çalıştırılır)."""
    from ingestion.hf_700k import strip_third_party_markup
    from ingestion.text import content_hash
    from ingestion.yargitay.store import _SNAPSHOT_SOURCE
    from ingestion.danistay.portal import document_url as danistay_url
    from ingestion.yargitay.portal import document_url as yargitay_url
    from verify_seeds import _MARK, _QUEUE_DONE, _TRASH, _VERIFY, SOURCES, compare_texts

    urls = {"yargitay": yargitay_url, "danistay": danistay_url,
            "emsal": lambda i: yargitay_url(i, base_url="https://emsal.uyap.gov.tr/")}
    totals = {"verified": 0, "mismatch": 0, "unavailable": 0, "requeued": 0, "skipped": 0}
    node_name = path.parent.name
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    with psycopg.connect(os.environ["DATABASE_ADMIN_URL"], autocommit=True) as connection:
        connection.execute("SET statement_timeout = '300s'")
        connection.execute("SET synchronous_commit = off")
        for row in rows:
            source, document_id = row["external_id"].split(":", 1)
            found = connection.execute(_ROW, (row["external_id"],)).fetchone()
            if not found:
                totals["skipped"] += 1  # zaten doğrulanmış/silinmiş ya da resmî kayıt
                continue
            source_id, seed_text = found
            now = datetime.now(UTC).isoformat(timespec="seconds")
            if row["status"] == "error":
                connection.execute(_REQUEUE, (source_id,))
                totals["requeued"] += 1
                continue
            if row["status"] == "not_found" or not (row.get("text") or "").strip():
                connection.execute(_MARK, {"id": source_id, "metadata": Jsonb(
                    {"verify_status": "unavailable", "verify_checked_at": now, "verify_reason": row.get("error") or "boş"})})
                totals["unavailable"] += 1
                continue
            official = row["text"]
            status, verification = compare_texts(seed_text or "", official, strip_third_party_markup(official))
            if status == "verified":
                cfg = SOURCES[source]
                digest = content_hash(official)
                with connection.transaction():
                    connection.execute(_SNAPSHOT_SOURCE, (source_id,))
                    connection.execute(_VERIFY, {
                        "id": source_id, "method": cfg["method"], "canonical": cfg["canonical"],
                        "url": urls[source](document_id), "text": official, "hash": digest,
                        "version": f"sha256:{digest[:16]}",
                        "metadata": Jsonb({"official_verified": True, "third_party": False,
                                           "provenance": "official_portal", "verified_via": f"fetcher:{node_name}",
                                           "verified_at": now, "verification": verification,
                                           "verify_status": "verified"}),
                    })
                totals["verified"] += 1
            else:
                connection.execute(_TRASH, {"id": source_id, "metadata": Jsonb(
                    {"verify_status": "mismatch", "verify_checked_at": now, "verify_reason": f"fetcher:{node_name}"})})
                totals["mismatch"] += 1
            connection.execute(_QUEUE_DONE, ([source_id],))
    (APPLIED / node_name).mkdir(parents=True, exist_ok=True)
    os.replace(path, APPLIED / node_name / path.name)
    return totals


class StreamApplier:
    """Toplama sürerken gelen sonuç dosyalarını hemen işler (2026-10-20: kullanıcı "anlık gelsin"; önceden tüm düğümler
    toplanıp ancak sonra işleniyordu, sayaç saatlerce sıçramalı artıyordu)."""

    def __init__(self, workers: int) -> None:
        import threading
        from concurrent.futures import ThreadPoolExecutor

        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.futures: list = []
        self.seen: set[Path] = set()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._poll, daemon=True)

    def _poll(self) -> None:
        while True:
            last = self.stop.is_set()
            for path in sorted(INBOX.glob("*/*.jsonl.gz")):
                if path not in self.seen:
                    self.seen.add(path)
                    self.futures.append(self.pool.submit(_apply_file, path))
            if last:
                return
            self.stop.wait(2)

    def start(self) -> None:
        APPLIED.mkdir(parents=True, exist_ok=True)
        self.thread.start()

    def finish(self) -> dict[str, int]:
        self.stop.set()
        self.thread.join()
        totals = {"verified": 0, "mismatch": 0, "unavailable": 0, "requeued": 0, "skipped": 0}
        for future in self.futures:
            for key, value in future.result().items():
                totals[key] += value
        self.pool.shutdown()
        return totals


def apply_all(connection: psycopg.Connection) -> dict[str, int]:
    """Sonuç dosyalarını paralel işler (2026-10-19: tek bağlantıyla ~60 karar/sn, sunucular ~110 bin/sa çekiyor)."""
    from concurrent.futures import ThreadPoolExecutor

    totals = {"verified": 0, "mismatch": 0, "unavailable": 0, "requeued": 0, "skipped": 0}
    APPLIED.mkdir(parents=True, exist_ok=True)
    files = sorted(INBOX.glob("*/*.jsonl.gz"))
    if not files:
        return totals
    with ThreadPoolExecutor(max_workers=int(os.getenv("FETCHER_APPLY_WORKERS", "6"))) as pool:
        for part in pool.map(_apply_file, files):
            for key, value in part.items():
                totals[key] += value
    return totals


# -- dispatch ------------------------------------------------------------------------------------
def next_batch_emsal(connection: psycopg.Connection, state: dict, n: int) -> tuple[list[str], list]:
    if state.get("emsal_done"):
        return [], []
    cursor = state.get("emsal", {})
    rows = connection.execute(_SELECT_EMSAL, {"cdate": cursor.get("date"), "cid": cursor.get("id"), "n": n}).fetchall()
    if not rows:
        state["emsal_done"] = True
        return [], []
    state["emsal"] = {"date": str(rows[-1][2]), "id": str(rows[-1][0])}
    return [row[1] for row in rows], []


def next_batch(connection: psycopg.Connection, state: dict, n: int) -> tuple[list[str], list]:
    """(kimlikler, kuyruktan alınanların legal_source_id'leri). Kuyruk işareti iş düğüme ulaşınca konur."""
    queued = connection.execute(_QUEUE, {"n": n}).fetchall()
    ids = [row[1] for row in queued]
    if len(ids) < n and not state.get("all_done"):
        cursor = state.get("all", {})
        rows = connection.execute(_SELECT, {"cdate": cursor.get("date"), "cid": cursor.get("id"), "n": n - len(ids)}).fetchall()
        if rows:
            seen = set(ids)
            ids += [row[1] for row in rows if row[1] not in seen]
            state["all"] = {"date": str(rows[-1][2]), "id": str(rows[-1][0])}
        else:
            state["all_done"] = True
    return ids, [row[0] for row in queued]


import threading

DISPATCH_LOCK = threading.Lock()


def _no_dispatch() -> set[str]:
    try:
        return {line.strip() for line in (ROOT / "data" / "campaign" / "no-dispatch.txt").read_text(encoding="utf-8").splitlines() if line.strip()}
    except OSError:
        return set()

_TOUR = 0


def dispatch(name: str, node: dict, connection: psycopg.Connection, state: dict, lane: str = "bedesten") -> int:
    jobs_dir, job_size, target = LANES[lane]
    batch = next_batch if lane == "bedesten" else next_batch_emsal
    # Dağıtılacak iş yoksa (imleç bitti ve yeniden kuyruğa alınan yok) düğümlere boşuna ssh atılmaz: yavaş düğümlerde 120 sn zaman aşımı
    # turu uzatıyordu (2026-10-22: 53 düğüm x 2 şerit, sayaç 10 dk durdu).
    with DISPATCH_LOCK:
        if lane == "emsal" and state.get("emsal_done"):
            return 0
        if lane == "bedesten" and state.get("all_done") and not connection.execute(_QUEUE, {"n": 1}).fetchone():
            return 0
    if node.get("kind") == "daytona":
        import fetcher_daytona as fd

        sandbox = fd.get_sandbox()
        pending = len(fd.ls(sandbox, jobs_dir))
    elif node["host"] is None:
        (Path(node["dir"]) / jobs_dir).mkdir(parents=True, exist_ok=True)
        pending = len(list((Path(node["dir"]) / jobs_dir).glob("*.jsonl.gz")))
    else:
        pending = int(ssh(node, f"mkdir -p {node['dir']}/{jobs_dir}; ls -1 {node['dir']}/{jobs_dir}/*.jsonl.gz 2>/dev/null | wc -l").strip() or 0)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    sent = 0
    index = 0
    while pending < target:
        with DISPATCH_LOCK:
            ids, queued = batch(connection, state, job_size)
        if not ids:
            break
        job = f"{stamp}-{index:02d}-{name}" + ("" if lane == "bedesten" else f"-{lane}")
        local = ROOT / "data" / "fetcher" / "jobs" / f"{job}.jsonl.gz"
        local.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(local, "wt", encoding="utf-8") as handle:
            for external_id in ids:
                handle.write(json.dumps({"external_id": external_id}) + "\n")
        if node.get("kind") == "daytona":
            fd.put(sandbox, str(local), jobs_dir, f"{job}.jsonl.gz")
        elif node["host"] is None:
            import shutil
            shutil.copyfile(local, Path(node["dir"]) / jobs_dir / f"{job}.jsonl.gz.part")
            os.replace(Path(node["dir"]) / jobs_dir / f"{job}.jsonl.gz.part", Path(node["dir"]) / jobs_dir / f"{job}.jsonl.gz")
        else:
            scp(node, str(local), f"{node['host']}:{node['dir']}/{jobs_dir}/{job}.jsonl.gz.part")
            ssh(node, f"mv {node['dir']}/{jobs_dir}/{job}.jsonl.gz.part {node['dir']}/{jobs_dir}/{job}.jsonl.gz")
        with DISPATCH_LOCK:
            if queued:
                connection.execute(_PICKED, (queued,))
            save_state(state)  # imleç ancak iş düğüme ulaştıktan sonra kalıcı
        sent += len(ids)
        pending += 1
        index += 1
    return sent


STOPPED_FILE = ROOT / "data" / "campaign" / "fetcher-stopped.txt"


def active_nodes() -> dict:
    """Kullanıcının durdurduğu (kapalı) düğümler `data/campaign/fetcher-stopped.txt` içinde (satır başına ad); atlanır."""
    stopped = {l.strip() for l in STOPPED_FILE.read_text(encoding="utf-8").splitlines() if l.strip()} if STOPPED_FILE.exists() else set()
    return {name: node for name, node in NODES.items() if name not in stopped}


def _collect_job(item: tuple[str, dict]) -> tuple[str, int, str]:
    name, node = item
    try:
        return name, collect(name, node), ""
    except Exception as exc:  # noqa: BLE001
        return name, 0, str(exc)[:200]


def run() -> int:
    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")
    state = load_state()
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute("SET statement_timeout = '300s'")
        # Sunucu sayısı arttıkça sırayla toplama saatler sürüyor (2026-10-18: 41 sunucu ~1 saat): SSH/scp işleri paralel yürütülür.
        from concurrent.futures import ThreadPoolExecutor

        # Yalnız toplama kipi (kullanıcı 2026-10-23: "PC'nin görevi sadece sunucuları boşaltmak"): işleme ayrı, düşük öncelikli
        # süreçte (`fetcher_hub.py apply --loop`); işleme iş parçacıkları ssh'ları aç bırakıp 25 sn zaman aşımına düşürüyordu.
        collect_only = (ROOT / "data" / "campaign" / "HUB_COLLECT_ONLY").exists()
        applier = None if collect_only else StreamApplier(int(os.getenv("FETCHER_APPLY_WORKERS", "6")))
        if applier:
            applier.start()  # önceki turdan kalanlar ve toplanan dosyalar anında işlenir
        # Toplama ayrı süreçlerde (iş parçacığı değil): 64 iş parçacığı tar akışlarını okurken GIL'i tutup listeleme ssh'larını
        # 25 sn zaman aşımına düşürüyordu (2026-10-23: ayrı betikte 252 düğüm 5 sn'de listelenirken hub'da ~%90 hata).
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=int(os.getenv("FETCHER_HUB_WORKERS", "12"))) as pool:
            for name, got, error in pool.map(_collect_job, list(active_nodes().items()), chunksize=4):
                if error:
                    _log(f"{name}: toplama hatası: {error}")
                elif got:
                    _log(f"{name}: {got} sonuç parçası alındı")
        # Sunucular boş kalmasın diye (kullanıcı 2026-10-18): iş dağıtımı, uzun süren işleme aşamasından ÖNCE yapılır.
        totals = applier.finish() if applier else {}
        if any(totals.values()):
            _log(f"işlendi: {totals}")
            for key, value in totals.items():
                state.setdefault("totals", {})[key] = state.get("totals", {}).get(key, 0) + value
            save_state(state)
        try:  # panel sayaçlarının fark satırlarını tabana kat (migration 059); hata asıl işi bozmaz
            connection.execute("SELECT corpus_counters_compact()")
        except Exception as exc:  # noqa: BLE001
            _log(f"sayaç katlama hatası: {exc}")
        # İş dağıtımı işleme sayacı yazıldıktan sonra: ssh yavaşlayınca sayaç geride kalmasın (sunucu kuyruğu ~2 gün yeter).
        def _dispatch_one(item: tuple[str, dict]) -> None:
            name, node = item
            if name in _no_dispatch():  # kredisi biten hesabın düğümlerine yeni iş gönderilmez (data/campaign/no-dispatch.txt)
                return
            for lane in node.get("lanes", tuple(LANES)):
                try:
                    sent = dispatch(name, node, connection, state, lane)
                    if sent:
                        _log(f"{name}/{lane}: {sent} kimlik gönderildi")
                except Exception as exc:  # noqa: BLE001
                    _log(f"{name}/{lane}: gönderme hatası: {exc}")

        # Sunucu kuyrukları ~2 günlük iş taşıyor; kuyruk yoklaması yavaş düğümlerde 120 sn zaman aşımına uğrayıp turu uzatıyordu
        # (2026-10-21: tur 1 saatten uzun, sonuçlar geç toplandı). Dağıtım her FETCHER_DISPATCH_EVERY. turda bir yapılır.
        global _TOUR
        _TOUR += 1
        if _TOUR % int(os.getenv("FETCHER_DISPATCH_EVERY", "3")) == 1:
            with ThreadPoolExecutor(max_workers=int(os.getenv("FETCHER_DISPATCH_WORKERS", "6"))) as pool:
                list(pool.map(_dispatch_one, list(active_nodes().items())))
        else:
            _log(f"tur {_TOUR}: iş dağıtımı atlandı (sunucu kuyrukları dolu)")
    return 0


def status() -> int:
    state = load_state()
    print(json.dumps({k: v for k, v in state.items()}, ensure_ascii=False, indent=1))
    for name, node in NODES.items():
        if node["host"] is None:
            d = Path(node["dir"])
            print(name, "yerel | iş:", len(list((d / "jobs").glob("*.jsonl.gz"))), "| sonuç:", len(list((d / "out").glob("*.jsonl.gz"))))
            continue
        try:
            print(name, ssh(node, f"systemctl is-active nhr-fetcher; ls {node['dir']}/jobs {node['dir']}/out 2>/dev/null | tr '\\n' ' '; echo; tail -n 2 {node['dir']}/worker.log").strip())
        except Exception as exc:  # noqa: BLE001
            print(name, "erişilemedi:", exc)
    return 0


def apply_loop() -> int:
    """Gelen kutusundaki sonuç dosyalarını ayrı, düşük öncelikli süreçte işler (HUB_COLLECT_ONLY kipinde toplama ile yarışmaz)."""
    try:
        import ctypes

        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL
    except Exception:  # noqa: BLE001
        pass
    from concurrent.futures import ThreadPoolExecutor

    url = os.getenv("DATABASE_ADMIN_URL")
    if not url:
        raise SystemExit("DATABASE_ADMIN_URL tanımlı değil")
    out = ROOT / "data" / "campaign" / "fetcher-apply.json"
    APPLIED.mkdir(parents=True, exist_ok=True)
    workers = int(os.getenv("FETCHER_APPLY_WORKERS", "4"))
    while True:
        files = sorted(INBOX.glob("*/*.jsonl.gz"))
        if files:
            totals = {"verified": 0, "mismatch": 0, "unavailable": 0, "requeued": 0, "skipped": 0}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for part in pool.map(_apply_file, files):
                    for key, value in part.items():
                        totals[key] += value
            try:
                total = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
            except Exception:  # noqa: BLE001
                total = {}
            for key, value in totals.items():
                total[key] = total.get(key, 0) + value
            out.write_text(json.dumps(total), encoding="utf-8")
            _log(f"apply: {len(files)} dosya işlendi: {totals}")
            try:
                with psycopg.connect(url, autocommit=True) as connection:
                    connection.execute("SELECT corpus_counters_compact()")
            except Exception as exc:  # noqa: BLE001
                _log(f"sayaç katlama hatası: {exc}")
        else:
            time.sleep(20)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("run", "status", "apply"))
    parser.add_argument("--loop", action="store_true", help="Turları sürekli döndür (PAUSE_FETCHER_HUB bayrağı duraklatır)")
    args = parser.parse_args()
    if args.command == "status":
        return status()
    if args.command == "apply":
        return apply_loop()
    if not args.loop:
        return run()
    while True:
        if not (ROOT / "data" / "campaign" / "PAUSE_FETCHER_HUB").exists():
            try:
                run()
            except Exception as exc:  # noqa: BLE001
                _log(f"tur hatası: {exc}")
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
