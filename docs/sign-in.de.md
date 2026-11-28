# Anmelden

Biwak hat keine Passwörter. Du meldest dich mit deiner Mail-Adresse an:

- **Ein Code per Mail:** Gib deine Adresse ein, Biwak mailt dir einen
  Code, tippe ihn ein. Das geht auch, wenn du die Mail auf dem Handy
  liest und Biwak auf dem Laptop offen ist.
- **Ein Passkey:** dein Fingerabdruck, dein Gesicht oder die PIN deines
  Geräts. Nach dem Anmelden per Code bietet Biwak an, einen
  hinzuzufügen; in den Einstellungen unter „Anmeldung“ fügst du sie
  hinzu und entfernst sie.
- **Single Sign-on:** „Über deine Organisation anmelden“ auf der
  Anmeldeseite, dann Google oder Microsoft, wo deine Organisation es
  eingerichtet hat. Wo sie Single Sign-on verlangt, führt dich die
  Eingabe deiner Adresse dorthin.

## Eine Authenticator-App

Ein zweiter Schritt, wenn du einen willst: Einstellungen, „Anmeldung“,
„Authenticator-App“, „Einrichten…“ zeigt einen QR-Code für eine App auf
deinem Handy (irgendeine Authenticator-App); gib den Code ein, den sie
zeigt, um sie einzuschalten. Von da an fragt das Anmelden per Code oder
über Google oder Microsoft auch nach dem Code der App. Ein Passkey
reicht allein: Er braucht schon dein Gerät und seine PIN oder deinen
Fingerabdruck.

- **Bestätigen, dass du es bist** (einen Passkey hinzufügen, Dinge
  einrichten), fragt dann nach dem Code der App oder einem Passkey,
  nicht nach einem Code per Mail.
- **Ausschalten** („Ausschalten…“) braucht einen Code aus der App.
- **App verloren?** Ein Passkey meldet dich weiterhin an, aber die App
  auszuschalten braucht ihren Code: Ohne die App bittest du um ein
  Zurücksetzen (unten). Es gibt keine Wiederherstellungscodes.

**Handy oder Laptop verloren, oder hatte vielleicht jemand anderes
Zugriff?** Bitte um ein Zurücksetzen: Auf deiner Seite entfernt
„Anmeldung zurücksetzen…“ deine Authenticator-App, deine Passkeys,
deine API-Tokens und deine Geräte für Push-Benachrichtigungen, meldet dich überall ab und mailt dir, was entfernt
wurde und von wem. Du meldest dich dann mit einem Code oder über die
Anmeldung deiner Organisation an und richtest alles neu ein; wo deine
Organisation einen zweiten Faktor verlangt, führt dich Biwak zuerst
dazu, einen hinzuzufügen. Mitarbeitende setzen Kund:innen zurück, Admins
alle anderen; niemand setzt sich selbst zurück. Die CLI: `biwak people
reset-sign-in ID`.

Einen Passkey hinzufügen oder entfernen und die App ein- oder
ausschalten schickt dir eine Mail, die sagt, was sich wann geändert hat:
Warst du es nicht, sag es einem Admin.

Personen, deren Organisation Single Sign-on verlangt, haben keine
Authenticator-App: Ihr Identity-Provider fragt nach einem zweiten
Schritt, wenn er einen will.

## Organisationen, die einen zweiten Faktor verlangen

Admins können für eine Organisation einen zweiten Faktor verlangen
(ihre Seite, „Anmeldung…“, „Zweiten Faktor verlangen“). Dann reicht für
ihre Personen ein Code per Mail allein nicht:

- Ein Passkey reicht, und ebenso eine Anmeldung über den
  Identity-Provider der Organisation (ihr eigenes Google Workspace oder
  ihr Microsoft-Tenant, kein persönliches Gmail-Konto);
- nach einem Code folgt der Code der Authenticator-App;
- Personen mit einem Passkey, aber ohne App melden sich mit dem Passkey
  an (ein Code allein wird abgelehnt);
- Personen mit keinem von beidem fügen gleich nach dem Anmelden per Code
  einen Passkey hinzu oder richten eine App ein, vor allem anderen;
  ebenso nach einem Zurücksetzen oder wenn die Einstellung eingeschaltet
  wird.

API-Tokens, die vorher erstellt wurden, funktionieren weiter. Wo Single
Sign-on verlangt wird, spielt die Einstellung keine Rolle: Es gibt keine
Codes.

