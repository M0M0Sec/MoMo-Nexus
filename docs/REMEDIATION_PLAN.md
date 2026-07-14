# MoMo-Nexus — Düzeltme Planı (Remediation Plan)

> Bu belge, kod incelemesinde tespit edilen tüm bulguları çözmek için gereken adımları
> fazlara ayrılmış, uygulanabilir bir plan olarak tanımlar. Her görevde konum, efor, kabul
> kriteri (Definition of Done) ve **donanım gereksinimi** işareti bulunur.
>
> **Notasyon:**
> - Efor: `S` (≤1 gün), `M` (2-4 gün), `L` (1-2 hafta), `XL` (2+ hafta)
> - Öncelik: `P0` (bloklayıcı), `P1` (yüksek), `P2` (orta), `P3` (iyileştirme)
> - 🖥️ = gerçek donanım (LoRa/Meshtastic, modem, BLE) olmadan tam doğrulanamaz
> - Satır numaraları inceleme anındaki kod tabanına aittir; uygulamadan önce doğrulayın.

## Sürüm Planı (özet)

| Sürüm | Faz | Tema |
|-------|-----|------|
| **v1.0.1** | Faz 0 | Paketleme + test ağı (bloklayıcı) |
| **v1.1.0** | Faz 1 | API güvenlik sertleştirme |
| **v1.2.0** | Faz 2 | Kritik async/mantık hataları (donanımsız test edilebilir) |
| **v1.3.0** | Faz 3 | Kanal katmanı thread doğruluğu (kısmen donanım) |
| **v1.4.0** | Faz 4 | Eksik özellikler (mDNS, fragmentasyon, cellular RX, cloud) |
| **v1.5.0** | Faz 5-6 | Bellek/kaynak sınırları + kod kalitesi |

---

## FAZ 0 — Paketleme ve Test Ağı (v1.0.1) 🔴 P0

> **Hedef:** Kod tabanını güvenle değiştirebilmek için önce **güvenilir test + CI** kur. Bu
> faz bitmeden kanal refactor'una başlanmamalı (bozuk kodu doğrulayacak ağ yok).

| ID | Görev | Konum | Efor | Kabul Kriteri |
|----|-------|-------|------|---------------|
| 0.1 | **`python-multipart`'ı runtime bağımlılığı yap.** `api/cloud.py` ve `api/sync.py` `Form`/`UploadFile` kullanıyor → `[api]` extra'sına (veya base `dependencies`) ekle. | `pyproject.toml` | S | Temiz `pip install .[api]` sonrası `import nexus.api.cloud` çalışır; upload endpoint runtime'da çökmez. |
| 0.2 | **`httpx`'i dev bağımlılıklarına ekle.** FastAPI `TestClient` gerektiriyor; yoksa integration/e2e collection çöküyor. | `pyproject.toml` `[dev]` | S | `pip install .[dev]` sonrası tüm test dizinleri collect olur. |
| 0.3 | **Editable install / test çağrısını düzelt.** Python 3.14 + hatchling editable install flaky (`import nexus` pip işlemlerinden sonra bozuluyor). `pytest` çağrısını `PYTHONPATH=src` ile sabitle veya `pip install -e .` yerine `pip install .` + `conftest`'te `sys.path` ekleme; alternatif olarak `[tool.pytest.ini_options] pythonpath = ["src"]`. | `pyproject.toml`, `tests/conftest.py` | S | `pytest` (env değişkeni olmadan) tüm testleri toplayıp çalıştırır. |
| 0.4 | **CI ekle.** `.github/workflows/ci.yml`: kurulum + `pytest` (sert kapı) + `ruff check` (başta `continue-on-error`) + `mypy` (başta bilgilendirici). Dashboard için ayrı job: `npm ci && tsc --noEmit`. | yeni `.github/workflows/ci.yml` | M | PR'lar yeşil/kırmızı kapıdan geçer; testler zorunlu. |
| 0.5 | **Skip envanteri.** 77 skip'i kategorize et: "gerçek bug maskeleyen" vs "gerçekten donanım/Phase-3". Maskeleyenleri Faz 2-3'te düzeltilecek şekilde etiketle (`xfail(reason=...)`). | `tests/**` | S | Her skip'in nedeni belgeli; bug-maskeleyenler `xfail`. |

**Çıkış kriteri:** CI ana dalda yeşil; `pytest` env-değişkeni olmadan çalışıyor; paket temiz kuruluyor.

---

