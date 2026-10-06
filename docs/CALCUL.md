# Cum se calculează

Ce citește programul, ce fișiere scrie și cum ajunge la fiecare cifră din raport. Pe scurt, în [README](../README.md).

## Ce primești

Programul deschide o fereastră de browser, te loghezi tu în eMAG, iar el citește istoricul de comenzi și de retururi (paginile pe care le vezi și tu). Apoi calculează și scrie:

- **cât ai cheltuit efectiv**: banii plătiți pe comenzile livrate sau ridicate („Total plătit”, după vouchere și reduceri, cu transportul și taxele), minus banii primiți înapoi la retururi; anulatele și ce n-a ajuns încă apar separat;
- **pe ce s-au dus banii**: pe categorii (reguli pe care le poți edita), pe ani, pe vânzători, plus cele mai valoroase produse păstrate; transportul și taxele, retururile cu voucher și diferențele la restituiri au rândurile lor, ca toate să se adune exact la cât ai cheltuit;
- **achiziții mari**: produsele cu prețul de listă pe bucată peste un prag (implicit 500 Lei, îl poți schimba);
- **prețuri la același produs**: dacă ai cumpărat același model de mai multe ori, vezi cum s-a schimbat prețul („mai scump” sau „mai ieftin” cu X Lei). Culorile se ignoră („alb” și „negru” sunt același produs), capacitatea sau dimensiunea nu (128GB și 256GB sunt produse diferite). Prețul include promoții și e dinainte de vouchere, iar vânzătorii pot fi diferiți: diferența arată o schimbare de preț, nu o pierdere sau un câștig;
- **avertismente cu detalii**: grupe care se deschid, cu explicația, efectul asupra cifrelor și linkuri către comenzile de pe eMAG, ca să verifici repede ce nu s-a legat.

Fișierele (într-un folder nou la fiecare rulare, în `iesiri/`): `raport.html` (un singur fișier, se deschide fără internet), `produse.csv` și `istoric_preturi.csv` (pentru Excel), `rezumat.txt` (cifrele principale, în text) și `analiza.json` (rezultatul complet, din care se desenează raportul).

## Definițiile

Toate sumele sunt bani plătiți: fiecare produs primește partea lui din reducerile comenzii (vouchere, card cadou), împărțite proporțional cu prețul, cum restituie și eMAG la retur.

- **Comandat** = valoarea tuturor produselor din comenzi, după reduceri. Nu intră blocurile cu statusul „Plata acceptata” (de exemplu asigurările plătite fără livrare).
- **Anulat** = produse din blocuri „Livrare anulată” fără retur finalizat.
- **Returnat** = retururi cu pasul „Restituire sumă”. Retururile vechi de la vânzători din marketplace apar în eMAG ca „Livrare anulată”; dacă există retur finalizat, se numără ca returnat, nu ca anulare. Se scad banii primiți înapoi: suma restituită afișată sau, dacă lipsește, partea plătită a produsului (estimare, numărată la cifrele de control). Un retur cu voucher sau sold eMAG nu se scade: voucherul scade deja „Total plătit” al comenzii în care îl folosești. Modurile de restituire stau în `config/restituiri.json`.
- **În curs** = produse al căror bloc arată un status de dinainte de livrare (plasată, predată curierului, în drum…). Programul nu verifică plata.
- **Transport și taxe** = livrarea, serviciile și taxele comenzilor livrate. Nu se împart pe produse: au rândul lor la categorii.
- **Plătit efectiv** = „Total plătit” al comenzilor livrate sau ridicate − banii primiți înapoi la retururi (plus, la vânzătorii din marketplace, produsele returnate cu voucher sau sold dintr-un bloc pe care eMAG îl arată „Livrare anulată”). Pe rânduri, la categorii: produsele păstrate, după reduceri, + „Transport și taxe” + „Retururi cu voucher sau sold eMAG” + „Diferențe la restituiri” (partea plătită a produselor returnate minus suma restituită afișată); un rând apare doar dacă are o sumă. Asta e „cât ai cheltuit”. O comandă fără „Total plătit” afișat se calculează din componentele ei (produse, reduceri, transport, taxe).
- **Prețul de listă** rămâne doar la pragul pentru „achiziție mare” și la „Prețuri la același produs”: sunt comparații de preț, nu de bani plătiți. Un status pe care programul nu-l recunoaște nu e numărat niciodată ca livrat: apare ca avertisment.
