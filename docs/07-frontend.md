# 07 — Arayüz kodu

Dizin: `WebInterface/frontend/`. Derleme adımı, paket yöneticisi ya da çatı (framework) yoktur:
tarayıcının kendi ES modülleri, tek bir `index.html` ve düz CSS.

```
frontend/
├── index.html            Sayfa iskeleti, beş görünüm, pencereler, ikon seti
├── css/
│   ├── base.css          Renk ve ölçü değişkenleri, sıfırlama, yazı
│   ├── components.css    Düğme, form, rozet, kart, tablo, pencere, bildirim…
│   ├── layout.css        Kenar çubuğu, üst çubuk, içerik alanı, duyarlı düzen
│   └── live.css  events.css  rules.css  reports.css  cameras.css  settings.css     Sayfaya özgü stiller
└── js/
    ├── main.js           Giriş noktası: ortak parçaları başlatır, sayfaları kaydeder
    ├── router.js         Adres çubuğuna bağlı sayfa geçişi
    ├── shell.js          Saat, sistem durumu satırı, olay rozeti, bağlantı uyarısı
    ├── api.js            Sunucuyla konuşan tek modül
    ├── ui.js             Kaçışlama, bildirim, pencere, onay, biçimlendirme yardımcıları
    ├── labels.js         Teknik değerlerin sade dil karşılıkları
    ├── live.js           Canlı İzleme sayfası
    ├── stream.js         Bir <img> öğesine canlı video (WebSocket)
    ├── overlay.js        Görüntü üstü çizimler (bölgeler, tespitler)
    ├── events.js         Olaylar sayfası
    ├── event-detail.js   Olay penceresi
    ├── rules.js          Kurallar sayfası (liste + form)
    ├── zone-editor.js    Çokgen çizim aracı
    ├── reports.js        Raporlar sayfası (sayılar, grafik, tablolar, yazdırma)
    ├── cameras.js        Kameralar sayfası ve pencereleri
    └── settings.js       Ayarlar sayfası
```

## Kurallar

Bu kurallar kodun tamamında geçerlidir; yeni kod da bunlara uymalıdır.

1. **Sunucuyla yalnızca `api.js` konuşur.** Sayfalar `fetch` çağırmaz, adres kurmaz. Yeni bir uç
   nokta gerekiyorsa `api.js`'e bir işlev eklenir.
2. **Her sayfa aynı arayüzü dışa verir:** `mount(params)`, `unmount()` ve gerekiyorsa `canLeave()`.
3. **Görünmeyen sayfa çalışmaz.** `unmount`, sayfanın zamanlayıcılarını, WebSocket ve SSE
   bağlantılarını kapatır. Sekme arka plana geçince canlı video da durur.
4. **Olaylar devredilir.** Düğmelere tek tek dinleyici bağlanmaz; kapsayıcıya bir dinleyici konur ve
   `data-action` niteliğine bakılır. `onclick` niteliği ve `window.*` işlevi yoktur.
5. **Her dış metin kaçışlanır.** Kamera adı, kural başlığı, sunucu iletisi… HTML'e `escapeHTML` ile
   yazılır. Bildirimler (`showToast`) düz metindir.
6. **Görünürlük `hidden` niteliğiyle** değiştirilir, `style.display` ile değil. Durumlar `is-*`
   sınıflarıyla ifade edilir (`is-active`, `is-danger`, `is-open`…).
7. **Satır içi stil yoktur.** Tek istisna, veriden gelen bir rengi CSS değişkeni olarak vermektir
   (`style="--zone-color: …"`).
8. **Sihirli sayı yoktur.** Süreler ve sınırlar modülün başında adlandırılmış sabittir.

Sistem testi bunların bir kısmını denetler: `index.html`'de yinelenen `id` olmaması, betiklerin
`$("#…")` ile aradığı her öğenin sayfada bulunması, bütün modüllerin `/ui/` içinde çözülmesi.

## Sayfa yaşam döngüsü

```js
// main.js
registerView("live", { title: "Canlı İzleme", ...live });   // live.js: mount, unmount
startRouter("live");                                         // adres boşsa açılacak sayfa
```

`router.navigate(ad, params)` sırasıyla:

1. Geçerli sayfanın `canLeave()` işlevini bekler (kaydedilmemiş değişiklik varsa kullanıcıya sorar).
2. Geçerli sayfanın `unmount()` işlevini çağırır.
3. `<section id="view-ad">` dışındaki bölümleri gizler, menüyü ve başlığı günceller, adresi `#ad` yapar.
4. Yeni sayfanın `mount(params)` işlevini çağırır.

