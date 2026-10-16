// Cronometrul din Worker pentru colectare: primește { id, ms } și, după `ms` milisecunde, răspunde cu `id`. Atât.
// Rulează într-un Worker al paginii extensiei (creat de waiting.js), unde Chrome nu reduce cronometrele când pagina e ascunsă mai mult de 5 minute, cum face în pagina însăși.
// Ce NU face: nu ține stare, nu importă nimic și nu știe la ce folosește pauza (scraperele o cer prin waiting.js).
onmessage = (event) => {
  const { id, ms } = event.data;
  setTimeout(() => postMessage(id), ms);
};
