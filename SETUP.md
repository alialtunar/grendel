# Harness kurulum ve kullanım rehberi

Bu iskelet, 10 fazlı bir projeyi şu döngüyle yürütür:
**spec → plan → planı denetle → uygula → her milestone'da reviewer + tester.**

---

## Klasör yapısı

```
projen/
├── ROADMAP.md                      ← 10 fazın üst-düzey planı
├── phases/                         ← her fazın artifact'ları buraya
│   └── phase-01/
│       ├── spec.md                 (otomatik üretilir)
│       ├── plan.md                 (otomatik üretilir)
│       ├── review.md               (reviewer yazar)
│       └── test-report.md          (tester yazar)
└── .claude/
    ├── settings.json               ← PostToolUse hook
    ├── agents/
    │   ├── plan-reviewer.md
    │   ├── reviewer.md
    │   └── tester.md
    ├── skills/
    │   └── phase/SKILL.md          ← /phase driver
    └── scripts/
        └── gate.sh                 ← hızlı lint/typecheck kapısı
```

---

## Adım adım kurulum

### 1. Dosyaları projene kopyala
Bu paketteki `.claude/` klasörünü, `ROADMAP.md` ve `phases/` klasörünü projenin
köküne koy. (`/brainstorming` ve `/writing-plans` skill'lerinin zaten kurulu
olduğunu varsayıyorum — bu iskelet onları kullanıyor, içermiyor.)

### 2. gate.sh'i kendi stack'ine göre ayarla
`.claude/scripts/gate.sh` içinde tek bir satır var. Onu kendi diline göre değiştir:

```bash
# Python:   QUICK_CMD="ruff check . && pyright"
# Node/TS:  QUICK_CMD="npm run lint && npm run typecheck"
# Go:       QUICK_CMD="gofmt -l . && go vet ./..."
# Rust:     QUICK_CMD="cargo fmt --check && cargo clippy -- -D warnings"
```

Sonra çalıştırılabilir yap:
```bash
chmod +x .claude/scripts/gate.sh
```

Not: Bu kapı sadece HIZLI kontrol (lint/typecheck) yapar. Ağır test takımını
`tester` agent'ı milestone'larda koşar — böylece her edit'te yavaşlamazsın.

### 3. ROADMAP.md'yi doldur
Projenin vizyonunu ve 10 fazın her birinin tek satırlık hedefini yaz.
Detay yazma — detaylar her fazda otomatik üretilecek.

### 4. Claude Code'u projenin kökünden başlat
```bash
cd projen/
claude
```
Hook ve skill'lerin tanındığını doğrula: `/hooks` ve `/agents` yazıp listeyi gör.

---

## Nasıl çalıştırılır

### Tek bir fazı elle yürüt (önerilen başlangıç)
```
/phase phase 01
```
`/phase` skill'i sırayla şunları yapar:
1. `/brainstorming` ile `spec.md` üretir
2. `/writing-plans` ile `spec.md`'den `plan.md` yazar
3. `plan-reviewer` agent'ı planı denetler (PASS olana kadar düzeltir)
4. Planı milestone milestone uygular
5. Her milestone'da `reviewer` + `tester` agent'larını çağırır
6. İkisi de `STATUS: PASS` verince fazı kapatır ve DURUR

Faz bitince sen `review.md` ve `test-report.md`'yi gözden geçirirsin, sonra
bir sonraki faza geçersin. Bu insan onay noktası greenfield projede kritiktir.

### Bir fazı otonom koştur (pattern oturduktan sonra)
```
/goal Complete phase 01 per phases/phase-01/plan.md,
  until phases/phase-01/review.md and phases/phase-01/test-report.md
  both say STATUS: PASS.
```
Hedef, iki denetçi de temiz diyene kadar kendini düzelterek döner.
`Ctrl+C` ile her an durdurabilirsin. `/goal clear` ile hedefi kaldırırsın.

### TÜM fazları otonom koştur (en güçlü ve en riskli mod)
Önce en az faz 01'i elle koşup pattern'in çalıştığını gör. Sonra:
```
/goal Build the entire project by running run-all, until PROGRESS.md
  says "ALL PHASES COMPLETE" — but STOP immediately and report if
  PROGRESS.md contains any "BLOCKED" line.
```
`run-all` skill'i ROADMAP'teki fazları sırayla `/phase`'den geçirir. Her faz
bitince `PROGRESS.md`'ye "phase NN: DONE" yazar. Bir faz PASS alamazsa
ATLAMAZ — durur, "phase NN: BLOCKED — sebep" yazar ve sana bildirir.

**Gözetimsiz koşarken `PROGRESS.md`'ye bakarak nerede olduğunu görürsün.**

Üç güvenlik kemeri:
1. Faz 01'i önce elle dene.
2. BLOCKED'da durma kuralını zayıflatma (skill'de var).
3. İlk tam koşuyu izleyebileceğin bir zamanda başlat; ilk birkaç fazı gözle.

---

## Akış (özet)

```
ROADMAP.md (10 faz)
      │
      ▼  /phase phase-NN
 ┌─────────────────────────────────────────────┐
 │  /brainstorming → spec.md                    │
 │  /writing-plans → plan.md                    │
 │  plan-reviewer  → planı güçlendir            │
 │  uygula ──► milestone kapısı:                │
 │            reviewer + tester                 │
 │            BLOCKING? → düzelt, tekrar         │
 │            PASS + PASS? → sonraki milestone   │
 └─────────────────────────────────────────────┘
      │  faz tamam → sen gözden geçir → sonraki faz
      ▼
```

---

## Önemli notlar

- **Maliyet:** `/goal` ve subagent'lar token yer. İlk fazı küçük tutup gözlemle.
- **İnsan onayı:** Faz aralarında dur; 10 fazı tek seferde otonom koşturma.
- **Genişletme:** Pattern güveni oturunca, 10 fazı tek bir dynamic workflow
  scriptine taşıyabilirsin (sıralı bağımlılık olduğu için `pipeline` kalıbı).
- **Sınırla:** Workflow aşırı karmaşıklaşırsa "en fazla N agent kullan" de.
