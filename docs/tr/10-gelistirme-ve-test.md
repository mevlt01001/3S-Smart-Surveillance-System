# 10 — Geliştirme ve test

## Geliştirme düzeni

Çalışan sistemi bozmadan çalışmanın en kolay yolu, aynı koddan ikinci bir örneği ayrı veri
diziniyle başlatmaktır:

```bash
AEGIS_DATA_DIR=/tmp/aegis-gelistirme EVREN_API_KEY="" .conda/bin/python -m uvicorn WebInterface.backend.server:app --port 8502 --reload --reload-dir WebInterface/backend
```

- `AEGIS_DATA_DIR`: asıl kameralara, kurallara ve olaylara dokunulmaz.
- `EVREN_API_KEY=""`: dış servise çağrı yapılmaz (kota harcanmaz). Kural derlemeyi ya da özeti
  denemek için bu değişkeni vermeyin.
- Arayüz dosyaları her istekte diskten okunur; HTML / CSS / JS değişikliği için tarayıcıyı
  yenilemek yeter. Python değişikliğinde `--reload` sunucuyu yeniden başlatır.

`Rule_Generator_LLM/` ve `Object_Detection/` altındaki değişiklikler `--reload` tarafından
izlenmez; sunucuyu elle yeniden başlatın.

## Sistem testi

```bash
.conda/bin/python WebInterface/tests/system_check.py --sim-ip <bu makinenin IP adresi>
```

Betik kendi portunda, **geçici bir veri dizininde**, dış servis çağrıları kapalı ayrı bir sunucu
başlatır; 137 denetim yapar; arkasını temizler. Çalışan sisteme dokunmaz. Yaklaşık iki dakika sürer.
Çıkış kodu yalnızca bütün denetimler geçtiyse `0`'dır. `--keep` geçici dizini silmez.

| Bölüm | Neyi doğrular |
| :--- | :--- |
| 1. Açılış ve arayüz dosyaları | Sunucunun torch yüklemediği (bellek < 300 MB), `index.html`'in andığı her dosyanın varlığı, yinelenen `id` olmadığı, betiklerin aradığı her öğenin sayfada bulunduğu, önbellek başlıkları. |
| 2. Boşta davranış | Kamera ve istemci yokken işlemci kullanılmadığı. |
| 3. Ayarlar | Geçersiz değerlerin aralığa çekildiği, sıfırlamanın çalıştığı. |
| 4. Kamera kaydı | Girdi doğrulama; ulaşılamayan cihazın çevrimdışı kaydedildiği; şifrenin yanıtta olmadığı. |
| 5. Kurallar | Oluşturma, güncelleme, silme, derleme durumu, hata kodları. |
| 6. Olay günlüğü | Deneme olayı, işaretleme, fotoğraf, depolama sayımı, dizin dışına çıkma denemeleri. |
| 7. Canlı bildirim | Yeni olayın SSE ile anında geldiği. |
| 8. Canlı video | WebSocket'in kaynağın kare hızını verdiği, her karenin farklı olduğu, hız sınırı, MJPEG, anomali skoru, engel bölgesi, kamera silmenin kurallarını da sildiği. |
| 9. Yük | 300 eşzamanlı istekte hata olmadığı ve p95 < 250 ms. |
| 10. Kalıcılık | Yeniden başlatmadan sonra kayıtların korunduğu, yarım kalmış olayın "sürüyor" kalmadığı, "tümünü sil"in dosyaları da sildiği. |
| 11. Kapanma ve tek örnek | Açık bağlantılarla hızlı kapanma; aynı veri dizininde ikinci sunucunun reddedildiği; günlükte hata izi olmadığı. |
| 12. Özetin biçimlenmesi | Model yanıtlarının başlık + ayrıntı + öneri biçimine zorlandığı ve değerlendirmenin ayıklandığı (model gerekmez). |
| 13. Takip ve kural mantığı | Nesne takibi, koşul değerlendirme, çalışma saatleri, rapor sayıları ve derleyici yanıtları (model gerekmez). |
| 14. Arayüz çevirileri | İngilizce kataloğun geçerli olduğu; her `t("…")` metninin ve her `index.html` metninin İngilizce karşılığı bulunduğu (sunucu gerekmez). |

8. bölüm kamera simülatörü çalışıyorsa yürütülür, yoksa `SKIP` olarak raporlanır. Anomali ve engel
bölgesi denetimleri için analiz sunucusu da çalışmalıdır.

**Her değişiklikten sonra bu testi koşun.** Yeni bir uç nokta ya da davranış eklediğinizde ilgili
bölüme bir `check(...)` satırı ekleyin.

## Otomatik test (GitHub Actions)

`.github/workflows/ci.yml`, `main` dalına yapılan her push'ta ve her pull request'te çalışır:

