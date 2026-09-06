# controller-claude-kit: havi riportok a szamlazz.hu számlákból

## Mi ez

Minden hónapban Excel riportokat kell csinálnod a szamlazz.hu-ban kiállított számlákból. Ez a készlet (egy mappa szkriptekkel és beállításokkal) megtanítja a Claude Code-ot, hogy ezeket a riportokat elkészítse helyetted. A riportot egyszer leírod neki: a Claude kérdez, te válaszolsz. Utána bármelyik hónapban egyetlen paranccsal újra elkészítteted, és a kész Excelt kapod vissza, ugyanolyan formában, mint legutóbb. Semmi nem fut magától: a riportot mindig te indítod el, akkor, amikor kell.

## Mire lesz szükséged

- A szamlazz.hu Számla Agent kulcsod. Ez egy hosszú betű- és számsor; ezzel tudja a készlet letölteni a számláidat a szamlazz.hu-ból. A szamlazz.hu-ban a Beállítások, azon belül a Számla Agent menüpontban találod. Legyen kéznél, a telepítő kérni fogja.
- Egy Windows 11 laptop, amire telepíthetsz programokat.
- Claude Pro vagy Max előfizetés, és ezen a laptopon már beléptél a Claude Code-ba. Ha már használtad, ez megvan.
- Ha akarod: egy OneDrive mappa a kész Excel fájloknak. Ha nincs, a készlet a saját mappájába teszi őket.

Gmail és NAV kezdetben nem kell. A Gmail később arra jó, hogy a Claude levélpiszkozatot írjon a riport mellé. A NAV Online Számla később arra jó, hogy a számlákat a NAV adataival is össze tudd vetni. Mindkettő beállítását a `docs/HALADO.md` írja le.

## Telepítés

Nyiss egy PowerShell ablakot (a Start menüben írd be: PowerShell, és nyomj Entert), írd be, hogy `claude`, és amikor a Claude jelentkezik, másold be neki ezt a szöveget egyben. A Claude letölti a készletet, megmutatja, mit fog telepíteni, majd egy külön ablakban elindítja a telepítőt. Közben többször rákérdez, futtathat-e egy-egy parancsot: mondj igent.

```
Segíts feltelepíteni egy Claude Code készletet. Ezeket csináld, sorban:
1. Nézd meg, van-e Git a gépen. Ha nincs, telepítsd fel winget-tel.
2. Töltsd le (klónozd) a https://github.com/vrsttl/controller-claude-kit.git tárolót a felhasználói mappámba (ahol a Dokumentumok és a Letöltések mappa is van), claude-kit néven. Ha már ott van, hagyd békén.
3. A claude-kit mappában futtasd az install.ps1 szkriptet ezekkel: -WhatIf -SkipGmail -SkipNav. Ez csak megmutatja a tervet, nem változtat semmit. Foglald össze magyarul, mit fog csinálni.
4. Utána indítsd el az install.bat fájlt a -SkipGmail -SkipNav paraméterekkel egy külön ablakban, Start-Process-szel, mert a telepítő kérdéseket tesz fel, és azokra én válaszolok abban az ablakban.
5. Állj meg, és várd meg, amíg szólok, hogy a telepítő ablakában megjelent a "Kész" felirat.
6. Ezután futtasd le a claude-kit mappából a doctor.ps1 szkriptet, és magyarázd el magyarul, sorról sorra, mit ír ki.
A Számla Agent kulcsot soha ne kérd tőlem itt a chatben. Azt csak a telepítő ablakába írom be.
```

A telepítő ablaka egyetlen dolgot kérdez: megadod-e most a szamlazz.hu Agent kulcsot. Írj be egy i betűt, nyomj Entert, aztán illeszd be a kulcsot, és megint Enter. A kulcs beírás közben nem látszik a képernyőn, ez így van rendjén. Mást nem kérdez. Közben feltelepít néhány programot (Git, Python, Node), és a Windows rákérdezhet, hogy engedélyezed-e: engedélyezd. Az egész nagyjából negyedóra, a net sebességétől függően.