## FAZ 1 — API Güvenlik Sertleştirme (v1.1.0) 🟠 P1

> **Hedef:** C2 API yüzeyini güvenli hale getir. Hepsi `TestClient` ile birim-test edilebilir.

| ID | Görev | Konum | Efor | Kabul Kriteri |
|----|-------|-------|------|---------------|
| 1.1 | **CORS'u güvenli yap.** `allow_origins=["*"]` + `allow_credentials=True` kombinasyonunu kır: ya credentials'ı kapat, ya da origin'leri config'ten gelen açık listeye indir. Varsayılan `cors_origins`'i `["*"]`'dan güvenli bir değere çek. | `api/app.py:216-222`, `config.py:150` | S | `*` origin + credentials birlikte kullanılmıyor; test doğrular. |
| 1.2 | **WebSocket auth'u sabit-zamanlı yap.** `api_key != expected_key` → `secrets.compare_digest`. Ayrıca query-param yerine `Sec-WebSocket-Protocol` veya ilk mesajda auth (URL log sızıntısını önle). | `api/websocket.py:158` | S | WS auth `compare_digest` kullanır; yanlış key 4001 ile kapatılır; test doğrular. |
| 1.3 | **Exception handler bilgi ifşasını kapat.** Global handler ham `str(exc)`'i istemciye döndürmesin; generic mesaj + sunucu-tarafı log + korelasyon ID. | `api/app.py:225-231` | S | 500 yanıtı iç detay/traceback içermez; test doğrular. |
| 1.4 | **Docs/OpenAPI'yi koru veya kapat.** Üretimde `/docs`,`/redoc`,`/openapi.json`'ı auth arkasına al veya `docs_url=None` (config ile aç/kapa). | `api/app.py:186-204` | S | Üretim modunda auth'suz OpenAPI şeması ifşa edilmez. |
| 1.5 | **Bind varsayılanını güvenli yap.** `host="0.0.0.0"` → `127.0.0.1` (uzak erişim açık opt-in). | `config.py:138` | S | Varsayılan loopback; `0.0.0.0` explicit ayar gerektirir. |
| 1.6 | **StaticFiles mount çakışmasını gider.** `app.mount("/", StaticFiles(...))` root route'u gölgeliyor; mount'u `/dashboard`'a al veya root handler'ı SPA fallback ile birleştir. | `api/app.py:244-252` | S | Root route ve dashboard tutarlı; test 200 döner. |
| 1.7 | **Router-seviyesi auth.** Endpoint başına tekrarlanan `_: str = require_auth` yerine `APIRouter(dependencies=[require_auth])` — auth'u unutma riskini kaldır. | `api/sync.py`, `api/cloud.py`, `api/routes.py` | S | Yeni endpoint otomatik korunur; test her router'ın auth'suz 401 döndürdüğünü doğrular. |

**Çıkış kriteri:** Yeni `tests/security/` — CORS, WS auth, exception-leak, router-auth için testler yeşil.

---

## FAZ 2 — Kritik Async/Mantık Hataları (v1.2.0) 🔴 P1 — ✅ TAMAMLANDI

> **Hedef:** Donanım GEREKTİRMEYEN, saf mantık/async hatalarını düzelt ve testle kilitle.
> Bunlar test skip'leriyle maskelenmiş gerçek bug'lar.

### Faz 2 — Uygulama Notları

| Görev | Yapılanlar | Doğrulama |
|-------|-----------|-----------|
| 2.1 | (İlk sprint) `manager.py` gerçek geçiş tespiti + `_check_health_once` | 2 test |
| 2.2 | (İlk sprint) `SequenceTracker` modüler 16-bit sliding-window | 2 test |
| 2.3 | (İlk sprint) `commands.py` başarısız/exception yolu temizliği + `sweep_expired()` | 3 test |
| 2.4 | `from_json`: bilinmeyen tip **reddedilir** (None); `from_dict`'e ayrıldı, iç try/except kaldırıldı | `test_from_json_unknown_type_rejected` |
| 2.5 | `bridge.py`: 3 fire-and-forget send → `_spawn_send` (task seti + done-callback ile hata loglama) | `test_send_alert_tracks_task` |
| 2.6 | `bridge.stop()`: SHUTDOWN artık `_running=False`'tan ÖNCE **doğrudan await** ile gönderiliyor | `test_stop_sends_shutdown_notification` |
| 2.7 | `monitor.py`: `consecutive_misses` kilit altında + **her kaçırılan kontrolde** (sadece geçişte değil) artıyor | `test_missed_heartbeats_counted_every_check` |
| 2.8 | `protocol.py` `to_dict`/`from_dict` eklendi; `bridge` swarm mesajını **dict olarak gömüyor** (çift-kodlama gitti); alım hem dict hem legacy string kabul ediyor | `test_to_dict_from_dict_roundtrip`, `test_embedding_dict_avoids_double_encoding` |
| 2.9 | `lora.py`: `message.id[:8]` → **tam ID** (12 char); ACK korelasyon/çakışma düzeldi | `test_serialize_preserves_full_message_id` |

