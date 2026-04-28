> 🇬🇧 [English README](./README.md) | 🇹🇷 Türkçe (bu dosya)

<p align="center">
  <img src="assets/system-flow.svg" alt="Ritual dApp Skills — Sistem Mimarisi" width="800">
</p>

<h1 align="center">ritual-dapp-skills</h1>

<p align="center">
  <strong>AI kodlama asistanlarına Ritual üzerinde dApp inşa etmeyi öğreten skill'ler ve AI ajanları.</strong>
</p>

<p align="center">
  <a href="https://skills.ritualfoundation.org"><img src="https://img.shields.io/badge/docs-microsite-f97316?style=flat-square" alt="Docs"></a>
  <a href="https://github.com/ritual-foundation/ritual-dapp-skills"><img src="https://img.shields.io/badge/license-Clear%20BSD-blue?style=flat-square" alt="License: Clear BSD"></a>
  <img src="https://img.shields.io/badge/chain-1979-09090b?style=flat-square&labelColor=f97316" alt="Chain ID 1979">
  <img src="https://img.shields.io/badge/skills-32-22c55e?style=flat-square" alt="32 Skills">
  <img src="https://img.shields.io/badge/agents-2-c084fc?style=flat-square" alt="2 Agents">
  <img src="https://img.shields.io/badge/meta--protocols-9-ea580c?style=flat-square" alt="9 Meta-Protocols">
  <img src="https://img.shields.io/badge/precompiles-16-22d3ee?style=flat-square" alt="16 Precompiles">
</p>

---

## Hızlı Başlangıç

```bash
# Claude Code
git clone https://github.com/ritual-foundation/ritual-dapp-skills.git .claude/skills/ritual-dapp-skills

# Ardından ajanınıza şunu söyleyin:
Read the file skills/ritual/SKILL.md and follow its instructions.

WALLET: 0xYOUR_FUNDED_WALLET_ADDRESS_DAPP_CAN_BE_DEPLOYED_FROM

Build me a chatbot that runs on-chain with streaming responses.
```

Cursor, OpenClaw, Hermes ve diğer harness'lar için [mikrositeye](https://skills.ritualfoundation.org) bakın.

---

## Nasıl Çalışır

Sistemin iki giriş noktası, üç skill sınıfı ve arka planda middleware olarak çalışan 10 davranış protokolü vardır.

**Ne istediğinizi tarif edersiniz.** Ajan davranış protokollerini devreye alır, doğru skill'leri yükler, aşama aşama inşa eder, her aşamayı doğrular ve hataları otomatik olarak düzeltir.

### Giriş Noktaları

| Giriş                                   | Kim   | Ne Yapar                                                                                                                                                |
| --------------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `skills/ritual/SKILL.md`                | İnsan | Amacı sınıflandırır (inşa et / hata ayıkla / öğren), fikir yoksa ilham üretir, fikri precompile'larla eşleştirir, uygun ajana yönlendirir               |
| `skills/ritual-meta-bootstrap/SKILL.md` | Ajan  | Tüm oturum boyunca görünmez middleware olarak 10 davranış kuralını etkinleştirir                                                                        |

### Üç Skill Sınıfı

![Üç Skill Sınıfı](assets/skill-classes.svg)

