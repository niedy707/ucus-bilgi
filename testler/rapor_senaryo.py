"""rapor.py senaryoları (taklit veri): python3 testler/rapor_senaryo.py [--gecmis]
1) her kaynak var, İstanbul kapalı → FR24 esas · 2) FR24 çöktü → Haneda'dan kalkış, ADS-B konum, geçmiş ortalama esas.
Önbellek geçici dizine yazılır; depodaki veri/ değişmez."""
import json
import shutil
import os
import sys
import tempfile

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)
GECICI = tempfile.mkdtemp(prefix='ucus-takip-test-')
import kaynaklar as k  # noqa: E402
D = GECICI
shutil.copy(os.path.join(KOK, 'ucus.json'), D)
k.KOK = D
from datetime import datetime
T = lambda s: int(datetime.fromisoformat(s).timestamp())
kalkis = T('2026-10-11T23:50:00+00:00')
iz = [{'lat': 35.55 + i * 0.05, 'lng': 139.78 - i * 0.6, 'alt': 31000, 'spd': 415, 'ts': kalkis + i * 360} for i in range(30)][::-1]
def sahte(url, *a, **kw):
    if 'search/web/find' in url: return {'results': [{'type': 'live', 'id': 'abc'}]}
    if 'clickhandler' in url: return {'time': {'real': {'departure': kalkis}, 'estimated': {'arrival': T('2026-10-12T12:17:00+00:00')}}, 'trail': iz, 'status': {'text': 'Estimated- 15:17'}}
    if 'flight/list.json' in url: return {'result': {'response': {'page': {'total': 1}, 'data': [
        {'time': {'real': {'departure': T('2026-10-09T23:41:00+00:00'), 'arrival': T('2026-10-10T12:22:00+00:00')}, 'scheduled': {'departure': T('2026-10-09T23:25:00+00:00')}}, 'airport': {'origin': {'code': {'iata': 'HND'}}, 'destination': {'code': {'iata': 'IST'}}}, 'aircraft': {'registration': 'JA822A'}},
        {'time': {'real': {'departure': T('2026-10-06T23:43:00+00:00'), 'arrival': T('2026-10-07T12:15:00+00:00')}, 'scheduled': {'departure': T('2026-10-06T23:25:00+00:00')}}, 'airport': {'origin': {'code': {'iata': 'HND'}}, 'destination': {'code': {'iata': 'IST'}}}, 'aircraft': {'registration': 'JA806A'}}]}}}
    if 'adsb.lol' in url: return {'ac': [{'lat': 38.8, 'lon': 115.1, 'alt_baro': 31500, 'gs': 418, 'track': 245, 'seen_pos': 1}]}
    if 'haneda' in url: return {'last_upd': '2026/10/12 11:40:00', 'flight_info': [{'定刻': '2026/10/12 08:25:00', '変更時刻': '2026/10/12 08:32:00', 'ターミナル区分': '2', 'ゲート番号コード': '73', 'チェックインカウンター番号': '', '備考コード': '17', '備考英名称': 'Departed', '備考和名称': '', '運航状態': '', 'AT': '', 'ET': '', '機種コード': '788', '航空会社': [{'ＡＬコード': 'ANA', '便名': '0219'}]}]}
    raise TimeoutError('The handshake operation timed out')
k.indir = sahte
os.environ['UCUS_SIMDI'] = '2026-10-12T05:48:00+03:00'
sys.argv = ['rapor.py'] + sys.argv[1:]
import rapor
rapor.main()
print('\n=== FR24 çöktü senaryosu ===')
eski = sahte
def bozuk(url, *a, **kw):
    if 'flightradar24' in url: raise TimeoutError('fr24 yok')
    return eski(url, *a, **kw)
k.indir = bozuk
rapor.main()
print('\nönbellek:', json.load(open(D + '/veri/NH219-HND-IST.json'))['seferler'].__len__())