`params` bellekte taşınır, adrese yazılmaz. Örnek: olay penceresindeki "Bu kamerayı canlı izle"
düğmesi `navigate("live", { cameraId })` çağırır.

Bir sayfanın iskeleti:

```js
let mounted = false;
let wired = false;

function wire() {            // dinleyiciler yalnızca bir kez bağlanır
  wired = true;
  $("#ornek-liste").addEventListener("click", onListClick);
}

export function mount() {
  mounted = true;
  if (!wired) wire();
  load();                    // veriyi her girişte tazele
}

export function unmount() {
  mounted = false;
  clearInterval(timer);      // açık ne varsa kapat
}
```

## Modüller

### `api.js`
Her uç nokta için bir işlev. Hepsi aynı `request()` yardımcısını kullanır: zaman aşımı uygular,
başarısız yanıtı sunucunun `detail` metnini taşıyan bir `ApiError`'a çevirir. Çağıran taraf:

```js
try {
  await updateCamera(id, { name });
} catch (err) {
  showError("Kamera kaydedilemedi", err);   // "Kamera kaydedilemedi: <sunucunun nedeni>"
}
```

### `ui.js`

| Dışa aktarım | İşlev |
| :--- | :--- |
| `escapeHTML`, `icon(ad)`, `setHTML(öğe, html)` | Güvenli HTML; ikon; içerik yalnızca değiştiyse yeniden yazılır. |
| `$`, `$$` | `querySelector` / `querySelectorAll` kısaltmaları. |
| `showToast(ileti, tür, süre)`, `showError(önek, hata)` | Geçici bildirim. |
| `openModal(id)`, `closeModal(id)`, `initModals()`, `isAnyModalOpen()` | Pencereler. Kapatma düğmesi (`data-close`), arka plana tıklama ve `Esc` ortak işlenir; kapanınca öğede `modal:closed` olayı yayınlanır. |
| `confirmDialog({title, message, confirmText, danger})` | Onay penceresi; `Promise<boolean>`. Tehlikeli işlemde odak "Vazgeç"tedir. |
| `showImage(src, başlık)` | Tam ekran görsel. |
| `bindSegmented(grup, nitelik, onChange)` | Düğme grubunu tek seçimli denetim yapar. |
| `withBusy(düğme, metin, iş)` | İş sürerken düğmeyi kilitler. |
| `formatDuration`, `maskCredentials`, `copyText`, `downloadBlob`, `NO_IMAGE` | Yardımcılar. |

`setHTML`, listelerin her güncellemede baştan çizilmesini önler: üretilen HTML öncekiyle aynıysa
DOM'a dokunulmaz; böylece fare vurgusu, odak ve kaydırma bozulmaz.

