# 11 — Sorun giderme

Önce menünün altındaki durum satırına ve sunucunun terminal çıktısına bakın. Hızlı durum sorguları:

```bash
curl -s localhost:8500/api/system/stats | python3 -m json.tool
```
```bash
curl -s localhost:8500/api/anomaly/status | python3 -m json.tool
```

## Sunucu başlamıyor

| Belirti | Neden | Çözüm |
| :--- | :--- | :--- |
| "Bu veri dizinini (…) kullanan başka bir AegisVision sunucusu çalışıyor" | Aynı veri diziniyle bir sunucu açık. | `pgrep -fa uvicorn` ile bulun, durdurun; ya da farklı `AEGIS_DATA_DIR` verin. |
| `Address already in use` | 8500 portu dolu. | Eski süreci durdurun. |
| `ModuleNotFoundError` | Yanlış Python ya da eksik paket. | `./WebInterface/run.sh` kullanın; `./.conda/bin/pip install -r requirements.txt`. |
| Açılıyor ama hemen yeniden başlıyor | `--reload` bir Python dosyasının değiştiğini gördü. | Beklenen davranış. |

## Arayüz

| Belirti | Neden | Çözüm |
| :--- | :--- | :--- |
| Eski arayüz görünüyor ya da sayfa boş | Tarayıcı önceki sürümü önbellekten gösteriyor. | Bir kez F5. Sürmezse Ctrl+Shift+R. |
| Üstte kırmızı "Sunucu bağlantısı koptu" şeridi | Tarayıcı sunucuya ulaşamıyor. | Sunucu çalışıyor mu, ağ erişimi var mı denetleyin; bağlantı gelince şerit kendiliğinden kalkar. |
| "Analiz durdu" | Triton'a ulaşılamıyor. | `docker ps` ile `triton_yoloe_server` çalışıyor mu bakın; Ayarlar → Gelişmiş'teki adresi denetleyin. |
| Sayfa açık ama görüntü akmıyor | Sekme arka planda. | Görünmeyen sekmede video bilerek durdurulur; sekmeye dönünce başlar. |
| İngilizce kipte bazı metinler Türkçe | Saklanan metinler (özetler, kural notları, adlar) ya da sunucunun çizdiği "sinyal yok" kartı. | Beklenen davranış; bkz. "Bilinen sınırlar". Başka bir Türkçe metin eksik bir katalog karşılığıdır: sistem testi (bölüm 14) adını verir. |
| Dil ya da tema kendiliğinden sıfırlandı | Tarayıcı site verisini tutmuyor (gizli pencere, silinmiş depolama). | Ayarlar → Görünüm'den yeniden seçin; seçim tarayıcı başınadır. |

## Kameralar

| Belirti | Neden | Çözüm |
| :--- | :--- | :--- |
| Tarama kamera bulmuyor | Kamera başka alt ağda ya da çok noktaya yayın engelli. | "Elle ekle" ile IP adresini yazın. |
| "Şifre hatalı" | ONVIF hesabı yanlış. | "Elle ekle" ile aynı adresi doğru bilgilerle yeniden ekleyin (kayıt güncellenir). |
| "Sinyal yok" | Yayın açılamıyor: kamera kapalı, RTSP portu kapalı, adres değişmiş. | `ffprobe <yayın adresi>` ile deneyin (adres: kamera bilgi penceresi). Adres değiştiyse silip yeniden ekleyin. |
| Açılışta bir süre "Bağlanıyor…" | Normal; 20 saniyeye kadar sürebilir. | Bekleyin. |
| "Hazır" yazıyor, görüntü yok | Kamera kullanılmadığı için bağlantı bırakılmış. | Canlı İzleme'de açınca bağlanır. |
| Görüntü takılıyor | Ağ ya da işlemci yetersiz. | Ayarlar → "Tam akıcılıkta yayın"ı kapatın (8 kare/sn); daha az kameralı düzen seçin. |

## Olaylar

