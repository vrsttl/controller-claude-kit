# A vezetői lap vázlata

Szöveges vázlat a `Vezetői összefoglaló` lapról. A 6. körben töltsd ki a válaszokból, és mutasd meg a spec vázlata alatt, még a spec megírása előtt. Számok ekkor még nincsenek: a helyükön `<érték>` marad. A tényleges számokat a próbafuttatás adja.

## Kitöltési szabályok

| Blokk | Honnan | Ha nincs kiválasztva |
|---|---|---|
| címsor | `title_hu`, mintahónap (`period.offset` szerint), `period.basis`, verzió 0.1.0 | mindig van |
| csempék | `output.executive.tiles` sorrendben, címke a katalógus megnevezése, alatta MoM és YoY | hatnál kevesebb csempénél a hely üres marad, ne találj ki mértéket |
| eltéréstábla | `output.executive.variance_rows` | a blokk kimarad |
| korosítás | csak ha `ar_aging` a mértékek között van | a blokk kimarad |
| ÁFA | csak ha `vat_by_rate` vagy `rev_net_vat` szerepel | a blokk kimarad |
| top-N | `output.executive.top_n` | a blokk kimarad, ha `rev_net_cust` nincs |
| kivételek | `exceptions[]` id és súlyosság sorrendben (critical, warn, info) | a blokk kimarad |
| lábjegyzet | három sor: forrás és alap, sztornó kezelése, futás adatai | mindig van |

A blokkok sorrendje az `output.executive.blocks` lista. Csak ASCII jelek: `+`, `-`, `|`. A csempe alatti két sor a MoM és a YoY változás; ha a mérték összehasonlítása csak `mom` vagy `avg3m`, a hiányzó sor `n.a.` vagy `3 havi átlag`.

## Sablon

```
<title_hu>  |  <ÉÉÉÉ-HH>  |  alap: <kelt|teljesites>  |  spec v0.1.0  |  ellenőrzés: <OK|FIGY>

+---------------------------+---------------------------+---------------------------+
| <csempe 1 megnevezés>     | <csempe 2 megnevezés>     | <csempe 3 megnevezés>     |
| <érték> e Ft              | <érték> e Ft              | <érték> e Ft              |
| MoM <+/-x,x %>            | MoM <+/-x,x %>            | MoM <+/-x,x %>            |
| YoY <+/-x,x %>            | YoY <+/-x,x %>            | YoY <+/-x,x %>            |
+---------------------------+---------------------------+---------------------------+
| <csempe 4 megnevezés>     | <csempe 5 megnevezés>     | <csempe 6 megnevezés>     |
| <érték>                   | <érték> nap               | <érték> db                |
| MoM <+/-x,x %>            | MoM <+/-x nap>            | MoM <+/-x db>             |
| YoY <+/-x,x %>            | YoY <+/-x nap>            | YoY <+/-x db>             |
+---------------------------+---------------------------+---------------------------+

Eltéréstábla
Mérték                  | Aktuális | Előző hó | MoM %  | Előző év | YoY %  | YTD     | YTD előző év | YTD %
<variance_rows 1. sora> | <érték>  | <érték>  | <x,x>  | <érték>  | <x,x>  | <érték> | <érték>      | <x,x>
... (legfeljebb 9 sor)

Korosított kintlévőség (fordulónap: <period.as_of>)
Nem lejárt <érték> | 1-30 nap <érték> | 31-60 nap <érték> | 61-90 nap <érték> | 90+ nap <érték> | összesen <érték>   [adatsáv]

ÁFA összesítő
Kulcs | Nettó e Ft | ÁFA e Ft | Bruttó e Ft
27 %  | <érték>    | <érték>  | <érték>
<további kulcsok a szűrő szerint>

Top <top_n> vevő
# | Vevő  | Nettó e Ft | Részarány | Halmozott | MoM    | 6 havi trend
1 | <név> | <érték>    | <x,x %>   | <x,x %>   | <nyíl> | [sparkline]
... (<top_n> sor)

Kivételek (legfeljebb 12 sor, teljes lista a Kivételek lapon)
Súly     | Szabály                       | Tétel            | Összeg
critical | <exc id> (<rule>)             | <számlaszám>     | <érték>
warn     | <exc id> (<rule>)             | <számlaszám>     | <érték>
info     | <exc id> (<rule>)             | <számlaszám>     | <érték>

Lábjegyzet
1. Forrás: szamlazz.hu Agent szinkron, <basis> alapon, díjbekérő nélkül. Ezer Ft, előjeles összegek.
2. Sztornó és helyesbítő: <storno_attribution> szerint; küszöbök: <a thresholds felsorolása>.
3. Futás: <run_ts> | spec <verzió> | kit <verzió> | ellenőrzések: <n> blokkoló hiba, <m> figyelmeztetés
```

## Példa kitöltve (alapértelmezett válaszokkal, számok nélkül)

```
Havi árbevétel és kintlévőség  |  2026-08  |  alap: kelt  |  spec v0.1.0  |  ellenőrzés: <OK|FIGY>

+---------------------------+---------------------------+---------------------------+
| Nettó árbevétel           | Bruttó árbevétel          | Kintlévőség               |
| <érték> e Ft              | <érték> e Ft              | <érték> e Ft              |
| MoM <+/-x,x %>            | MoM <+/-x,x %>            | MoM <+/-x,x %>            |
| YoY <+/-x,x %>            | YoY <+/-x,x %>            | YoY n.a.                  |
+---------------------------+---------------------------+---------------------------+
| Lejárt kintlévőség        | DSO                       | Számlák száma             |
| <érték> e Ft              | <érték> nap               | <érték> db                |
| MoM <+/-x,x %>            | MoM <+/-x nap>            | MoM <+/-x db>             |
| YoY n.a.                  | 3 havi átlag <+/-x nap>   | YoY <+/-x db>             |
+---------------------------+---------------------------+---------------------------+

Eltéréstábla: rev_net, rev_gross, inv_count, avg_inv, cash_in, coll_rate, storno_rate, cust_active, cust_new
Korosítás: 5 sáv és összesen
ÁFA: kulcsonként nettó, ÁFA, bruttó
Top 10 vevő
Kivételek: exc_overdue_big (critical), exc_overdue30 (warn), exc_taxno (warn), exc_fx (warn), exc_storno (info)
Lábjegyzet: 3 sor
```

Ezt a rövidített formát használd, ha a teljes sablon nem fér el a válaszban; a csempéket mindig teljesen írd ki.
