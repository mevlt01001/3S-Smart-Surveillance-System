# 08 — Kurallar ve analiz

Sistem görüntüyü iki bağımsız yoldan inceler: **olağandışı hareket** (kural gerektirmez) ve
**kurallar** (kullanıcının çizdiği bölgeler). İkisi de aynı olay kaydı yolunda birleşir.

---

## A. Olağandışı hareket

Kod: `WebInterface/backend/anomaly_service.py`. Model: Triton üzerindeki `anomaly_detector`.

### Skorun üretilmesi

1. Her kameranın son **16 karesi** 224×224 RGB olarak alınır. Yayın yeni bağlandıysa ve 16 kare
   yoksa en eski kare yinelenerek tamamlanır.
2. Aynı anda en çok `batch_size` (varsayılan 4, en çok 8) kamera tek istekte gönderilir.
   Tensör biçimi `[K, 3, 16, 224, 224]`, 0–1 aralığında `float32`.
3. Modelin çıktısı (`logits`, kamera başına bir sayı) sigmoid'den geçirilip 100 ile çarpılır:
   **0–100 arası skor**.
4. Yalnızca son turdan beri **yeni kare getiren** kameralar puanlanır. Bir tur 0,25 saniyedir.

### Yumuşatma

- Skor uyarı seviyesinin **üstündeyse** olduğu gibi kullanılır: alarm gecikmez.
- **Altındaysa** önceki değerle harmanlanır (`0,15 × önceki + 0,85 × yeni`): sakin sahnede skor titremez.

### Seviyeler

| Skor | `tier` | Arayüzde |
| :--- | :--- | :--- |
| < uyarı seviyesi (`threshold_normal`, varsayılan 25) | `normal` | — |
| ≥ uyarı seviyesi | `warning` | Şüpheli hareket / Uyarı |
| ≥ kritik seviyesi (`threshold_warning`, varsayılan 50) | `critical` | Kritik hareket / Kritik |

Ayar adları tarihsel nedenle kafa karıştırıcıdır: `threshold_normal` "normalin bittiği yer", yani
**uyarı** eşiğidir; `threshold_warning` "uyarının bittiği yer", yani **kritik** eşiğidir.

Olayın başlığı, en yüksek skora göre seçilir (`_describe`):

| En yüksek skor | Başlık |
| :--- | :--- |
| ≥ 80 | Kavga veya panik olabilir |
| ≥ 60 | Koşma veya itişme olabilir |
| ≥ 40 | Olağandışı hareket |
| diğer | Hafif şüpheli hareket |

Bu başlıklar modelin çıktısı değil, skora bağlı sabit ifadelerdir; ne olduğunu asıl anlatan, video
karelerinden yazılan özettir.

### Olay yaşam döngüsü

| Durum | Koşul | Ne olur |
| :--- | :--- | :--- |
| Açılış | Skor ≥ uyarı seviyesi ve kamerada açık olay yok | Kayıt oluşturulur (`anom_…`, `is_ongoing: true`), o anki kare fotoğraf olarak saklanır. |
| Sürme | Skor ≥ uyarı seviyesi | Son etkinlik zamanı ilerler; skor yükseldiyse en yüksek an güncellenir. |
| Kısa duraklama | Skor düştü, süre ≤ `tolerance_sec` | Olay sürer (tek olay sayılır). |
| Bölünme | Süre ≥ `max_clip_duration_sec` | Olay kapatılır; hareket sürüyorsa bir sonraki turda yenisi açılır. |
| Kapanış | Sakinlik > `tolerance_sec` | Aşağıdaki adımlar. |

Kapanışta (`_close_incident`):

1. Video aralığı: `[başlangıç − padding_sec, son etkinlik + padding_sec]`. Kareler kameranın
   bellekteki tamponundan alınır.
2. Kayıt güncellenir: en yüksek skor ve seviye, kesin saatler, süre, `is_ongoing: false`.
   Açılıştaki fotoğrafın yerine **en yüksek anın** karesi konur.
3. Kareler en az 1 saniyelik gerçek görüntü kapsıyorsa ve video kaydı açıksa video kodlanır
   (ayrı iş parçacığı). Kodlama bitince disk kotası uygulanır.
4. Özet servisi kullanılabiliyorsa özet istenir (ayrı iş parçacığı).

