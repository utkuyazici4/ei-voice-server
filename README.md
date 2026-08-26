# Ses Eşleştirme Sunucusu

Twilio ile ElevenLabs arasındaki boşluğu dolduran servis. Railway'e deploy
edilir.

## Ne yapıyor

İki kapısı var.

**Kapı 1 — `WS /twilio-stream`**
Twilio, arayanın ses kanalını buraya gönderir. Servis sesi biriktirir,
4 saniye dolduğunda cinsiyet ve yaş bandını tespit eder, sonucu çağrı
numarasıyla hafızada tutar.

**Kapı 2 — `POST /assignment`**
ElevenLabs "bu çağrı için hangi ses" diye sorar. Servis hafızasına bakar,
havuz tablosundan hücreyi okur ve şunu döndürür:

```json
{"matched_voice_key": "en_03", "match_language": "en", "consultant_name": "Daniel"}
```

Bilmiyorsa hata vermez, `fallback` döner. Görüşme kurumsal sesle sürer.

## Dosyalar

| Dosya | İçeriği |
|---|---|
| `main.py` | İki kapı, hafıza yönetimi |
| `classifier.py` | Cinsiyet ve yaş tespiti |
| `pool.py` | Ses havuzu tablosu, 20 hücre |
| `similar.py` | Opsiyonel similar-voices katmanı |

## Railway'e kurulum

1. Bu klasörü bir GitHub reposuna at.
2. Railway'de New Project, Deploy from GitHub, repoyu seç.
3. Deploy biter bitmez Settings, Networking bölümünden Generate Domain.
4. `https://<alan-adin>/health` adresini aç. `{"ok": true, ...}` görmelisin.

Değişkenler Railway'de Variables sekmesinden girilir, `.env.example`
dosyasındakiler. Hiçbirini girmesen de varsayılanlarla çalışır.

## ElevenLabs tarafını bağlama

Tools bölümündeki `get_consultant_assignment` tool'unun URL'ini değiştir:

```
https://<alan-adin>/assignment
```

Body parameters'ta `call_sid` alanı olmalı. Şimdilik
`system__conversation_id` bağlıysa çalışır ama gerçek eşleşme için Twilio'nun
`callSid` değerini göndermen gerekir, o da TwiML aşamasında ayarlanır.

Assignments bölümünde üç eşleme dursun: `matched_voice_key`,
`match_language`, `consultant_name`.

## Twilio tarafını bağlama

Giden çağrının TwiML'inde iki blok olacak:

```xml
<Response>
  <Start>
    <Stream url="wss://<alan-adin>/twilio-stream" track="inbound_track">
      <Parameter name="language" value="en" />
    </Stream>
  </Start>
  <Connect>
    <Stream url="wss://api.elevenlabs.io/..." />
  </Connect>
</Response>
```

`track="inbound_track"` önemli. Yalnızca arayanın sesini verir, asistanın
kendi sesi örneğe karışmaz.

## Havuz tablosu

`pool.py` içinde 20 hücre var: 5 dil × 2 cinsiyet × 2 yaş bandı. Her hücrede
bir ses anahtarı ve bir danışman ismi.

Anahtarlar (`en_01`, `ar_02`, ...) ElevenLabs Voice sekmesindeki
etiketlerle **birebir aynı** olmalı, büyük küçük harf dahil. Uyuşmazsa
metin varsayılan sesle okunur ve sessizce yanlış çalışır.

İsimler de oradan geliyor. Ses ve isim her zaman birlikte döndüğü için
tutarsızlık olmaz.

## similar-voices katmanı

Varsayılan olarak kapalı. Açmak için `USE_SIMILAR_VOICES=true` ve
`ELEVENLABS_API_KEY` gerekiyor. Ayrıca `pool.py` içindeki
`library_voice_id` alanlarının dolu olması lazım.

Açıkken hücreyi değiştirmez, yalnızca hücre içindeki adaylar arasında
sıralama yapar. Hücre seçimi her zaman sınıflandırıcının işi.

Bir uyarı: bu endpoint'in çalıştığı ayırt edici detay 4 kHz üstünde ve
telefon hattı o bandı taşımıyor. Sonuçlar gürültü olabilir. Loglarda
`source` alanı `classifier` mi `classifier+similar` mi olduğunu gösteriyor,
gerçek çağrılarda ikisini karşılaştırıp karar ver.

## Sınıflandırıcı

Varsayılan yöntem sinyal işleme: temel frekanstan cinsiyet, spektral eğim ve
titreşimden yaş bandı. Model indirmiyor, milisaniyeler sürüyor.

Cinsiyet güvenilir, çünkü temel frekans telefon bandında bozulmadan geçiyor.
Yaş bandı daha kaba, iki kategoriden ibaret ve zayıf halka bu.

`MIN_CONFIDENCE` altında kalan çağrılar tahmin edilmez, fallback'e gider.
Yanlış cinsiyette ses atamak, nötr ses kullanmaktan kötüdür.

Daha iyi yaş tespiti gerekirse `classifier.py` içindeki `speechbrain`
fonksiyonu doldurulup `CLASSIFIER_BACKEND=speechbrain` yapılır.

## Test uçları

`GET /health` — servis ayakta mı, kaç çağrı hafızada

`GET /debug/<call_sid>` — bir çağrı için ne tespit edildi, hangi f0, hangi
güven skoru. Ayar yaparken en çok bunu kullanacaksın.

`POST /mock/<voice_key>` — sabit cevap döndürür. Örneğin
`/mock/ar_02` her zaman Arapça node'una yönlendirir. Twilio bağlanmadan
önce beş dilin yönlendirmesini tek tek doğrulamak için.

## Bilinmeyenler

Yaş bandı tespitinin gerçek telefon sesinde ne kadar isabetli olduğu
ölçülmedi. İlk gerçek çağrılarda `/debug` çıktılarını kaydedip elle
karşılaştırmak lazım.

Fallback oranının ne olacağı da bilinmiyor. Yüksek çıkarsa
`MIN_CONFIDENCE` düşürülür veya `MIN_SPEECH_MS` artırılır, ama ikisi de
takas: daha fazla eşleşme, daha fazla yanlış eşleşme.
