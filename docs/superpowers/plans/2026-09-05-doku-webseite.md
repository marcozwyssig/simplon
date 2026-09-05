# Dokumentationswebseite — Umsetzungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development

**Goal:** Eine Hugo-Seite auf GitHub Pages, die Simplon erklaert — mit einer Befehlsreferenz, die aus der laufenden CLI erzeugt wird und deshalb nicht veralten kann.

**Spec:** `docs/superpowers/specs/2026-09-05-doku-webseite-design.md`
**Issue:** #2

## Global Constraints

- **Was ableitbar ist, wird erzeugt. Was nicht ableitbar ist, wird geschrieben.** Die Befehlsreferenz entsteht aus der gebauten Typer-App, nicht aus `catalogue.yaml` und nicht von Hand.
- **`docs:site` ist ein Katalog-Task und damit ein Versprechen an drei Produkte.** Er liest seine Daten aus dem Manifest und nimmt keine Verzeichnisse an. Kein `simplon`-spezifischer Pfad im Kernel-Code.
- **Ein fehlendes Werkzeug ist nicht dasselbe wie ein gescheitertes** (die Regel aus 0.1.7). Fehlt Hugo: Hinweis, rc 0. Ist Hugo da und scheitert: sichtbar, rc != 0.
- **Tests, die man hat fallen sehen.** Jeder neue Test wird gegen den unreparierten Stand gefahren, bevor er behalten wird.
- Ausgangsstand: **1165 Tests**. Die Zahl darf steigen, nicht sinken.
- Theme: **Hextra als Hugo-Modul**, kein Submodul, nicht vendored. Es ist Produktdatum im Manifest, keine Kernelfestlegung.
- Nur HTML. Kein PDF.

---

### Aufgabe 1: `docs:site` — der Kernel-Task

**Dateien:** neu `src/simplon/tasks/site.py`; `src/simplon/catalogue.yaml`; neu `tests/test_tasks_site.py`

Der Task ruft Hugo auf. Aus dem Manifest kommen die Daten: wo die Inhalte liegen, wohin gebaut wird, welches Theme, welcher Basis-URL. Sieh dir `simplon/tasks/docs.py` an — es ist das Vorbild fuer die Trennung zwischen Mechanik und Produktdatum, und sein Kopfkommentar sagt ausdruecklich, warum das Rendern dem Kernel gehoert und die Konfiguration dem Produkt.

**Drei Dinge, die leicht falsch werden:**

1. **Hugo-Modul heisst Go im Pfad.** `hugo mod get` braucht eine Go-Installation. Fehlt sie, ist das ein anderer Fehler als "Hugo fehlt" — die Meldung muss sagen, welches der beiden fehlt.
2. **Der Ausgabepfad gehoert dem Produkt.** Nimm keinen an; lies ihn.
3. **Ein Bau, der nichts erzeugt, gilt als gescheitert.** Hugo kann mit rc 0 enden und ein leeres Verzeichnis hinterlassen (leere Inhalte, falscher `contentDir`). Pruef, dass am Ende eine `index.html` steht — sonst wiederholst du genau den Defekt, den 0.1.7 behoben hat.

**Test-Abnahme:** ein Lauf ohne Hugo im PATH gibt rc 0 mit Hinweis; ein Lauf mit Hugo, dessen Konfiguration nichts erzeugt, gibt rc != 0.

---

### Aufgabe 2: Die erzeugte Befehlsreferenz

**Dateien:** neu `src/simplon/tasks/cliref.py` (oder in `site.py`, entscheide nach Umfang); `src/simplon/catalogue.yaml`; Tests

Erzeugt aus der **gebauten Typer-App** eine Markdown-Datei je Gruppe (oder eine grosse — entscheide und begruende). Enthalten: Gruppen, Befehle, Parameter mit Typ und Vorgabe, Hilfetexte, und die Unterscheidung agnostisch/umgebungs-erst.

**Der Kern:** die App kennen, ohne sie auszufuehren. Typer baut auf Click; ein `click.Command` traegt seine Parameter und Hilfetexte als Objekte. Geh den Baum durch, statt `--help` zu parsen — Text zu parsen, den ein anderes Werkzeug formatiert hat, bricht bei der naechsten Version von Click.

**Abnahme, gemessen statt geschaetzt:**
1. Die Zahl der Eintraege in der Referenz **gleicht** der Zahl der Befehle, die die App kennt.
2. Ein neu in den Katalog gestellter Befehl erscheint ohne Handarbeit. **Stell das nach**: Befehl hinzufuegen, erzeugen, pruefen, wieder entfernen.
3. Die Ausgabe ist Markdown, das Hugo einliest — keine AsciiDoc-Reste.

---

### Aufgabe 3: Die Seite selbst

**Dateien:** `site/` (Hugo-Projekt), `simplon.yaml` (die `docs:site`-Daten), Inhalte in Markdown

Zwei Teile fuer zwei Rollen, wie die Spec sie trennt:

**Teil 1 — Benutzen.** Warum es Simplon gibt; der Einstieg (`simplon init`, der erzeugte Starter, der erste Lauf); Beispiele entlang echter Aufgaben; die erzeugte Referenz.

**Teil 2 — Ein Produkt darauf bauen.** Das Manifest (Baumform, `task:`, der Doppelpunkt-Unterschied zwischen eigenem Rumpf und Katalog-Koordinate); eigene Tasks; Umgebungen; das Regelkapitel.

**Das Regelkapitel ist der Teil, der nicht erzeugt werden kann**, und der Grund, warum die Seite mehr ist als eine Referenz. Es beginnt mit dem Satz, den ein Konsument formuliert hat:

> Ein Werkzeug, das fehlt, ist nicht dasselbe wie ein Werkzeug, das gescheitert ist.

Beleg ihn mit dem Fall, der ihn erzwungen hat (#6): der Docker-Zweig des Allure-Renderns schrieb als fremde uid, scheiterte, und meldete trotzdem rc 0 — zwei Releases lang unbemerkt, weil der einzige Konsument, der ihn haette sehen koennen, am Docker-Pfad vorbeiging.

Weitere Kandidaten aus der Historie dieses Kernels, jeder mit seinem Fall: warum `catalogue.yaml` im Paket mitreist statt im Repo zu liegen; warum eine Gruppe ohne Befehle nicht erscheint; warum eine Namenskollision laut bricht statt still aufzuloesen; warum ein Schritt `sys.executable` benutzt und nicht `python`.

**Schreib die Beispiele nicht knapp, weil die Referenz vollstaendig ist.** Die Spec warnt ausdruecklich davor: eine vollstaendige Befehlsliste beantwortet nicht, wann man welchen braucht.

---

### Aufgabe 4: Veroeffentlichen

**Dateien:** `.github/workflows/` (Pages-Veroeffentlichung), `pyproject.toml` (Projekt-URL)

Beim **Tag**, nicht bei jedem Push. Die veroeffentlichte Doku beschreibt damit immer eine Version, die es auf PyPI gibt.

`pyproject.toml` bekommt die Seite als Projekt-URL, damit PyPI sie verlinkt.

**Abnahme:** ein Release ohne Doku-Aenderung baut die Seite trotzdem neu — die Veroeffentlichung haengt am Tag, nicht an einer geaenderten Datei. Pruef das, statt es anzunehmen.
