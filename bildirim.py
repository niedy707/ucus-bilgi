"""Bark bildirimi — iki yol, ilk bulunan kullanılır:

  1. UCUS_TAKIP_BARK_URL   Bark sunucusu + cihaz anahtarı, ör. https://api.day.app/<anahtar>
                           (GitHub Actions'ta depo sırrı BARK_URL olarak verilir). JSON POST edilir.
  2. UCUS_TAKIP_BARK       Bark betiği (varsayılan /root/scripts/bark.sh; VPS'te kurulu): betik BAŞLIK MESAJ

Başarı ölçütü ikisinde de Bark'ın yanıtındaki "code": 200. Başarısızsa False döner; çağıran yeniden dener.
Hata metinlerinde URL'ler gizlenir (anahtar içerir).
"""
import json
import os
import re
import subprocess
import urllib.request

KURU = False  # True ise göndermez, yazdırır (takip.py --kuru)


def _gizle(metin):
    return re.sub(r'https?://\S+', '<url>', metin)[:200]


def bark(baslik, mesaj, grup='ucus-takip'):
    if KURU:
        print(f'[kuru] BARK «{baslik}»\n       ' + mesaj.replace('\n', '\n       '))
        return True
    url = os.environ.get('UCUS_TAKIP_BARK_URL')
    if url:
        try:
            istek = urllib.request.Request(
                url.rstrip('/'), data=json.dumps({'title': baslik, 'body': mesaj, 'group': grup}).encode(),
                headers={'Content-Type': 'application/json; charset=utf-8'})
            with urllib.request.urlopen(istek, timeout=30) as yanit:
                return json.loads(yanit.read().decode('utf-8')).get('code') == 200
        except Exception as hata:  # noqa: BLE001 — her hata "gönderilemedi" demektir
            print(f'BARK HATA {_gizle(f"{type(hata).__name__}: {hata}")}', flush=True)
            return False
    betik = os.environ.get('UCUS_TAKIP_BARK', '/root/scripts/bark.sh')
    try:
        r = subprocess.run([betik, baslik, mesaj], capture_output=True, text=True, timeout=40)
    except Exception as hata:  # noqa: BLE001
        print(f'BARK HATA {type(hata).__name__}', flush=True)
        return False
    ok = r.returncode == 0 and '"code":200' in r.stdout.replace(' ', '')
    if not ok:
        print(f'BARK HATA rc={r.returncode} yanit={_gizle((r.stdout + " " + r.stderr).strip())}', flush=True)
    return ok
