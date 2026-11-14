# YouTube Niş Radarı

Son 45 günde açılmış, en az 3 videosu 10.000+ izlenme almış **yeni YouTube kanallarını** bulur.
Başlık, etiket ve açıklamalardan anahtar kelimeleri çıkarır. Bu kelimeleri **Almanca ve
İspanyolca'ya çevirip YouTube'da aratır** ve "bu niş o dilde hâlâ açık mı?" sorusunu cevaplayan
bir HTML rapor üretir.

Sadece resmi ve **ücretsiz YouTube Data API v3** kullanılır. Ek program ya da paket gerekmez.

---

## 1. Kurulum (bir kez)

### a) Python
- **Windows:** https://www.python.org/downloads/ adresinden indir. Kurarken
  **"Add python.exe to PATH"** kutusunu işaretle.
- **Mac:** Terminal'i aç ve `python3 --version` yaz. Sürüm 3.9 veya üstüyse hazırsın. Değilse
  aynı siteden indir.

### b) Programı indir
GitHub'da bu deponun sayfasında **Code → Download ZIP** ile indir, zip'i aç ve
`youtube-radar` klasörünü istediğin yere koy (örn. Masaüstü).

### c) Ücretsiz YouTube API anahtarı
1. https://console.cloud.google.com adresine Google hesabınla gir. Üstten **yeni proje** oluştur.
2. Soldaki menüden **APIs & Services → Library**'ye gir, "**YouTube Data API v3**" ara ve **Enable**'a bas.
3. **APIs & Services → Credentials → Create credentials → API key** ile anahtarı oluştur ve kopyala.
4. (Önerilir) Anahtarın ayarlarında **API restrictions → YouTube Data API v3** seç.

### d) Anahtarı programa ver
`youtube-radar` klasöründeki **`.env.example`** dosyasının bir kopyasını oluşturup adını **`.env`**
yap. Not Defteri ile aç ve anahtarını yaz:

```
YT_API_KEY=AIza...senin_anahtarin
```

Bu dosya sadece senin bilgisayarında kalır, kimseyle paylaşma.

---

## 2. Çalıştırma

**En kolayı:**
- Windows'ta **`calistir.bat`** dosyasına çift tıkla.
- Mac'te **`calistir.command`** dosyasına çift tıkla. İlk seferde sağ tık → Aç demen gerekebilir.

Rapor bitince tarayıcıda kendiliğinden açılır ve `rapor/` klasörüne kaydedilir.

**Komut satırından (daha fazla seçenek):**

```bash
python radar.py                                  # genel tarama
python radar.py --konu "shark,ocean mystery"     # belirli bir nişte tara
python radar.py --kanal @TheDeepRecord-q5t       # tek bir kanalı analiz et
python radar.py --gun 30 --min-izlenme 20000     # daha sıkı filtre
python radar.py --diller de,es,fr                # Fransızca da ekle
python radar.py --kaynak-dil de --diller en,es   # Almanca kanalları tara
python radar.py --help                           # tüm seçenekler
```

Mac'te `python` yerine `python3` yaz.

---

## 3. Günlük kota

Ücretsiz kotan **günde 10.000 birimdir** ve Türkiye saatiyle 10:00–11:00 arasında sıfırlanır (ABD Pasifik gece yarısı).

| İşlem | Maliyet |
|---|---|
| 1 YouTube araması | 100 birim |
| 50 kanal / 50 video bilgisi | 1 birim |

Varsayılan bir tarama yaklaşık **4.000–6.000 birim** harcar, yani günde 1–2 tam tarama
yapabilirsin. Program `--kota` sınırını (varsayılan 9.000) aşmaz. Sonuçları 20 saat önbellekte
tutar, aynı aramayı tekrarlamak kota harcamaz.

Kotayı korumak için:
- `--konu` ile niş vermek, genel taramadan daha verimlidir.
- `--no-talep`: "tüm zamanların talebi" aramasını atlar, kotayı yarıya indirir.
- `--kelime 2`: kanal başına daha az ifade aratır.

---

## 4. Çeviri

Program anahtar kelimeleri şu sırayla çevirmeye çalışır:

1. **`ceviriler.json`**: Senin yazdığın çeviriler. Program çeviremediği ifadeleri bu dosyaya
   boş olarak ekler. Doldurup tekrar çalıştırırsan önbellek sayesinde kota harcamaz.
2. **DeepL Free** (ayda 500.000 karakter ücretsiz): https://www.deepl.com/pro-api adresinden ücretsiz
   anahtar al ve `.env` dosyasına `DEEPL_API_KEY=...:fx` satırını ekle. **Önerilen yol bu.**
3. **Google Cloud Translation**: Aynı Google projesinde "Cloud Translation API"yi açıp `.env`'e
   `GOOGLE_TRANSLATE=1` eklersen kullanılır. Faturalandırma hesabı ister.

---

## 5. Raporu okumak

| Sonuç | Anlamı |
|---|---|
| **BÜYÜK AÇIK** | Talep var, o dilde son 30 günde 10K+ izlenme alan **yerli** kanal yok |
| **AÇIK** | 1–2 yerli kanal tutuyor, hâlâ yer var |
| **GİRİLMİŞ / DARALIYOR** | 3–5 yerli kanal aynı işi yapıyor |
| **KALABALIK** | 6+ kanal |
| **TALEP ZAYIF** | O dilde bu konuyu kimse izlemiyor |

**"Çeviri/dublaj rakip"**: Videonun sesi başka dilde, ama YouTube başlığı çevirip o dilin
kullanıcısına gösteriyor. Bunlar gerçek rakip ama yerli seslendirmeyle geçilebilir.

**Sınırlamalar:**
- Gelir/RPM tahmini yapmaz. NexLev gibi araçların asıl ücretli kısmı bu.
- Keşif, YouTube aramasına dayanır. Hiç arama sonucuna çıkmayan kanalları göremez. Bu yüzden
  `--konu` ile farklı nişler denemek sonuçları zenginleştirir.
- Anahtar kelime çıkarma İngilizce başlıklar için en iyi çalışır.
