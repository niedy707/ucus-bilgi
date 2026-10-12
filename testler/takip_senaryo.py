"""takip.py senaryoları (taklit veri, Bark gönderilmez): python3 testler/takip_senaryo.py
Beklenen: Takip başladı → Kapı değişti → Kalktı + İstanbul iniş saati → (2 dk oynama: sessiz) → indi →
Bagaj bandı + Takip kapandı. ucus.json'daki NH219 tanımına göre yazılmıştır."""
import os
import sys
import tempfile

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)
GECICI = tempfile.mkdtemp(prefix='ucus-takip-test-')
DIZIN = os.path.join(GECICI, 'durum')
os.environ['UCUS_TAKIP_DIZIN'] = DIZIN
os.environ['UCUS_TAKIP_CRON'] = DIZIN + '/cron'
sys.argv = ['takip.py', '--kuru']
import kaynaklar

def hnd(kod='11', kapi='73', degisen='', last='2026/10/12 07:00:00'):
    return {'last_upd': last, 'flight_info': [{'定刻': '2026/10/12 08:25:00', '変更時刻': degisen, 'ターミナル区分': '2',
        'ゲート番号コード': kapi, 'チェックインカウンター番号': 'P', '備考コード': kod, '備考英名称': '', '備考和名称': '',
        '運航状態': '', 'AT': '', 'ET': '', '機種コード': '788', '航空会社': [{'ＡＬコード': 'ANA', '便名': '0219'}]}]}
def ist(tahmin='2026-10-12T15:35:00', remark='', bant=''):
    return {'result': {'data': {'flights': [{'flightNumber': 'NH219', 'fromCityCode': 'HND',
        'scheduledDatetime': '2026-10-12T15:35:00', 'estimatedDatetime': tahmin, 'gate': '', 'carousel': bant,
        'remarkCode': '', 'remark': remark, 'baggageRemark': ''}]}}}

def kos(simdi, h, i):
    os.environ['UCUS_TAKIP_SIMDI'] = simdi
    kaynaklar.indir = lambda url, *a, **k: h if 'haneda' in url else i
    if 'takip' in sys.modules: del sys.modules['takip']
    import takip
    print(f'--- {simdi}'); rc = takip.main(); print('rc', rc)

kos('2026-10-12T07:00:00+09:00', hnd(), ist())                          # başlangıç
kos('2026-10-12T07:30:00+09:00', hnd(kapi='74'), ist())                 # kapı değişti
kos('2026-10-12T08:35:00+09:00', hnd(kod='17', kapi='74', degisen='2026/10/12 08:32:00'), ist(tahmin='2026-10-12T15:20:00'))  # kalktı + ETA
kos('2026-10-12T15:10:00+03:00', hnd(kod='17'), ist(tahmin='2026-10-12T15:18:00'))  # 2 dk oynama: bildirim yok
kos('2026-10-12T15:19:00+03:00', hnd(kod='17'), ist(tahmin='2026-10-12T15:18:00', remark='Landed'))  # indi
kos('2026-10-12T16:50:00+03:00', hnd(kod='17'), ist(tahmin='2026-10-12T15:18:00', remark='Landed', bant='7'))  # kapanış
