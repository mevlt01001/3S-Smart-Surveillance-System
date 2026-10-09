# 03 — Kullanım kılavuzu

Arayüzün beş sayfası soldaki menüdedir. Sol alttaki satır sistemin durumunu söyler:

| Gösterge | Anlamı |
| :--- | :--- |
| ● Sistem çalışıyor | Kameralar izleniyor, analiz çalışıyor. |
| ● Analiz durdu | Analiz sunucusuna ulaşılamıyor. Canlı görüntü çalışır; olay algılama ve kurallar durur. Aynı uyarı her sayfanın üstünde kırmızı bir satır olarak da görünür. |
| ● Bağlantı yok | Tarayıcı sunucuya ulaşamıyor. Ekranın üstünde kırmızı şerit de çıkar; ekrandaki bilgiler eskimiş olabilir. |

"Olaylar"ın yanındaki sayı, henüz incelenmemiş olay sayısıdır.

---

## Canlı İzleme

Açılış sayfasıdır.

| Denetim | İşlev |
| :--- | :--- |
| **1 / 4 / 6 / 12** | Ekran düzeni: bir satırda 1, 2, 3 ya da 4 kamera. Fazlası aşağı doğru kayar. |
| **Yalnızca alarmdakiler** | Sadece uyarı veren, alarmdaki ya da sinyali kesilen kameraları gösterir. |
| **Bölgeler** | Kurallarda çizilen bölgeleri görüntünün üzerine çizer. |
| **Tespitler** | Tespit edilen kişi ve nesneleri çerçeveler; engel bölgelerinin durumunu gösterir. |
| **n/m çevrimiçi** | Görüntü veren kamera sayısı. |

### Kamera karosu

- Sol üstte kameranın adı ve durum noktası: yeşil (normal), turuncu (uyarı), kırmızı (alarm),
  mavi yanıp sönen (bağlanıyor), gri (sinyal yok).
- Sağ üstteki etiket yalnızca bir durum varken görünür: **Şüpheli hareket**, **Kritik hareket**,
  bir kural ihlalinin açıklaması, **Bağlanıyor…** ya da **Sinyal yok**.
- Alarmda çerçeve renklenir; kritik durumda yanıp söner.
- Sinyal kesilince son kare soluk ve gri kalır; donmuş bir görüntü canlıymış gibi gösterilmez.
- Sağ alttaki düğmeler: **fotoğraf** (o anki kareyi indirir) ve **büyüt**.
- Engel / değişiklik bölgesi olan kamerada ayrıca **Referans al** düğmesi vardır (aşağıya bakın).

### Tek kamera görünümü

Bir karoya tıklayınca kamera büyür ve altında iki şey açılır:

- **Son 30 dakika** şeridi: her dilim yeşil (olay yok), turuncu (uyarı) ya da kırmızı (kritik).
  Renkli dilime tıklayınca o olay açılır.
- **Bu kameranın son olayları** listesi.

Çıkmak için "Tüm kameralar"a, görüntüye ya da `Esc` tuşuna basın.

---

## Olaylar

Kaydedilen her alarm burada listelenir. Yeni olaylar sayfa yenilenmeden listenin başına düşer.

Bir kural ihlali sürdüğü sürece **tek olaydır**: kartında "Sürüyor" yazar; ihlal bitince ne kadar
sürdüğü görünür (örneğin "22 dk"). Videosu ihlalin başladığı anı gösterir.

### Süzme

| Denetim | Seçenekler |
| :--- | :--- |
| Arama | Kamera adı, olay başlığı, kural açıklaması ve özet metninde arar. |
| Kamera | Olayı olan kameralar. |
| Zaman | Tümü, son 15 dakika, son 1 saat, son 6 saat, bugün. |
| Tür | Kritik, Uyarı, Kural ihlali. |
| Durum | İncelenmemiş, Doğru alarm, Hatalı alarm. |

Sağdaki iki düğme kart ve liste görünümü arasında geçer. **Dışa aktar**, o an süzülmüş olayları
Excel'de açılan bir CSV dosyası olarak indirir. **Tümünü sil**, bütün olayları videoları ve
fotoğraflarıyla birlikte kalıcı olarak siler (onay ister).

### Olay kartı

Fotoğraf (video varsa oynat simgesiyle), süre, seviye rozeti, tarih-saat, başlık, kamera ve varsa
tek satırlık özet. Olağandışı hareket olaylarında başlık, özet yazılana kadar "Olağandışı
hareket"tir; sonra özetin ne olduğunu anlatan cümlesi olur.

