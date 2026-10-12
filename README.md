# ucus-bilgi

Uçuşlarla ilgili iki şey bir arada:

1. **Havayolu notları** ([`havayollari/`](havayollari/)): uçakta bizzat görülen, valiz hazırlarken işe yarayan
   ayrıntılar (şarj, kulaklık, internet). Şimdilik: [ANA](havayollari/ANA.md).
2. **Uçuş takip aracı** (kök dizin): bir uçuşun anlık durum raporu ve değişiklik bildirimi (Bark). Yalnız Python
   standart kitaplığı kullanılıyor, kurulacak paket yok. İlk kullanım: **NH219 Tokyo Haneda → İstanbul, 12.10.2026**.

Takip aracının sunucudaki adı `ucus-takip`'tir (dizin, cron dosyası, log); depo 12.10.2026'da `ucus-bilgi` adıyla açıldı.

## Havayolu notları

Her havayolu için bir dosya: `havayollari/<AD>.md`. Gözlem ile havayolunun kendi yayımladığı bilgi ayrı bölümlerde
durur; her bölümün başında **tarih, uçuş ve kabin sınıfı** yazar. Yeni gözlem eskisinin üstüne eklenir, eskisi silinmez.

| Havayolu | İçerik |
|---|---|
| [ANA](havayollari/ANA.md) | Ekonomide koltuk ekranında yalnız USB-A · kulaklık için kablo · uçak içi internet |

## Uçuş takip aracı

| Dosya | İş |
|---|---|
| [`rapor.py`](rapor.py) | **Anlık durum raporu.** Kalkış, geçen süre, tahmini uçuş süresi, yüzde, kalan süre, tahmini iniş, konum, geçmiş sefer ortalaması. Tek seferlik okuma. |
| [`takip.py`](takip.py) | **Değişiklik takipçisi.** Kapı, terminal, saat, gecikme, iptal, kalkış, iniş tahmini (≥5 dk), iniş ve bagaj bandı değişince **Bark** gönderir. Cron'dan dakikada bir koşar, iş bitince kendini kaldırır. |
| [`kaynaklar.py`](kaynaklar.py) | Veri okuyucular: Haneda, İstanbul Havalimanı, Flightradar24 (canlı + geçmiş), ADS-B (adsb.lol). |
| [`bildirim.py`](bildirim.py) | Bark: `UCUS_TAKIP_BARK_URL` (HTTP) ya da `/root/scripts/bark.sh`. |
| [`ucus.json`](ucus.json) | **İzlenen uçuşun tanımı.** Yeni uçuş için yalnız bu değişir. |
| `veri/` | Geçmiş sefer önbelleği (FR24 yalnız ~7 gün veriyor; burada birikir). Actions kendisi işler. |
| [`.github/workflows/rapor.yml`](.github/workflows/rapor.yml) | Raporu GitHub Actions'ta üretir (elle ya da Claude'dan tetiklenir). |
| [`kurulum/ucus-takip.cron`](kurulum/ucus-takip.cron) | takip.py için `/etc/cron.d` dosyası. |
| `testler/` | Taklit veriyle senaryolar: `python3 testler/takip_senaryo.py`, `python3 testler/rapor_senaryo.py --gecmis`. |

Veri uçları ve tuzakları: [`COZUMLER.md`](COZUMLER.md). Bekleyen işler: [`TODO.md`](TODO.md).

## Yeni bir uçuş

`ucus.json`'u düzenle. Saatler ilgili havalimanının **yerel** saatiyle yazılır. `ad`, raporda saat diliminin adı olarak
görünür. `nabiz`, takip.py'nin "durum özeti" attığı an; `son_sinir` ise en geç kapanacağı an.

```json
{"etiket": "NH219", "havayolu": "ANA", "iata": "NH", "icao": "ANA", "numara": "219",
 "kalkis": {"iata": "HND", "dilim": "Asia/Tokyo", "ad": "Tokyo", "plan": "2026-10-12T08:25"},
 "varis": {"iata": "IST", "dilim": "Europe/Istanbul", "ad": "TR", "plan": "2026-10-12T15:35"},
 "nabiz": "2026-10-12T04:45:00+09:00", "son_sinir": "2026-10-13T06:00:00Z"}
```

Mesafe hesabı için havalimanı `kaynaklar.HAVALIMANI`'nda yoksa `"konum": [enlem, boylam]` ekle.
**takip.py şimdilik yalnız HND → IST'yi destekliyor** (kaynakları bu iki havalimanına özgü); rapor.py her uçuşta
çalışır (FR24 + ADS-B), yalnız Haneda ve İstanbul satırları o havalimanlarında dolar.

## Rapor

Kalkış saati hem kalkış hem varış saatiyle yazılır. Öteki bütün saatler **varış yerinin** saatiyle.

**Tahmini iniş** için ilk bulunan kaynak esas alınır, ötekiler "yedek tahminler" olarak altına yazılır:

1. **Flightradar24**: esas kaynak.
2. **Varış havalimanının tahmini**: şimdilik yalnız İstanbul. GitHub Actions'tan okunamıyor, VPS'ten okunuyor.
3. **Geçmiş sefer ortalaması**: kalkış + son ≤20 seferin ortalama havada kalma süresi.
4. **Konum + hız (kaba)**: kalan kuş uçuşu mesafe × 1,05 rota payı ÷ şimdiki yer hızı + 10 dk. Hedefe 2.000 km'den
   az kalınca 3'ün önüne geçer.
5. **Tarife**.

