# 09 — Veri ve yapılandırma

## Ortam değişkenleri

Depo kökündeki `.env` dosyasından ya da ortamdan okunur; ortamda tanımlı olan `.env`'i ezer.

| Değişken | Varsayılan | Etkisi |
| :--- | :--- | :--- |
| `EVREN_API_KEY` | boş | Dil modeli servisinin anahtarı. Boşsa servis kullanılmaz. |
| `EVREN_BASE_URL` | `https://evren-llmapi.ssyz.org.tr/v1` | Servisin adresi (OpenAI uyumlu API). |
| `EVREN_VLM_MODEL` | `qwen3-vl-30b` | Kural derleme ve özet için model adı. |
| `AEGIS_DATA_DIR` | `WebInterface/backend` | Veri dizini. |
| `AEGIS_LOCK_WAIT_SEC` | `20` | Açılışta veri dizini kilidi için beklenen süre. |

`.env` iki yerde okunur: `WebInterface/run.sh` dosyadaki bütün değişkenleri ortama aktarır;
`Rule_Generator_LLM/llm_config.py` ise sunucu `run.sh` olmadan (doğrudan `uvicorn` ile ya da bir
betikten) başlatıldığında `EVREN_*` değerlerini oradan alır. `AEGIS_*` değişkenleri bu ikinci yolda
`.env`'den okunmaz; komut satırında verilmelidir.

## Veri dizini

```
<AEGIS_DATA_DIR>/
├── cameras_db.json          Kameralar (şifreler düz metin!)
├── rules_db.json            Kurallar, bölgeler ve derlenmiş planlar
├── settings.json            Ayarlar
├── anomaly_journal.json     Olay günlüğü
├── .aegis.lock              Tek örnek kilidi (içinde süreç numarası)
├── change_refs/             Engel bölgelerinin referans görüntüleri
└── recordings/
    ├── clips/               Olay videoları      clip_<olay kimliği>.mp4
    └── snapshots/           Olay fotoğrafları   snap_<olay kimliği>.jpg
```

- Bu dosyaların hiçbiri depoya girmez (`.gitignore`). Boş bir veri diziniyle sunucu sıfırdan başlar.
- Dosyalar bellekteki durumun dökümüdür; sunucu çalışırken elle düzenlemeyin. (`cameras_db.json` ve
  `rules_db.json` dışarıdan değişirse yeniden yüklenir, diğerleri yüklenmez.)
- **Yedekleme:** sunucuyu durdurup dizini kopyalamak yeterlidir.
- **Sıfırlama:** sunucuyu durdurup ilgili dosyayı silin.

### `cameras_db.json`

Kamera kimliğinden kayda sözlük.

| Alan | Anlamı |
| :--- | :--- |
| `id` | `cam_<ip>_<port>` |
| `ip`, `port`, `rtsp_port` | Adres; `port` ONVIF servis portudur. |
| `username`, `password` | ONVIF / RTSP hesabı. **Düz metin.** API yanıtlarında `password` yer almaz. |
| `name`, `description` | Görünen ad; kameranın neyi gördüğü. |
| `manufacturer`, `model`, `firmware_version`, `serial_number` | Cihazdan okunan bilgiler. |
| `resolution`, `encoding`, `framerate`, `profiles_supported`, `profiles_detail` | Yayın bilgileri. |
| `stream_uri`, `snapshot_uri` | Cihazın bildirdiği RTSP ve fotoğraf adresleri. |
| `status`, `status_message`, `last_seen` | Son iletişimin sonucu. |

### `rules_db.json`

Kural kimliğinden kayda sözlük.

| Alan | Anlamı |
| :--- | :--- |
| `id`, `title`, `enabled` | `rule_…`; ad; açık mı. |
| `scope`, `camera_id`, `camera_name` | `camera` ya da `system`. |
| `description` | Bölge açıklamalarının birleşimi (bilgi amaçlı). |
| `severity` | `warning` / `critical`; ihlal kaydının seviyesini belirler. Arayüz her zaman `warning` gönderir. |
| `zones[]` | Aşağıdaki tablo. |
| `created_at`, `updated_at` | Zaman damgaları. `updated_at` plan önbelleğinin anahtarıdır. |

