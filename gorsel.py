#!/usr/bin/env python3
"""Uçuşun haritası ve tahmini iniş grafiği (PNG) — rapor.py'nin veri/izlem kayıtlarından.

  harita.png  uçulan iz (FR24), şimdiki konum, hedefe kalan kuş uçuşu yol, kalkış/varış
  grafik.png  okuma saatine göre tahmini iniş: FR24 · geçmiş ortalama · konum+hız; tarife çizgisi ve
              geçmiş seferlerin iniş aralığı (gölge)

Gerekenler: matplotlib (pip) ve dünya haritası TopoJSON'u (npm paketi world-atlas@2: countries-50m.json):
  npm pack world-atlas@2.0.2 && tar -xzf world-atlas-2.0.2.tgz      → package/countries-50m.json
  python3 gorsel.py --dunya package/countries-50m.json --cikti /tmp/gorsel
Bu betik Actions'ta koşmaz (rapor.yml paket kurmaz); görseller isteyen yerde üretilir.
"""
import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

import matplotlib

matplotlib.use('Agg')
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

import kaynaklar as k  # noqa: E402

# Renkler: dataviz başvuru paleti, açık yüzey (ilk üç kategorik yuva tüm çiftlerde doğrulandı)
YUZEY, MUREKKEP, IKINCIL, SOLUK = '#fcfcfb', '#0b0b0b', '#52514e', '#8a8984'
KARA, SINIR, DENIZ_YAZI = '#e9e8e3', '#fcfcfb', '#9a9993'
MAVI, TURUNCU, SU = '#2a78d6', '#eb6834', '#1baf7a'

ULKE_ADLARI = [  # (boylam, enlem, ad) — haritada yön bulmak için, Türkçe
    (137.6, 37.4, 'Japonya'), (128.6, 35.0, 'Kore'), (104.0, 33.0, 'Çin'), (103.0, 46.6, 'Moğolistan'),
    (67.5, 48.0, 'Kazakistan'), (63.6, 41.6, 'Özbekistan'), (59.0, 38.6, 'Türkmenistan'), (74.6, 41.4, 'Kırgızistan'),
    (54.0, 32.5, 'İran'), (36.5, 38.0, 'Türkiye'), (95.0, 53.5, 'Rusya'), (69.0, 33.6, 'Afganistan'),
]
DENIZ_ADLARI = [(50.6, 42.0, 'Hazar\nDenizi'), (34.5, 43.4, 'Karadeniz'), (124.0, 35.6, 'Sarı Deniz')]


# ── Veri ────────────────────────────────────────────────────────────────────
def izlem_oku(ucus):
    taban = os.path.join(k.KOK, 'veri', 'izlem', f'{ucus.etiket}-{ucus.plan_kalkis:%Y-%m-%d}')
    with open(taban + '.csv', encoding='utf-8') as f:
        satirlar = list(csv.DictReader(f))
    iz = None
    if os.path.exists(taban + '-iz.json'):
        with open(taban + '-iz.json', encoding='utf-8') as f:
            iz = json.load(f)['iz']
    return satirlar, iz


def zaman(s):
    return datetime.strptime(s, '%Y-%m-%dT%H:%MZ').replace(tzinfo=timezone.utc) if s else None


def topojson_ulkeler(yol):
    """TopoJSON (world-atlas) → [[(boylam, enlem), ...] halka listesi]. Yalnız standart kitaplık."""
    with open(yol, encoding='utf-8') as f:
        topo = json.load(f)
    tr = topo.get('transform')
    yaylar = []
    for yay in topo['arcs']:
        x = y = 0
        noktalar = []
        for dx, dy in yay:
            if tr:
                x, y = x + dx, y + dy
                noktalar.append((x * tr['scale'][0] + tr['translate'][0], y * tr['scale'][1] + tr['translate'][1]))
            else:
                noktalar.append((dx, dy))
        yaylar.append(noktalar)

    def halka(indeksler):
        sonuc = []
        for i in indeksler:
            parca = yaylar[i] if i >= 0 else list(reversed(yaylar[~i]))
            sonuc.extend(parca if not sonuc else parca[1:])
        return sonuc

    halkalar = []
    for g in topo['objects']['countries']['geometries']:
        if g['type'] == 'Polygon':
            halkalar += [halka(h) for h in g['arcs']]
        elif g['type'] == 'MultiPolygon':
            halkalar += [halka(h) for poligon in g['arcs'] for h in poligon]
    return halkalar