1. Python 3.10 ortamını kurar, `requirements.txt`'i yükler (ffmpeg ve OpenCV'nin sistem kitaplıklarıyla).
2. Python dosyalarını derler (`compileall`) ve arayüz betiklerinin sözdizimini `node --check` ile denetler.
3. Sistem testini koşar.

GitHub'ın makinelerinde ekran kartı, analiz sunucusu ve kamera yoktur. Sistem testi bunu kendisi
fark eder: canlı video isteyen 8. bölümü `SKIP` olarak raporlar, geri kalan **115 denetimi** koşar
(arayüz dosyaları, ayarlar, kamera kaydı, kurallar, olay günlüğü, canlı bildirim, yük, kalıcılık,
kapanma, özet metninin biçimlenmesi, nesne takibi, kural mantığı, çalışma saatleri, rapor hesabı ve çeviriler). Canlı video, anomali ve engel bölgesi denetimleri (22 denetim) yalnızca simülatör ve Triton
çalışan bir makinede koşar; bu yüzden **birleştirmeden önce tam testi geliştirme makinesinde elle
koşmak hâlâ gereklidir.**

Test başarısız olursa iş akışının son adımı sunucunun günlüğünü yazdırır. Dış servis anahtarı
gerekmez; test dil modeli çağrılarını kendisi kapatır.

Sonuç, GitHub'da deponun **Actions** sekmesinde ve her commit'in yanındaki işarette görünür.
`main` dalını korumak için: *Settings → Branches → Add rule → Require status checks to pass* altında
"Sistem testi"ni seçin.

Otomatik dağıtım (CD) tanımlı değildir: sistem, ekran kartı olan tek bir yerel makinede çalışır ve
bulutta bir hedefi yoktur. Tam testin de otomatik koşması istenirse, geliştirme makinesi
"self-hosted runner" olarak GitHub'a bağlanabilir; depo herkese açıksa bu, yabancı pull
request'lerin o makinede kod çalıştırmasına izin vermek anlamına geldiği için önerilmez.

## Doğruluk ölçümü

Sistem testi "çalışıyor mu" sorusunu yanıtlar; "ne kadar doğru" sorusunu `accuracy_check.py` yanıtlar.

```bash
.conda/bin/python WebInterface/tests/accuracy_check.py                    # bütün etiketli videolar
.conda/bin/python WebInterface/tests/accuracy_check.py --only Test_Videos  # yolunda bu metin geçenler
.conda/bin/python WebInterface/tests/accuracy_check.py --no-summaries      # dil modelini çağırmadan
```

**Ne yapar.** Her video grubu için özel bir medya sunucusu ve özel bir backend başlatır (kendi
portları, geçici veri dizini; çalışan sisteme dokunmaz), videoları **bir kez, gerçek zamanlı**
RTSP kamerası olarak yayınlar ve olağandışı hareket algılamanın bunlarla ne yaptığına bakar. Video
oynarken kameranın skorunu örnekler; bitince sistemin kaydettiği olayları günlükten okur. Hiçbir şey
taklit edilmez: sayılar gerçek hattın sayılarıdır (yayın, model, eşikler, olay mantığı, özet).

**Etiketler** `WebInterface/tests/accuracy_labels.json` dosyasındadır:

```json
{"file": "Anomaly_Detection/Test_Videos/test_video_15.mp4", "expect": "event", "what": "Kişi kapı önünde düşüyor", "window": [2, 8]}
```

| Alan | Anlamı |
| :--- | :--- |
| `file` | Depo köküne göre video yolu (videolar depoda değildir; dosya yoksa atlanır). |
| `expect` | `event`: olay bekleniyor. `none`: olay yok, her alarm yanlış alarmdır. `unknown`: oynatılır ve raporlanır ama sayılmaz. |
| `window` | İsteğe bağlı `[başlangıç, bitiş]` saniye: olay yalnızca bu aralıkta (±3 sn) yakalanırsa sayılır, dışındaki alarmlar yanlış alarmdır. |
| `what` | İnsan için açıklama; ölçüme etkisi yoktur. |

Etiket dosyasındaki ilk liste **taslaktır**: videoların küçük karelerine bakılarak çıkarıldı.
Videoları bilen biri gözden geçirmeden sayılar kesin kabul edilmemelidir.

**Rapor** (`accuracy_report/report.md` ve `report.json`; `--out` ile başka yere):

- **Özet:** olay içeren videoların kaçında olay yakalandı, kaçanlar; olaysız videolarda kaç yanlış
  alarm ve saatte kaç; özetin "gerçek / olağan" değerlendirmesinin gerçek olaylarda ve yanlış
  alarmlarda ne dediği; bir olay kaç ayrı kayda bölündü.
