# Simplons Dokumentationswebseite

Spec zu #2.

## Das Ziel

Eine Webseite, die erklaert, warum man Simplon braucht, wie man startet, was
die Befehle tun, und wie man ein Produkt darauf aufsetzt. Veroeffentlicht ueber
GitHub Pages, verlinkt von der PyPI-Projektseite.

## Das Werkzeug: Hugo, nicht docToolchain

Entscheidung des Eigentuemers: die Seite entsteht mit **Hugo**, damit sie wie
eine professionelle Seite aussieht, und die Inhalte werden in **Markdown**
geschrieben.

**Das ersetzt `simplon.tasks.docs:render` nicht. Es sind zwei verschiedene
Anwendungsfaelle, und sie bleiben nebeneinander stehen.**

| | `docs:render` (docToolchain) | `docs:site` (Hugo) |
|---|---|---|
| Was | Architekturdokumentation eines Produkts | Produktwebseite |
| Fuer wen | Entwickler und Architekten, die AM System arbeiten | Benutzer und Uebernehmer, die MIT dem System arbeiten |
| Format | AsciiDoc, arc42-naeher Aufbau | Markdown |
| Ausgabe | HTML **und PDF** -- das PDF ist dort der Zweck (Abgabe, Ablage, Review) | HTML, und nur HTML |
| Lebt | im Repo, versioniert mit dem Code | veroeffentlicht, versioniert mit dem Release |
| Aussehen | zweitrangig, Inhalt zaehlt | erstrangig, es ist die Aussenseite |

Sie durch dasselbe Werkzeug zu zwingen, weil eines schon da ist, waere die
falsche Sparsamkeit -- und umgekehrt `docs:render` abzuschaffen, weil Hugo
huebscher aussieht, waere es genauso: eine Architekturdoku als Webseite zu
veroeffentlichen loest kein Problem, das jemand hat.

**Ein Produkt kann beides brauchen.** netctl hat heute `docs:render`; wenn es
morgen eine Webseite will, bekommt es `docs:site` daneben, nicht statt dessen.

**Der Kernel baut seine Doku mit sich selbst**, und zwar ueber einen Task **im
Katalog** -- Entscheidung des Eigentuemers. Der Hugo-Lauf gehoert nicht in ein
Skript daneben, sonst waere Simplons eigene Webseite das einzige, was Simplon
nicht baut.

Der Task heisst sinngemaess `docs:site` und steht neben `docs:render`. Damit
kann jedes Produkt eine Hugo-Seite bauen, nicht nur der Kernel.

**Die Gegenrede, und warum sie hier nicht traegt.** Der Katalogkommentar
verbietet Faehigkeiten auf Vorrat, und heute hat genau ein Produkt eine Seite
-- Simplon selbst. Dagegen steht: der Kernel traegt bereits `docs:render` als
allgemeine Doku-Faehigkeit, und ein zweites Werkzeug daneben ist keine neue
Kategorie, sondern eine zweite Auspraegung derselben. Die Mechanik (Hugo
aufrufen, Ausgabeverzeichnis, Theme aufloesen) traegt kein Produktwissen. Was
das Produkt beitraegt, sind Daten: wo die Inhalte liegen, wie die Seite heisst,
welches Theme. Das ist genau die Trennung, nach der `docs:render` schon gebaut
ist.

**Was daraus folgt, und der Plan muss es einhalten:** ein Katalog-Task ist ein
Versprechen an drei Produkte, nicht eine Bequemlichkeit fuer eines. Er muss
seine Daten aus dem Manifest lesen statt Simplons Verzeichnisse anzunehmen, und
er muss laut werden, wenn Hugo fehlt -- nach derselben Regel, die 0.1.7 gelernt
hat: ein Werkzeug, das fehlt, ist nicht dasselbe wie ein Werkzeug, das
gescheitert ist.

## Vier Entscheidungen des Eigentuemers

| Frage | Antwort |
|---|---|
| Woraus entsteht die Befehlsreferenz? | **Aus der laufenden CLI** |
| Wen bedient die Seite? | **Benutzer UND Produktbauer** |
| Wann wird veroeffentlicht? | **Bei jedem Release (Tag)** |
| Und das PDF? | **Nur HTML** |

## Die tragende Unterscheidung

**Was erzeugt werden kann, wird erzeugt. Was nicht erzeugt werden kann, wird
geschrieben.** Daran haengt der ganze Aufbau, und die Trennlinie laeuft nicht
zwischen Kapiteln, sondern zwischen zwei Arten von Wahrheit.

Die **Befehlsreferenz** ist ableitbar: Simplon baut seine Typer-App aus dem
Manifest, und danach steht fest, welche Gruppen, Befehle, Parameter und
Hilfetexte es gibt. Sie von Hand zu pflegen hiesse, dieselbe Information
zweimal zu halten -- und die zweite Fassung veraltet, sobald jemand einen
Befehl hinzufuegt und die Doku vergisst. Das ist kein hypothetisches Risiko:
genau dieses Muster (zwei Quellen fuer dieselbe Sache) hat agile-cockpit heute
in `tests/suites.txt` beseitigt.

Die **Regeln, nach denen der Kernel entworfen ist**, sind nicht ableitbar. Der
Satz aus #6 -- *ein Werkzeug, das fehlt, ist nicht dasselbe wie ein Werkzeug,
das gescheitert ist* -- steht in keinem Katalog. Er ist der Grund, warum
`render_report` drei Zustaende hat statt zwei, aber aus dem Code liest ihn
niemand heraus. Solche Saetze gehoeren von Hand geschrieben und mit dem Fall
belegt, der sie erzwungen hat.