## Single Sign-on

Jede Organisation entscheidet, wie sich ihre Personen anmelden (Admins
ändern es auf der Seite der Organisation, „Anmeldung…“):

- **Codes und Passkeys**, der Standard.
- **Single Sign-on erlaubt:** das Google-Workspace- oder Microsoft-Entra-ID-Konto
  der Organisation zusätzlich zu Codes und Passkeys. Unsere eigene
  Organisation meldet sich so mit Google an.
- **Single Sign-on verlangt:** nur der Identity-Provider der
  Organisation. Die Eingabe deiner Adresse führt dich dorthin; Codes
  werden abgelehnt, Passkeys und Authenticator-Apps werden nicht
  angeboten (der Wechsel zu „verlangt“ entfernt sie), und du meldest
  dich alle 24 Stunden wieder über den Provider an, meist mit einem
  Klick. API-Tokens laufen 24 Stunden nach dem Erstellen ab, und es gibt
  keine Kalenderlinks.

Eine Anmeldung mit Google zählt nur für ein Konto, das das Google
Workspace der Organisation verwaltet (ihre Mail-Domains), mit deiner
Adresse in Biwak. Eine Gmail-Adresse kann sich mit Google anmelden, wo
die Organisation Single Sign-on erlaubt oder nicht nutzt, nicht aber, wo
sie es verlangt. Eine Anmeldung mit Microsoft zählt nur für den eigenen
Tenant der Organisation und Adressen ihrer Mail-Domains. Deaktivierte
Personen können sich gar nicht anmelden.

Einstellungen, „Anmeldung“, zeigt die Google- oder Microsoft-Konten, die
mit deinem verbunden sind („Trennen“ beendet die Verbindung; die nächste
Anmeldung über den Provider verbindet es wieder), deine Passkeys, deine
Authenticator-App und deine Sitzungen.

## Single Sign-on einrichten (Admins)

Die Installation braucht pro Provider eine App-Registrierung; deren
Client-ID und Secret sind Einstellungen des Servers
(`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `MICROSOFT_CLIENT_ID`,
`MICROSOFT_CLIENT_SECRET`). Ohne sie lässt sich der Provider nicht
wählen.

**Google:** Erstelle in der Google Cloud Console unter „APIs &
Services“ eine OAuth-Client-ID vom Typ „Web application“ mit der
autorisierten Redirect-URI
`https://YOUR-BIWAK/accounts/google/login/callback/`. Der OAuth-Consent-Screen
fragt nach den Scopes `openid`, `email` und `profile`; stelle ihn auf
„External“, wenn sich auch Personen anderer Workspaces anmelden.

**Microsoft:** Registriere im Microsoft Entra Admin Center unter „App
registrations“ eine App für „Accounts in any organizational directory
(multitenant)“ mit der Web-Redirect-URI
`https://YOUR-BIWAK/accounts/microsoft/login/callback/`, und erstelle
unter „Certificates & secrets“ ein Client-Secret. Sie fragt nach
`openid`, `email`, `profile` und `User.Read`; ein Admin einer
Organisation muss vielleicht einmal für den eigenen Tenant zustimmen.

Dann, auf der Seite der Organisation:

1. Prüfe die Mail-Domains der Organisation: Anmeldungen mit Google
   zählen für ihre Workspace-Domains, die mit Microsoft für Adressen
   dieser Domains. Microsoft: Kopiere die „Directory (tenant) ID“ aus
   dem Entra Admin Center der Organisation.
2. „Anmeldung…“: Wähle den Provider und zuerst „erlaubt“, und probiere
   es aus.
3. Wechsle zu „verlangt“, wenn sich alle über den Provider anmelden
   können. Gehörst du selbst zur Organisation, melde dich zuerst über
   den Provider an.

Solange sich eine Organisation über Single Sign-on anmeldet, ändern nur
Admins ihre Mail-Domains. Nur Admins verschieben Personen aus einer
Organisation, die es verlangt. Mitarbeitende führen Organisationen
zusammen, die sich gleich anmelden; in eine, die sich strenger anmeldet,
zusammenzuführen, ist für Admins, die bestätigen, was mit den Personen
passiert, die umziehen; in eine, die sich weniger streng anmeldet,
zusammenzuführen, geht nicht: Ändere zuerst ihre Anmeldung.