Seviye rozetinin yanında gri bir **Olağan görünüyor** rozeti varsa, özet görüntüde olağandışı bir
şey görmemiştir. Bu yalnızca bir ipucudur: özet birkaç küçük kareye bakar ve yanılabilir, bu yüzden
olay silinmez ve seviyesi değişmez. Videoyu izleyip kararı siz verin. Altındaki **Doğru** / **Hatalı** düğmeleri olayı pencereyi açmadan işaretler;
seçili düğmeye yeniden basmak kararı geri alır.

### Olay penceresi

Karta tıklayınca açılır.

- **Video.** Oynatıcının altında −2 sn, +2 sn ve hız (1× → 0,5× → 0,25× → 2×) düğmeleri.
  **Kareleri göster**, videodan eşit aralıklı sekiz kareyi dizer; kareye tıklayınca büyür.
  **İndir**, videoyu MP4 olarak kaydeder.
- **Bilgiler.** Kamera, saat aralığı ve süre; kural ihlalinde kuralın ne gördüğü, olağandışı
  harekette hareket seviyesi.
- **Olay özeti.** Tek cümlelik başlık, en fazla iki ayrıntı ve bir öneri. Özet olay bittikten
  birkaç saniye sonra kendiliğinden gelir. **Yeniden oluştur** özeti baştan yazdırır.
- **Bu alarm doğru muydu?** Doğru alarm / Hatalı alarm.
- **Bu kamerayı canlı izle.** Canlı İzleme'de o kameranın tek kamera görünümünü açar.

Video yoksa (kayıt kapalıysa ya da video disk kotası nedeniyle silindiyse) olay anı fotoğrafı gösterilir.

---

## Kurallar

Liste; her kuralın adını, ne aradığını, hangi kamerada geçerli olduğunu ve açık olup olmadığını gösterir.

| Rozet | Anlamı |
| :--- | :--- |
| Hazırlanıyor | Açıklama işleniyor; kural birkaç saniye içinde çalışmaya başlar. |
| Genel ayarla çalışıyor | Açıklama tam çözümlenemedi. Açıklamayı sadeleştirin ya da **Yeniden dene**. |
| Hazır değil / Hazırlanamadı | Kural şu an çalışmıyor. **Yeniden dene**'ye basın; düzelmezse sol alttaki duruma bakın. |
| Yapılamıyor | İsteğiniz kameradan anlaşılabilecek bir şey değil (örneğin ses ya da plaka okuma gerektiriyor). Rozetin üstüne gelince nedeni ve ne isteyebileceğiniz yazar. Kural çalışmaz; açıklamayı değiştirin. |
| Kamerası yok | Kuralın kamerası silinmiş. Düzenleyip başka bir kameraya taşıyın. |

Bölgenin altında turuncu bir not varsa kural çalışıyordur ama **istediğinizden farklı** çalışıyordur.
Sistem yapamadığı bir şey istendiğinde amaca en yakın kuralı kurar ve farkı size söyler. Örneğin
"Ahmet yerinden ayrılırsa haber ver" yazarsanız not şunu der: "Kişileri adıyla ayırt edemem. Bunun
yerine bölgede kimse kalmadığında haber veririm; Ahmet'in yerine başka biri gelirse haber vermem."
Aynı not, kuralı kaydettiğinizde bildirim olarak da gösterilir.

Rozet yoksa kural hazırdır. Satırdaki anahtar kuralı açıp kapatır; kalem düzenler, çöp kutusu siler.

### Yeni kural

1. **Yeni kural**'a basın.
2. Kuralın geçerli olacağı yeri seçin: **Tek kamera** (ve kamerayı) ya da **Tüm kameralar**.
3. Görüntüye tıklayarak (telefonda dokunarak) bölgenin köşelerini işaretleyin, sonra **Bölgeyi
   tamamla**'ya basın. İlk noktaya tıklamak, çift tıklamak ya da `Enter` de bölgeyi kapatır.
   `Backspace` ve **Geri al** son noktayı geri alır, `Esc` çizimi iptal eder.
   Bölgenin kenarları birbirini kesemez; kesecek bir köşe kabul edilmez.
   Bir kuralda birden çok bölge olabilir; her biri "Bölgeler" satırında bir etiket olur.
4. Seçili bölge için **Ne izlensin?** sorusunu yanıtlayın:
   - **Kişi ve nesneler, kendi cümlenizle:** bölgede ne olunca haber verileceğini yazın.
     Altındaki hazır cümlelerden biriyle başlayabilirsiniz.
   - **Kişi ve nesneler, listeden:** ne aranacağını (kişi, araç, baretsiz kişi, yeleksiz kişi,
     forklift, çanta) ve ne zaman haber verileceğini (görülünce, belirli süreden uzun kalınca,
     belirli süre hiç yokken, sayı bir sınırı geçince ya da altına inince) seçin; gerekiyorsa süreyi
     ya da sayıyı yazın. Bu yol dil servisine ihtiyaç duymaz ve kural kaydedilir kaydedilmez çalışır.
   - **Engel veya değişiklik:** açıklama gerekmez (acil çıkış önü, yangın dolabı gibi boş kalması
     gereken yerler için).
