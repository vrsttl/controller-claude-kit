# E-mail: a gmail-utility ügynök és a /draft-email

A levelezést a `gmail` MCP-n keresztül a `gmail-utility` ügynök kezeli; a `/draft-email` skill hívja. Két fiók: a céges Workspace postafiók és a személyes Gmail. A teljes szabálykönyv: `~/.claude/agents/gmail-utility.md`.

## Szabályok röviden

- Mindig piszkozat. Küldés (`send_email`) csak akkor, ha a felhasználó az adott levélre szó szerint azt írta: "küldd el". A "mehet" és az "oké" nem küldés.
- Soha ne állítsd, hogy egy levél elment: piszkozat készült, azonosítóval.
- Fiókválasztás téma szerint. szamlazz.hu, NAV, ügyfél, kolléga, vezető, havi riport, könyvelő: céges; minden más: személyes. Az ügynök a `list_accounts` hívással azonosít, és a válaszban kiírja, melyik fiókban dolgozott. Alapértelmezett fiókot kérés nélkül nem vált.
- Válasznál a szál előzménye megmarad. A levél HTML, markdown nélkül, gondolatjel nélkül.
- Nyelv a címzett domainje szerint: `.hu` magyar, minden más angol; a felhasználó felülírhatja.
- Aláírás a `~/.claude/email-signatures.json` fájlból (kulcs: a fiók e-mail címe, érték: HTML részlet); ha hiányzik, csak a név, és a válasz jelzi.
- Törlés, címkézés, szűrő és tömeges művelet csak kimondott kérésre; tömegesnél előbb darabszám és megerősítés.
- Mellékletet az MCP nem tud csatolni: a levél végén a fájl útvonala áll, a felhasználó csatolja kézzel.

## Recept A: számlaértesítők begyűjtése

Kérés: "töltsd le a számlaértesítőket", opcionálisan hónappal.

1. `switch_account` a céges fiókra.
2. `search_emails`: `from:@szamlazz.hu has:attachment newer_than:35d` (adott hónapra `after:` és `before:` szűréssel).
3. Minden találatnál `read_email`, a PDF mellékletekre `download_attachment` ide: `~/Riportok/data/drops/pdf/<ÉÉÉÉ-HH>/`, a hónap a levél dátumából; fájlnév az eredeti, ütközésnél a levél dátuma kerül elé.
4. Nincs törlés, címkézés, olvasottra állítás.
5. Jelentés: hány levél, hány PDF, hová, mi maradt ki.

Ez PDF-archívum a kézi visszakereséshez. A riportok forrása a szinkron (`szamlazz_sync.py`), nem ezek a fájlok.

## Recept B: a havi riport kísérőlevele

A `/report-run` a leszállítás után felajánlja; a `build.py --json` kimenetét és a címzetteket adja át az ügynöknek.

| Elem | Tartalom |
|---|---|
| fiók | céges |
| tárgy | `Havi riport <ÉÉÉÉ-HH>: <title_hu>` |
| törzs | egy mondat (időszak, a riport neve), majd 3 és 5 közötti pont a JSON kiemeléseiből: érték, MoM és YoY változás, küszöbsértés vagy kivétel |
| zárás | "A riportot csatolom." és a fájl útvonala (vagy OneDrive link, ha van) |
| számok | csak ami a JSON-ban szerepel, magyar írásmóddal (1 234 e Ft; 12,5 %) |

Hiányzó adatot az ügynök nem pótol: a pont kimarad.

## A 7 napos token-figyelmeztetés

Minden Gmail-fiókhoz egy Google Cloud OAuth-ügyfél tartozik. Ha a hozzájárulási képernyő (OAuth consent screen) Tesztelés (Testing) állapotban maradt, a Google 7 nap után érvényteleníti a tokent, és a `gmail` MCP belépési hibát ad. Megoldás: a Google Cloud Console-ban a képernyő közzététele éles (In production) állapotba; Workspace-fióknál a Belső (Internal) típus eleve nem jár le. Utána a fiók újra hozzáadása:

```
node "%USERPROFILE%\Gmail-MCP-Server\dist\index.js" auth --keys <oauth-client.json>
```

A `doctor.ps1` figyelmeztet, ha a token 5 napnál régebbi. Belépési hibánál ezt nézd meg először, mielőtt az MCP-t vagy a fiókot hibáztatnád. A `GMAIL_CREDENTIALS_PATH` környezeti változót soha ne állítsd be: a fiókokat a `~/.gmail-mcp/accounts/<email>/` mappák kezelik.