### `shell.js`
5 saniyede bir `/api/system/stats` sorgular. Art arda iki başarısızlıkta "bağlantı koptu" şeridini
gösterir. Analiz sunucusu yanıt vermiyorsa her sayfanın üstündeki `#analysis-notice` satırını açar
(kurallar o sırada denetlenmez; kural listesi bunu kendiliğinden göstermez).
`subscribeSystemStats(dinleyici)` ile başka modüller aynı veriyi alır (Ayarlar'daki sistem durumu). `refreshEventsBadge()` menüdeki incelenmemiş olay sayısını günceller.

### `stream.js`
`startStream(cameraId, img, maxFps)` → durdurma işlevi. WebSocket'ten gelen her JPEG'i `<img>`'e
verir. Tarayıcı bir kareyi çözerken yenisi gelirse bekleyen kare değiştirilir ("son kare kazanır");
böylece yoğun bir sekme kare atlar ama gerçek zamanın gerisine düşmez. Bağlantı koparsa artan
aralıklarla yeniden dener, bu arada saniyede bir fotoğraf çeker.

### `overlay.js`
`drawOverlay(canvas, img, sahne)`: kural bölgeleri, tespit kutuları ve engel bölgelerinin durumu.
Görüntü `object-fit: contain` ile sığdırıldığı için, 0–1 aralığındaki koordinatlar önce görüntünün
gerçekten kapladığı alana çevrilir.

### `live.js`
- `/api/live/state` 400 ms'de bir sorgulanır; yanıt gelmeden yenisi gönderilmez.
- `tileState(id)` bir karonun ne göstereceğine tek yerde karar verir: sinyal yok → kural alarmı →
  kritik → şüpheli → normal.
- Karolar `IntersectionObserver` ile izlenir; ekranda olmayan karonun yayını durdurulur.
- Kamera listesi ya da kurallar başka bir ekrandan değişirse duvar yeniden kurulur.

### `events.js` ve `event-detail.js`
`events.js` listeyi, süzgeçleri, sayfalamayı ve SSE bağlantısını yönetir; süzme tarayıcıda yapılır
(en çok 300 olay yüklenir). `event-detail.js` olay penceresidir ve hem Olaylar sayfası hem canlı
izlemedeki geçmiş tarafından kullanılır: `openEventDetail(olay, değişince)`. Pencere açıkken olay
sürüyorsa ya da özeti yazılıyorsa 3 saniyede bir kendini tazeler, bu yüzden SSE olmayan sayfada da
güncel kalır.

### `rules.js` ve `zone-editor.js`
`zone-editor.js` yalnızca çizimi bilir: `createZoneEditor(canvas, { onChange, canDraw, onReject })` bir nesne
döndürür (`setZones`, `getZones`, `getSelected`, `select`, `updateSelected`, `removeZone`,
`finishDrawing`, `cancelDrawing`, `undo`, `clear`, `resize`, `draftPoints`). Formla ilgili her şey
`rules.js`'tedir. Köşeler 0–1 aralığında saklanır. Kenarı önceki bir kenarı kesecek köşe kabul
edilmez (`onReject` çağrılır); dokunmatik ekranda ilk köşeye tıklayıp kapatma alanı daha geniştir.

### `cameras.js`
Liste, ağ taraması, ekleme, düzenleme (canlı önizlemeli), bilgi ve silme. Küçük resimler 2,5
saniyede bir, önce bellekte yüklenip sonra değiştirilerek tazelenir (titreme olmaz).

### `settings.js`
Form geneldir: her denetim hangi ayarı düzenlediğini `data-setting="bölüm.alan"` ile söyler; modül
ayar adlarını bilmez. Yeni bir ayar eklemek için çoğu zaman yalnızca `index.html`'e bir denetim
eklemek yeter.

```html
<label for="set-padding">Olay öncesi ve sonrası <output data-output="recording.padding_sec" data-unit=" sn"></output></label>
<input type="range" id="set-padding" data-setting="recording.padding_sec" min="0.5" max="5" step="0.5">
```

### `labels.js`
`classLabel("NO-Hardhat")` → "Baretsiz kişi"; `describePlan(plan_summary)` → "Baretsiz kişi — bölgede
görülünce". Bilinmeyen sınıf adı olduğu gibi gösterilir. Yeni bir model sınıfı eklendiğinde buraya da
eklenmelidir (aynı sözlüğün sunucu tarafı: `Rule_Generator_LLM/evaluator.py`, `_CLASS_LABELS`).

## Stil sistemi

- Renk, köşe yarıçapı, yazı ve temel ölçüler `base.css`'teki değişkenlerdedir
  (`--bg`, `--surface`, `--accent`, `--ok`, `--warn`, `--danger`, `--radius`…). Yeni bir stil sabit
  renk yazmaz, değişken kullanır.
- Ortak parçalar `components.css`'tedir: `.btn` (`.btn-primary`, `.btn-danger`, `.btn-sm`),
  `.btn-icon`, `.input`, `.select`, `.textarea`, `.field`, `.switch`, `.check`, `.badge`, `.chip`,
  `.segmented`, `.card`, `.toolbar`, `.empty`, `.notice`, `.table`, `.modal`, `.toast`.
- İkonlar `index.html`'in başındaki SVG kümesindedir; HTML'de `<svg class="icon"><use href="#i-ad"/></svg>`,
  JS'te `icon("ad")`.
- Duyarlı düzen: 1100 pikselin altında kenar çubuğu yalnızca ikon gösterir; 640 pikselin altında
  ekranın altına iner.

## Yeni sayfa eklemek

1. `index.html`: menüye `<a class="nav-item" href="#rapor" data-view="rapor">` ve içerik alanına
   `<section id="view-rapor" class="view" hidden>` ekleyin.
2. `js/rapor.js`: `mount` ve `unmount` dışa verin.
3. `js/main.js`: `registerView("rapor", { title: "Raporlar", ...rapor })`.
4. Sayfaya özgü stil gerekiyorsa `css/rapor.css` oluşturup `index.html`'e bağlayın.
5. Gereken uç noktalar için `js/api.js`'e işlev ekleyin.

## Tarayıcıda saklananlar

| Anahtar | İçerik |
| :--- | :--- |
| `aegis.events.layout` | Olaylar: `cards` / `table` |
| `aegis.cameras.layout` | Kameralar: `grid` / `list` |
| `aegis-ui-refreshed` (oturum) | Eski önbellekten yenileme döngüsünü önleyen zaman damgası |