**Not:** `wifi.py:337` receive-loop task yaşam döngüsü (2.5'in kanal kısmı) Faz 3.5'e bırakıldı
(WiFi kanalı, thread/donanım bağlamı). Swarm boyut-limiti (`200` vs `237`) tutarlılığı Faz 3'te.

---

### Faz 2 — Orijinal Görev Tablosu

| ID | Görev | Konum | Efor | Kabul Kriteri |
|----|-------|-------|------|---------------|
| 2.1 | **Kanal kurtarma ölü kodunu onar.** `old_status`/`new_status` aynı property'yi okuyor → önceki durumu ayrı sakla (döngüler arası `dict`), gerçek geçişte event emit + `_try_recover_channel`. | `channels/manager.py:248-260` | M | Kanal DOWN→UP geçişinde `CHANNEL_DOWN`/`CHANNEL_UP` emit edilir; kurtarma tetiklenir; test (sahte kanal status'ü değiştirerek) doğrular. |
| 2.2 | **SequenceTracker'ı doğru yaz.** Sliding-window + `_seen` set ile out-of-order kabul, replay reddi, wrap-around (modüler mesafe) ele alma. | `swarm/protocol.py:468-503` | M | Sıra-dışı meşru mesaj kabul, tekrar reddedilir, 65535→0 sarımı doğru; birim test matrisi yeşil. |
| 2.3 | **`fleet/commands.py` `_pending` sızıntısını kapat.** Tüm çıkış yollarında (gönderim-başarısız, exception, `wait=False`) komutu `_pending`'den temizle veya TTL-tabanlı süpürme ekle. | `fleet/commands.py:169-223` | M | Başarısız/yanıtsız komut sonrası `_pending` boşalır; test sızıntı olmadığını doğrular. |
| 2.4 | **`from_json` tip güvenliği.** Bilinmeyen mesaj tipinde ham string yerine `UNKNOWN` enum'a düş veya mesajı reddet; `msg.type.value` erişimi `AttributeError` fırlatmasın. | `swarm/protocol.py:178-180`, `bridge.py:481` | S | Bozuk/bilinmeyen tipli mesaj handler'ı çökertmez; test doğrular. |
| 2.5 | **Referanssız `create_task`'ları düzelt.** `bridge.py` ve `wifi.py`'deki fire-and-forget task'ları bir sete al + `add_done_callback(discard)`; gönderim sonucunu gerçekten döndür (daima `True` değil). | `swarm/bridge.py:285+`, `channels/wifi.py:337` | M | Task'lar GC edilmez; `send_*` gerçek başarı/başarısızlık döndürür; test doğrular. |
| 2.6 | **SHUTDOWN sıralama hatası.** `stop()` içinde `_running=False`'tan ÖNCE `send_alert(SHUTDOWN)` gönder (ya da guard'ı bir bayrakla ayır). | `swarm/bridge.py:183-195` | S | Kapanışta SHUTDOWN bildirimi gerçekten gönderilir; test doğrular. |
| 2.7 | **Monitor kilit yarışı.** `consecutive_misses += 1` kilit içine alınsın; süregelen kaçırma sayısı `is_healthy`'e doğru yansısın. | `fleet/monitor.py:300-311` | S | Eşzamanlı heartbeat + timeout altında sayaç tutarlı; test doğrular. |
| 2.8 | **Çift JSON kodlamayı gider.** Swarm mesajını `NexusMessage.data` içine string olarak gömme; yapısal (dict) taşı veya tek serileştirme katmanı kullan. LoRa/swarm boyut limitlerini (`200` vs `237`) tutarlı hale getir. | `swarm/bridge.py:238-249`, `lora.py:193,226` | M | Swarm payload'ı gereksiz escape ile şişmez; boyut limitleri tutarlı; test doğrular. |
| 2.9 | **Mesaj ID kırpmasını kaldır.** `"id": message.id[:8]` → tam ID (veya dedup/ACK için yeterli entropi). | `channels/lora.py:236-249` | S | ID round-trip'te kaybolmaz; test doğrular. |