- **Başka eşiklerde ne olurdu:** her videonun en yüksek skoruna göre, uyarı eşiği 10, 20, … 90
  olsaydı kaç olay yakalanır ve kaç olaysız video alarm verirdi. Eşik seçmek için bu tabloya bakılır.
- **Videolar:** her video için beklenen, sonuç, en yüksek skor ve alarmların saniyesi, skoru, özeti.

**Bilinmesi gerekenler**

- Eşikler ve kayıt ayarları **çalışan kurulumun** `settings.json` dosyasından alınır (`--settings`
  ile başkası verilebilir); yani rapor, sistemi o an ayarlandığı hâliyle anlatır. Olağandışı hareket
  algılama ölçüm sırasında her zaman açıktır.
- Gerçek zamanlıdır: süre, videoların toplam süresine yakındır (`--parallel` kadar video aynı anda oynar).
  Analiz sunucusunu çalışan sistemle paylaşır; ölçüm sırasında ağır başka iş yapılmamalıdır.
- Özetler açıkken her olay için dil modeli bir kez çağrılır; servisin günlük kotası sınırlıysa
  `--no-summaries` kullanın.
- Videonun ilk karesi 8 saniye tutulur (sistemin yayına bağlanması için); süreler bundan sonrasına göredir.
- Analiz sunucusu, `ffmpeg` ve simülatörün MediaMTX dosyası gerekir. CI'da koşmaz.

### İlk ölçüm (9 Ekim 2026)

Taslak etiketlerle, kurulumun o günkü ayarlarıyla (uyarı eşiği 39, kritik 40, olay birleştirme 1 sn):

| Ölçü | Sonuç |
| :--- | :--- |
| Olay içeren 11 video | 10'unda olay yakalandı (%91). Kaçan: gece sokakta araç çarpması (en yüksek skor 23). |
| Olaysız 63 video, 73 dakika | 2 yanlış alarm (saatte 1,6): biri duran bir kişinin üstünde ışık renginin değişmesi, biri kalabalığın yürüdüğü videonun ilk saniyesi. |
| Eşik 60 olsaydı | Yine 10 / 11 olay, 0 yanlış alarm. Eşik 20 olsaydı 11 / 11 olay, 3 olaysız videoda alarm. |
| Bir olayın bölündüğü kayıt sayısı | Ortalama 3,7 (birleştirme 1 sn). Birleştirme 5 sn ile 2,7. |
| Özetin değerlendirmesi | Gerçek olaylara ait alarmların yaklaşık üçte birine "gerçek", yarısına "olağan" dedi; 10 olayın 7–8'inde en az bir alarmı doğruladı. Belirgin olmayan düşmeleri (forklift önünde düşen işçi, kapı önünde düşen kişi) göremedi. |

Özetin değerlendirmesini iyileştirmek için üç değişiklik aynı videolarla ölçüldü ve **hiçbiri fark
yaratmadı**: özete olayın çevresinden daha uzun görüntü vermek, kareleri iki kat büyütmek, olayları
daha uzun birleştirmek. Bu yüzden değerlendirme yalnızca bilgi olarak kalmalı, alarm bastırmada
kullanılmamalıdır; iyileştirmek başka bir yaklaşım ister (daha çok kare, daha güçlü ya da videoyu
doğrudan gören bir model).

Sınırlar: etiketler taslaktır; 11 olay videosu azdır (bir video sonucu 9 puan oynatır); olaysız
görüntünün tamamı tek bir ofistendir; videolar müşteri kameralarından değil, toplanmış kliplerdir.

## Birim testleri

```bash
.conda/bin/python Object_Detection/run_tests.py
```

Tespit kitaplığının testleridir. **Model yüklerler ve birkaç GB bellek isterler.** 16 GB'lık
geliştirme makinesinde canlı sistem, simülatör ve Triton çalışırken koşulduğunda bellek tükenmiş ve
çekirdek süreç öldürmüştür. Önce `free -h` ile bakın, gerekirse web sunucusunu durdurun.

## Bilinçli olarak testi olmayanlar

- **Kural derleme ve olay özeti**, gerçek dil modeli yanıtı gerektirir; sistem testi bunları kapalı
  koşar. Elle denemek için geliştirme örneğini `EVREN_API_KEY` vermeden (yani `.env`'deki anahtarla)
  başlatın, bir kural kaydedin ve bir olayın özetini yeniden oluşturun.
- **Arayüzün görsel davranışı** otomatik sınanmaz; yalnızca yapısal tutarlılığı (bölüm 1) ve çeviri
  kapsamı (bölüm 14) sınanır.
- **Gerçek donanım kameraları** ile sınama yapılmamıştır; bütün doğrulamalar simülatörle yapılmıştır.

## Sık yapılan değişiklikler

### Yeni bir API uç noktası

1. İş mantığını ilgili servise yazın (`backend/*.py`).
2. `backend/api/` altındaki uygun yönlendiriciye uç noktayı ekleyin; gövde gerekiyorsa
   `api/schemas.py`'ye model ekleyin. Engelleyen çağrıyı `asyncio.to_thread` ile yapın.
3. `frontend/js/api.js`'e karşılığını ekleyin.
4. `tests/system_check.py`'ye en az bir başarılı ve bir hatalı durum denetimi ekleyin.
5. `docs/tr/06-api.md`'yi (ve `docs/06-api.md`'yi) güncelleyin.

