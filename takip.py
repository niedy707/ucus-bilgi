#!/usr/bin/env python3
"""takip.py — kapı, saat, gecikme, iptal, kalkış, iniş tahmini ve bagaj bandı değişikliklerinde Bark.

Uçuş ucus.json'dan okunur (UCUS_TANIM ile başka dosya). VPS'te /etc/cron.d/ucus-takip ile dakikada bir koşar;
değişiklik görünce Bark atar (bildirim.py). İlk kullanım: NH219 HND → IST, 12.10.2026.
Desteklenen kaynaklar: kalkış HANEDA, varış İSTANBUL (kaynaklar.py). Başka havalimanı → TODO.md.

Sözleşme (KURALLAR.md § 7):
  1. Kalkış görülene kadar her koşuda uçuşun kaydı Haneda verisinde bulunmalı ve veri taze olmalı;
     takip bitene kadar İstanbul verisinde bulunmalı. Bulunamayan koşu çıkış 1 ile biter; art arda
     KOR_ESIK kör koşuda Bark "takip kör" der, düzelince yine haber verir.
  2. Kanal: Bark (bildirim.py: BARK_URL ya da /root/scripts/bark.sh). Bark 200 dönmezse değişiklik bildirilmiş sayılmaz; anlık
     görüntü güncellenmez, sonraki koşuda yeniden denenir.
  3. Nabız: ucus.json "nabiz" saatinde durum özeti. O saatte bildirim gelmediyse takipçi çalışmıyordur.
  Kapanış: iniş görüldükten 90 dk sonra, en geç ucus.json "son_sinir"da cron dosyasını kendisi
  siler ve haber verir.

Kullanım:
  takip.py           normal koşu
  takip.py --kuru    Bark göndermez, cron dosyasına dokunmaz, ne göndereceğini yazdırır. Durum
                     dosyasını yalnız UCUS_TAKIP_DIZIN ile başka bir dizin verilmişse yazar
                     (deneme içindir); UCUS_TAKIP_SIMDI ile saat de taklit edilebilir.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import bildirim
from kaynaklar import hm, kisa, ucus_yukle
import kaynaklar

UCUS = ucus_yukle()
if (UCUS.kalkis_kod, UCUS.varis_kod) != ('HND', 'IST'):
    sys.exit(f'takip.py şimdilik yalnız HND → IST destekliyor (ucus.json: {UCUS.kalkis_kod} → {UCUS.varis_kod}); TODO.md')
ETIKET = UCUS.etiket
NABIZ = UCUS.nabiz
SON_SINIR = UCUS.son_sinir or (UCUS.plan_varis + timedelta(hours=15))
# Tarifedeki blok sürenin %70'i dolmadan "indi" sayılmaz (yanlış eşleşmeye karşı)
EN_ERKEN_INIS = UCUS.plan_kalkis + (UCUS.plan_varis - UCUS.plan_kalkis) * 0.7
INIS_SONRASI = timedelta(minutes=90)
KOR_ESIK = 3  # art arda kör koşu → Bark
BAYAT_DK = 60  # Haneda verisinin last_upd'si bundan eskiyse kör sayılır
ETA_ESIK_DK = 5  # İstanbul tahmini bundan az oynarsa bildirilmez

VARSAYILAN_DIZIN = '/opt/ucus-takip'
DIZIN = os.environ.get('UCUS_TAKIP_DIZIN', VARSAYILAN_DIZIN)
DURUM_DOSYA = os.path.join(DIZIN, 'durum.json')
CRON_DOSYA = os.environ.get('UCUS_TAKIP_CRON', '/etc/cron.d/ucus-takip')
KURU = '--kuru' in sys.argv
bildirim.KURU = KURU

simdi = datetime.now(timezone.utc)
if KURU and os.environ.get('UCUS_TAKIP_SIMDI'):
    simdi = datetime.fromisoformat(os.environ['UCUS_TAKIP_SIMDI']).astimezone(timezone.utc)

HND_DURUM = {
    '': 'planlandığı gibi', '10': 'planlandığı gibi', '11': 'check-in açık',
    '13': 'check-in kapandı', '14': 'biniş başladı', '15': 'son çağrı',
    '16': 'kapı kapandı', '17': 'kalktı',
}
IST_DURUM = {
    'landed': 'indi', 'arrived': 'vardı', 'delayed': 'gecikmeli', 'early': 'erken',
    'on time': 'zamanında', 'cancelled': 'iptal', 'canceled': 'iptal', 'expected': 'bekleniyor',
    'diverted': 'başka havalimanına yönlendirildi', 'baggage claim': 'bagaj alımı',
    'first bag': 'ilk bagaj bantta', 'last bag': 'son bagaj bantta',
}


def log(*parca):
    print(simdi.strftime('%Y-%m-%dT%H:%M:%SZ'), *parca, flush=True)


# ── Haneda ──────────────────────────────────────────────────────────────────
def hnd_oku():
    """Anlık görüntü; kayıt yoksa None. Veri bayatsa ValueError (saat taklidinde bayatlık bakılmaz)."""
    return kaynaklar.hnd_oku(UCUS, simdi, None if os.environ.get('UCUS_TAKIP_SIMDI') else BAYAT_DK)


def hhmm(s):
    return f'{s[:2]}:{s[2:]}' if len(s) == 4 and s.isdigit() else s


def fark_dk(eski, yeni, bicim):
    try:
        dk = round((datetime.strptime(yeni, bicim) - datetime.strptime(eski, bicim)).total_seconds() / 60)
    except ValueError:
        return None
    return dk


def fark_yazi(dk):
    if dk is None:
        return ''
    if dk == 0:
        return ' (planlanan saat)'
    return f' ({"+" if dk > 0 else "−"}{abs(dk)} dk)'


def hnd_durum_yazi(s):
    if s['iptal'] == 'C':
        return 'İPTAL'
    if s['kod'] in HND_DURUM:
        return HND_DURUM[s['kod']]
    return s['not_en'] or s['not_ja'] or f'kod {s["kod"]}'


def hnd_ozet(s):
    kalkis = hm(s['degisen'] or s['plan'])
    parca = [f'Kalkış {kalkis} (Tokyo)', f'T{s["terminal"] or "?"}',
             f'kapı {s["kapi"] or "belli değil"}', hnd_durum_yazi(s)]
    if s['kontuar']:
        parca.append(f'kontuar {s["kontuar"]}')
    return ' · '.join(parca)


def hnd_fark(e, y):
    """(öncelik, başlık, satır) listesi; öncelik küçükse başlığa o çıkar."""
    s = []
    kalkti = y['kod'] == '17'
    if y['iptal'] != e['iptal']:
        if y['iptal'] == 'C':
            s.append((0, 'İPTAL', 'Haneda verisinde uçuş iptal görünüyor. ANA uygulamasına bakın.'))
        elif e['iptal'] == 'C':
            s.append((0, 'İptal kalktı', 'Uçuş yeniden listede: ' + hnd_ozet(y)))
        else:
            s.append((1, 'Durum', f'İşletme durumu: {e["iptal"] or "—"} → {y["iptal"] or "—"}'))
    if y['terminal'] != e['terminal']:
        s.append((1, 'TERMİNAL DEĞİŞTİ', f'Terminal: {e["terminal"] or "—"} → {y["terminal"] or "—"}'))
    if y['plan'] != e['plan']:
        s.append((2, 'Saat değişti', f'Planlanan kalkış: {hm(e["plan"])} → {hm(y["plan"])}'))
    if y['degisen'] != e['degisen'] and not kalkti:
        eski, yeni = e['degisen'] or e['plan'], y['degisen'] or y['plan']
        dk = fark_dk(y['plan'], yeni, '%Y/%m/%d %H:%M:%S')
        s.append((2, 'Saat değişti', f'Kalkış: {hm(eski)} → {hm(yeni)}{fark_yazi(dk)}'))
    if y['et'] != e['et'] and y['et'] and not kalkti:
        s.append((2, 'Saat değişti', f'Tahmini kalkış: {hhmm(y["et"])}'))
    if y['kapi'] != e['kapi']:
        s.append((3, 'Kapı değişti' if e['kapi'] else 'Kapı belli oldu',
                  f'Kapı: {e["kapi"] or "—"} → {y["kapi"] or "—"}'))
    if y['kontuar'] != e['kontuar']:
        s.append((4, 'Check-in kontuarı', f'Check-in kontuarı: {e["kontuar"] or "—"} → {y["kontuar"] or "—"}'))
    if y['kod'] != e['kod'] or y['not_en'] != e['not_en']:
        if kalkti:
            saat = hhmm(y['at']) if y['at'] else hm(y['degisen'] or y['plan'])
            s.append((2, 'Kalktı', f'Kalkış {saat} (plan {hm(y["plan"])}), kapı {y["kapi"] or "—"}.'))
        else:
            yazi = hnd_durum_yazi(y)
            s.append((5, yazi[:1].upper() + yazi[1:], f'Durum: {hnd_durum_yazi(e)} → {yazi}'))
    if y['ucak'] != e['ucak']:
        s.append((6, 'Uçak tipi değişti', f'Uçak tipi: {e["ucak"] or "—"} → {y["ucak"] or "—"} (koltuk düzeni değişmiş olabilir)'))
    return s


# ── İstanbul ────────────────────────────────────────────────────────────────
def ist_oku():
    return kaynaklar.ist_oku(UCUS, varis=True)


def ist_durum_yazi(metin):
    if not metin:
        return '—'
    tr = IST_DURUM.get(metin.strip().lower())
    return f'{tr} ({metin})' if tr else metin


def ist_indi(s):
    m = (s['not'] + ' ' + s['bagaj']).lower()
    return any(k in m for k in ('land', 'arriv', 'bag')) or s['kod'] in ('LND', 'LAN', 'ARR')


def ist_ozet(s):
    parca = [f'İstanbul tahmini iniş {hm(s["tahmin"] or s["plan"])}']
    if s['not']:
        parca.append(ist_durum_yazi(s['not']))
    if s['bant']:
        parca.append(f'bagaj bandı {s["bant"]}')
    return ' · '.join(parca)


def ist_fark(e, y, bildirilen_tahmin):
    """(satırlar, yeni bildirilen tahmin). Küçük tahmin oynamaları bildirilmez."""
    s = []
    tahmin = y['tahmin'] or y['plan']
    dk = fark_dk(bildirilen_tahmin, tahmin, '%Y-%m-%dT%H:%M:%S') if bildirilen_tahmin else None
    if dk is not None and abs(dk) >= ETA_ESIK_DK:
        plana = fark_dk(y['plan'], tahmin, '%Y-%m-%dT%H:%M:%S')
        s.append((2, 'İstanbul iniş saati', f'Tahmini iniş (İstanbul): {hm(bildirilen_tahmin)} → {hm(tahmin)}{fark_yazi(plana)}'))
        bildirilen_tahmin = tahmin
    if y['not'] != e['not']:
        baslik = 'İstanbul: ' + ist_durum_yazi(y['not'])
        s.append((1 if 'cancel' in y['not'].lower() else 3, baslik,
                  f'İstanbul durumu: {ist_durum_yazi(e["not"])} → {ist_durum_yazi(y["not"])}'))
    if y['bant'] != e['bant']:
        s.append((3, 'Bagaj bandı', f'Bagaj bandı: {e["bant"] or "—"} → {y["bant"] or "—"}'))
    if y['bagaj'] != e['bagaj']:
        s.append((4, 'Bagaj', f'Bagaj: {ist_durum_yazi(e["bagaj"])} → {ist_durum_yazi(y["bagaj"])}'))
    if y['kapi'] != e['kapi']:
        s.append((5, 'İstanbul kapısı', f'İstanbul kapı: {e["kapi"] or "—"} → {y["kapi"] or "—"}'))
    return s, bildirilen_tahmin


# ── Bildirim ve durum ───────────────────────────────────────────────────────
def bark(baslik, mesaj):
    return bildirim.bark(baslik, mesaj)


def durum_yukle():
    try:
        with open(DURUM_DOSYA, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def durum_yaz(d):
    if KURU and DIZIN == VARSAYILAN_DIZIN:
        return
    os.makedirs(DIZIN, exist_ok=True)
    gecici = DURUM_DOSYA + '.gecici'
    with open(gecici, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(gecici, DURUM_DOSYA)


def cron_sil():
    if KURU:
        print(f'[kuru] cron dosyası silinirdi: {CRON_DOSYA}')
        return
    try:
        os.remove(CRON_DOSYA)
        log(f'cron dosyası silindi: {CRON_DOSYA}')
    except FileNotFoundError:
        pass


def main():
    d = durum_yukle()
    if d.get('bitti'):
        cron_sil()
        return 0
    kor = d.setdefault('kor', {'hnd': 0, 'ist': 0})
    kor_bildirildi = d.setdefault('kor_bildirildi', {'hnd': False, 'ist': False})
    hnd_eski, ist_eski = d.get('hnd'), d.get('ist')
    satirlar, sistem, eksik = [], [], False
    yeni = {}  # yalnız Bark başarılıysa işlenecek alanlar

    # Haneda: kalkış görüldükten sonra okunmaz
    kalkti = bool(hnd_eski and hnd_eski['kod'] == '17')
    hnd = hnd_eski
    if not kalkti:
        neden = None
        try:
            hnd = hnd_oku()
            if hnd is None:
                neden = f'{ETIKET} kaydı Haneda verisinde yok'
        except Exception as hata:  # noqa: BLE001
            neden = 'Haneda verisi okunamadı: ' + kisa(hata)
        if neden:
            hnd, eksik = hnd_eski, True
            kor['hnd'] += 1
            log('HND KÖR', kor['hnd'], neden)
            if kor['hnd'] >= KOR_ESIK and not kor_bildirildi['hnd']:
                sistem.append((1, 'Takip kör', f'Haneda kaynağı {kor["hnd"]} koşudur okunamıyor: {neden}. ANA uygulamasından bakın.'))
                yeni['kor_hnd'] = True
        else:
            kor['hnd'] = 0
            if kor_bildirildi['hnd']:
                sistem.append((6, 'Takip düzeldi', 'Haneda kaynağı yeniden okunuyor.'))
                yeni['kor_hnd'] = False
            if hnd_eski is not None:
                satirlar += hnd_fark(hnd_eski, hnd)
            yeni['hnd'] = hnd

    # İstanbul
    ist, neden = ist_eski, None
    try:
        ist = ist_oku()
        if ist is None:
            neden = f'{ETIKET} kaydı İstanbul varış verisinde yok'
    except Exception as hata:  # noqa: BLE001
        neden = 'İstanbul verisi okunamadı: ' + kisa(hata)
    if neden:
        ist, eksik = ist_eski, True
        kor['ist'] += 1
        log('IST KÖR', kor['ist'], neden)
        if kor['ist'] >= KOR_ESIK and not kor_bildirildi['ist']:
            sistem.append((1, 'Takip kör', f'İstanbul kaynağı {kor["ist"]} koşudur okunamıyor: {neden}.'))
            yeni['kor_ist'] = True
    else:
        kor['ist'] = 0
        if kor_bildirildi['ist']:
            sistem.append((6, 'Takip düzeldi', 'İstanbul kaynağı yeniden okunuyor.'))
            yeni['kor_ist'] = False
        if ist_eski is not None:
            fark, bt = ist_fark(ist_eski, ist, d.get('ist_tahmin') or ist_eski['tahmin'] or ist_eski['plan'])
            satirlar += fark
            yeni['ist_tahmin'] = bt
        else:
            yeni['ist_tahmin'] = ist['tahmin'] or ist['plan']
        yeni['ist'] = ist
        if ist_indi(ist) and simdi >= EN_ERKEN_INIS and not d.get('inis_goruldu'):
            yeni['inis_goruldu'] = simdi.isoformat()

    ozet = '\n'.join(p for p in (hnd_ozet(hnd) if hnd else 'Haneda: veri yok',
                                 ist_ozet(ist) if ist else 'İstanbul: veri yok') if p)

    # Başlangıç, nabız, kapanış
    if not d.get('basladi'):
        sistem.append((7, 'Takip başladı', ozet + (f'\nDeğişiklik olursa bildirim gelir; {NABIZ.astimezone(UCUS.kalkis_dilim):%H:%M}\'te '
                         f'({UCUS.ham["kalkis"].get("ad", UCUS.kalkis_kod)}) durum özeti atılır.' if NABIZ else '')))
        yeni['basladi'] = True
    elif NABIZ and simdi >= NABIZ and not d.get('nabiz') and not kalkti:
        sistem.append((7, 'Sabah durumu', ozet))
        yeni['nabiz'] = True
    inis = d.get('inis_goruldu')
    bitir = simdi >= SON_SINIR or bool(inis and simdi - datetime.fromisoformat(inis) >= INIS_SONRASI)
    if bitir:
        gorulen = 'İniş görüldü.' if inis else 'İniş görülmeden süre sınırı doldu.'
        sistem.append((8, 'Takip kapandı', f'{gorulen} {ozet}\nZamanlayıcı VPS\'ten kaldırıldı.'))

    log('HND[' + (hnd_ozet(hnd) if hnd else 'yok') + '] IST[' + (ist_ozet(ist) if ist else 'yok') + ']',
        f'değişiklik={len(satirlar)} sistem={len(sistem)}')

    hepsi = sorted(satirlar + sistem, key=lambda x: x[0])
    gonderildi = True
    if hepsi:
        baslik = f'✈️ {ETIKET} · {hepsi[0][1]}'
        gonderildi = bark(baslik, '\n'.join(x[2] for x in hepsi))
        for x in hepsi:
            log('  →', x[1], '|', x[2].replace('\n', ' / '), '' if gonderildi else '(GÖNDERİLEMEDİ)')

    if gonderildi:
        for k in ('hnd', 'ist', 'ist_tahmin', 'inis_goruldu', 'basladi', 'nabiz'):
            if k in yeni:
                d[k] = yeni[k]
        for k in ('hnd', 'ist'):
            if 'kor_' + k in yeni:
                kor_bildirildi[k] = yeni['kor_' + k]
    if bitir and (gonderildi or simdi >= SON_SINIR + timedelta(minutes=30)):
        d['bitti'] = simdi.isoformat()
        cron_sil()
    durum_yaz(d)
    return 1 if (eksik or not gonderildi) else 0


if __name__ == '__main__':
    sys.exit(main())
