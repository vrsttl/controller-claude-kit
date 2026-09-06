# Átadó levél

Szia!

Ez a levél a készlethez tartozik, amit a laptopodra rakunk. Rövid, mert a többit a `README.md` elmondja.

## Mit raktam össze neked

Megtanítottam a Claude Code-ot, hogy a szamlazz.hu számláidból Excel riportot csináljon. A riportot egyszer leírod neki, utána minden hónapban egy paranccsal újra elkészíti, ugyanúgy, ugyanabba a mappába. Közben a számokat is ellenőrzi (tételösszeg, ÁFA-bontás, sztornók), és ha valami nem stimmel, nem ad ki rossz fájlt, hanem szól.

## Amire szükségem van tőled, mielőtt elkezdjük

- A szamlazz.hu Számla Agent kulcsod (Beállítások, Számla Agent). Ne küldd el nekem, csak legyen kéznél: a telepítőbe te írod be.
- Egy mappa a kész Excel fájloknak. Lehet OneDrive mappa is; akkor a teljes útvonala kell, ahogy a Fájlkezelő címsorában látszik.
- Később, ha a kísérőleveleket is a Claude-dal íratnád: be kell tudnod lépni a céges Google postafiókba. Ez ráér.

## Telepítés

1. Nézd át a `README.md` "Mire lesz szükséged" részét, és készítsd elő a kulcsot.
2. Csináld végig a "Telepítés" részt: egy szöveget adsz oda a Claude-nak, a többit ő és a telepítő intézi. A kulcsot a telepítő ablakába írod.
3. A végén a Claude lefuttatja az ellenőrzőt (`doctor.ps1`). Ha nem csupa OK, küldd el nekem, amit kiírt.

## Az első délután együtt

Egy délután elég rá. Sorban:

1. Letöltjük az idei számlákat egy számlaszám-előtagra (a parancs a `README.md` "Az első riport" részében van).
2. Kiíratjuk a letöltő `status` parancsával, hány számla jött le, és nincs-e hiányzó sorszám. Összevetjük azzal, amit a szamlazz.hu mutat.
3. Elkészítjük az első riportot a `/report-new` paranccsal, és együtt megnézzük a próbaváltozatot.

## Egy kérdés a szamlazz.hu-nak, mielőtt egy egész évet letöltenénk

Azt feltételezzük, hogy a számlák lekérdezése az Agent kulccsal ingyenes, és díjat csak a kiállított számlák után számolnak. Ezt írásban kérdezd meg tőlük, mielőtt egy egész évet letöltünk. Ezt küldd el a céges címről a szamlazz.hu ügyfélszolgálatának:

> Tárgy: Számla Agent lekérdezés díja
> Tisztelt Ügyfélszolgálat! A Számla Agent felületet kizárólag a saját kimenő számláink lekérdezésére használnánk (xmlszamlaxml művelet, számlaszám alapján, havonta egyszer), számla kiállítása nélkül.
> Kérem, erősítsék meg, hogy ezeknek a lekérdezéseknek nincs külön díja, és nem számítanak bele a csomag bizonylatkeretébe. Ha van díj vagy korlát, kérem, írják meg a mértékét.
> Köszönettel: <név, cég, szamlazz.hu felhasználónév>

Amíg nincs válasz, csak kis adagban töltünk le; ezt az első délutánon együtt csináljuk.

## Ha elakadsz

Futtasd le az ellenőrzőt (a parancs a `README.md` "Ha valami nem megy" részében van), és küldd el nekem, amit kiírt, egy-két mondattal arról, mit csináltál, és mi történt. Kulcsot, jelszót soha ne másolj a levélbe; az ellenőrző úgyis csak azt mutatja, hogy megvan-e.
