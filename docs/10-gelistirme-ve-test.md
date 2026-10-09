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
başlatır; 134 denetim yapar; arkasını temizler. Çalışan sisteme dokunmaz. Yaklaşık iki dakika sürer.
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
fark eder: canlı video isteyen 8. bölümü `SKIP` olarak raporlar, geri kalan **112 denetimi** koşar
(arayüz dosyaları, ayarlar, kamera kaydı, kurallar, olay günlüğü, canlı bildirim, yük, kalıcılık,
kapanma, özet metninin biçimlenmesi, nesne takibi, kural mantığı, çalışma saatleri ve rapor hesabı). Canlı video, anomali ve engel bölgesi denetimleri (22 denetim) yalnızca simülatör ve Triton
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
- **Arayüzün görsel davranışı** otomatik sınanmaz; yalnızca yapısal tutarlılığı sınanır (bölüm 1).
- **Gerçek donanım kameraları** ile sınama yapılmamıştır; bütün doğrulamalar simülatörle yapılmıştır.

## Sık yapılan değişiklikler

### Yeni bir API uç noktası

1. İş mantığını ilgili servise yazın (`backend/*.py`).
2. `backend/api/` altındaki uygun yönlendiriciye uç noktayı ekleyin; gövde gerekiyorsa
   `api/schemas.py`'ye model ekleyin. Engelleyen çağrıyı `asyncio.to_thread` ile yapın.
3. `frontend/js/api.js`'e karşılığını ekleyin.
4. `tests/system_check.py`'ye en az bir başarılı ve bir hatalı durum denetimi ekleyin.
5. `docs/06-api.md`'yi güncelleyin.

### Yeni bir ayar

1. `settings_service.py`: `DEFAULT_SETTINGS`'e varsayılanı, `_sanitize`'a aralığı ekleyin.
2. Ayarı okuyan servisin `_load_settings` / `reload_settings` işlevine ekleyin.
3. `frontend/index.html`: Ayarlar formuna `data-setting="bölüm.alan"` nitelikli bir denetim ekleyin
   (çoğu zaman JavaScript yazmak gerekmez).
4. `docs/09-veri-ve-yapilandirma.md`'deki tabloya ekleyin.

### Yeni bir kural koşulu

1. `Rule_Generator_LLM/schema.py`: `ConditionType`'a ekleyin; gerekiyorsa `Condition`'a alan ekleyin.
2. `Rule_Generator_LLM/evaluator.py`: `_evaluate_condition`'a dal ve `_eval_<ad>` işlevi ekleyin;
   ihlal iletisini sade Türkçe yazın.
3. `Rule_Generator_LLM/prompts.py`: derleyici yönergesine koşulu ve bir örneğini ekleyin.
4. `frontend/js/labels.js`: `CONDITION_LABELS`'a sade dil karşılığını ekleyin.
5. `docs/08-kurallar-ve-analiz.md`'deki tabloya ekleyin.

### Yeni bir model sınıfı ya da model

- Sınıf adının arayüzde Türkçe görünmesi için: `frontend/js/labels.js` (`CLASS_LABELS`) ve
  `Rule_Generator_LLM/evaluator.py` (`_CLASS_LABELS`).
- Derleyicinin sınıfı tanıması için: `Rule_Generator_LLM/compiler.py` başındaki sınıf listeleri.
- Yeni bir Triton modeli için: `Object_Detection/model_repository/<ad>/config.pbtxt` ve
  `Object_Detection/detector.py`'deki model eşlemesi.

### Yeni bir arayüz sayfası
Bkz. [07 — Arayüz kodu](07-frontend.md), "Yeni sayfa eklemek".

## Kod kuralları

**Python**
- Modül başında ne işe yaradığını anlatan bir belge dizgisi; açıklamalar "neden"i söyler.
- Zaman, eşik ve sınır değerleri modül başında adlandırılmış sabittir.
- Servisler birbirini doğrudan içe aktarır; `api/` yalnızca servisleri çağırır.
- `print` yerine `logging`; yeni modüllerde günlükçü adı `aegis.<konu>` biçimindedir.
- Kullanıcıya dönen hata iletileri Türkçe ve eyleme dönüktür.
- Diske yazım `paths.atomic_write_json` ile; uzun döngüler `SHUTTING_DOWN` denetler.

**JavaScript / CSS**
Bkz. [07 — Arayüz kodu](07-frontend.md), "Kurallar".

Depoda otomatik biçim denetleyici (ruff, eslint) kurulu değildir; eklenmesi iyi bir ilk iştir.

## Sürüm denetimi

- Çalışma verisi, model ağırlıkları, videolar ve `.env` depoya girmez
  (bkz. [09](09-veri-ve-yapilandirma.md), ".gitignore kapsamı").
- `Anomaly_Detection/` bir alt modüldür: `git submodule update --init`.
- Commit öncesi: `git status` ile yalnızca kaynak dosyaların eklendiğini doğrulayın ve sistem testini koşun.
