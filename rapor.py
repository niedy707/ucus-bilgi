#!/usr/bin/env python3
"""Uçuşun anlık durum raporu — tek seferlik okuma (cron'a gerek yok).

Biçim (kullanıcı isteği, 12.10.2026): uçuş · kalkış saati (yalnız bu hem kalkış hem varış saat diliminde) ·
kalkıştan beri geçen · tahmini uçuş süresi · yüzde kaçı geçti · kalan süre · tahmini iniş. Kalkış dışındaki
bütün saatler VARIŞ yerinin saatiyle.

Tahmini iniş için öncelik (ilk bulunan esas alınır, ötekiler "yedek tahminler" olarak yazılır):
  1. Flightradar24 tahmini          — esas kaynak
  2. Varış havalimanının tahmini    — şimdilik yalnız İstanbul (Actions'tan okunamıyor, VPS'ten okunuyor)
  3. Geçmiş seferlerin ortalaması   — kalkış + son ≤20 seferin ortalama havada kalma süresi
  4. Konum + hız (kaba)             — kalan kuş uçuşu × 1,05 rota payı ÷ şimdiki yer hızı + 10 dk
                                      (rüzgâr değiştikçe sapar; hedefe 2.000 km'den az kalınca 3'ün önüne geçer)
  5. Tarife                         — planlanan varış (blok saat; kalkış gecikmesini bilmez)
Kalkış anı için öncelik: FR24 gerçek kalkış → Haneda kapıdan ayrılış + taksi payı → tarife + geçmiş ortalama gecikme.

Geçmiş seferler her raporda: FR24 geçmişi (~7 gün, ~1 sn) her koşuda okunur, veri/ önbelleğine eklenir;
ortalama önbellekteki son ≤20 seferden hesaplanır. FR24 okunamazsa önbellek yeter.

Kullanım:
  rapor.py               raporu yazdır (GITHUB_STEP_SUMMARY varsa oraya da)
  rapor.py --gecmis      sefer sefer geçmiş tablosunu da yazdır
  rapor.py --bildir      raporu Bark ile de gönder (bildirim.py)
  UCUS_TANIM=baska.json  başka bir uçuş tanımı
"""
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

import bildirim
import kaynaklar as k

ROTA_PAYI = 1.05        # kalan kuş uçuşu mesafeye eklenen hava yolu payı
YAKLASMA_DK = 10        # alçalma/yaklaşmada kaybedilen süre (kaba)
TAKSI_DK = 18           # Haneda kapıdan ayrılış → tekerlek kesme (kaba; FR24 yoksa kullanılır)
GECMIS_SAYI = 20


def sayi(x):
    return f'{x:,.0f}'.replace(',', '.')


def dk_yazi(dk):
    dk = round(dk)
    return f'{dk // 60} sa {dk % 60:02d} dk' if dk >= 0 else f'−{dk_yazi(-dk)}'


def dene(ad, is_, hatalar):
    try:
        return is_()
    except Exception as hata:  # noqa: BLE001 — her kaynak bağımsız; biri düşerse ötekiler sürer
        hatalar.append(f'{ad}: {k.kisa(hata)}')
        return None


# ── Geçmiş önbelleği (veri/<etiket>-<kalkış>-<varış>.json) ──────────────────
def gecmis_yolu(ucus):
    return os.path.join(k.KOK, 'veri', f'{ucus.etiket}-{ucus.kalkis_kod}-{ucus.varis_kod}.json')


def gecmis_yukle(ucus):
    try:
        with open(gecmis_yolu(ucus), encoding='utf-8') as f:
            return json.load(f)['seferler']
    except FileNotFoundError:
        return []


def gecmis_birlestir(ucus, yeni):
    eski = {s['kalkis_ts']: s for s in gecmis_yukle(ucus)}
    for s in yeni:
        eski[s['kalkis_ts']] = s
    hepsi = sorted(eski.values(), key=lambda s: s['kalkis_ts'], reverse=True)[:60]
    os.makedirs(os.path.dirname(gecmis_yolu(ucus)), exist_ok=True)
    with open(gecmis_yolu(ucus), 'w', encoding='utf-8') as f:
        json.dump({'aciklama': 'Tamamlanmış seferler (FR24 gerçek kalkış/iniş, UTC epoch). rapor.py --gecmis yazar.',
                   'seferler': hepsi}, f, ensure_ascii=False, indent=1)
        f.write('\n')
    return hepsi


