# Simplons Dokumentationswebseite

Spec zu #2.

## Das Ziel

Eine Webseite, die erklaert, warum man Simplon braucht, wie man startet, was
die Befehle tun, und wie man ein Produkt darauf aufsetzt. Veroeffentlicht ueber
GitHub Pages, verlinkt von der PyPI-Projektseite.

## Was schon da ist

`simplon.tasks.docs:render` rendert AsciiDoc ueber docToolchain in Docker und
erzeugt HTML und PDF. Der Kernel baut seine Doku also **mit sich selbst** --
dieselbe Regel wie beim Build.

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

Nur HTML. Der PDF-Zweig von `docs:render` bleibt ungenutzt; ein zweites
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