Analiz kapalıyken ya da analiz sunucusu ulaşılamazken de açık olaylar süresi dolunca kapatılır.

---

## B. Kurallar

Bir kural, bir ya da birden çok **bölgeden** oluşur. İki bölge türü vardır.

| | Kişi / nesne kuralı (`detection`) | Engel / değişiklik (`change_detection`) |
| :--- | :--- | :--- |
| Tanım | Çokgen + düz cümle | Yalnızca çokgen |
| Hazırlık | Cümle, dil modeliyle bir kez plana çevrilir | Bölge boşken "Referans al" |
| Çalışma | Nesne tespiti + koşul değerlendirme | Canlı görüntünün referansla karşılaştırılması |
| Dil modeli gerekir mi | Evet (yalnızca kaydederken) | Hayır |
| Analiz sunucusu gerekir mi | Evet | Hayır |

### B.1 Derleme: cümleden plana

Kod: `WebInterface/backend/rule_compilation.py` → `Rule_Generator_LLM/compiler.py` (`RuleCompiler`),
yönerge: `Rule_Generator_LLM/prompts.py`.

1. Kural kaydedilir kaydedilmez yanıt döner; derleme arka planda başlar (`compile_status: compiling`).
2. Derleyici, bölge açıklamasını yönergeyle birlikte dil modeline gönderir ve JSON bir plan ister.
3. Yanıt ayıklanır (kod çiti ve düşünme etiketleri temizlenir), `_normalize_plan_data` ile
   düzeltilir (model seçimi, sınıf adlarının modelin gerçek sınıflarına eşlenmesi, eksik alanlar)
   ve `DetectionPlan` şemasıyla doğrulanır.
4. Plan, bölge kaydına yazılır. Derleme sırasında kural değiştiyse sonuç atılır.
5. Dil modeli yanıt vermez ya da geçersiz yanıt verirse genel bir **yedek plan** üretilir
   (`fallback`): kural çalışır ama açıklamayı tam karşılamayabilir.

Bir bölgenin açıklaması değişmediyse (yalnızca adı, köşeleri ya da kuralın başlığı değiştiyse)
plan korunur ve yeniden derleme yapılmaz.

**Derleme durumları**

| `compile_status` | Anlamı | Arayüzde |
| :--- | :--- | :--- |
| `compiling` | Derleme sürüyor | Hazırlanıyor |
| `compiled` | Bütün bölgelerin planı hazır | (rozet yok) |
| `not_required` | Kuralda yalnızca engel bölgeleri var | (rozet yok) |
| `fallback` | En az bir bölge yedek planla çalışıyor | Genel ayarla çalışıyor |
| `pending` | Plan yok, servis kullanılabilir | Hazır değil |
| `unavailable` | Plan yok, servis kullanılamıyor | Hazırlanamadı |
| `error` | Derleme hata verdi | Hazırlanamadı |

### B.2 Algılama planı

Şema: `Rule_Generator_LLM/schema.py`, `DetectionPlan`.

```json
{
  "source_prompt": "Baret takmayan biri bölgeye girerse haber ver.",
  "selected_model": "safety_detector",
  "triton_model_name": "safety_detector",
  "model_classes": ["NO-Hardhat"],
  "detection_targets": [{"class_name": "NO-Hardhat", "role": "trigger"}],
  "conditions": [{"type": "zone_presence", "targets": ["NO-Hardhat"], "logic": "ANY", "min_confidence": 0.3}],
  "alert_on": "ANY_CONDITION_MET",
  "status": "success"
}
```

| Alan | Anlamı |
| :--- | :--- |
| `selected_model` / `triton_model_name` | Hangi model: `safety_detector`, `coco_detector`, `yoloe_detector`. |
| `model_classes` | Modelden istenecek sınıflar. |
| `detection_targets[].role` | `trigger`, `subject`, `required_equipment`, `forbidden`, `counter`. |
| `conditions[]` | Değerlendirilecek koşullar (aşağıda). |
| `alert_on` | `ANY_CONDITION_MET` (biri yeter) ya da `ALL_CONDITIONS_MET`. |
| `expanded_classes` | `yoloe_detector` için eş anlamlı sözcükler (ör. forklift → reach truck, pallet jack…). |
| `status` | `success` / `fallback`. |

**Model seçimi**

