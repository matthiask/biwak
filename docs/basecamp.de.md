# Von Basecamp her

Biwak folgt Basecamp eng: Projekte mit To-do-Listen, Mitteilungen,
Dokumente und Dateien, Check-ins, Kund:innen, die nur sehen, was ihnen
gezeigt wird, und Mails, auf die du antworten kannst. Das meiste, was du
kennst, funktioniert gleich. Diese Seite zeigt, wo Biwak anders ist und
warum, damit dich nichts überrascht.

## Weniger Orte zum Suchen

- **Eine Art Liste.** Neben den To-do-Listen gibt es kein Kartenboard:
  Jede Liste lässt sich als Board zeigen, ihre Gruppen als Spalten
  ([To-dos](todos.de.md)). Ein To-do bleibt in beiden Ansichten
  dasselbe.
- **Kein Chat, keine Pings, kein Terminplan.** Gespräche bleiben beim
  To-do oder bei der Mitteilung, um die es geht, wo du sie wiederfindest.
  Fälligkeiten stehen an den To-dos; die To-do-Seite listet sie nach
  Datum, und deine eigenen kannst du in deine Kalender-App holen.
- **Keine Kommentare zu Listen und Ordnern.** Ein Kommentar zu einer
  Liste wird zu einem eigenen To-do, das niemand abhaken kann.
  Kommentiere die To-dos, oder schreibe eine Mitteilung.
- **Nur Projekte und Listen werden archiviert.** To-dos werden
  erledigt, alles andere kommt in den Papierkorb, wenn es nicht mehr
  gebraucht wird.
- **Start** zeigt, was heute dich braucht und wo etwas los ist, und
  lässt Abschnitte ohne Inhalt weg.

## Von weniger hören, aber vom Richtigen

- **Neue Mitglieder werden nicht überflutet.** Wer einem Projekt
  beitritt, abonniert nichts, was schon da ist; du hörst von dem, was ab
  jetzt passiert.
- **„Nur was mich betrifft“ ist die Standardstufe:** Du hörst davon,
  wenn du erwähnt oder zugewiesen wirst, und von deinen eigenen Sachen.
  „Alles“ ist eine Wahl, pro Person oder pro Projekt
  ([Benachrichtigungen](notifications.de.md)).
- **Eine Benachrichtigung pro Änderung.** In derselben Änderung
  zugewiesen und erwähnt ergibt eine Benachrichtigung, nicht zwei.
- **In der App gelesen, nicht gemailt.** Die Laterne (das „Hey!“ von
  Biwak) gruppiert Benachrichtigungen nach Eintrag. Was du dort liest,
  bevor seine Mail rausgeht, fehlt in der Mail oder der Zusammenfassung;
  du kannst Mails auch ganz abstellen und nur die Laterne nutzen.
- **Ruhezeiten und Abwesenheit** halten Mails zurück, während du nicht
  arbeitest, wie „Work can wait“, und andere sehen beim Zuweisen oder
  Erwähnen, dass du abwesend bist.
- **Reaktionen** haben 32 Emoji und kurze Texte bis 40 Zeichen und
  sagen es nur der Autorin oder dem Autor, in der nächsten Mail oder der
  Zusammenfassung.

## Kund:innen: schwer, es falsch zu machen

- **Der Schalter ist am Behälter.** Listen und Ordner sind für
  Kund:innen sichtbar oder intern; was darin ist, folgt ihnen. Neues ist
  intern, bis es gezeigt wird.
- **Zeigen fragt zuerst** und sagt, was sich ändert. Verbergen ist ein
  Klick.
- **Keine internen Kommentare zu sichtbaren Einträgen:** Was dort steht,
  lesen Kund:innen mit. Intern besprecht ihr es in einer internen
  Mitteilung.
- **Ein Reiter am Fensterrand** sagt, dass Kund:innen es sehen, und
  bleibt beim Scrollen sichtbar, dazu das Abzeichen auf jeder Zeile
  ([Kund:innen](clients.de.md)).

## Schreiben

- **Checklisten in jedem Text.** Notizen, Kommentare, Mitteilungen und
  Dokumente können Checklisten haben (`- [ ]`), direkt auf der Seite
  abgehakt und auf der Zeile des To-dos gezählt.
- **Dokumente werden live gemeinsam geschrieben**, vor allem Notizen
  von Sitzungen: mehrere Personen gleichzeitig, ohne Sperren, mit
  Versionen, zu denen ihr zurückkönnt
  ([Mitteilungen, Dokumente und Dateien](files.de.md)).
- **Texte werden als Markdown gespeichert**, so kommen sie aus der API
  und der CLI als einfacher Text und lassen sich von überall einfügen.
  Der Editor sieht aus wie jeder andere.
- **To-dos aus Text hinzufügen** legt alles in die Liste, auf die du ihn
  ziehst: Überschriften werden Gruppen, nicht neue Listen.

## Sich bewegen

- **Die Befehlspalette** (<kbd>Ctrl</kbd>+<kbd>K</kbd> oder
  <kbd>/</kbd>) springt zu Projekten, Personen und Einträgen und führt
  Aktionen der Seite aus; einzelne Tasten wirken innerhalb der Seiten
  und lassen sich abschalten ([Tastatur](keyboard.de.md)).
- **Startdaten** halten ein To-do aus der laufenden Arbeit, bis es
  beginnen kann.
- **Teams** werden beim Auswählen zu ihren Mitgliedern: Ändert sich ein
  Team später, ändert das nichts an dem, was damit zugewiesen wurde.
- **Öffentliche Links** gelten 1 bis 30 Tage, und der Dialog bietet
  zuerst den eigenen Link des Eintrags an: Wer ein Konto hat, braucht nie
  einen öffentlichen.
- **Wenn jemand nicht mehr dabei ist**, bleiben die Zuweisungen, so
  lassen sich die offenen To-dos noch finden und übergeben, mehrere auf
  einmal.

## Anmelden und der Rest

- **Keine Passwörter.** Du meldest dich mit einem Code per Mail, einem
  Passkey oder mit Google oder Microsoft an, wie es deine Organisation
  erlaubt ([Anmelden](sign-in.de.md)).
- **Alles, was die Seiten können, können auch die API und der Befehl
  `biwak`**, für Skripte und KI-Agenten
  ([Die CLI und die API](cli.de.md)).
- **Biwak läuft auf dem eigenen Server deiner Organisation**, auf
  Deutsch und Englisch, gewählt pro Person.
- **Basecamp-Projekte lassen sich importieren**, durch Admins, mit
  ihren Personen, Kommentaren und Dateien.

## Was Biwak nicht tut

- **Zeiterfassung und Rechnungen.** Nutze dafür deine bisherigen
  Werkzeuge; ein Projekt kann darauf verlinken (füge auf der Seite des
  Projekts einen Link hinzu).
- **Chat.** Diskutiert wird in Kommentaren zu To-dos und Mitteilungen.
- **Ein Projektkalender.** To-dos haben Fälligkeiten, und die To-do-Seite
  listet sie nach Datum; deine eigenen To-dos kannst du in einer
  Kalender-App abonnieren ([To-dos](todos.de.md)).
- **Hill Charts und Doors.** Verlinke die Werkzeuge, die ihr nutzt, auf
  der Seite des Projekts.
- **To-dos ausserhalb von Listen.** Jedes To-do gehört zu einer Liste.