**Kalkış anı** sırası: FR24 gerçek kalkış (tekerlek kesme) → Haneda kapıdan ayrılış + 18 dk taksi → tarife + geçmiş
ortalama gecikme.

**Yüzde** iki türlü verilir:
- *zamana göre*: geçen süre ÷ (tahmini iniş − kalkış).
- *konuma göre*: uçulan iz ÷ (uçulan iz + kalan kuş uçuşu mesafe). Kalan kısım kuş uçuşu olduğu için bu oran biraz
  iyimserdir.

Raporu almanın üç yolu:
- **GitHub'da:** Actions → *rapor* → Run workflow. Rapor işin özet sayfasında görünür. *tablo* seçilirse seferler
  tek tek yazılır; *bildir* seçilirse rapor Bark ile de gelir (depo sırrı `BARK_URL` gerekir).
- **Claude bulut oturumundan:** `actions_run_trigger` (run_workflow, `rapor.yml`, ref `main`) → ~40 sn →
  `list_workflow_runs` → `list_workflow_jobs` → `get_job_logs` (`return_content`). Gerekçesi COZUMLER.md'de.
- **Yerelde / VPS'te:** `python3 rapor.py [--gecmis] [--bildir]`.

## Takip (Bark)

VPS'e ya da pi63'e kurulur. İstanbul Havalimanı kaynağı GitHub Actions'tan okunamadığı için Actions'a kurulmaz.

```bash
ssh vps 'mkdir -p /opt/ucus-takip'
scp takip.py kaynaklar.py bildirim.py ucus.json vps:/opt/ucus-takip/
ssh vps 'cd /opt/ucus-takip && UCUS_TAKIP_DIZIN=/tmp/ut-deneme python3 takip.py --kuru'   # Bark göndermeden dene
scp kurulum/ucus-takip.cron vps:/etc/cron.d/ucus-takip                                     # başlat
ssh vps 'tail -f /var/log/ucus-takip.log'
```

- Kurulunca hemen "Takip başladı" bildirimi gelir. `nabiz` saatinde de durum özeti gelir; gelmezse takipçi
  çalışmıyordur.
- Kaynak art arda 3 kez okunamazsa "takip kör" bildirimi gelir.
- Takipçi iniş + 90 dk'da, en geç `son_sinir`'de cron dosyasını kendisi siler. Erken durdurmak için:
  `ssh vps 'rm /etc/cron.d/ucus-takip'`.
- Durum dosyası: `/opt/ucus-takip/durum.json`. Yeni uçuştan önce bu dosyayı sil.

## Bu depo herkese açık

- **Yazılmaz:** yolcu adı, rezervasyon kodu, koltuk numarası, e-bilet, Bark anahtarı, sunucu adresi. Örnek ve test
  verisi de bunları taşımaz.
- Bark anahtarı yalnız depo sırrı `BARK_URL` ya da sunucudaki betik üzerinden kullanılır; hiçbir dosyaya girmez.
- Commit yazarı GitHub'ın gizli e-posta adresidir.

## Ön tarama (12.10.2026)

Kod, depo açılmadan önce uçuş sırasında yazıldı; benzer iş taraması depo açılırken yapıldı. Her aday açılıp okundu.

| Depo | Ne yapıyor | Durum | Lisans | Bize yarar mı |
|---|---|---|---|---|
| [JeanExtreme002/FlightRadarAPI](https://github.com/JeanExtreme002/FlightRadarAPI) | Flightradar24 için resmî olmayan SDK (Python, Node.js, Go) | ★430, son push 09.10.2026, canlı | MIT | **Başvuru kaynağı.** Bizimle aynı anahtarsız uçları kullanıyor (`/v1/search/web/find`, `clickhandler`, `common/v1`). Uç değişirse ilk bakılacak yer |
| [Flightradar24/fr24api-sdk-python](https://github.com/Flightradar24/fr24api-sdk-python) | Flightradar24'ün resmî API istemcisi | ★28, son push 03.06.2026 | MIT | Şimdilik hayır: `FR24_API_TOKEN` (ücretli abonelik) istiyor. 7 günden eski sefer geçmişi gerekirse seçenek |
| [AlexandrErohin/home-assistant-flightradar24](https://github.com/AlexandrErohin/home-assistant-flightradar24) | Home Assistant eklentisi: bölgedeki uçuşlar, belirli uçağı izleme, otomasyonla bildirim | ★550, son push 06.10.2026, canlı | MIT | Hayır: Home Assistant kurulumu gerektirir; kapı ve bagaj bandı yok |
| [johanohly/AirTrail](https://github.com/johanohly/AirTrail) | Kişisel uçuş defteri (geçmiş uçuşlar, istatistik, içe aktarma) | ★1630, son push 26.09.2026, canlı | GPL-3.0 | Hayır: canlı durum izlemiyor, geçmişi kaydediyor |
| [karenc/flights-notifier](https://github.com/karenc/flights-notifier) | Uçuş durumunu e-postayla bildiren betik | ★1, son push 2011, terk | yok | Hayır: amaç aynı ama 15 yıldır güncellenmiyor |

**Karar:** kendi kodumuz kalıyor, dışarıdan kod alınmadı. Gerekçe: araç bağımlılıksız (sunucuda ve Actions'ta paket
kurulmuyor), Flightradar24'ten gereken üç uç ~200 satır, kapı ve bagaj bandını veren havalimanı kaynakları (Haneda,
İstanbul) adayların hiçbirinde yok.
