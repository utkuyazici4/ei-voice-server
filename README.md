# Ses Eşleştirme Sunucusu

Twilio ile ElevenLabs arasındaki eşleştirme katmanı. Railway'de çalışır.

Sınıflandırma yok. Eşleştirmenin tamamı ElevenLabs `/v1/similar-voices`
üzerinden yapılıyor.

## Nasıl çalışıyor

```
Twilio arayanın sesini  WS /twilio-stream  adresine gönderir
  → 5 saniye ses birikince /v1/similar-voices çağrılır
  → dönen kütüphane sesleri havuzumuzla kesiştirilir
  → transkriptten gelen dile göre filtrelenir
  → en üst sıradaki seçilir
  → 12 saniyede daha uzun örnekle bir kez daha denenir

ElevenLabs  POST /assignment  ile sorar
  → {"matched_voice_key": "en_f_02", "match_language": "en",
     "consultant_name": "Claire"}
  → bilinmiyorsa fallback döner, çağrı kurumsal sesle sürer
```

Dil bilgisi similar-voices'tan gelmiyor, ElevenLabs'in transkripsiyonundan
geliyor ve tool çağrısında `language` alanıyla gönderiliyor.

## Havuz

`pool.py` içinde 20 slot var: İngilizce ve Türkçe, kadın ve erkek, beşer ses.

Her ses için **iki kimlik** gerekiyor ve bunlar aynı şey değil:

| Alan | Ne | Nereden |
|---|---|---|
| `library_voice_id` | similar-voices'ın döndürdüğü kimlik | Voice Library |
| `workspace_voice_id` | agent'ın konuşabildiği kimlik | Sese workspace'e eklenince oluşur |

`library_voice_id` boşsa o ses hiç eşleşemez.
`workspace_voice_id` boşsa eşleşme konuşulamaz.

`label` alanı (`en_f_01` gibi), Voice sekmesindeki multi-voice etiketiyle
birebir aynı olmalı, büyük küçük harf dahil.

## Havuzu doldurma

1. Voice Library'den 20 ses seç, workspace'ine ekle.
2. Sunucuda `GET /pool/suggest` çağır. Workspace'indeki sesleri listeler,
   `sharing_original_voice_id` alanı genelde aradığın kütüphane kimliğidir.
3. İki kimliği `pool.py` içindeki slotlara yapıştır.
4. `GET /pool/status` ile kaç slotun hazır olduğunu gör.

## Ortam değişkenleri

```
ELEVENLABS_API_KEY=...     zorunlu
SIMILAR_TOP_K=40           kaç aday istensin
SIMILAR_TIMEOUT=8
MIN_SPEECH_MS=5000         ilk deneme için gereken ses
RETRY_SPEECH_MS=12000      daha uzun örnekle ikinci deneme
RESULT_TTL_SECS=1800
LOG_LEVEL=INFO
```

## Twilio bağlantısı

```xml
<Response>
  <Start>
    <Stream url="wss://<alan-adin>/twilio-stream" track="inbound_track">
      <Parameter name="match_id" value="<kendi urettigin kimlik>" />
      <Parameter name="language" value="en" />
    </Stream>
  </Start>
  <Connect>
    <Stream url="wss://api.elevenlabs.io/..." />
  </Connect>
</Response>
```

`track="inbound_track"` şart. Yalnızca arayanın sesini verir, asistanın kendi
sesi örneğe karışmaz.

`match_id` önemli: ElevenLabs kendi konuşma kimliğini gönderiyor, Twilio kendi
`callSid` değerini biliyor, ikisi farklı. Aynı değeri hem buraya hem tool
çağrısına verirsen sunucu doğru kaydı bulur.

## Test uçları

`GET /health` — ayakta mı, kaç çağrı hafızada, havuz durumu

`GET /debug/<call_sid>` — o çağrı için ne bulundu, kaç aday döndü, sıralama
ne oldu, örnek kaç milisaniyeydi. En çok kullanacağın uç bu.

`POST /mock/<label>` — sabit cevap. `/mock/tr_f_02` her zaman Türkçe kadın
sesine yönlendirir. Twilio olmadan workflow testi için.

## Doğrulanmamış olan

similar-voices'ın 8 kHz telefon sesinde anlamlı çalışıp çalışmadığı
bilinmiyor. Bir sesi diğerinden ayıran detayın çoğu 4 kHz üstünde ve telefon
hattı o bandı taşımıyor.

Her çağrıda dönen sıralamanın tamamı `/debug` altında saklanıyor. İlk 20-30
çağrıda şuna bak: aynı kişinin farklı çağrılarında aynı sesler mi dönüyor.
Tutarsızsa eşleştirme gürültüdür ve sisteme güvenilmez.

Bu kontrol yapılmadan canlıya çıkma.