Bölge (`zones[]`):

| Alan | Anlamı |
| :--- | :--- |
| `id`, `name`, `color_idx` | Kimlik, ad, arayüzdeki renk sırası. |
| `zone_type` | `detection` / `change_detection`. |
| `description` | Düz cümle (yalnızca `detection`). |
| `points[]` | `{x, y}`, 0–1 aralığında köşeler. |
| `detection_plan`, `compile_meta`, `compile_logs`, `raw_llm_response` | Derleme çıktısı (bkz. bölüm 08). |

Eski sürümlerden kalan `assignee`, `escalation`, `actions` alanları okunmaz; zararsızdır.

### `anomaly_journal.json`

Olay kayıtlarının listesi, en yeni başta. Kapasite `max_stored_clips` kadardır; aşan en eski kayıt
kanıtlarıyla silinir.

| Alan | Anlamı |
| :--- | :--- |
| `id` | Önek türü söyler: `anom_` olağandışı hareket, `rule_` kural ihlali, `sim_` deneme. |
| `timestamp`, `timestamp_str`, `date_str` | Açılış zamanı. |
| `camera_id`, `camera_name` | Olayın kamerası (ad, olay anındaki addır). |
| `score`, `tier`, `label` | En yüksek skor; `warning` / `critical`; seviyenin adı. |
| `anomaly_type` | Kural ihlalinde `Kural İhlali: <kural adı>`, olağandışı harekette her zaman `Olağandışı hareket`. Arayüz ikincisinde özetin başlığını gösterir. |
| `rule_title`, `rule_description` | Yalnızca kural ihlalinde: kuralın adı ve ne görüldüğü. |
| `start_time_str`, `peak_time_str`, `end_time_str`, `duration_sec` | Videonun kapsadığı aralık. |
| `is_ongoing` | Olay sürüyor. |
| `snapshot_url`, `clip_url` | Kanıt adresleri; video yoksa `clip_url` `null`. |
| `clip_expired` | Video disk kotası nedeniyle silindi. |
| `ai_status` | `none`, `generating`, `completed`, `fallback`, `error`, `interrupted`. |
| `ai_summary`, `ai_headline` | Özet metni ve başlığı. |
| `ai_verdict` | Özetin görüntü hakkındaki kararı: `confirmed`, `normal`, `unclear` ya da `null`. Yalnızca bilgidir. |
| `operator_label` | `correct`, `false_positive`, `unlabeled`; alan yoksa incelenmemiştir. |
| `operator_notes`, `operator_name`, `operator_labeled_at` | Kararın ayrıntıları. |
| `interrupted` | Olay sürerken sunucu yeniden başladı. |
| `message` | Tek satırlık metin (aramada kullanılır). |

## Ayarlar (`settings.json`)

Her değer kaydedilirken aşağıdaki aralığa çekilir (`settings_service._sanitize`). Değişiklik
sunucuyu yeniden başlatmadan uygulanır.

### `anomaly`

| Alan | Varsayılan | Aralık | Etkisi | Arayüzde |
| :--- | :--- | :--- | :--- | :--- |
| `continuous_pipeline` | `true` | — | Olağandışı hareket algılama açık / kapalı. | Algılama |
| `threshold_normal` | 25 | 1–95 | **Uyarı** eşiği. | Uyarı seviyesi (5–45) |
| `threshold_warning` | 50 | 2–99, her zaman > `threshold_normal` | **Kritik** eşiği. | Kritik seviyesi (30–80) |
| `triton_url` | `localhost:8000` | — | Analiz sunucusu (`host:port`). | Gelişmiş |
| `model_name` | `anomaly_detector` | — | Anomali modelinin adı. | Gelişmiş |
| `batch_size` | 4 | 1–8 | Tek istekteki kamera sayısı. | Gelişmiş |
| `clip_len` | 16 | sabit | Modelin girdi uzunluğu; değiştirilemez. | — |