def gecmis_ozet(seferler):
    son = seferler[:GECMIS_SAYI]
    if not son:
        return None
    sureler = [(s['varis_ts'] - s['kalkis_ts']) / 60 for s in son]
    gecikmeler = [(s['kalkis_ts'] - s['plan_kalkis_ts']) / 60 for s in son if s.get('plan_kalkis_ts')]
    return {'sayi': len(son), 'ort': statistics.mean(sureler), 'ortanca': statistics.median(sureler),
            'min': min(sureler), 'max': max(sureler),
            'gecikme': statistics.mean(gecikmeler) if gecikmeler else None, 'son': son}


# ── Rapor ───────────────────────────────────────────────────────────────────
def rapor(ucus, simdi, gecmis_tablo=False):
    hatalar = []
    fr = dene('Flightradar24', lambda: k.fr24_canli(ucus), hatalar)
    adsb = dene('ADS-B', lambda: k.adsb_oku(ucus), hatalar)
    hnd = dene('Haneda', lambda: k.hnd_oku(ucus, simdi), hatalar) if ucus.kalkis_kod == 'HND' else None
    ist = dene('İstanbul', lambda: k.ist_oku(ucus, varis=True), hatalar) if ucus.varis_kod == 'IST' else None
    seferler = gecmis_yukle(ucus)
    yeni = dene('FR24 geçmiş', lambda: k.fr24_gecmis(ucus), hatalar)
    if yeni:
        seferler = gecmis_birlestir(ucus, yeni)
    gec = gecmis_ozet(seferler)

    v_ad, k_ad = ucus.ham['varis'].get('ad', ucus.varis_kod), ucus.ham['kalkis'].get('ad', ucus.kalkis_kod)
    vs = lambda t: t.astimezone(ucus.varis_dilim).strftime('%H:%M')  # noqa: E731
    ks = lambda t: t.astimezone(ucus.kalkis_dilim).strftime('%H:%M')  # noqa: E731
    ts = lambda x: datetime.fromtimestamp(x, timezone.utc)  # noqa: E731

    # Kalkış anı
    kalkis, kalkis_kay = None, ''
    if fr and fr['kalkis_ts']:
        kalkis, kalkis_kay = ts(fr['kalkis_ts']), 'FR24, tekerlek kesme'
    elif hnd and hnd['kod'] == '17' and (hnd['degisen'] or hnd['plan']):
        ayrilis = datetime.strptime(hnd['degisen'] or hnd['plan'], '%Y/%m/%d %H:%M:%S').replace(tzinfo=ucus.kalkis_dilim)
        kalkis, kalkis_kay = ayrilis + timedelta(minutes=TAKSI_DK), f'Haneda kapıdan ayrılış {ks(ayrilis)} + {TAKSI_DK} dk taksi payı'
    elif simdi > ucus.plan_kalkis + timedelta(minutes=30) and (fr or adsb):
        gecikme = (gec or {}).get('gecikme') or 20
        kalkis = ucus.plan_kalkis + timedelta(minutes=gecikme)
        kalkis_kay = f'tarife + geçmiş ortalama gecikme {round(gecikme)} dk (kaba)'

    inis = ts(fr['varis_ts']) if fr and fr['varis_ts'] else None

    # Konum ve konuma göre ilerleme
    konum, uculan, kalan_km = None, None, None
    if fr and fr['konum']:
        lat, lon, alt, spd, zaman = fr['konum']
        konum = {'lat': lat, 'lon': lon, 'alt': alt, 'gs': spd, 'zaman': ts(zaman) if zaman else simdi, 'kay': 'FR24'}
        n = [(p[0], p[1]) for p in fr['iz']]
        uculan = sum(k.mesafe_km(*a, *b) for a, b in zip(n, n[1:]))
    elif adsb:
        konum = {'lat': adsb['lat'], 'lon': adsb['lon'], 'alt': adsb['alt'], 'gs': adsb['gs'],
                 'zaman': simdi - timedelta(seconds=adsb['yas_sn'] or 0), 'kay': 'ADS-B'}
    toplam_km = k.mesafe_km(*ucus.kalkis_konum, *ucus.varis_konum)
    if konum:
        kalan_km = k.mesafe_km(konum['lat'], konum['lon'], *ucus.varis_konum)
        if uculan is None:
            uculan = max(0.0, toplam_km - kalan_km)  # kuş uçuşu yaklaşımı

    # Tahmini iniş adayları (öncelik sırasıyla)
    adaylar = []
    if fr and fr['tahmin_ts']:
        adaylar.append(('Flightradar24', ts(fr['tahmin_ts'])))
    if ist and (ist['tahmin'] or ist['plan']):
        adaylar.append(('İstanbul Havalimanı',
                        datetime.fromisoformat(ist['tahmin'] or ist['plan']).replace(tzinfo=ucus.varis_dilim)))
    konum_hiz, ortalama = None, None
    if konum and kalan_km is not None and kalkis and (konum['gs'] or 0) * 1.852 > 300:
        kalan_saat = kalan_km * ROTA_PAYI / (konum['gs'] * 1.852)
        konum_hiz = ('Konum + hız (kaba)', konum['zaman'] + timedelta(hours=kalan_saat, minutes=YAKLASMA_DK))
    if gec and kalkis:
        ortalama = (f'Geçmiş {gec["sayi"]} sefer ortalaması', kalkis + timedelta(minutes=gec['ort']))
    sira = [konum_hiz, ortalama] if kalan_km is not None and kalan_km < 2000 else [ortalama, konum_hiz]
    adaylar += [a for a in sira if a]
    adaylar.append(('Tarife', ucus.plan_varis))
    esas_ad, esas = (('Gerçek iniş', inis) if inis else adaylar[0])

    # Metin
    s = [f'**{ucus.etiket}** {ucus.kalkis_kod} → {ucus.varis_kod} · okuma {vs(simdi)} {v_ad}', '']
    s.append('| | |')
    s.append('|---|---|')
    s.append(f'| Uçuş | {ucus.etiket} ({ucus.ham.get("havayolu", ucus.icao)}), {ucus.kalkis_kod} → {ucus.varis_kod} |')
    if kalkis:
        s.append(f'| Kalkış | **{ks(kalkis)} {k_ad} / {vs(kalkis)} {v_ad}** ({kalkis_kay}) |')
    else:
        s.append(f'| Kalkış | henüz kalkmadı · tarife {ks(ucus.plan_kalkis)} {k_ad} / {vs(ucus.plan_kalkis)} {v_ad} |')
    if kalkis:
        bitis = inis or simdi
        gecen = (bitis - kalkis).total_seconds() / 60
        sure = (esas - kalkis).total_seconds() / 60
        s.append(f'| Kalkıştan beri geçen | {dk_yazi(gecen)} |')
        s.append(f'| Tahmini uçuş süresi | {dk_yazi(sure)} |')
        oran = f'%{100 * gecen / sure:.0f} (zamana göre)' if sure > 0 else '—'
        if uculan is not None and kalan_km is not None and not inis:
            oran += f' · %{100 * uculan / (uculan + kalan_km):.0f} (konuma göre)'
        s.append(f'| Geçen kısım | {oran} |')
        if inis:
            s.append(f'| İniş | **{vs(inis)} {v_ad}** (gerçek) |')
        else:
            s.append(f'| Kalan süre | **{dk_yazi((esas - simdi).total_seconds() / 60)}** |')
            fark = round((esas - ucus.plan_varis).total_seconds() / 60)
            s.append(f'| Tahmini iniş | **{vs(esas)} {v_ad}** ({esas_ad}; tarife {vs(ucus.plan_varis)}, '
                     f'{"+" if fark > 0 else "−" if fark < 0 else "±"}{abs(fark)} dk) |')
    if konum and not inis:
        alt_m = f'{sayi(konum["alt"] * 0.3048)} m' if konum['alt'] else '—'
        gs = f'{sayi(konum["gs"] * 1.852)} km/sa' if konum['gs'] else '—'
        s.append(f'| Konum | {konum["lat"]:.2f}, {konum["lon"]:.2f} · {alt_m} · yer hızı {gs} · '
                 f'hedefe kuş uçuşu {sayi(kalan_km)} km ({konum["kay"]}, {vs(konum["zaman"])}) |')
    if hnd:
        s.append(f'| {ucus.kalkis_kod} | {k.hm(hnd["degisen"] or hnd["plan"])} {k_ad} · T{hnd["terminal"] or "?"} · '
                 f'kapı {hnd["kapi"] or "—"} · {hnd["not_en"] or hnd["kod"] or "—"} |')
    if ist:
        s.append(f'| {ucus.varis_kod} | tahmini {k.hm(ist["tahmin"] or ist["plan"])} · {ist["not"] or "—"}'
                 + (f' · bagaj bandı {ist["bant"]}' if ist['bant'] else '') + ' |')

    if not inis and len(adaylar) > 1:
        s += ['', 'Yedek tahminler (iniş, ' + v_ad + '):']
        for ad, t in adaylar:
            isaret = ' ← esas' if ad == esas_ad else ''
            s.append(f'- {ad}: {vs(t)}{isaret}')
    if gec:
        s += ['', f'Geçmiş ({gec["sayi"]} sefer): havada ortalama {dk_yazi(gec["ort"])}, ortanca '
                  f'{dk_yazi(gec["ortanca"])}, en kısa {dk_yazi(gec["min"])}, en uzun {dk_yazi(gec["max"])}'
                  + (f'; kalkış gecikmesi ortalama {round(gec["gecikme"])} dk' if gec['gecikme'] is not None else '')]
        if gecmis_tablo:
            for x in gec['son']:
                kt, vt = ts(x['kalkis_ts']), ts(x['varis_ts'])
                gk = (f', plana göre {round((x["kalkis_ts"] - x["plan_kalkis_ts"]) / 60):+d} dk'
                      if x.get('plan_kalkis_ts') else '')
                s.append(f'- {kt.astimezone(ucus.kalkis_dilim):%d.%m.%Y}: kalkış {ks(kt)} {k_ad}{gk} · iniş '
                         f'{vs(vt)} {v_ad} · havada {dk_yazi((x["varis_ts"] - x["kalkis_ts"]) / 60)} · {x["tescil"]}')
    if hatalar:
        s += ['', 'Okunamayan kaynaklar: ' + ' · '.join(hatalar)]
    kisa_ozet = (f'İniş {vs(esas)} {v_ad} ({esas_ad})' if not inis else f'İndi {vs(inis)} {v_ad}')
    if kalkis and not inis:
        kisa_ozet += f' · kalan {dk_yazi((esas - simdi).total_seconds() / 60)}'
    return '\n'.join(s), kisa_ozet


def main():
    ucus = k.ucus_yukle()
    simdi = datetime.now(timezone.utc)
    if os.environ.get('UCUS_SIMDI'):  # deneme için saat taklidi
        simdi = datetime.fromisoformat(os.environ['UCUS_SIMDI']).astimezone(timezone.utc)
    metin, kisa_ozet = rapor(ucus, simdi, gecmis_tablo='--gecmis' in sys.argv)
    print(metin)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(metin + '\n')
    if '--bildir' in sys.argv:
        tablo_disi = [x for x in metin.splitlines() if x.startswith('| ') and not x.startswith('| |')]
        govde = '\n'.join(x.strip('| ').replace(' | ', ': ', 1).replace('**', '') for x in tablo_disi)
        if not bildirim.bark(f'✈️ {ucus.etiket} · {kisa_ozet}', govde):
            print('Bark gönderilemedi', file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