**Ω Meta** — Koşulsuz olarak yüklenir. 10 davranış kuralı, ilham (canlı trendlerden JIT fikir üretimi), projeksiyon (fikri Ritual-native spec'e dönüştürme), doğrulama (skill başına kontroller + 12 adımlı uçtan uca yolculuk).

**α Build** — Kullanıcının hedefine göre koşullu olarak yüklenen özellik skill'leri. Builder ajan proje başına 3-6 tane seçer. Aşamalı çalışır: mimari → smart contract'lar → frontend → backend → test → deploy.

**β Debug** — Reaktif olarak yüklenen tanı skill'leri. Sıralı pipeline: önceliklendirme → smoke testleri → 10 bilinen kök nedenle hızlı eşleştirme → sistematik tanı → düzeltme + doğrulama.

### 10 Davranış Kuralı

| #   | Kural                        | Amaç                                                             |
| --- | ---------------------------- | ---------------------------------------------------------------- |
| 1   | Maliyeti Takip Et            | Token bütçesi tüm eşikleri yönetir                               |
| 2   | Önceki Bilgiye Güvenme       | Ritual, Ethereum varsayımlarını ihlal eder. Infernet yok.        |
| 3   | Tembel Bilgi Toplama         | 0-5 JIT soru, asla statik form                                   |
| 4   | Build+Debug'ı İç İçe Geçir  | Her geri alınamaz işlemden sonra doğrula                         |
| 5   | Devre Kesici                 | Yol sapmasını tespit et, bütçeyi harcamadan dur                  |
| 6   | Sormadan Önce Ara            | Önce 5 adımlı çözüm hiyerarşisini tüket                          |
| 7   | Çatallanmada Sor             | Yalnızca pahalı ve tercih gerektiren çatallanmalarda             |
| 8   | Şablon Karşıtı               | UI çıktıları için boyutsal ayrıştırma                            |
| 9   | Etkileşimsiz Doğrula         | Skill başına kontroller + 12 adımlı uçtan uca yolculuk           |
| 10  | Proje Diziniyle Sınırla      | Tüm yazma işlemleri proje kökünde, çapraz kirlilik yok           |

---

## AI Ajanları

| Ajan                     | Amaç                                                                                                                                          | Etkinleştirme                                                   |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| **ritual-dapp-builder**  | Uçtan uca dApp geliştirme: projeksiyon → mimari → smart contract'lar → frontend → backend → test → deploy → build sonrası doğrulama            | Kullanıcı ne inşa etmek istediğini tarif eder                   |
| **ritual-dapp-debugger** | Ritual'a özgü sorunları tanılar ve düzeltir: takılı işlemler, eksik callback'ler, boş makbuzlar, encoding uyuşmazlıkları                      | Kullanıcı bir sorun bildirir ya da builder build sonrası hata tespit eder |

---

## Skill'ler

### Meta Protokoller (Ω)

| Skill                              | Amaç                                                                      |
| ---------------------------------- | ------------------------------------------------------------------------- |
| `ritual-meta-bootstrap`            | Arka planda middleware olarak 10 davranış kuralı                          |
| `ritual-meta-inspiration`          | Canlı blockchain ve AI trendlerinden JIT fikir üretimi                    |
| `ritual-meta-projection`           | Ham fikirleri precompile eşlemeleriyle Ritual-native spec'e dönüştürür    |
| `ritual-meta-elicitation`          | Tembel hedef-durum varyans azaltma (0-5 bağlamsal soru)                   |
| `ritual-meta-orchestrator`         | 4 prensiple build-debug iç içe geçirme                                    |
| `ritual-meta-circuit-breaker`      | Yol sapması tespiti                                                        |
| `ritual-meta-human-in-loop`        | Oturum ortası çatallanma bilgi toplama                                     |
| `ritual-meta-non-interactive-bias` | Sormadan önce ara                                                          |
| `ritual-meta-verification`         | Skill başına kontroller, skill'ler arası entegrasyon, 12 adımlı uçtan uca yolculuk |

### Mimari ve Referans (Ω)

| Skill                     | Ne Öğretir                                                                                                                                                |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ritual-dapp-overview`    | Chain mimarisi, TEE-EOVMT, deterministik olmayan hesaplama, 3 çalışma modeli, 9 durumlu asenkron yaşam döngüsü, sıralama hakları, sistem smart contract'ları |
| `ritual-dapp-precompiles` | Alan sayıları, Solidity + viem encoding örnekleriyle tüm 16 precompile ABI'ı                                                                              |
| `ritual-dapp-deploy`      | Chain yapılandırması (ID 1979, testnet), Foundry/Hardhat kurulumu, deploy script'leri, faucet                                                             |
| `ritual-dapp-design`      | Koyu mod terminal estetiği, tipografi, renk anlambilimi, WCAG 2.1 AA                                                                                     |

### Precompile Özellikleri (α)

| Skill                     | Precompile                                                                       | Çalışma Modeli                      |
| ------------------------- | -------------------------------------------------------------------------------- | ----------------------------------- |
| `ritual-dapp-http`        | HTTP (0x0801)                                                                    | Kısa süreli asenkron                |
| `ritual-dapp-llm`         | LLM (0x0802) + SSE streaming                                                     | Kısa süreli asenkron                |
| `ritual-dapp-agents`      | Persistent Agent (0x0820), Sovereign Agent (0x080C)                              | Uzun süreli asenkron (callback)     |
| `ritual-dapp-longrunning` | Long HTTP (0x0805)                                                               | Uzun süreli asenkron (poll/deliver) |
| `ritual-dapp-multimodal`  | Image (0x0818), Audio (0x0819), Video (0x081A)                                   | Uzun süreli asenkron (callback)     |
| `ritual-dapp-onnx`        | ONNX ML inference (0x0800)                                                       | Senkron                             |
| `ritual-dapp-ed25519`     | Ed25519 imza doğrulama (0x0009)                                                  | Senkron                             |
| `ritual-dapp-scheduler`   | Scheduler sistem smart contract'ı + predikatlar                                  | Zamanlanmış çalışma                 |
| `ritual-dapp-secrets`     | ECIES şifreleme, SECRET_NAME string değiştirme, PII redaksiyon, delege ACL       | Çapraz kesit                        |
| `ritual-dapp-x402`        | HTTP üzerinden X402 mikro ödeme                                                  | Çağrı başına ücretli API'lar        |
| `ritual-dapp-passkey`     | SECP256R1 (0x0100) + TxPasskey (0x77)                                            | Senkron                             |

### Smart Contract'lar (α)

| Skill                   | Ne Öğretir                                                                              |
| ----------------------- | --------------------------------------------------------------------------------------- |
| `ritual-dapp-contracts` | Consumer kalıpları: senkron, kısa süreli decoding, uzun süreli callback'ler, auth, event'ler |
| `ritual-dapp-wallet`    | RitualWallet yatırma/kilitleme/çekme, ücret tahmini, acil durum çekimi                 |

### Full-Stack (α)

| Skill                  | Ne Öğretir                                                                           |
| ---------------------- | ------------------------------------------------------------------------------------ |
| `ritual-dapp-frontend` | Next.js + wagmi, 9 durumlu asenkron TX makinesi, spcCalls parsing, SSE streaming    |
| `ritual-dapp-backend`  | Event indexer, AsyncJobTracker watcher, gönderici kilidi serileştirme, health endpoint'leri |
| `ritual-dapp-testing`  | Foundry unit/fuzz/fork, precompile'lar için vm.mockCall, Vitest, Playwright E2E      |

---

## Build Çalışma İzi

"Bana X inşa et" dediğinizde ajan dosyaları şu sırayla okur:

| Adım | Dosya                                                                         | Amaç                                    |
| ---- | ----------------------------------------------------------------------------- | --------------------------------------- |
| 1    | `skills/ritual-meta-projection/SKILL.md`                                      | Fikri Ritual-native spec'e dönüştür     |
| 2    | `agents/ritual-dapp-builder.md`                                               | Aşamalı build protokolü                 |
| 3    | `examples/registry.json`                                                      | Ritual Chain üzerindeki referans smart contract'lar |
| 4    | `skills/ritual-dapp-overview/SKILL.md`                                        | Chain mimarisi                          |
| 5    | `skills/ritual-dapp-precompiles/SKILL.md`                                     | ABI referansı                           |
| 6+   | Seçilen precompile'lara göre özellik skill'leri                               | Özellik başına kalıplar                 |
| 7+   | `contracts`, `wallet`, `frontend`, `design`, `deploy`, `testing`              | Aşamaya özgü skill'ler                  |
| Son  | `agents/ritual-dapp-debugger.md` + `skills/ritual-meta-verification/SKILL.md` | Build sonrası doğrulama                 |

Her aşamadan sonra ilerleme `.ritual-build/progress.json` dosyasına kaydedilir.

---

## Uyumlu Harness'lar

| Harness             | Entegrasyon                                                        |
| ------------------- | ------------------------------------------------------------------ |
| **Claude Code**     | `skills/` klasörünü ajan skill yoluna bırakın. Native `SKILL.md` formatı. |
| **Cursor**          | `.cursor/rules/` dizinine ekleyin veya ajan skill'i olarak referans verin |
| **OpenClaw**        | `skills/` klasörünü ajan skill yoluna bırakın. Native `SKILL.md` formatı. |
| **Hermes Agent**    | `skills/blockchain/ritual/` dizinine kopyalayın veya `skills_sync.py` ile senkronize edin |
| **Codex / ChatGPT** | Sistem prompt'unu `skills/ritual/SKILL.md`'ye yönlendirin         |

### Önerilen Kombinasyonlar

- **Claude Code + Opus 4.7 Max**
- **Cursor + Codex 5.3 Extra High**

Diğer kombinasyonlar da çalışır ancak sonuçlar değişkenlik gösterebilir.

---

## Chain Referansı

| Özellik         | Değer                                   |
| --------------- | --------------------------------------- |
| Chain ID        | `1979`                                  |
| Para Birimi     | RITUAL (18 ondalık, testnet)            |
| Blok süresi     | ~350ms (ihtiyatlı temel değer)          |
| RPC (HTTP)      | `https://rpc.ritualfoundation.org`      |
| RPC (WebSocket) | `wss://rpc.ritualfoundation.org/ws`     |
| Explorer        | `https://explorer.ritualfoundation.org` |

| Sistem Smart Contract | Adres                                        |
| --------------------- | -------------------------------------------- |
| RitualWallet          | `0x532F0dF0896F353d8C3DD8cc134e8129DA2a3948` |
| AsyncJobTracker       | `0xC069FFCa0389f44eCA2C626e55491b0ab045AEF5` |
| TEEServiceRegistry    | `0x9644e8562cE0Fe12b4deeC4163c064A8862Bf47F` |
| Scheduler             | `0x56e776BAE2DD60664b69Bd5F865F1180ffB7D58B` |
| SecretsAccessControl  | `0xf9BF1BC8A3e79B9EBeD0fa2Db70D0513fecE32FD` |
| AsyncDelivery         | `0x5A16214fF555848411544b005f7Ac063742f39F6` |
| ModelPricingRegistry  | `0x7A85F48b971ceBb75491b61abe279728F4c4384f` |

---

## Dizin Yapısı

```
ritual-dapp-skills/
├── skills/
│   ├── ritual/                         # Ω — İnsan giriş kapısı
│   ├── ritual-dapp-overview/           # Ω — Mimari + TEE-EOVMT
│   ├── ritual-dapp-precompiles/        # Ω — ABI referansı (16 precompile)
│   ├── ritual-dapp-deploy/             # α — Chain yapılandırması + deploy
│   ├── ritual-dapp-design/             # α — Tasarım sistemi
│   ├── ritual-dapp-contracts/          # α — Solidity kalıpları
│   ├── ritual-dapp-wallet/             # α — Ücret yönetimi
│   ├── ritual-dapp-http/               # α — HTTP precompile (0x0801)
│   ├── ritual-dapp-llm/                # α — LLM precompile (0x0802)
│   ├── ritual-dapp-agents/             # α — Agent precompile'ları (0x0820/0x080C)
│   ├── ritual-dapp-longrunning/        # α — Uzun süreli HTTP (0x0805)
│   ├── ritual-dapp-multimodal/         # α — Görüntü/Ses/Video (0x0818-0x081A)
│   ├── ritual-dapp-onnx/               # α — ONNX ML inference (0x0800)
│   ├── ritual-dapp-ed25519/            # α — Ed25519 doğrulama (0x0009)
│   ├── ritual-dapp-scheduler/          # α — Zamanlanmış işlemler
│   ├── ritual-dapp-secrets/            # α — Secret yönetimi + PII redaksiyon
│   ├── ritual-dapp-x402/               # α — Mikro ödemeler
│   ├── ritual-dapp-passkey/            # α — Passkey kimlik doğrulama
│   ├── ritual-dapp-frontend/           # α — React/Next.js frontend
│   ├── ritual-dapp-backend/            # α — Backend servisleri
│   ├── ritual-dapp-testing/            # α/β — Test kalıpları
│   ├── ritual-meta-bootstrap/          # Ω — 10 davranış kuralı
│   ├── ritual-meta-inspiration/        # Ω — JIT fikir üretimi
│   ├── ritual-meta-projection/         # Ω — Fikir → Ritual-native spec
│   ├── ritual-meta-elicitation/        # Ω — Tembel hedef-durum varyans azaltma
│   ├── ritual-meta-orchestrator/       # Ω — Build-debug iç içe geçirme
│   ├── ritual-meta-circuit-breaker/    # Ω — Yol sapması tespiti
│   ├── ritual-meta-human-in-loop/      # Ω — Oturum ortası çatallanma bilgi toplama
│   ├── ritual-meta-non-interactive-bias/ # Ω — Sormadan önce ara
│   └── ritual-meta-verification/       # Ω — Doğrulama protokolleri
├── agents/
│   ├── ritual-dapp-builder.md          # α — Build orkestratörü
│   ├── ritual-dapp-debugger.md         # β — Debug orkestratörü
│   └── debugger-reference/             # β — Tanı pipeline'ı
├── site/                               # Mikrosite (Cloud Run'a deploy edilir)
├── assets/                             # SVG diyagramları
├── examples/
│   ├── persistent-agent/             # Persistent Agent (0x0820) uçtan uca akış
│   ├── sovereign-agent/              # Sovereign Agent (0x080C) uçtan uca akış
│   ├── README.md
│   └── registry.json
├── templates/
│   ├── nextjs-starter/
│   └── hardhat-starter/
└── scripts/
    ├── pull_contracts.py
```

---

## Zamanlanmış Asenkron Hata Ayıklama Araçları

Zamanlanmış/zamanlanmış-asenkron izleme için şu dosyadaki çalıştırılabilir Python snippet'lerini kullanın:
`agents/debugger-reference/scheduled-async-rpc-runbook.md`

Bu runbook şunları içerir:

- deterministik zamanlanmış-hash türetme aracı
- asenkron kaynak hash'lerinden commitment sorgulama aracı

---

<p align="center">
  <a href="https://docs.ritualfoundation.org">Docs</a> · <a href="https://explorer.ritualfoundation.org">Explorer</a> · <a href="https://skills.ritualfoundation.org">Microsite</a>
</p>
