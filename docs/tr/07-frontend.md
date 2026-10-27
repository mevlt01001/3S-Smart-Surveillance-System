# 07 — Arayüz kodu

Dizin: `WebInterface/frontend/`. Derleme adımı, paket yöneticisi ya da çatı (framework) yoktur:
tarayıcının kendi ES modülleri, tek bir `index.html` ve düz CSS.

```
frontend/
├── index.html            Sayfa iskeleti, altı görünüm, pencereler, ikon seti
├── css/
│   ├── base.css          Renk ve ölçü değişkenleri, sıfırlama, yazı
│   ├── components.css    Düğme, form, rozet, kart, tablo, pencere, bildirim…
│   ├── layout.css        Kenar çubuğu, üst çubuk, içerik alanı, duyarlı düzen
│   └── live.css  events.css  rules.css  reports.css  cameras.css  settings.css     Sayfaya özgü stiller
└── js/
    ├── theme.js          Tema seçimi; stillerden önce yüklenen düz betik
    ├── i18n.js           Arayüz dili: t(), translatePage(), setLanguage()
    ├── i18n-en.js        İngilizce katalog (Türkçe metin → İngilizce metin)
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
9. **Her metin `t()`'den geçer.** Metinler kodda Türkçe yazılır ve `i18n-en.js`'te karşılığı bulunur
   (bkz. "Arayüz dili").

Sistem testi bunların bir kısmını denetler: `index.html`'de yinelenen `id` olmaması, betiklerin
`$("#…")` ile aradığı her öğenin sayfada bulunması, bütün modüllerin `/ui/` içinde çözülmesi ve her
metnin İngilizce karşılığının olması.

## Sayfa yaşam döngüsü

```js
// main.js
registerView("live", { title: t("Canlı İzleme"), ...live });   // live.js: mount, unmount
startRouter("live");                                            // adres boşsa açılacak sayfa
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

## Arayüz dili

Kaynak dil ve varsayılan Türkçedir; İngilizce her cihazda Ayarlar → Görünüm'den seçilir.

- **`t(metin, parametreler)`** (`i18n.js`) metni arayüz dilinde döndürür. İngilizce kipte Türkçe metni
  `i18n-en.js`'te arar, karşılığı yoksa Türkçesini döndürür. `{ad}` yer tutucuları parametrelerden
  doldurulur:

  ```js
  showToast(t("Kural kaydedildi."));
  t("{n} olay", { n: 3 });            // İngilizce kipte "3 events"
  ```

  `t()`'ye her zaman cümlenin tamamı verilir, parçalar yapıştırılmaz; iki dilde sözcük sırası farklıdır.
- **`translatePage()`** `index.html`'in sabit metinlerini açılışta bir kez çevirir: metin düğümleri ile
  `placeholder`, `title`, `aria-label` ve `alt` nitelikleri. Metinler, çevresindeki boşluk dışında
  yazıldığı gibi eşleştirilir.
- **`setLanguage(dil)`** seçimi `localStorage`'a (`aegis-lang`) yazar ve sayfayı yeniler; böylece her
  sayfa yeniden çizim mantığı gerekmeden yeni dilde açılır. Tarih ve sayılar için `lang` ve `locale`
  (`tr-TR` / `en-GB`) dışa verilir; `ui.js`'teki `formatPercent` ve `formatDuration` bunlara uyar.
- **Katalog** `i18n-en.js`, `// catalogue:begin` ve `// catalogue:end` işaretleri arasında bir JSON
  nesnesidir; sistem testi onu böyle okur. Anahtarlar, Türkçe metinlerin kodda geçtiği hâlidir. Bir
  cümlenin devamı olan değer baştaki boşluğunu korur.
- **Sunucu** kural plan cümlelerini ve çalışma saati metnini `Accept-Language` başlığının dilinde
  yazar; `api.js` bu başlığı her istekte gönderir. Sunucunun hata iletileri Türkçedir ve katalogda
  karşılıkları vardır.
- **Çalışırken Türkçe üretilen metinleri** — kural motorunun alarm cümleleri — `labels.js`'teki
  `alarmText()` yeniden yazar. Bir kez yazılıp saklanan metinler (olay özetleri, kural derleyicinin
  notları, kullanıcının girdiği adlar) yazıldıkları dilde kalır.

