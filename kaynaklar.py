"""Uçuş verisi kaynakları — yalnız standart kitaplık.

Hepsi belgelenmemiş, anahtarsız uçlar (ayrıntı ve tuzaklar: COZUMLER.md):
  Haneda kalkış   GET  tokyo-haneda.com/app_resource/flight/data/int/hdacfdep.json
  İstanbul        POST www.istairport.com/umbraco/api/FlightInfo/GetFlightStatusBoard
  Flightradar24   GET  www.flightradar24.com/v1/search/web/find  →  data-live…/clickhandler
                  GET  api.flightradar24.com/common/v1/flight/list.json  (geçmiş, ~7 gün)
  ADS-B           GET  api.adsb.lol/v2/callsign/<çağrı adı>
Her okuyucu bulamazsa None döner, okuyamazsa istisna fırlatır; çağıran ayırt eder.
"""
import gzip
import json
import math
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
KOK = os.path.dirname(os.path.abspath(__file__))
HAVALIMANI = {  # mesafe hesabı için; yeni havalimanı gerekirse buraya
    'HND': (35.5494, 139.7798), 'NRT': (35.7720, 140.3929), 'KIX': (34.4347, 135.2440),
    'IST': (41.2753, 28.7519), 'SAW': (40.8986, 29.3092),
}


# ── Uçuş tanımı ─────────────────────────────────────────────────────────────
class Ucus:
    """ucus.json'daki tanım. Saatler ilgili havalimanının yerel saatiyle yazılır."""

    def __init__(self, d):
        self.ham = d
        self.etiket = d['etiket']                      # NH219
        self.iata, self.icao, self.numara = d['iata'], d['icao'], str(d['numara'])
        self.cagri = d.get('cagri') or f'{self.icao}{self.numara}'   # ADS-B çağrı adı: ANA219
        k, v = d['kalkis'], d['varis']
        self.kalkis_kod, self.varis_kod = k['iata'], v['iata']
        self.kalkis_dilim, self.varis_dilim = ZoneInfo(k['dilim']), ZoneInfo(v['dilim'])
        self.plan_kalkis = datetime.fromisoformat(k['plan']).replace(tzinfo=self.kalkis_dilim)
        self.plan_varis = datetime.fromisoformat(v['plan']).replace(tzinfo=self.varis_dilim)
        self.varis_konum = tuple(v.get('konum') or HAVALIMANI[self.varis_kod])
        self.kalkis_konum = tuple(k.get('konum') or HAVALIMANI[self.kalkis_kod])
        self.nabiz = _zaman(d.get('nabiz'))            # takip.py: o saatte durum özeti
        self.son_sinir = _zaman(d.get('son_sinir'))    # takip.py: en geç kapanış

    def kalkis_saat(self, ts):
        return datetime.fromtimestamp(ts, timezone.utc).astimezone(self.kalkis_dilim)

    def varis_saat(self, ts):
        return datetime.fromtimestamp(ts, timezone.utc).astimezone(self.varis_dilim)


