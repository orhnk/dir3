Bu projenin bir de android applikasyonu olmalı. Özellikler:

- Tıpkı Google Calendar gibi bir arayüz, halihazırdaki plan unsurları güzel bir arayüzde görüntülenebilir, intuitif bir şekilde yeni eventler oluşturulabilir vs. (herşey tıpatıp standart bir calendar applikasyon temelinde olduğu için sıfırdan bir uygulama yazmak yerine kaliteli ve tercihe uygun açık kaynaklı bir proje bulmaya çalış ve onu modifiye et)
- Plan kodlarına telefondan bir editör üzerinden erişip düzenleme
- Plan dosyalarını bilgisayardan pratik bir yöntem ile güncelleme (kod yazmakk telefondan zor, bilgisayardaki kodu telefondan güncelleyebilmek lazım)
- dir3 bazı eventleri alarm işlevi görmeli. Event başladığı zaman (yahut bittiği, yahut belirlenen bir offset üzere) telefonda alarm çalmalı, alarmın bütün özellikleri de dir3 kodu üzerinden belirlenmeli. Şu alarm uygulamasını referans olarak kullan yahut gerekli gördüğün şekilde kopyala: https://github.com/BlackyHawky/Clock NOT: Şimdiki planda sabah namazı ve teheccüt/sahur gibi gece uykudan kalkma eventleri alarmlı olmalı! Eğer teheccüt ve sahur gibi ardardalarsa ilkinin başlangıcında bir alarm yeterli ama. (bu projedeki clock özelliklerinin HEPSİ dir3 tarafından desteklenmeli)
- Event vakti geldiği zaman custom bildirim sesi yahut direkt event'in isminin sesli okunması.
- dir3 cli da telefon üzerinden pratik bir şekilde intuitif bir arayüzle kullanılabilir olmalı.

kurulumun nasıl yapılacağını da README.md ye ekle.

# TODO

Stand 2026-11-15: alle Punkte umgesetzt.

- [x] **Kein Schlaf nach Fajr.** `sleepplan.py` kennt keinen Morgenschlaf mehr;
  der persönliche Plan beginnt nach Fajr mit Frühstück und Weg.
- [x] **Kaylûle nach Studienlage.** Kurz (20–30 min), in der frühen
  Nachmittagssenke um 14:00, nie nach Asr; reicht der Platz nicht, rutscht sie
  nach vorn oder entfällt (`sleepplan.py`, `gebetsplan.py`).
- [x] **Rakahdauer 4 min.** Default in `PrayerPlanSettings.min_per_rakat`,
  Beispiele und Doku angepasst.
- [x] **Portionen für n Personen.** `MealPlanSettings.people` /
  `servings_per_person`, `Recipe.scaled()` und `--people`/`--servings` in
  `dir3-recipes diet`.
- [x] **Sync-Defaults im Planfile.** `sync = {"until": ..., "from": ...,
  "offline": ..., "config": ...}` in `SyncSettings`; CLI-Flags haben Vorrang.
- [x] **Nix-Befehle.** `nix build` und `nix develop` laufen (geprüft).
- [x] **Sync dokumentiert.** README-Abschnitt „Google Calendar sync“ inklusive
  Defaults, `--clear`, `--nuke`, Tasks und Rate Limits.
- [x] **Sıla-i Rahim.** `family.py` mit `Relative`, `buffer_minutes`,
  `sila_rahim_events` und `whom`-Auswahl (`random`, `under`, Index, Callable).
- [x] **Yemek planı.** Rezeptdatenbank (`recipes.py`), Diätmotor (`diet.py`),
  Wochenplan, Einkaufsliste und `shopping_task`.

## Android-App (2026-11-16)

- [x] **Kalender-App** auf Basis von Toast UI Calendar (MIT) im nativen
  Kotlin-Shell; Monat/Woche/Tag, Event-Erstellung, Farben, Icons und Alarme.
- [x] **Plan-Code-Editor** (CodeMirror) fuer Planfile, `plan/`, `examples/`;
  atomares Speichern mit Backup unter `.dir3/backups/`; Credential-Dateien
  werden nicht ausgeliefert.
- [x] **PC → Telefon** ueber `dir3 serve` im LAN; Telefon-Cache + 15-Minuten-
  Sync, damit Alarme auch ohne PC weiterlaufen. Telefon → PC per `PUT`.
- [x] **Alarm-DSL** (`alarm=`, `WakeAlarmPolicy`): Fajr/Tahajjud/Suhoor wecken
  automatisch, Nachtketten klingeln nur einmal; Ton (System/Asset/URI/App/
  Zufall), TTS, Crescendo, Vibration, Snooze-Limit, Mathe-/Flip-/Shake-/
  Swipe-Dismiss, Vollbild, Hintergrund, Taschenlampe, Pre-Notification,
  Skip-next.
- [x] **`dir3 export`** als providerneutrales JSON (Events + absolute
  Alarm-Trigger) und **`dir3 serve`** als LAN-API/CLI-Panel.
- [x] **CLI auf dem Telefon**: Compile/Sync/Clear/Dry-run mit echter Ausgabe.
- [x] **README**: Installation, APK-Bau (Actions/Studio), Rechte, Grenzen.
- [x] **Widget** (4×2, resizable): Tagesplan aus dem Cache, Farbbalken,
  Alarm-Badge, naechster Alarm in der Fusszeile, `↻`-Sync, Tap oeffnet den
  Tag in der App.
- [ ] **Nicht geplant**: Timer/Stoppuhr/Weltuhr aus Clock (keine
  Plan-Events); Power-Knopf-Dismiss wird auf Lautstaerketasten abgebildet.