def buyuk_daire(a, b, n=120):
    """İki (enlem, boylam) arasında büyük daire noktaları → [(boylam, enlem)]."""
    e1, b1, e2, b2 = map(math.radians, (*a, *b))
    v1 = (math.cos(e1) * math.cos(b1), math.cos(e1) * math.sin(b1), math.sin(e1))
    v2 = (math.cos(e2) * math.cos(b2), math.cos(e2) * math.sin(b2), math.sin(e2))
    aci = math.acos(max(-1.0, min(1.0, sum(p * q for p, q in zip(v1, v2)))))
    sonuc = []
    for i in range(n + 1):
        t = i / n
        if aci < 1e-9:
            v = v1
        else:
            s1, s2 = math.sin((1 - t) * aci) / math.sin(aci), math.sin(t * aci) / math.sin(aci)
            v = tuple(s1 * p + s2 * q for p, q in zip(v1, v2))
        sonuc.append((math.degrees(math.atan2(v[1], v[0])), math.degrees(math.asin(v[2]))))
    return sonuc


def sayi(x):
    return f'{x:,.0f}'.replace(',', '.')


def dk_yazi(dk):
    dk = round(dk)
    return f'{dk // 60} sa {dk % 60:02d} dk'


# ── Harita ──────────────────────────────────────────────────────────────────
def harita(ucus, satirlar, iz, dunya, cikti):
    son = satirlar[-1]
    v_ad = ucus.ham['varis'].get('ad', ucus.varis_kod)
    okuma = zaman(son['okuma_utc'])
    if iz:
        yol = [(p[1], p[0]) for p in iz]
    else:  # FR24 izi yoksa okuma noktalarını birleştir
        yol = [(float(s['lon']), float(s['lat'])) for s in satirlar if s['lat']]
    simdi = (float(son['lon']), float(son['lat'])) if son['lat'] else yol[-1]

    bmin = min(ucus.varis_konum[1], ucus.kalkis_konum[1]) - 6
    bmax = max(ucus.varis_konum[1], ucus.kalkis_konum[1]) + 6
    emin, emax = 24, 56
    oran = 1 / math.cos(math.radians((emin + emax) / 2))
    gen = 13
    fig, ax = plt.subplots(figsize=(gen, gen * (emax - emin) * oran / (bmax - bmin) + 1.0), dpi=150)
    fig.patch.set_facecolor(YUZEY)
    ax.set_facecolor(YUZEY)
    for h in dunya:
        if len(h) > 2:
            ax.add_patch(Polygon(h, closed=True, facecolor=KARA, edgecolor=SINIR, linewidth=0.6, zorder=1))
    for b, e, ad in ULKE_ADLARI:
        if bmin < b < bmax and emin < e < emax:
            ax.text(b, e, ad, fontsize=9, color=SOLUK, ha='center', va='center', zorder=2)
    for b, e, ad in DENIZ_ADLARI:
        if bmin < b < bmax and emin < e < emax:
            ax.text(b, e, ad, fontsize=8.5, color=DENIZ_YAZI, ha='center', va='center', style='italic', zorder=2)

    # Hedefe kalan kuş uçuşu yol (kesikli), uçulan iz (düz)
    kalan = buyuk_daire((simdi[1], simdi[0]), ucus.varis_konum)
    ax.plot(*zip(*kalan), color=MAVI, linewidth=1.6, linestyle=(0, (2, 3)), alpha=0.7, zorder=3,
            label='Kalan yol (kuş uçuşu)')
    ax.plot(*zip(*yol), color=MAVI, linewidth=2.4, solid_capstyle='round', zorder=4, label='Uçulan iz (FR24)')

    # Kalkış, varış, şimdi
    for (e, b), ad, ha in ((ucus.kalkis_konum, f'{ucus.ham["kalkis"].get("ad", "")} {ucus.kalkis_kod}', 'right'),
                           (ucus.varis_konum, f'İstanbul {ucus.varis_kod}', 'left')):
        ax.plot(b, e, 'o', markersize=8, markerfacecolor=MUREKKEP, markeredgecolor=YUZEY, markeredgewidth=2, zorder=5)
        ax.text(b + (1.2 if ha == 'left' else -1.2), e - 1.6, ad, fontsize=10.5, color=MUREKKEP, ha=ha,
                va='center', fontweight='bold', zorder=6)
    ax.plot(*simdi, 'o', markersize=13, markerfacecolor=MAVI, markeredgecolor=YUZEY, markeredgewidth=2.5, zorder=7)
    irtifa = f'{sayi(float(son["irtifa_ft"]) * 0.3048)} m' if son['irtifa_ft'] else ''
    hiz = f'{sayi(float(son["yer_hizi_kt"]) * 1.852)} km/sa' if son['yer_hizi_kt'] else ''
    ax.annotate(f'Şimdi · {okuma.astimezone(ucus.varis_dilim):%H:%M} {v_ad}\n{irtifa} · {hiz}',
                xy=simdi, xytext=(0, -24), textcoords='offset points', ha='center', va='top', fontsize=10.5,
                color=MUREKKEP, zorder=8,
                bbox=dict(boxstyle='round,pad=0.35', facecolor=YUZEY, edgecolor='none', alpha=0.9))

    ax.set_xlim(bmin, bmax)
    ax.set_ylim(emin, emax)
    ax.set_aspect(oran)
    ax.axis('off')
    esas = zaman(son['esas_inis_utc'])
    kalan_dk = (esas - okuma).total_seconds() / 60 if esas else None
    toplam = k.mesafe_km(*ucus.kalkis_konum, *ucus.varis_konum)
    kalan_km = float(son['kalan_km']) if son['kalan_km'] else None
    baslik = f'{ucus.etiket} · Tokyo → İstanbul · {okuma.astimezone(ucus.varis_dilim):%H:%M} {v_ad}'
    alt = []
    if kalan_km is not None:
        alt.append(f'hedefe kuş uçuşu {sayi(kalan_km)} km (toplam {sayi(toplam)} km)')
    if esas:
        alt.append(f'tahmini iniş {esas.astimezone(ucus.varis_dilim):%H:%M} {v_ad} ({son["esas"]})')
    if kalan_dk is not None:
        alt.append(f'kalan {dk_yazi(kalan_dk)}')
    fig.text(0.02, 0.97, baslik, fontsize=15, fontweight='bold', color=MUREKKEP, va='top')
    fig.text(0.02, 0.915, ' · '.join(alt), fontsize=11, color=IKINCIL, va='top')
    ax.legend(loc='lower left', frameon=False, fontsize=9.5, labelcolor=IKINCIL)
    fig.subplots_adjust(left=0.01, right=0.99, bottom=0.01, top=0.88)
    yol_png = os.path.join(cikti, 'harita.png')
    fig.savefig(yol_png, facecolor=YUZEY)
    plt.close(fig)
    return yol_png