### Yeni bir ayar

1. `settings_service.py`: `DEFAULT_SETTINGS`'e varsayılanı, `_sanitize`'a aralığı ekleyin.
2. Ayarı okuyan servisin `_load_settings` / `reload_settings` işlevine ekleyin.
3. `frontend/index.html`: Ayarlar formuna `data-setting="bölüm.alan"` nitelikli bir denetim ekleyin
   (çoğu zaman JavaScript yazmak gerekmez) ve İngilizce karşılığını `js/i18n-en.js`'e ekleyin.
4. `docs/tr/09-veri-ve-yapilandirma.md`'deki tabloya (ve İngilizce bölüme) ekleyin.

### Yeni bir kural koşulu

1. `Rule_Generator_LLM/schema.py`: `ConditionType`'a ekleyin; gerekiyorsa `Condition`'a alan ekleyin.
2. `Rule_Generator_LLM/evaluator.py`: `_evaluate_condition`'a dal ve `_eval_<ad>` işlevi ekleyin;
   ihlal iletisini sade Türkçe yazın.
3. `Rule_Generator_LLM/prompts.py`: derleyici yönergesine koşulu ve bir örneğini ekleyin.
4. `frontend/js/labels.js`: `CONDITION_LABELS`'a sade dil karşılığını, kataloğa İngilizcesini ekleyin;
   ihlal iletisi yeniyse `alarmText()`'e bir kalıp ekleyin.
5. `docs/tr/08-kurallar-ve-analiz.md`'deki tabloya (ve İngilizce bölüme) ekleyin.

### Yeni bir model sınıfı ya da model

- Sınıf adının arayüzde sade görünmesi için: `frontend/js/labels.js` (`CLASS_LABELS`) ve katalog
  karşılığı, `Rule_Generator_LLM/evaluator.py` (`_CLASS_LABELS`) ve `Rule_Generator_LLM/manual.py`
  (`_CLASS_LABELS_EN`).
- Derleyicinin sınıfı tanıması için: `Rule_Generator_LLM/compiler.py` başındaki sınıf listeleri.
- Yeni bir Triton modeli için: `Object_Detection/model_repository/<ad>/config.pbtxt` ve
  `Object_Detection/detector.py`'deki model eşlemesi.

### Yeni bir arayüz sayfası
Bkz. [07 — Arayüz kodu](07-frontend.md), "Yeni sayfa eklemek".

### Yeni bir arayüz metni
Metni Türkçe olarak `t("…")` içine ya da `index.html`'e yazın ve İngilizce karşılığını `js/i18n-en.js`'e
ekleyin; karşılığı olmayan metni sistem testi (bölüm 14) adıyla gösterir. Bkz.
[07 — Arayüz kodu](07-frontend.md), "Arayüz dili".

## Kod kuralları

**Python**
- Modül başında ne işe yaradığını anlatan bir belge dizgisi; açıklamalar "neden"i söyler.
- Zaman, eşik ve sınır değerleri modül başında adlandırılmış sabittir.
- Servisler birbirini doğrudan içe aktarır; `api/` yalnızca servisleri çağırır.
- `print` yerine `logging`; yeni modüllerde günlükçü adı `aegis.<konu>` biçimindedir.
- Kullanıcıya dönen hata iletileri Türkçe ve eyleme dönüktür (İngilizce de görünsün diye katalogda
  karşılıkları bulunur).
- Diske yazım `paths.atomic_write_json` ile; uzun döngüler `SHUTTING_DOWN` denetler.

**JavaScript / CSS**
Bkz. [07 — Arayüz kodu](07-frontend.md), "Kurallar".

**Belgeler**
Bölümler İngilizce (`docs/`) ve Türkçe (`docs/tr/`) olarak bulunur; birindeki değişiklik ötekine de
yapılmalıdır.

Depoda otomatik biçim denetleyici (ruff, eslint) kurulu değildir; eklenmesi iyi bir ilk iştir.

## Sürüm denetimi

- Çalışma verisi, model ağırlıkları, videolar ve `.env` depoya girmez
  (bkz. [09](09-veri-ve-yapilandirma.md), ".gitignore kapsamı").
- `Anomaly_Detection/` bir alt modüldür: `git submodule update --init`.
- Commit öncesi: `git status` ile yalnızca kaynak dosyaların eklendiğini doğrulayın ve sistem testini koşun.