| Model | Ne zaman |
| :--- | :--- |
| `safety_detector` | İş güvenliği sınıfları: `Hardhat`, `NO-Hardhat`, `Safety Vest`, `NO-Safety Vest`, `Mask`, `NO-Mask`, `Person`, `Safety Cone`, `machinery`, `vehicle`. |
| `coco_detector` | 80 COCO sınıfından biri: kişi, araba, kamyon, sırt çantası, bavul… |
| `yoloe_detector` | Yukarıdakilerde olmayan nesneler; sınıf adı metin olarak verilir. |

Plan yalnızca "kişi" arıyor ve iş güvenliği donanımı içermiyorsa çalışma anında `coco_detector`'a
yönlendirilir (`live_detection_service._get_plan`): kişi tespitinde daha tutarlıdır.

### B.3 Koşul türleri

Kod: `Rule_Generator_LLM/evaluator.py`, `ConditionEvaluator`. Bir tespit, kutusunun şu dört
noktasından biri çokgenin içindeyse **bölgede** sayılır: merkez, alt orta (ayak), üstten %25 (gövde),
üstten %75 (kalça). Bu, yerdeki bölgelerde ayakta duran ve oturan kişileri de yakalar.

| Koşul | Ne zaman alarm | Parametreler | Örnek cümle |
| :--- | :--- | :--- | :--- |
| `zone_presence` | Hedef sınıflardan biri (`ANY`) ya da hepsi (`ALL`) bölgede | `targets`, `logic`, `min_confidence` | "Bölgeye araç girerse haber ver." |
| `zone_absence` (donanım) | Bölgedeki özne, gerekli donanımla örtüşmüyor | `subject`, `required`, `overlap_iou_threshold` | "Yeleksiz çalışan olursa haber ver." |
| `zone_absence` (terk) | Hedef, `duration_sec` boyunca bölgede yok | `targets`, `duration_sec` | "Nöbetçi 10 saniyeden uzun ayrılırsa haber ver." |
| `object_count` | Bölgedeki sayı eşiği sağlıyor | `targets`, `count_threshold`, `count_operator` (`gt`, `gte`, `lt`, `lte`, `eq`) | "5'ten fazla kişi olursa haber ver." |
| `loitering` | Özne `duration_sec` (varsayılan 30) boyunca bölgede | `subject`, `duration_sec` | "Bir kişi 30 saniyeden uzun beklerse haber ver." |
| `unauthorized_object` | Yasak sınıf bölgede | `targets` | "Bölgede çanta bırakılırsa haber ver." |
| `line_crossing` | Hedef bölgede görüldü | `targets` | "Hattı geçen olursa haber ver." |

Sınırlar:

- **Nesne takibi yoktur.** `loitering` ve terk koşulları "bu sınıftan biri bölgede var mı" sorusuna
  bakar; aynı kişi mi olduğunu bilmez. Bekleme süresi, tespit 1,5 saniyeden uzun kesilirse sıfırlanır.
- `line_crossing` yön bilmez; bölgede görünmeyi alarm sayar.
- Kişi tanıma yoktur: "Ahmet yerinde mi?" kuralı "bölgede bir kişi var mı" olarak derlenir.

İhlal iletileri de burada üretilir ve operatöre gösterilir: "Bölgede görüldü: baretsiz kişi",
"Kişi 12 saniyedir bölgede bekliyor", "Bölgedeki sayı sınırı aşıldı: 6 kişi".

### B.4 Çalışma döngüsü

Kod: `WebInterface/backend/live_detection_service.py`.

Her turda (en az 80 ms arayla), **etkin kuralı olan** ve **yeni kare getiren** her kamera için:

1. Kameraya uygulanan kurallar toplanır: kendi kuralları + `scope: system` kuralları, yalnızca açık olanlar.
2. Her bölge için:
   - Engel bölgesi → `change_detector.check_frame`.
   - Kişi / nesne bölgesi → planın modeli ve sınıflarıyla tespit. Aynı karede aynı model ve
     sınıflar birden çok bölgede isteniyorsa tespit bir kez yapılır.
   - `ConditionEvaluator.evaluate(plan, tespitler, çokgen)` → alarm ve tetikleyen koşullar.
3. Kameranın durumu yayınlanır (`/api/live/state` → `detections`): kutular, alarm ve alarm metni.
4. Alarm varsa ve aynı kamera + kural için son 30 saniyede kayıt açılmadıysa
   `anomaly_service.record_rule_violation` çağrılır.

