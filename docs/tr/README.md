# 3S Belgeleri

Bu dizin sistemi, işletilmesinden kodunun değiştirilmesine kadar anlatır. Bölümler kodun bugünkü
hâlini yansıtır; bir davranışı değiştirdiğinizde onu anlatan bölümü aynı commit'te güncelleyin —
koddan kopan belge, hiç olmamasından kötüdür.

Belgeler aynı içerikle iki dildedir: Türkçesi burada, İngilizcesi bir üst dizinde
([English documentation](../README.md)). Birindeki değişiklik ötekine de yapılmalıdır.

| Bölüm | İçerik | Kimin için |
| :--- | :--- | :--- |
| [01 — Genel bakış](01-genel-bakis.md) | Sistem ne yapar, bileşenleri, terimler | Herkes |
| [02 — Kurulum ve çalıştırma](02-kurulum.md) | Gereksinimler, ilk kurulum, başlatma ve durdurma, portlar | Kuran kişi |
| [03 — Kullanım kılavuzu](03-kullanim-kilavuzu.md) | Arayüzün her sayfası adım adım; tema ve dil | Operatörler |
| [04 — Mimari](04-mimari.md) | Süreçler, iş parçacıkları, veri akışı, tasarım kararları | Geliştiriciler |
| [05 — Sunucu modülleri](05-backend.md) | `WebInterface/backend` altındaki her modülün görevi ve arayüzü | Geliştiriciler |
| [06 — API başvurusu](06-api.md) | Bütün HTTP / WebSocket / SSE uç noktaları, örnek istek ve yanıtlarla | Geliştiriciler, entegratörler |
| [07 — Arayüz kodu](07-frontend.md) | `WebInterface/frontend` yapısı, kurallar, arayüz dili, renk rolleri ve temalar, sayfa eklemek | Geliştiriciler |
| [08 — Kurallar ve analiz](08-kurallar-ve-analiz.md) | Kural derleme, yetenekler ve sınırlar, çalışma saatleri, takip, koşul türleri, olay yaşam döngüsü, özetler | Geliştiriciler |
| [09 — Veri ve yapılandırma](09-veri-ve-yapilandirma.md) | Diskteki dosyalar, kayıt biçimleri, bütün ayarlar, ortam değişkenleri | Geliştiriciler, kurulumcular |
| [10 — Geliştirme ve test](10-gelistirme-ve-test.md) | Çalışma düzeni, sistem testi, doğruluk ölçümü ve ilk sonuçları, sık değişiklikler için tarifler | Geliştiriciler |
| [11 — Sorun giderme](11-sorun-giderme.md) | Belirtiye göre neden ve çözüm, bilinen sınırlar | Herkes |

Nereden başlamalı:

- **Sistemi işletmek:** 03, bir şey ters görünürse 11.
- **Kurmak:** 02 ve 09.
- **Geliştirmeyi devralmak:** önce 01, 04 ve 10; başvuru için 05–08.