## Warum aus der laufenden CLI und nicht aus catalogue.yaml

Der Katalog beschreibt die **Absicht**, die gebaute App das **Ergebnis**.
Zwischen beiden liegt die Zusammenfuehrung mit dem Produktmanifest -- genau die
Stelle, an der 0.1.6 eine stille Namenskollision gefunden hat. Eine Referenz
aus dem Katalog haette dort beide Befehle beschrieben und verschwiegen, dass nur
einer laeuft.

Aus der laufenden App erzeugt, beschreibt die Referenz, was ein Benutzer
wirklich tippen kann. Und sie faellt aus, wenn die App nicht baut -- was ein
Ausfall an der richtigen Stelle ist.

## Aufbau

Zwei Teile fuer zwei Rollen. Wer Simplon benutzt und wer ein Produkt darauf
baut, sind verschiedene Menschen mit verschiedenen Fragen; sie in ein Kapitel
zu mischen bedient keinen von beiden.

**Teil 1 -- Benutzen.** Warum es das gibt, der Einstieg (`simplon init`, der
erzeugte Starter, der erste Lauf), Beispiele entlang echter Aufgaben, und die
**erzeugte Befehlsreferenz**.

**Teil 2 -- Ein Produkt darauf bauen.** Das Manifest (Baumform, `task:`, der
Doppelpunkt-Unterschied zwischen eigenem Rumpf und Katalog-Koordinate), eigene
Tasks, Umgebungen, und das Regelkapitel.

## Veroeffentlichung

Beim Tag, nicht bei jedem Push. Die veroeffentlichte Doku beschreibt damit immer
eine Version, die es auf PyPI gibt. Zwischen zwei Releases altert sie -- aber sie
luegt nie ueber etwas, das noch niemand installieren kann.

Nur HTML. Hugo erzeugt ohnehin kein PDF; die frueher erwogene Kopplung an den
PDF-Zweig von `docs:render` entfaellt mit dem Werkzeugwechsel. Ein zweites
Artefakt will gepflegt und geprueft werden, und niemand hat danach gefragt.

## Abnahme

1. Die erzeugte Referenz nennt **jede** Gruppe und **jeden** Befehl der
   gebauten App. Gemessen: die Zahl der Eintraege in der Referenz gegen die
   Zahl, die die App kennt -- nicht geschaetzt.
2. Ein neuer Befehl im Katalog erscheint ohne Handarbeit in der Referenz.
   Nachgestellt durch Hinzufuegen eines Befehls und erneutes Erzeugen.
3. Die Seite ist unter der Pages-URL erreichbar, und die PyPI-Projektseite
   verlinkt sie.
4. Ein Release ohne Doku-Aenderung baut die Seite trotzdem neu -- die
   Veroeffentlichung haengt am Tag, nicht an einer geaenderten Datei.

## Was der Werkzeugwechsel an den Anforderungen aendert

Die tragende Unterscheidung (erzeugt gegen geschrieben) bleibt unberuehrt --
sie ist eine Aussage darueber, welche Information woher kommt, nicht darueber,
womit gesetzt wird. Drei Dinge aendern sich konkret:

1. **Das Format ist Markdown**, nicht AsciiDoc. Die erzeugte Befehlsreferenz
   muss also Markdown ausgeben, das Hugo einliest -- nicht AsciiDoc.
2. **Das Theme ist entschieden: Hextra, als Hugo-Modul.** Ein Doku-Theme mit
   Suche, Dunkelmodus und Navigation ab Werk, das kein npm braucht -- nur Hugo
   Extended. Als Hugo-Modul steht die Version in `go.mod`, Aktualisieren ist ein
   Befehl, und das Repo bleibt schlank; der CI-Lauf braucht dafuer Go, das auf
   GitHub-Runnern ohnehin liegt.

   Ausdruecklich **kein Submodul**: agile-cockpit ist heute erst eines
   losgeworden, weil Submodule bei jedem Klon und in jeder Pipeline eigene
   Aufmerksamkeit verlangen. Und **nicht vendored**: ein kopiertes Theme hat
   keinen Aktualisierungspfad, und niemand merkt, wenn das Original weiterzieht.

   Da der Task im Katalog steht, ist das Theme **Produktdatum, nicht
   Kernelentscheidung** -- Hextra ist Simplons Wahl, nicht die aller Produkte.
3. **Der Bau braucht Hugo, nicht Docker.** `docs:render` umgeht eine lokale
   Installation, indem es containerisiert laeuft; fuer Hugo ist das nicht noetig,
   aber der CI-Lauf muss die Binaerdatei bekommen. Wie -- Action, Container oder
   Paketmanager -- entscheidet der Plan.

## Ausserhalb dieser Spec

- Der Provider-Entwurf (#5) und die Versionierung (#3).
- Eine Doku fuer die einzelnen Produkte. Diese Seite beschreibt den Kernel.
- Uebersetzungen.

## Das Risiko, benannt

Die erzeugte Referenz kann **vollstaendig und trotzdem nutzlos** sein: eine
Liste aller Befehle mit ihren Hilfetexten beantwortet nicht, wann man welchen
braucht. Der Wert der Seite entsteht in den handgeschriebenen Teilen; die
Erzeugung sorgt nur dafuer, dass der mechanische Teil nicht veraltet. Wer die
Spec umsetzt und dabei die Beispiele knapp haelt, weil die Referenz ja
"vollstaendig" ist, hat sie missverstanden.