Hiçbir kamerada etkin kural yoksa döngü 0,5 saniye uyur; tespit modeli hiç yüklenmez.

### B.5 Engel / değişiklik bölgeleri

Kod: `WebInterface/backend/change_detector.py`.

- **Referans:** "Referans al" anındaki canlı kare, çokgenle maskelenip 160×120 gri tonlamaya
  indirgenerek `change_refs/` altına kaydedilir. Canlı görüntü yoksa referans alınmaz (donmuş bir
  kareyle ayarlamak kalıcı yanlış alarm üretirdi).
- **Karşılaştırma:** Her karede aynı bölge aynı biçime getirilir ve referansla **SSIM** (yapısal
  benzerlik, 0–1) hesaplanır. Ayrıca fark görüntüsünde 400 pikselden büyük bölgelerin kapladığı alan
  oranı (`change_pct`) bulunur.

| SSIM | `alarm_level` | Alarm |
| :--- | :--- | :--- |
| < 0,72 | `alarm` | Evet |
| 0,72 – 0,88 | `warning` | Değişen alan %10'u geçerse evet |
| ≥ 0,88 | `clear` | Hayır |

SSIM, küçük ışık değişimlerine piksel farkından daha dayanıklıdır; yine de kalıcı ışık değişimi ya
da kameranın oynaması yanlış alarm üretir. Çözüm referansı yeniden almaktır.

### B.6 Kural ihlalinin kaydı

`record_rule_violation(kamera, kural başlığı, ileti, önem)`:

- Kayıt kimliği `rule_…`; `tier`, kuralın önemine göre `warning` ya da `critical`; skor sabit 75.
- Video: ihlalden **önceki** 5 saniye (kameranın tamponundan). Kamera yeni bağlandıysa var olan
  kadarı; 1 saniyeden azsa video kaydedilmez, yalnızca fotoğraf kalır.
- Özet: olağandışı hareketle aynı yol; ayrıca kuralın başlığı ve ihlal iletisi modele bağlam olarak verilir.

---

## C. Olay özeti

Kod: `Rule_Generator_LLM/vlm_summarizer.py`.

1. Olayın karelerinden eşit aralıklı **8 tanesi** seçilir (ilk ve son kare atlanır), uzun kenarı
   256 piksele küçültülür.
2. Kareler ve kısa bir yönerge görsel dil modeline gönderilir. Yönerge şu biçimi ister:

   ```
   **Özet Başlık:** Ne olduğunu anlatan tek cümle (en fazla 20 kelime).
   - En fazla 2 madde: başlıkta olmayan, karara yarayan bilgi.
   **Öneri:** Görevliye emir kipinde tek cümle (gerekmiyorsa yazılmaz).
   ```

   Kurallar: toplam 60 kelime; yalnızca karelerde görünen; tekrar, kıyafet rengi gibi önemsiz
   ayrıntı ve genel güvenlik bilgisi yok; sistem / kural / model adı ve teknik terim yok; kareler
   alarmı doğrulamıyorsa bunu başlıkta söyle.
3. Yanıt `compact_summary` ile **zorla** bu biçime indirgenir: tek başlık, başlığı yinelemeyen en
   çok iki madde (her biri ilk cümlesiyle), tek öneri. Model yönergeye uymasa da kayda uzun metin girmez.
4. Sonuç kayda yazılır: `ai_summary`, `ai_headline`, `ai_status: completed`.

Özet yazılamazsa (`ai_status: fallback`) kayda tek satırlık dürüst bir not düşer: "Görüntü
incelenemediği için özet yazılamadı (neden)". Nedenler: videodan kare alınamadı, servis
kullanılamıyor, servise ulaşılamadı, günlük kullanım kotası doldu.

Özet uzunluğunu ve biçimini değiştirmek için dosyanın başındaki sabitlere (`SUMMARY_MAX_WORDS`,
`SUMMARY_MAX_DETAILS`, `SUMMARY_MAX_TOKENS`, `FRAME_COUNT`) ve `_prompt` işlevine bakın.

**Maliyet:** Her olay bir model çağrısıdır. Hareketli bir sahnede olağandışı hareket algılama dakikada
birkaç olay üretebilir; servis kotası sınırlıysa uyarı seviyesini yükseltin ya da anahtarı boş bırakın.
