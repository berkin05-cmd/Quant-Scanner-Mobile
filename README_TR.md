# QUANT SCANNER MOBILE v1 — FULL SYSTEM

Bu paket Android uygulaması + analiz sunucusunu birlikte içerir.

## İçerik
- Android Kivy uygulaması
- FastAPI analiz sunucusu
- Mevcut v6.4 analiz motoru
- Capital Protection
- Çakılma Riski
- Dip Hunter
- 2/3/5 günlük geçmiş sinyal doğrulama ve MAE
- Teknik + temel + makro + jeopolitik analiz
- Sosyal/haber duyarlılığı
- 714 benzersiz sembollük yüklenen liste

## Windows'ta kullanma
1. `backend` klasörüne girin.
2. `BASLAT_WINDOWS.bat` dosyasına çift tıklayın.
3. Bilgisayar ve telefon aynı Wi-Fi'da olsun.
4. Windows'ta `ipconfig` yazarak bilgisayarın IPv4 adresini bulun.
5. Android uygulamasında sunucu alanına örneğin `http://192.168.1.25:8000` yazın.
6. `Bağlan`, sonra `PİYASAYI TARA`.

## APK oluşturma
Bu çalışma ortamında Android SDK/Buildozer olmadığı için derlenmiş APK bu ZIP'in içinde değildir.
Kaynak proje hazırdır.

İki derleme yolu:
- Linux/WSL: `android/APK_OLUSTUR_LINUX.sh`
- GitHub: `.github/workflows/build-apk.yml` hazırdır. Projeyi GitHub'a koyup Actions > Build Android APK > Run workflow ile APK artifact alınır.

## Neden sunuculu?
714 sembol + yfinance + pandas + temel analiz + sosyal haber taraması + backtest telefon APK'sına gömülürse
uygulama çok ağır, yavaş ve kırılgan olur. Bu mimaride Android yalnızca arayüzdür; ağır analiz bilgisayarda/sunucuda çalışır.

## Güvenlik/yorum
Bu sistem gerçek dibi veya gelecekteki fiyatı garanti etmez.
Geçmiş başarı gelecekteki sonucu garanti etmez.
Kısa vadeli işlemlerde kayıp riski vardır.
Yatırım tavsiyesi değildir.
