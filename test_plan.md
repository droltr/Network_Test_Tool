# Test Planı

Lütfen aşağıdaki testleri uygulayın ve her birinin sonucunu `(çalıştı)` veya `(çalışmadı)` olarak işaretleyin.

## Network Status Ekranı

### Test 1.1: Otomatik Yenilemenin Başlangıç Durumu
- **Adımlar:**
  1. Uygulamayı başlatın.
  2. "Network Status" sekmesine gidin.
- **Beklenen Sonuç:** "Auto Refresh" butonunun metni "Auto Refresh: ON" olarak görünmelidir.
- **Sonuç:** 

### Test 1.2: Hatalı Bağlantı Durumu Formatı
- **Adımlar:**
  1. Ağ bağlantınızı kesin (örn. Wi-Fi'yi kapatın).
  2. "Network Status" sekmesinde "Refresh Information" butonuna basın.
- **Beklenen Sonuç:** "Connection Status" listesindeki "Internet Connection: Disconnected" gibi bir girdide, ":" öncesi ("Internet Connection") kalın, ":" sonrası ("Disconnected") ise kırmızı renkte olmalıdır.
- **Sonuç:** 

### Test 1.3: Ağ Adaptörü Yönetimi
- **Not:** Bu testi yapmak için programı yönetici olarak çalıştırmanız gerekebilir.
- **Adımlar:**
  1. "Network Status" sekmesindeki "Network Adapters" listesinden bir adaptör seçin (örn. Wi-Fi).
  2. "Disable Selected" butonuna tıklayın.
  3. İlgili ağ bağlantısının kesildiğini doğrulayın.
  4. Aynı adaptör seçiliyken "Enable Selected" butonuna tıklayın.
  5. Ağ bağlantısının tekrar kurulduğunu doğrulayın.
- **Beklenen Sonuç:** Seçilen ağ adaptörü başarıyla devre dışı bırakılmalı ve tekrar etkinleştirilmelidir.
- **Sonuç:** 

### Test 1.4: Bilgilerin Görüntülenmesi
- **Adımlar:**
  1. Uygulamayı başlatın.
  2. "Network Status" sekmesine gidin.
- **Beklenen Sonuç:** Hostname, IP Address, Gateway, DNS Server ve MAC Address bilgilerinin doğru bir şekilde görüntülendiğini doğrulayın. Connection Status listesinin dolu olduğunu doğrulayın.
- **Sonuç:** 

## Ping Testi

### Test 2.1: TTL Değerinin Görüntülenmesi
- **Adımlar:**
  1. "Ping Test" sekmesine gidin.
  2. "8.8.8.8" gibi geçerli bir adrese ping atın.
- **Beklenen Sonuç:** Sonuçlar bölümündeki her bir yanıtta "... time=Xms TTL=Y" formatında TTL değeri görünmelidir.
- **Sonuç:** 

### Test 2.2: Ping Sayısı
- **Adımlar:**
  1. "Ping Test" sekmesine gidin.
  2. "Ping Count" değerini 4 olarak ayarlayın.
  3. Ping testini başlatın.
- **Beklenen Sonuç:** Ping testinin tam olarak 4 kez yapıldığını doğrulayın.
- **Sonuç:** 

### Test 2.3: Hedef Geçmişi
- **Adımlar:**
  1. "Ping Test" sekmesine gidin.
  2. "Target Host" alanına birkaç farklı adres yazın ve ping testleri yapın.
  3. Uygulamayı kapatıp tekrar açın.
  4. "Target Host" alanına tıklayın.
- **Beklenen Sonuç:** Daha önce girilen adreslerin bir geçmiş olarak listelendiğini doğrulayın.
- **Sonuç:** 

## Port Tarayıcı

### Test 3.1: Sonuçları Dışa Aktarma
- **Adımlar:**
  1. "Port Scanner" sekmesine gidin.
  2. Bir tarama yapın (örn. localhost üzerinde).
  3. Tarama bittikten sonra aktif hale gelen "Export Log" butonuna tıklayın.
  4. Logları bir `.txt` dosyası olarak kaydedin.
- **Beklenen Sonuç:** Tarama sonuçlarını içeren metin dosyası başarıyla oluşturulmalıdır.
- **Sonuç:** 

### Test 3.2: Hedef Geçmişi
- **Adımlar:**
  1. "Port Scanner" sekmesine gidin.
  2. "Target Host" alanına birkaç farklı adres yazın ve taramalar yapın.
  3. Uygulamayı kapatıp tekrar açın.
  4. "Target Host" alanına tıklayın.
- **Beklenen Sonuç:** Daha önce girilen adreslerin bir geçmiş olarak listelendiğini doğrulayın.
- **Sonuç:** 

## Speedtest

### Test 4.1: Sonuçları Dışa Aktarma
- **Adımlar:**
  1. "Speed Test" sekmesine gidin.
  2. "Full Speed Test" yapın.
  3. Test bittikten sonra aktif hale gelen "Export Log" butonuna tıklayın.
  4. Logları bir `.txt` dosyası olarak kaydedin.
- **Beklenen Sonuç:** Hız testi sonuçlarını içeren metin dosyası başarıyla oluşturulmalıdır.
- **Sonuç:** 

### Test 4.2: Full Speed Test Fonksiyonelliği
- **Adımlar:**
  1. "Speed Test" sekmesine gidin.
  2. "Full Speed Test" butonuna tıklayın.
- **Beklenen Sonuç:** İndirme, yükleme ve ping değerlerinin doğru bir şekilde görüntülendiğini doğrulayın.
- **Sonuç:** 

### Test 4.3: Latency Test Fonksiyonelliği
- **Adımlar:**
  1. "Speed Test" sekmesine gidin.
  2. "Latency Test Only" butonuna tıklayın.
- **Beklenen Sonuç:** Ping değerinin doğru bir şekilde görüntülendiğini doğrulayın.
- **Sonuç:** 

## Arayüz Genel

### Test 5.1: Çıkış Butonu
- **Adımlar:**
  1. Pencerenin sağ alt köşesindeki "Exit" butonuna tıklayın.
- **Beklenen Sonuç:** Uygulama kapanmalıdır.
- **Sonuç:** 

### Test 5.2: Genel Durum Göstergesi
- **Adımlar:**
  1. Uygulamayı normal bir internet bağlantısıyla başlatın.
  2. Pencerenin sağ üst köşesindeki durum yazısını kontrol edin.
  3. İnternet bağlantınızı kesin ve bir süre bekleyin.
  4. Durum yazısını tekrar kontrol edin.
- **Beklenen Sonuç:** Bağlantı varken yazı yeşil renkte "OK" olmalı, bağlantı kesildiğinde ise kırmızı renkte "Problem Detected" olmalıdır.
- **Sonuç:** 

### Test 5.3: Yardım Menüsü
- **Adımlar:**
  1. Pencerenin üst kısmındaki menü çubuğundan "Help" -> "About" seçeneğine tıklayın.
  2. "Help" -> "GitHub" seçeneğine tıklayın.
- **Beklenen Sonuç:** "About" seçeneği program hakkında bilgi veren bir pencere açmalı, "GitHub" seçeneği ise web tarayıcınızda ilgili GitHub sayfasını açmalıdır.
- **Sonuç:** 

### Test 5.4: Yardım Menüsü Konumu
- **Adımlar:**
  1. Uygulamayı başlatın.
- **Beklenen Sonuç:** "Help" menüsünün pencerenin sağ tarafında konumlandığını doğrulayın.
- **Sonuç:** 

### Test 5.5: Çıkış Butonu Görüntüsü
- **Adımlar:**
  1. Uygulamayı başlatın.
- **Beklenen Sonuç:** "Exit" butonunun düzgün bir şekilde görüntülendiğini ve diğer UI elemanlarıyla çakışmadığını doğrulayın.
- **Sonuç:** 

## Otomatik Test Sekmesi

### Test 6.1: Otomatik Test ve Loglama
- **Adımlar:**
  1. "Automated Test" sekmesine gidin.
  2. "Start Troubleshooting" butonuna tıklayın.
  3. Testin tamamlanmasını bekleyin.
  4. Test bittikten sonra "Export Log" butonuna tıklayarak sonucu kaydedin.
- **Beklenen Sonuç:** Test sorunsuz bir şekilde çalışmalı, log metin alanında görünmeli ve dosyaya aktarılabilmelidir.
- **Sonuç:** 

### Test 6.2: Log Temizleme Butonu
- **Adımlar:**
  1. "Automated Test" sekmesine gidin.
  2. Bir test çalıştırın.
  3. Log metin alanının dolduğunu doğrulayın.
  4. Yeni eklenecek "Clear Log" butonuna tıklayın.
- **Beklenen Sonuç:** Log metin alanının temizlendiğini doğrulayın.
- **Sonuç:** 

### Test 6.3: Hız Testi Entegrasyonu
- **Adımlar:**
  1. "Automated Test" sekmesine gidin.
  2. "Start Troubleshooting" butonuna tıklayın.
- **Beklenen Sonuç:** Log çıktısında hız testi sonuçlarının (indirme, yükleme, ping) yer aldığını doğrulayın.
- **Sonuç:** 

### Test 6.4: Network Status Bilgileri Log Başlangıcında
- **Adımlar:**
  1. "Automated Test" sekmesine gidin.
  2. "Start Troubleshooting" butonuna tıklayın.
- **Beklenen Sonuç:** Log çıktısının başlangıcında hostname, IP adresleri, gateway, DNS sunucuları ve MAC adresleri gibi ağ durumu bilgilerinin yer aldığını doğrulayın.
- **Sonuç:** 