**Çıkış kriteri:** Bu bug'lar için birim testler yeşil; ilgili "skip/xfail"ler etkinleştirilir.

---

## FAZ 3 — Kanal Katmanı Thread Doğruluğu (v1.3.0) 🟠 P1 🖥️ — 🟡 KISMİ (donanımsız kısım tamam)

### Faz 3 — Uygulama Notları
- **3.4** ✅ BLE RX buffer `MAX_RX_BUFFER=64KB` ile sınırlandı; `disconnect_device` ilgili adresin buffer'ını temizliyor. `test_rx_buffer_overflow_discarded`, `test_disconnect_clears_rx_buffer`.
- **3.5** ✅ WiFi receive-loop task takip ediliyor (`_ws_receive_task`); `_disconnect` ve reconnect'te iptal ediliyor (task birikmesi bitti). `test_disconnect_cancels_receive_task`.
- **3.1/3.2/3.3** ⏸️ **DONANIM GEREKTİRİR** (LoRa RX thread köprüsü, Cellular AT katmanı+RX, kanal reconnect) — gerçek Meshtastic/modem/BLE olmadan doğrulanamaz.

---

### Faz 3 — Orijinal Görev Tablosu

## FAZ 3 — Kanal Katmanı Thread Doğruluğu (v1.3.0) 🟠 P1 🖥️

> **Hedef:** Thread↔asyncio köprü hatalarını düzelt. Köprü mantığı **birim test edilebilir**
> (sahte thread callback'i ile) ama tam uçtan-uca doğrulama **gerçek donanım** ister.

| ID | Görev | Konum | Efor | Not |
|----|-------|-------|------|-----|
| 3.1 | **LoRa RX thread köprüsü.** Meshtastic seri thread'inden gelen callback `asyncio.create_task` yerine `loop.call_soon_threadsafe(...)` veya `asyncio.run_coroutine_threadsafe(coro, loop)` kullansın (loop referansı `start`'ta saklanmalı). | `channels/lora.py:288-305` | M 🖥️ | Köprü, sahte-thread testiyle doğrulanır; tam doğrulama Meshtastic donanımı ister. |
| 3.2 | **Cellular AT katmanı.** Worker thread içindeki `asyncio.get_event_loop().time()` → `time.monotonic()`; busy-wait yerine `serial` timeout / kısa `time.sleep`; **RX yolu ekle** (modemden gelen veri okuma döngüsü → `_on_message`). | `channels/cellular.py:196-256, 566-582` | L 🖥️ | AT parse birim-test edilir; tam doğrulama modem ister. |
| 3.3 | **Kanal reconnect.** `base.py` health-check DOWN tespitinde disconnect+reconnect denesin (manager kurtarması 2.1 ile canlanınca). | `channels/base.py:333-372` | M 🖥️ | Kopan transport otomatik yeniden bağlanır; mock kanalla test + donanım doğrulaması. |
| 3.4 | **BLE RX buffer sınırı.** `_rx_buffer[address]` için maksimum boyut; `disconnect_device` ilgili adres buffer'ını temizlesin. | `channels/ble.py:265-317` | S 🖥️ | Bozuk stream belleği şişirmez; disconnect buffer'ı temizler; birim test. |
| 3.5 | **WiFi receive-loop yaşam döngüsü.** `_websocket_receive_loop` task'ı saklansın + disconnect'te iptal; health-check tekrarlı task doğurmasın. | `channels/wifi.py:337,470` | S | Tek receive-loop; disconnect temiz; test doğrular. |

**Çıkış kriteri:** Thread-köprü birim testleri yeşil; donanım-bağımlı kısımlar `docs/HARDWARE_TESTS.md`'de "saha testi bekliyor" olarak işaretli.

---

## FAZ 4 — Eksik Özellikler (v1.4.0) 🟡 P2

