# TODO — ucus-bilgi

- [ ] **Uçuş boyunca periyodik Bark bildirimi** (kullanıcı isteği, 12.10.2026, NH219 havadayken).
  **İstek:** uçuş süresince **30 dk'da bir** bildirim; **inişe 30 dk kala 10 dk'da bir**; her bildirimde
  **bir öncekine göre fark**. Kanal: Bark.
  **Engel (o gün):** Bark anahtarı Claude bulut oturumunda yok; VPS'e (bark.sh) erişim yok; GitHub Actions'tan
  göndermek için depo sırrı `BARK_URL` gerekiyor ve sırrı yalnız kullanıcı ekleyebilir.

  1. **Bark anahtarı (kullanıcı):** Bark uygulaması → ana ekrandaki sunucu adresi (`https://api.day.app/<anahtar>/`
     ya da kendi Bark sunucun). GitHub → `ucus-bilgi` → Settings → Secrets and
     variables → Actions → New repository secret → ad `BARK_URL`, değer bu adres. Anahtar hiçbir dosyaya, nota ya da
     commit'e yazılmaz.
  2. **bildirim.py:** `BARK_URL`'ye JSON yerine Bark belgelerindeki form POST'u gönder (`title`, `body`, `group`;
     yanıt `{"code":200}`). Gerçek bir bildirimle doğrula.
  3. **rapor.py `--bildir` içeriği:**
     - Başlık: `✈️ NH219 · iniş 15:14 TR · kalan 8 sa 44 dk`.
     - Gövde: geçen / tahmini uçuş süresi (%); konum **ülke/bölge adıyla** (ters coğrafi kodlama, ör. Nominatim
       `reverse?format=json&zoom=5&accept-language=tr`; denizde "… denizi üzeri"); irtifa, yer hızı, hedefe kalan km;
       yedek tahminler tek satır; geçmiş ortalama tek satır.
     - **Önceki bildirime göre:** iniş tahmini `15:18 → 15:14 (−4 dk)`, bu arada alınan yol (km), kalan sürenin
       değişimi, esas kaynak değiştiyse (FR24 düştü vb.) bunu ayrıca yaz.
     - İniş görülünce son bildirim: gerçek iniş saati, tarifeye ve ilk tahmine göre fark; sonra durur.
  4. **Önceki bildirimin durumu nerede saklanacak** (fark için): VPS'te `durum.json` (takip.py gibi); Actions'ta
     `actions/cache` (anahtar `run_id`, geri yüklemede önek) — `main`'e commit atmadan.
  5. **Zamanlama — önerilen:** VPS/pi63 cron'da dakikada bir `rapor.py --bildir --aralikli`; betik aralığı kendi seçer
     (son bildirimden ≥30 dk geçtiyse ya da kalan ≤30 dk iken ≥10 dk geçtiyse gönderir). Gerekçe: VPS'te bark.sh hazır
     (BARK_URL gerekmez), İstanbul kaynağı VPS'ten okunuyor, GitHub cron'u 5–15 dk gecikebiliyor.
     **Yedek yol:** Actions `schedule: '*/10 * * * *'` + aynı `--aralikli` mantığı + `BARK_URL` sırrı.
  6. **Test:** `testler/` altında taklit senaryo: 30 dk aralıkla 3 bildirim (farklar doğru), kalan 30 dk'ya inince 10 dk
     kademesi, iniş bildirimi ve durma; `--kuru` ile Bark gönderilmeden.

- [ ] **takip.py'yi HND → IST dışına aç.** Bir sonraki yolculuk büyük olasılıkla İstanbul kalkışlı. Önce İstanbul
  kalkış kaynağını ekle (`kaynaklar.ist_oku(ucus, varis=False)` hazır; takip.py'de kapı/durum farkı yazılmalı).
  Sonra FR24'ü her havalimanı için genel yedek kaynak yap (`airport.origin.info.gate`, `time.estimated`).
  Önerilen yol: kaynak başına "normalize anlık görüntü" (plan, tahmin, kapı, terminal, durum, iptal, bant), fark
  mantığı tek yerde.
- [ ] **20 seferlik geçmiş.** FR24 anahtarsız ~7 gün veriyor; `veri/` önbelleği her Actions koşusunda büyüyor. Daha hızlı
  doldurmak için ikinci kaynak dene (FlightAware geçmişi ~14 gün, HTML).
- [ ] **VPS'teki eski kopya.** `/opt/ucus-takip/takip.py` japan-itinerary-app'ten kopyalanan eski tek dosyalık sürüm;
  12–13.10.2026'da kendini kaldırıyor. Bir sonraki kurulumda bu depodan yeni sürümü kopyala (README § Takip).
- [ ] **Bark'ı Actions'tan denemek** için depo sırrı `BARK_URL` (Bark sunucusu + anahtar) eklenmedi. İstenirse:
  GitHub → Settings → Secrets and variables → Actions → `BARK_URL`.