Akkor sikerült, ha az ellenőrző (`doctor.ps1`) listájában szinte minden sor elején OK áll. A Gmail és a NAV sorok most még nem OK, ez rendben van, hiszen kihagytuk őket. Ha máshol is felkiáltójel vagy X van, másold ki az egészet, és küldd el nekem.

## Az első riport

Előbb egyszer le kell tölteni az idei számlákat. Nyiss egy új PowerShell ablakot (a telepítés után mindenképp újat), és másold be ezt a két sort; az SZLA helyére a saját számlaszámaid elejét írd (ha a számlaszám például SZLA-2026-14, akkor SZLA). Pár perc alatt kiírja, hány számlát töltött le.

```
cd ~/Riportok
uv run scripts/szamlazz_sync.py pull --agent-only --prefix SZLA --year 2026
```

Ez egyszer letölti az idei számlákat; később már csak az újakat kéri le. Ha többféle előtaggal számlázol, futtasd le mindegyikre.

Ezután ugyanabban az ablakban írd be, hogy `claude`, majd a Claude-nak azt, hogy `/report-new`. A Claude nagyjából hét dolgot kérdez meg: miről szóljon a riport, melyik hónapról, mely vevőkről, milyen számok kelljenek bele, mikor szóljon figyelmeztetés (például mekkora kintlévőség felett), és hová kerüljön a kész Excel. Minden kérdéshez ajánl egy választ, azt is elfogadhatod. A végén elkészíti a riport próbaváltozatát az előző hónapra, és megmutatja. Ha jó, mondj igent. Ettől kezdve a riport megvan, és bármikor újra lefuttathatod.

## Minden hónapban

1. Nyisd meg a Claude Code-ot a Riportok mappában. PowerShell ablakban ez a két sor; a második után a Claude jelentkezik.

```
cd ~/Riportok
claude
```

2. Írd be: `/report-run` és utána a riport neve (a nevet a `/report-list` mutatja). A Claude lekéri az új számlákat, elkészíti a riportot, ellenőrzi a számokat, és a kész fájlt a megadott mappába teszi.
3. Nyisd meg az Excelt, amit visszaad. A Claude általában meg is nyitja neked.

Ha közben változott valami (új vevő, más figyelmeztetési határ), írd be a `/report-edit` parancsot és a riport nevét: ez csak arról kérdez, ami változott.

## Ha valami nem megy

Először futtasd le az ellenőrzőt. PowerShell ablakban ez az egy sor; egy listát ír ki, minden sor elején OK, felkiáltójel vagy X, és a hibás sorok alatt egy tanács.

```
powershell -ExecutionPolicy Bypass -File "$HOME/claude-kit/doctor.ps1"
```

Jelöld ki, amit kiírt, másold ki, és küldd el nekem egy-két mondattal: mit csináltál, mi történt.

Három gyakori eset:

- Nyitva volt az Excel, és a kész fájl `.pending` végződéssel jött létre a riport mellett. Zárd be az Excelt, és futtasd újra a riportot, vagy nevezd át a fájlt a rendes névre.
- A Claude megkérdezi, futtathat-e egy parancsot. A készlet saját szkriptjeire (a Riportok mappában lévőkre) mondj igent. Ha nem érted, mit kér, mondj nemet, attól nem romlik el semmi.
- A Claude azt írja, hiányzik az Agent kulcs. Ismételd meg a Telepítés lépést ugyanazzal a szöveggel: a telepítő a kész lépéseket átugorja, és csak a kulcsot kéri.

## Mit nem csinál

- Nem küld e-mailt magától. Ha egyszer beállítod a Gmailt, akkor is csak piszkozatot ír; elküldeni neked kell.
- Nem változtat semmit a szamlazz.hu-ban, csak olvassa a számlákat.
- Nem tölt fel semmit sehová. A kész fájl a laptopodon marad, vagy abban az OneDrive mappában, amit te választottál.
- Nem fut magától. Csak akkor csinál bármit, amikor te elindítod.

## Haladóknak

Minden, ami innen kimaradt (Gmail és NAV beállítása, a telepítő kapcsolói, a letöltő parancsok, a készlet frissítése és eltávolítása, a szamlazz.hu díjkérdés), a `docs/HALADO.md` fájlban van.