# ── Grafik ──────────────────────────────────────────────────────────────────
def grafik(ucus, satirlar, cikti):
    v_ad = ucus.ham['varis'].get('ad', ucus.varis_kod)
    dilim = ucus.varis_dilim
    tablo = [s for s in satirlar if s['okuma_utc']]
    x = [zaman(s['okuma_utc']).astimezone(dilim).replace(tzinfo=None) for s in tablo]
    seriler = [('fr24_utc', 'Flightradar24 (esas)', MAVI, 2.4), ('gecmis_ort_utc', 'Geçmiş seferlerin ortalaması',
               TURUNCU, 2.0), ('konum_hiz_utc', 'Konum + hız (kaba)', SU, 2.0)]
    fig, ax = plt.subplots(figsize=(11, 5.6), dpi=150)
    fig.patch.set_facecolor(YUZEY)
    ax.set_facecolor(YUZEY)

    # Geçmiş seferlerin iniş aralığı (bugünkü kalkışa göre) — gölge
    kalkis = next((zaman(s['kalkis_utc']) for s in reversed(tablo) if s['kalkis_utc']), None)
    try:
        with open(os.path.join(k.KOK, 'veri', f'{ucus.etiket}-{ucus.kalkis_kod}-{ucus.varis_kod}.json'),
                  encoding='utf-8') as f:
            gecmis = json.load(f)['seferler'][:20]
    except FileNotFoundError:
        gecmis = []
    if kalkis and gecmis:
        sureler = [(g['varis_ts'] - g['kalkis_ts']) / 60 for g in gecmis]
        alt_s = (kalkis + timedelta(minutes=min(sureler))).astimezone(dilim).replace(tzinfo=None)
        ust_s = (kalkis + timedelta(minutes=max(sureler))).astimezone(dilim).replace(tzinfo=None)
        ax.axhspan(alt_s, ust_s, color=TURUNCU, alpha=0.08, zorder=0, linewidth=0)
        ax.text(x[0], ust_s, f'  geçmiş {len(gecmis)} seferin iniş aralığı (bugünkü kalkışla)', fontsize=9,
                color=IKINCIL, va='bottom')

    tarife = ucus.plan_varis.astimezone(dilim).replace(tzinfo=None)
    ax.axhline(tarife, color=SOLUK, linewidth=1.2, linestyle=(0, (4, 3)), zorder=1)
    ax.text(x[-1], tarife, f'  Tarife {tarife:%H:%M}', fontsize=10, color=IKINCIL, va='bottom', ha='left')

    for alan, ad, renk, kalinlik in seriler:
        noktalar = [(xx, zaman(s[alan]).astimezone(dilim).replace(tzinfo=None))
                    for xx, s in zip(x, tablo) if s[alan]]
        if not noktalar:
            continue
        xs, ys = zip(*noktalar)
        ax.plot(xs, ys, color=renk, linewidth=kalinlik, marker='o', markersize=6.5, markeredgecolor=YUZEY,
                markeredgewidth=1.5, label=ad, zorder=3)
        ax.annotate(f'{ys[-1]:%H:%M}', xy=(xs[-1], ys[-1]), xytext=(8, 0), textcoords='offset points',
                    fontsize=10.5, color=MUREKKEP, va='center', fontweight='bold')

    ax.yaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    ax.yaxis.set_major_locator(mdates.MinuteLocator(byminute=range(0, 60, 15)))
    ax.grid(axis='y', color='#e4e3df', linewidth=0.8)
    ax.grid(axis='x', visible=False)
    for kenar in ('top', 'right', 'left'):
        ax.spines[kenar].set_visible(False)
    ax.spines['bottom'].set_color('#c9c8c2')
    ax.tick_params(colors=IKINCIL, labelsize=9.5, length=0)
    ax.set_xlabel(f'Okuma saati ({v_ad})', color=IKINCIL, fontsize=10)
    sag = x[-1] + (x[-1] - x[0]) * 0.18
    ax.set_xlim(x[0] - (x[-1] - x[0]) * 0.03, sag)
    fig.text(0.015, 0.965, f'{ucus.etiket} · Tahmini iniş saati nasıl değişti ({v_ad})', fontsize=14,
             fontweight='bold', color=MUREKKEP, va='top')
    fig.text(0.015, 0.905, 'Her nokta bir okuma; çizgi sonundaki saat en son tahmin', fontsize=10.5,
             color=IKINCIL, va='top')
    ax.legend(loc='upper left', bbox_to_anchor=(0, -0.13), ncol=3, frameon=False, fontsize=9.5,
              labelcolor=IKINCIL)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.84, bottom=0.2)
    yol_png = os.path.join(cikti, 'grafik.png')
    fig.savefig(yol_png, facecolor=YUZEY)
    plt.close(fig)
    return yol_png


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--dunya', required=True, help='world-atlas countries-50m.json (ya da -110m)')
    ap.add_argument('--cikti', default='.', help='PNG dizini')
    a = ap.parse_args()
    ucus = k.ucus_yukle()
    satirlar, iz = izlem_oku(ucus)
    os.makedirs(a.cikti, exist_ok=True)
    print(harita(ucus, satirlar, iz, topojson_ulkeler(a.dunya), a.cikti))
    print(grafik(ucus, satirlar, a.cikti))
    return 0


if __name__ == '__main__':
    sys.exit(main())