def _zaman(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')) if s else None


def ucus_yukle(yol=None):
    yol = yol or os.environ.get('UCUS_TANIM') or os.path.join(KOK, 'ucus.json')
    with open(yol, encoding='utf-8') as f:
        return Ucus(json.load(f))


# ── Yardımcılar ─────────────────────────────────────────────────────────────
def indir(url, veri=None, basliklar=None, zaman_asimi=25):
    b = {'User-Agent': UA, 'Accept-Encoding': 'gzip'}
    b.update(basliklar or {})
    istek = urllib.request.Request(url, data=veri, headers=b)
    with urllib.request.urlopen(istek, timeout=zaman_asimi) as yanit:
        govde = yanit.read()
        if yanit.headers.get('Content-Encoding') == 'gzip':
            govde = gzip.decompress(govde)
    return json.loads(govde.decode('utf-8'))


def kisa(hata):
    """Hata metni; URL'ler (anahtar içerebilir) gizlenir."""
    return re.sub(r'https?://\S+', '<url>', f'{type(hata).__name__}: {hata}')[:140]


def mesafe_km(e1, b1, e2, b2):
    e1, b1, e2, b2 = map(math.radians, (e1, b1, e2, b2))
    a = math.sin((e2 - e1) / 2) ** 2 + math.cos(e1) * math.cos(e2) * math.sin((b2 - b1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


def hm(s):
    """'2026/10/12 08:25:00' ya da '2026-10-12T15:35:00' → '08:25'."""
    return s[11:16] if s and len(s) >= 16 else (s or '—')


# ── Haneda (yalnız kalkış) ──────────────────────────────────────────────────
HND_URL = 'https://tokyo-haneda.com/app_resource/flight/data/int/hdacfdep.json'


def hnd_oku(ucus, simdi=None, bayat_dk=60):
    """Haneda uluslararası kalkış verisinde uçuşun anlık görüntüsü; yoksa None, bayatsa ValueError."""
    d = indir(HND_URL)
    jst = ZoneInfo('Asia/Tokyo')
    guncel = datetime.strptime(d['last_upd'], '%Y/%m/%d %H:%M:%S').replace(tzinfo=jst)
    yas = ((simdi or datetime.now(timezone.utc)) - guncel).total_seconds() / 60
    if bayat_dk and yas > bayat_dk:
        raise ValueError(f'veri {yas:.0f} dk bayat (last_upd {d["last_upd"]})')
    gun = ucus.plan_kalkis.strftime('%Y/%m/%d')
    for f in d['flight_info']:
        if not f.get('定刻', '').startswith(gun):
            continue
        # Alan ADI tam genişlikli (ＡＬコード), değeri ASCII ICAO kodu (ANA); uçuş no başında sıfırla (0219)
        if any(a.get('ＡＬコード') == ucus.icao and a.get('便名', '').lstrip('0') == ucus.numara
               for a in f.get('航空会社', [])):
            return {
                'plan': f.get('定刻', ''), 'degisen': f.get('変更時刻', ''),
                'terminal': f.get('ターミナル区分', ''), 'kapi': f.get('ゲート番号コード', ''),
                'kontuar': f.get('チェックインカウンター番号', ''), 'kod': f.get('備考コード', ''),
                'not_en': f.get('備考英名称', ''), 'not_ja': f.get('備考和名称', ''),
                'iptal': f.get('運航状態', ''), 'at': f.get('AT', ''), 'et': f.get('ET', ''),
                'ucak': f.get('機種コード', ''),
            }
    return None


# ── İstanbul Havalimanı (varış; nature=1 ile kalkış) ────────────────────────
IST_URL = 'https://www.istairport.com/umbraco/api/FlightInfo/GetFlightStatusBoard'


def ist_oku(ucus, varis=True):
    """Varış (nature=0) ya da kalkış (nature=1) kaydı; yoksa None.
    Dikkat: GitHub Actions IP'lerinden TLS el sıkışması zaman aşımına düşüyor; VPS'ten çalışıyor."""
    gun = (ucus.plan_varis if varis else ucus.plan_kalkis).strftime('%Y-%m-%d')
    govde = urllib.parse.urlencode({
        'nature': 0 if varis else 1, 'searchTerm': ucus.etiket, 'pageSize': 20, 'isInternational': 1,
        'date': gun, 'endDate': gun, 'culture': 'en', 'clickedButton': '',
    }).encode()
    yol = 'arriving-flights' if varis else 'departing-flights'
    d = indir(IST_URL, govde, {
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Referer': f'https://www.istairport.com/en/flights/flight-info/{yol}/',
        'Origin': 'https://www.istairport.com', 'X-Requested-With': 'XMLHttpRequest',
    })
    karsi = ucus.kalkis_kod if varis else ucus.varis_kod
    for f in d['result']['data']['flights']:
        no = f.get('flightNumber') or ''
        karsi_kod = f.get('fromCityCode') if varis else f.get('toCityCode')
        if (no[:2] == ucus.iata and no[2:].lstrip('0') == ucus.numara and karsi_kod == karsi
                and (f.get('scheduledDatetime') or '').startswith(gun)):
            return {
                'plan': f.get('scheduledDatetime') or '', 'tahmin': f.get('estimatedDatetime') or '',
                'kapi': f.get('gate') or '', 'bant': f.get('carousel') or '',
                'kod': f.get('remarkCode') or '', 'not': f.get('remark') or '',
                'bagaj': f.get('baggageRemark') or '',
            }
    return None


# ── Flightradar24 ───────────────────────────────────────────────────────────
def fr24_canli(ucus):
    """Havadaki (ya da yeni kalkmış/inmiş) uçuşun FR24 görüntüsü; canlı kayıt yoksa None.
    Dönen: id, kalkis/varis_ts (gerçek), tahmin_ts, konum (son iz noktası), iz (eskiden yeniye)."""
    ara = indir(f'https://www.flightradar24.com/v1/search/web/find?query={ucus.etiket}&limit=10')
    canli = [r for r in ara.get('results') or [] if r.get('type') == 'live']
    if not canli:
        return None
    fid = canli[0]['id']
    d = indir(f'https://data-live.flightradar24.com/clickhandler/?version=1.5&flight={fid}')
    t = d.get('time') or {}
    iz = [(p['lat'], p['lng'], p.get('alt'), p.get('spd'), p.get('ts'))
          for p in reversed(d.get('trail') or []) if 'lat' in p and 'lng' in p]
    kapi = (((d.get('airport') or {}).get('origin') or {}).get('info') or {}).get('gate')
    return {
        'id': fid,
        'kalkis_ts': (t.get('real') or {}).get('departure'),
        'varis_ts': (t.get('real') or {}).get('arrival'),
        'tahmin_ts': (t.get('estimated') or {}).get('arrival') or (t.get('other') or {}).get('eta'),
        'durum': ((d.get('status') or {}).get('text') or ''),
        'kapi': kapi or '',
        'iz': iz,
        'konum': iz[-1] if iz else None,
    }


def fr24_gecmis(ucus, sayfa_siniri=5):
    """Tamamlanmış seferler (kalkış→varış eşleşenler), yeniden eskiye. Ücretsiz uç ~7 gün verir."""
    url = ('https://api.flightradar24.com/common/v1/flight/list.json'
           f'?query={ucus.etiket}&fetchBy=flight&page={{sayfa}}&limit=100')
    seferler, goruldu, sayfa, toplam = [], set(), 1, 1
    while sayfa <= min(toplam, sayfa_siniri):
        d = indir(url.format(sayfa=sayfa))['result']['response']
        toplam = (d.get('page') or {}).get('total') or 1
        for u in d.get('data') or []:
            t = u.get('time') or {}
            kalkis, varis = (t.get('real') or {}).get('departure'), (t.get('real') or {}).get('arrival')
            a = u.get('airport') or {}
            nereden = ((a.get('origin') or {}).get('code') or {}).get('iata')
            nereye = ((a.get('destination') or {}).get('code') or {}).get('iata')
            if (nereden, nereye) != (ucus.kalkis_kod, ucus.varis_kod) or not kalkis or not varis:
                continue
            if kalkis in goruldu:
                continue
            goruldu.add(kalkis)
            plan = (t.get('scheduled') or {}).get('departure')
            seferler.append({
                'kalkis_ts': kalkis, 'varis_ts': varis, 'plan_kalkis_ts': plan,
                'tescil': (u.get('aircraft') or {}).get('registration') or '',
            })
        sayfa += 1
    return sorted(seferler, key=lambda s: s['kalkis_ts'], reverse=True)


# ── ADS-B (yer istasyonu kapsamındaysa) ─────────────────────────────────────
def adsb_oku(ucus):
    d = indir(f'https://api.adsb.lol/v2/callsign/{ucus.cagri}')
    ac = d.get('ac') or []
    if not ac:
        return None
    a = ac[0]
    if a.get('lat') is None:
        return None
    return {'lat': a['lat'], 'lon': a['lon'], 'alt': a.get('alt_baro'), 'gs': a.get('gs'),
            'yon': a.get('track'), 'yas_sn': a.get('seen_pos')}