### `recording`

| Alan | Varsayılan | Aralık | Etkisi | Arayüzde |
| :--- | :--- | :--- | :--- | :--- |
| `auto_record_clips` | `true` | — | Olay videosu kaydı. | Kayıt |
| `padding_sec` | 1.5 | 0–10 | Olaydan önce ve sonra eklenen süre. | Olay öncesi ve sonrası (0,5–5) |
| `max_clip_duration_sec` | 60 | 5–300 | Bir olayın / videonun en uzun süresi. | En uzun video (15–180) |
| `max_storage_mb` | 1000 | 50–100000 | Videolar için disk kotası. | Kayıtlar için ayrılan alan (100–5000) |
| `tolerance_sec` | 2.0 | 0,5–10 | Bundan kısa duraklamalar olayı bölmez. | Gelişmiş: Olay birleştirme süresi |
| `max_stored_clips` | 500 | 10–5000 | En çok video **ve** olay kaydı sayısı. | Gelişmiş: En fazla video sayısı |

Arayüzdeki kaydırıcıların aralığı sunucunun kabul ettiğinden dardır; dosyada daha geniş bir değer
varsa kaydırıcı o değeri gösterecek kadar genişler.

### `live_wall`

| Alan | Varsayılan | Etkisi |
| :--- | :--- | :--- |
| `default_layout` | `grid-3x2` | Açılış düzeni: `grid-1x1`, `grid-2x2`, `grid-3x2`, `grid-4x3`. |
| `alarm_borders` | `true` | Alarmda çerçeve vurgusu. |
| `hud_badges` | `true` | Uyarı / alarm etiketi. (Sinyal etiketi her zaman görünür.) |
| `click_to_focus` | `true` | Tıklayınca büyütme. |
| `zero_latency_mode` | `true` | Kapalıyken yayın saniyede 8 kareyle sınırlanır. |

## Bellek ve disk hesabı

- **Bellek:** Her kamera, en uzun olay videosunu kesebilecek kadar JPEG karesini bellekte tutar:
  `max_clip_duration_sec + 2 × padding_sec + tolerance_sec + 8` saniye. Varsayılanlarla ~73 saniye;
  1080p ve 25 kare/sn'de kamera başına kabaca 60–80 MB. Çok kameralı kurulumda `max_clip_duration_sec`
  değerini düşürmek belleği doğrudan azaltır.
- **Disk:** Videolar H.264 `ultrafast` ile kodlanır; 5 saniyelik 1080p video kabaca 0,3–0,7 MB.
  Kota dolunca en eski videolar silinir, olay kaydı ve fotoğrafı kalır (`clip_expired`).

## `.gitignore` kapsamı

| Dışarıda tutulan | Neden |
| :--- | :--- |
| `.env` | Erişim anahtarı. |
| `WebInterface/backend/*.json`, `recordings/`, `change_refs/`, `static/` | Çalışma verisi; kamera şifrelerini içerir. |
| `*.pt`, `*.onnx`, `*.plan`, `*.engine`, `*.trt`, `*.ts`, `*.pkl` | Model ağırlıkları (büyük, makineye özel). |
| `*.mp4`, `*.avi`, `*.png`, `*.jpg`, `*.jpeg` | Videolar ve görseller. |
| `.conda/`, `venv/`, `__pycache__/`, `.text_feat_cache/` | Ortamlar ve önbellekler. |
| `*.log`, `Camera_System_Simulator/recordings/` | Günlükler ve simülatör çıktısı. |

`*.png` / `*.jpg` kuralı belgelere görsel eklemeyi de engeller; eklemek gerekirse o dosya için
istisna yazın (`!docs/**/*.png`).