| ID | Görev | Konum | Efor | Not |
|----|-------|-------|------|-----|
| 4.1 | **WiFi mDNS keşfi.** `zeroconf` ile `_start_mdns` gerçek implementasyon; otomatik peer keşfi. | `channels/wifi.py:367` | M | Yazılım-only, test edilebilir. |
| 4.2 | **LoRa fragmentasyon + reassembly.** 200 byte üstü mesajları parçala; karşı tarafta yeniden birleştir; kayıp/sıra kontrolü. | `channels/lora.py:195` | L 🖥️ | Fragman mantığı test edilebilir; tam doğrulama donanım. |
| 4.3 | **Cellular RX yolu.** (3.2 ile birlikte) modemden gelen mesajları işleyen tam çift-yönlü akış. | `channels/cellular.py` | L 🖥️ | |
| 4.4 | **Cloud cracking kuyruğu.** `sync.py:349` TODO + `cloud/manager.py` gerçek entegrasyon (ya da dürüstçe "planlanan" işaretle). MoMo tarafındaki cloud stub ile hizala. | `api/sync.py:349`, `api/cloud.py`, `cloud/*` | L | Karar: tamamla ya da işaretle (bkz. MoMo `FEATURE_STATUS.md` deseni). |
| 4.5 | **LoRa ACK korelasyonu.** `_pending_messages` ölü iskeletini canlandır: `wantAck` ile gönderilen mesajlar için ACK eşleme + retry, ya da kaldır. | `channels/lora.py:82` | M 🖥️ | |
| 4.6 | **`FEATURE_STATUS.md` oluştur.** Her kanal/özellik için Gerçek/Kısmi/Stub/Donanım-bekliyor tablosu (MoMo'daki gibi) — "çalışıyor sanılan ama bozuk" durumunu bitir. | yeni `docs/FEATURE_STATUS.md` | S | Tek doğruluk kaynağı. |

---

## FAZ 5 — Bellek/Kaynak Sınırları (v1.5.0) 🟡 P2 — 🟡 KISMİ (ağ-kontrollü yapılar sınırlandı)

### Faz 5 — Uygulama Notları
- ✅ **SequenceTracker** `_seen`/`_last_seq` artık `max_sources=1000` ile LRU-sınırlı (OrderedDict); spoofed `src` bellek şişirmesi engellendi. `test_source_cap_evicts_oldest`.
- ✅ **`bridge._devices`** `max_tracked_devices=500` ile LRU-sınırlı (device_id ağdan gelir). `test_devices_tracking_is_bounded`.
- ⏭️ `fleet/monitor._health` (registry unregister'da temizleme) ve `mock.py` listeleri — daha düşük risk, sonraki iterasyon.

---

### Faz 5 — Orijinal Görev Tablosu

| ID | Görev | Konum | Efor |
|----|-------|-------|------|
| 5.1 | **Sınırsız cihaz-başı yapıları sınırla.** `fleet/monitor._health`, `swarm/bridge._devices`, `swarm/protocol._last_seq/_seen` — TTL/LRU tahliye; registry `unregister`'da monitor kaydını da sil. | `fleet/monitor.py:63`, `swarm/bridge.py:142`, `swarm/protocol.py:468` | M |
| 5.2 | **Spoof-dayanıklılığı.** `src`/device-id ile büyüyen yapılarda üst sınır + doğrulama (sahte ID ile bellek şişirme önlenir). | çeşitli | S |
| 5.3 | **Mock sınırsız listeleri.** `mock.py` `_sent/_received_messages` için maks boyut (test-only ama tutarlılık). | `channels/mock.py:47` | S |

---

## FAZ 6 — Kod Kalitesi (v1.5.0) 🟢 P3 — 6.1 ✅

### Faz 6 — Uygulama Notları
- **6.1** ✅ Ruff **temiz** (679→0): auto-fix (574) + W293-in-string unsafe-fix (48) + kaynak F841 kaldırıldı; UP042 (str-Enum idiom) global ignore, test-idiyomatik kurallar (E402/F841/B017/E722/F811/W293) test per-file-ignore. CI lint artık **sert kapı**.
- **6.2** ⏭️ mypy strict (185 hata) — kademeli, sonraki iterasyon.
- **6.3** ⏭️ `get_best_channel` skor cache — küçük.

---

### Faz 6 — Orijinal Görev Tablosu

| ID | Görev | Konum | Efor |
|----|-------|-------|------|
| 6.1 | **Ruff temizle.** `ruff check --fix` (599 W293 boşluk + I001 import sıralama otomatik); kalan gerçekleri (F841, E402, UP042) elle. CI lint'i sert kapıya çevir. | proje geneli | M |
| 6.2 | **mypy strict'i kademeli uygula.** `strict=true` beyan edilmiş ama 185 hata var. `security/`, `core/`, `domain/` gibi temiz modüllerden başlayarak modül-modül strict'e geç; CI'da type kapısı. | proje geneli | L |
| 6.3 | **`get_best_channel` verimliliği.** Her karşılaştırmada `to_model().score()` yeniden üretiliyor; skoru bir kez hesapla. | `channels/manager.py:389` | S |

---

## Bağımlılık Grafiği

```
Faz 0 (paketleme+CI+test) ─► Faz 1 (API güvenlik) ─► Faz 2 (mantık bug'ları) ─► Faz 5-6
                          └─► Faz 2 ────────────────► Faz 3 (thread) ─► Faz 4 (özellikler 🖥️)
```
- **Faz 0 mutlak önce** — test/CI olmadan kanal refactor'u körlemesine olur.
- **Faz 2, Faz 3'ten önce** — kanal kurtarma (2.1) canlanmadan reconnect (3.3) anlamsız.
- **🖥️ işaretli işler saha testine bağlı** — kod hazır olsa da RPi/LoRa/modem/BLE ister.

## Önerilen İlk Sprint (2 hafta) — ✅ TAMAMLANDI

1. ✅ `0.1`+`0.2`+`0.3` — Paketleme + test çağrısı (yarım gün, her şeyi açar).
2. ✅ `0.4` — CI (test sert kapı).
3. ✅ `2.1` — Kanal kurtarma ölü kodu (en yüksek etkili tek bug).
4. ✅ `2.2` — SequenceTracker (mesaj kaybı).
5. ✅ `1.1`+`1.2`+`1.3` — CORS + WS constant-time + exception-leak (hızlı güvenlik kazanımları).
6. ✅ `2.3` — Komut `_pending` sızıntısı.

### İlk Sprint — Uygulama Notları

| Görev | Yapılanlar | Doğrulama |
|-------|-----------|-----------|
| 0.1-0.3 | `python-multipart`→`[api]`, `httpx`→`[dev]`, `[tool.pytest] pythonpath=["src"]` | `pytest` env-değişkeni olmadan 438 test toplar |
| 0.4 | `.github/workflows/ci.yml` (backend: test sert kapı + lint/type bilgilendirici; dashboard: `tsc --noEmit` sert kapı) | YAML geçerli |
| 2.1 | `manager.py`: `_last_status` dict ile gerçek geçiş tespiti; `_check_health_once` metoduna ayrıldı (test edilebilir); recovery task referansla tutuluyor | `test_health_monitor_detects_transition`, `test_down_transition_schedules_recovery` |
| 2.2 | `protocol.py` `SequenceTracker.is_valid`: modüler 16-bit mesafeyle gerçek sliding-window (sıra-dışı kabul, replay/too-old reddi, wrap-around) | `test_out_of_order_within_window_accepted` + güncellenmiş replay/wrap testleri |
| 1.1 | `app.py` CORS: `*` origin ile `allow_credentials` birlikte kullanılmıyor | `test_wildcard_origin_does_not_allow_credentials` |
| 1.2 | `websocket.py`: auth `secrets.compare_digest` (sabit-zaman) | `test_ws_rejects_missing_and_wrong_key`, `test_ws_accepts_correct_key` |
| 1.3 | `app.py`: exception handler ham `str(exc)` sızdırmıyor | `test_500_does_not_leak_internal_detail` |
| 2.3 | `commands.py`: başarısız-gönderim + exception yollarında `_complete_command`; `sweep_expired()` (wait=False TTL) | `TestCommandDispatcherLeaks` (3 test) |

**Test durumu (sprint sonu):** `372 passed, 77 skipped, 0 failed` (+11 yeni test).
Dokunulan kaynak dosyalarında yeni ruff/mantık hatası yok.

> Bu sıra: önce güvenlik ağını kurar, sonra en yüksek etkili donanımsız-test-edilebilir
> bug'ları kapatır — kanal donanım işleri (Faz 3-4) sağlam bir zemin üzerine oturur.

---

### Kapsam Notu
`cloud/`, `geo/`, `plugins/` katmanları bu turda **derinlemesine incelenemedi** (otomatik
inceleme güvenlik filtresine takıldı). Faz 4.4 öncesi bu katmanlar için ayrı bir inceleme
turu (SQL/async/stub) yapılmalı. Güvenlik çekirdeği (`security/*`, `api/auth`), veritabanı
(`infrastructure/database.py`) ve replay koruması incelendi ve **sağlam** bulundu.