Yeni metin eklemek: metni Türkçe olarak `t("…")` içine (ya da `index.html`'e) yazın ve karşılığını
`i18n-en.js`'e ekleyin. Karşılığı olmayan bir `t("…")` ya da sözcük içeren bir `index.html` metni sistem
testini (grup [14]) düşürür.

## Modüller

### `api.js`
Her uç nokta için bir işlev. Hepsi aynı `request()` yardımcısını kullanır: zaman aşımı uygular,
`Accept-Language` gönderir, başarısız yanıtı sunucunun `detail` metnini taşıyan bir `ApiError`'a çevirir. Çağıran taraf:

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
| `showToast(ileti, tür, süre)`, `showError(önek, hata)` | Geçici bildirim; ikisi de metnini çevirir. |
| `openModal(id)`, `closeModal(id)`, `initModals()`, `isAnyModalOpen()` | Pencereler. Kapatma düğmesi (`data-close`), arka plana tıklama ve `Esc` ortak işlenir; kapanınca öğede `modal:closed` olayı yayınlanır. |
| `confirmDialog({title, message, confirmText, danger})` | Onay penceresi; `Promise<boolean>`. Tehlikeli işlemde odak "Vazgeç"tedir. |
| `showImage(src, başlık)` | Tam ekran görsel. |
| `bindSegmented(grup, nitelik, onChange)` | Düğme grubunu tek seçimli denetim yapar. |
| `withBusy(düğme, metin, iş)` | İş sürerken düğmeyi kilitler. |
| `formatDuration`, `formatPercent`, `maskCredentials`, `copyText`, `downloadBlob`, `NO_IMAGE` | Yardımcılar. |

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
(ve katalog karşılığı) eklemek yeter.

```html
<label for="set-padding">Olay öncesi ve sonrası <output data-output="recording.padding_sec" data-unit=" sn"></output></label>
<input type="range" id="set-padding" data-setting="recording.padding_sec" min="0.5" max="5" step="0.5">
```

Görünüm altındaki tema ve dil seçicileri ayar değildir: o cihazda hemen etki ederler
(`window.aegisTheme.set`, `setLanguage`).

### `labels.js`
`classLabel("NO-Hardhat")` → "Baretsiz kişi" (İngilizce kipte "Person without a hard hat"); `describePlan(plan_summary)` → "Baretsiz kişi — bölgede
görülünce". Bilinmeyen sınıf adı olduğu gibi gösterilir. Yeni bir model sınıfı eklendiğinde buraya da
eklenmelidir (aynı sözlüğün sunucu tarafı: `Rule_Generator_LLM/evaluator.py`, `_CLASS_LABELS`; İngilizce
kural cümleleri: `Rule_Generator_LLM/manual.py`, `_CLASS_LABELS_EN`). `alarmText(metin)` kural motorunun
Türkçe alarm cümlelerini İngilizce kipte yeniden yazar.

## Stil sistemi

- Renk, köşe yarıçapı, yazı ve temel ölçüler `base.css`'teki değişkenlerdedir. Yeni bir stil sabit
  renk yazmaz, değişken kullanır. Tek istisna, video üstündeki yazı ve düğmelerdir (siyah zemin,
  beyaz yazı): onlar temadan bağımsızdır.
- **Renk rolleri.** Her tema aynı değişkenleri tanımlar; bir stil rengi rolüne göre seçer:

  | Değişken | Rolü |
  | :--- | :--- |
  | `--bg`, `--surface`, `--surface-2`, `--surface-3`, `--border`, `--border-strong` | Zeminler ve çizgiler |
  | `--text`, `--text-2`, `--text-3` | Yazı: asıl, ikincil, silik |
  | `--primary`, `--primary-hover`, `--primary-soft`, `--on-primary` | **Eylem ve denetim rengi:** ana düğme, anahtar, kaydırıcı, odak çerçevesi, seçili etiket |
  | `--accent`, `--accent-soft`, `--accent-ink`, `--on-accent` | **Marka vurgusu (açık turuncu):** logo, etkin menü öğesi, "buraya bak" vurguları. `--accent-ink` aynı tonun yazı olarak okunabilen koyusudur |
  | `--ok`, `--warn`, `--danger`, `--info` (+ `-soft`) | Durum renkleri; yazı olarak okunabilir koyulukta |
  | `--warn-solid`, `--on-warn-solid` | Uyarının dolgu ya da kenarlık hâli (parlak kehribar) ve üstündeki yazı |
  | `--series-rule`, `--series-movement` | Rapor grafiğinin iki serisi; her temanın zemini için renk körlüğü ayrımı ve kontrastı ölçülmüştür |

- **Temalar.** `<html data-theme="light | navy | dark">`; varsayılan `light` (`:root`'taki değerler).
  `js/theme.js` sayfanın başında, stillerden önce yüklenen düz bir betiktir (modül değildir): seçimi
  `localStorage`'dan okur ve ilk karede uygular, `window.aegisTheme.get()` / `.set(ad)` sunar.
  Açık temada menü laciverttir: `base.css`, `.sidebar` içinde zemin ve yazı değişkenlerini yeniden
  tanımlar. Yeni tema eklemek: `base.css`'e bir `:root[data-theme="ad"]` bloğu, `theme.js`'teki
  listeye bir satır ve Ayarlar'daki seçiciye bir düğme.
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
3. `js/main.js`: `registerView("rapor", { title: t("Raporlar"), ...rapor })`.
4. Sayfaya özgü stil gerekiyorsa `css/rapor.css` oluşturup `index.html`'e bağlayın.
5. Gereken uç noktalar için `js/api.js`'e işlev ekleyin.
6. Yeni metinlerin İngilizce karşılıklarını `js/i18n-en.js`'e ekleyin.

## Tarayıcıda saklananlar

| Anahtar | İçerik |
| :--- | :--- |
| `aegis.events.layout` | Olaylar: `cards` / `table` |
| `aegis.cameras.layout` | Kameralar: `grid` / `list` |
| `aegis-theme` | Tema: `light` / `navy` / `dark` |
| `aegis-lang` | Dil: `tr` / `en` |
| `aegis-ui-refreshed` (oturum) | Eski önbellekten yenileme döngüsünü önleyen zaman damgası |