| Belirti | Neden | Çözüm |
| :--- | :--- | :--- |
| Hiç olay oluşmuyor | Algılama kapalı, analiz sunucusu kapalı ya da eşik yüksek. | Ayarlar → Algılama; menünün altındaki durum; uyarı seviyesini düşürün. |
| Çok fazla olay | Eşik sahneye göre düşük. | Uyarı seviyesini yükseltin; "Olay birleştirme süresi"ni artırın. |
| Olayın videosu yok | Kayıt kapalı; kamera yeni bağlanmıştı (< 1 sn görüntü); video kotadan silindi. | Ayarlar → Kayıt; kota için "Kayıtlar için ayrılan alan". |
| Video yavaş ya da hızlı oynuyor | — | Kare hızı yakalama zamanlarından hesaplanır; sürüyorsa hata olarak bildirin. |
| Özet gelmiyor | Anahtar yok, servis kapalı ya da kota dolu. | Olay penceresindeki not nedeni söyler. `.env` içindeki `EVREN_API_KEY` değerini denetleyin; sunucuyu yeniden başlatın. |
| Özet yanlış ya da ilgisiz | Model sekiz küçük kareden yazıyor. | Kameraya açıklama girin (Kameralar → düzenle); "Yeniden oluştur". |

## Kurallar

| Belirti | Neden | Çözüm |
| :--- | :--- | :--- |
| "Hazırlanamadı" | Dil modeli servisine ulaşılamıyor ya da anahtar yok. | Anahtarı ve ağ erişimini denetleyin; "Yeniden dene". Ya da bölgeyi servis gerektirmeyen listelerden tanımlayın. |
| "Genel ayarla çalışıyor" | Açıklama plana çevrilemedi. | Tek koşullu, somut bir cümle yazın (bkz. kullanım kılavuzu). |
| Kural hazır ama alarm vermiyor | Kural kapalı ya da çalışma saati dışında; nesne modelin tanıdığı bir sınıf değil; nesne bölgenin dışında. | Canlı İzleme'de "Tespitler"i açıp kutuların çizilip çizilmediğine bakın. Planı görmek için: `GET /api/rules/{id}/plan`. |
| Sürekli alarm veriyor | Koşul sahnede hep sağlanıyor (ör. bölgede zaten biri çalışıyor). | Bölgeyi daraltın ya da açıklamayı kesinleştirin. |
| Engel bölgesi "referans bekleniyor" | Referans alınmamış. | Bölge boşken Canlı İzleme → "Referans al". |
| Engel bölgesi sürekli alarmda | Işık ya da kamera açısı kalıcı değişti. | Referansı yeniden alın. |

## Analiz sunucusu

| Belirti | Neden | Çözüm |
| :--- | :--- | :--- |
| Kapsayıcı başlamıyor | Docker ya da NVIDIA Container Toolkit eksik. | `python Object_Detection/check_environment.py`. |
| Model yüklenmiyor | `model.plan` başka bir ekran kartında üretilmiş. | Motorları bu makinede yeniden üretin (`convert_to_tensorrt.sh`). |
| Bellek yetersiz | 4 GB'lık kartta dört model sınırda çalışır. | Kullanılmayan modeli depodan çıkarın; `batch_size`'ı düşürün. |

## Bellek

Sunucunun belleği kamera sayısı ve `max_clip_duration_sec` ile büyür
(bkz. [09](09-veri-ve-yapilandirma.md), "Bellek ve disk hesabı"). Makinede takas alanı yoksa bellek
tükendiğinde çekirdek rastgele bir süreci öldürür; belirti, bir sürecin iz bırakmadan kaybolmasıdır.
Denetim: `journalctl -k | grep -i "out of memory"`.

## Bilinen sınırlar

| Konu | Durum |
| :--- | :--- |
| Kimlik doğrulama | Yok. Arayüz ve API ağdaki herkese açık; CORS her kaynağa izinli. |
| Kamera şifreleri | Veri dizininde düz metin. |
| Erişim anahtarı | Eski anahtar git geçmişinde duruyor; yenilenmeli. |
| Ölçek | Tek süreç, tek makine; veriler JSON dosyalarında. 9 kamerayla sınandı. |
| Kayıt | Sürekli kayıt yok; yalnızca olay videoları. |
| Nesne takibi | Tek kamera içinde ve yalnızca kutu konumuna göre; yön, çizgi geçişi ve giren-çıkan sayımı yok. |
| Kişi tanıma | Yok. |
| Tarayıcı | Chromium tabanlı tarayıcılarda sınandı; Firefox sınanmadı. |
| Donanım | Gerçek kameralarla değil, simülatörle sınandı. |
| Dil | Arayüz Türkçe ve İngilizce. Olay özetleri, kural derleyicinin notları ve sunucunun çizdiği durum kartları yalnızca Türkçe; kural açıklamaları Türkçe anlaşılır (İngilizce çoğunlukla çalışır). |