5. **Kural ne zaman çalışsın?** Varsayılan "Her zaman"dır. "Yalnızca belirli saatlerde" seçerseniz
   bir saat aralığı ve günleri belirlersiniz; bitiş saati başlangıçtan önceyse aralık gece yarısını
   geçer (22:00 ile 06:00 arası). Cümlenizde saat geçiyorsa ("gece 23:00 ile 05:00 arasında…") bu
   alanı elle doldurmanız gerekmez: sistem saatleri cümleden okur ve kural listesinde gösterir.
   Formdan seçtiğiniz saatler, cümledekilerin önüne geçer.
6. Kurala bir ad verip **Kaydet**'e basın.

Kural listesinde her bölgenin altında sistemin **ne anladığı** yazar ("Kişi bölgede 20 saniyeden
uzun kalınca"), varsa çalışma saatleri de. Kural açık ama saatinin dışındaysa **Saat dışında**
rozeti görünür; o sırada denetlenmez.

### İyi açıklama yazmak

| Yazın | Yazmayın |
| :--- | :--- |
| "Baret takmayan biri bölgeye girerse haber ver." | "Güvenliğe dikkat et." |
| "Bölgede bir kişi 30 saniyeden uzun beklerse haber ver." | "Şüpheli davranışları yakala." |
| "Bölgede 5'ten fazla kişi olursa haber ver." | "Kalabalık olmasın." |
| "Bölgeye araç girerse haber ver." | "Araçları izle." |

Tek bir koşul, somut bir nesne ve gerekiyorsa bir sayı ya da süre içeren cümleler en iyi sonucu verir.

Sistemin kurallarla **yapamadıkları:** kişileri tanımak (ad, görev, yetkili / yetkisiz), plaka ve
yazı okumak, davranış tanımak (koşma, sigara içme; kavga ve düşme gibi olağandışı hareketler kural
yazmadan ayrıca izlenir), yön ve çizgi geçişi, giren-çıkan saymak, mesafe ölçmek, belirli bir
tarih ya da tatil günü ve ses. "Mesai dışında" gibi belirsiz bir zaman yazarsanız sistem makul
saatleri varsayar ve hangilerini seçtiğini söyler. Yapamadığı bir şey yazarsanız sistem ya en yakın kuralı kurup farkı söyler ya
da yapamadığını açıklar.
Desteklenen koşullar [08 — Kurallar ve analiz](08-kurallar-ve-analiz.md) bölümündedir.

### Engel / değişiklik bölgesi için referans

Bu tür bir kuralı kaydettikten sonra bölge, boş hâlini bilmediği için beklemededir. Bölge boşken
**Canlı İzleme**'de o kameranın karosundaki **Referans al** düğmesine bir kez basın. Bundan sonra
bölgeye bir şey konduğunda alarm verilir. Kamera yerinden oynar ya da ışık kalıcı olarak değişirse
referansı yeniden alın.

---

## Raporlar

Seçtiğiniz dönemde (**Bugün**, **7 gün**, **30 gün**) neler olduğunu özetler.

- **Üstteki sayılar:** toplam olay, kural ihlali, olağandışı hareket, incelenmeyi bekleyen olay ve
  **hatalı alarm oranı** ("Hatalı" işaretledikleriniz, incelediğiniz olayların yüzde kaçı).
- **Grafik:** günlere (Bugün seçiliyse saatlere) göre olay sayısı; mavi kural ihlali, turuncu
  olağandışı hareket. Bir sütunun üstüne gelince sayıları gösterir. **Tablo olarak göster** aynı
  veriyi tablo yapar.
- **Kurallara göre:** her kuralın kaç kez ihlal edildiği, ihlallerin **toplam süresi** ve kararlarınız.
- **Kameralara göre:** her kameradaki olaylar ve kararlarınız. Altında, olay özetlerinin kendi
  değerlendirmesinin sizin kararlarınızla ne kadar örtüştüğü yazar.

**Yazdır / PDF**, raporu yazıcıya gönderir; yazıcı yerine "PDF olarak kaydet" seçerseniz dosya olur.
Oranlar, olayları **Doğru** / **Hatalı** diye işaretledikçe anlam kazanır. Olay günlüğü sınırlı
sayıda olay tutar (Ayarlar → Kayıt); günlük dolduysa uzun dönemlerde eski olaylar eksik kalır ve
sayfa bunu söyler.

---

## Kameralar

| İşlem | Nasıl |
| :--- | :--- |
| Ağdaki kameraları bulmak | **Ağda kamera ara** → kullanıcı adı ve şifreyi yazın → tek tek **Ekle** ya da **Tümünü ekle**. |
| Adresle eklemek | **Elle ekle** → IP adresi, kullanıcı adı, şifre. Portlar "Bağlantı ayarları" altındadır; çoğu kamerada değiştirmek gerekmez. |
| Ad ve açıklama | Kalem simgesi. Açıklama ("Bu kamera neyi görüyor?") olay özetlerinin isabetini artırır. |
| Yeniden bağlanmak | Ok simgesi; kamerayı kayıtlı bilgilerle yeniden yoklar. |
| Teknik bilgiler | Bilgi simgesi: marka / model, adres, çözünürlük, seri numarası, yayın adresi (kopyalanabilir). |
| Silmek | Çöp kutusu. Kameraya tanımlı kurallar da silinir; kaydedilmiş olaylar kalır. |

| Durum | Anlamı ve yapılacak |
| :--- | :--- |
| Canlı | Görüntü geliyor. |
| Hazır | Kamera erişilebilir; şu an izleyen ve analiz eden olmadığı için bağlantı bırakılmış. İzlenince kendiliğinden bağlanır. |
| Bağlanıyor… | Bağlantı kuruluyor (açılışta 20 saniyeye kadar normaldir). |
| Sinyal yok | Görüntü gelmiyor. Kameranın açık ve ağda olduğunu denetleyin. |
| Şifre hatalı | "Elle ekle" ile aynı adresi doğru bilgilerle yeniden ekleyin. |

---

## Ayarlar

Bir değeri değiştirince sağ altta "Kaydedilmemiş değişiklikler var" çubuğu çıkar. **Kaydet** değişikliği
hemen uygular; sunucuyu yeniden başlatmak gerekmez. Kaydetmeden sayfadan çıkmak isterseniz sistem sorar.

### Görünüm

Üç tema vardır; seçim **yalnızca o cihazda** geçerlidir (telefon açık, kontrol odasındaki ekran koyu
olabilir) ve anında uygulanır, kaydetmek gerekmez.

| Tema | Nasıl görünür |
| :--- | :--- |
| Açık (varsayılan) | Açık zemin, lacivert menü; düğmeler mavi, vurgular açık turuncu. |
| Lacivert | Koyu lacivert zemin; düğmeler ve vurgular açık turuncu. |
| Koyu | Nötr koyu gri zemin, turuncu vurgu. |

### Algılama

| Ayar | Etkisi |
| :--- | :--- |
| Olağandışı hareketleri algıla | Kapalıyken yalnızca tanımlı kurallar çalışır ve ekran kartı boşa çıkar. |
| Uyarı seviyesi | Hareket skoru bu değeri geçince **Uyarı** olayı açılır. Düşürmek sistemi hassaslaştırır, yanlış alarmı artırır. |
| Kritik seviyesi | Skor bu değeri geçince olay **Kritik** sayılır. Her zaman uyarı seviyesinin üstündedir. |

### Canlı izleme

Açılış düzeni; alarmda çerçeve vurgusu; durum etiketi; tıklayınca büyütme; tam akıcılıkta yayın
(kapalıyken görüntü saniyede 8 kareye iner, yavaş bağlantılar içindir).

### Kayıt

| Ayar | Etkisi |
| :--- | :--- |
| Olayları video olarak kaydet | Kapalıyken olaylar yalnızca fotoğrafla kaydedilir. |
| Olay öncesi ve sonrası | Videoya olayın başından önce ve bitişinden sonra eklenen süre. |
| En uzun video | Uzun süren bir olay bu süreyi aşınca yeni bir olay olarak devam eder. |
| Kayıtlar için ayrılan alan | Alan dolunca en eski videolar silinir; olay kaydı ve fotoğrafı kalır. |

"Kullanılan alan" kutusu doluluğu gösterir. Hiçbir olaya bağlı olmayan video varsa burada sayısı ve
**Temizle** düğmesi çıkar.

### Gelişmiş

Yalnızca kurulumu yapan kişinin değiştirmesi önerilir: analiz sunucusu adresi, analiz modeli adı, aynı
anda analiz edilen kamera sayısı, olay birleştirme süresi (bu süreden kısa aralıklı alarmlar tek olay
sayılır), en fazla video sayısı. Altında sistem durumu (analiz sunucusu, analiz süreleri, ekran kartı
belleği ve sıcaklığı) ve **Varsayılan ayarlara dön** düğmesi bulunur.

Bütün ayarların sınırları ve varsayılanları: [09 — Veri ve yapılandırma](09-veri-ve-yapilandirma.md).
