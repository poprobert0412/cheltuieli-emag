// Ecranul „Loghează-te în eMAG”: apare cât extensia așteaptă ca omul să se logheze în fila eMAG de lucru (cel mult LOGIN_WAIT_SECONDS, verificat la LOGIN_POLL_SECONDS).
// Primește: clicul pe „Deschide fila eMAG” (aduce fila de lucru în față) și pe „Oprește”. Dă înapoi: nimic; cheamă apelurile primite la init.
// Parola și codul 2FA le scrie omul, în fila eMAG: extensia nu atinge câmpurile și nu citește cookie-uri. Butonul rămâne inactiv (aria-disabled, nu disabled: focusul nu se pierde) până există fila.
// Ce NU face: nu verifică login-ul (colectare/session_check.js) și nu mută singură între ecrane (main.js).

/** Leagă butoanele ecranului de login. */
export function initLoginScreen({ onShowTab, onCancel }) {
  const { dom } = window.App;
  dom.byId('btn-show-tab').addEventListener('click', (event) => {
    if (event.currentTarget.getAttribute('aria-disabled') === 'true') return;
    onShowTab();
  });
  dom.byId('btn-login-cancel').addEventListener('click', (event) => {
    const button = event.currentTarget;
    if (button.getAttribute('aria-disabled') === 'true') return;
    button.textContent = 'Se oprește…';
    button.setAttribute('aria-disabled', 'true');
    dom.announce('Opresc analiza…');
    onCancel();
  });
}

/** La intrarea pe ecran: „Oprește” redevine activ și butonul care deschide fila așteaptă fila (inactiv) dacă `hasTab` e fals. */
export function enterLogin(hasTab) {
  const { dom } = window.App;
  const cancel = dom.byId('btn-login-cancel');
  cancel.textContent = 'Oprește';
  cancel.removeAttribute('aria-disabled');
  setShowTabEnabled(hasTab);
}

/** Activează sau dezactivează butonul „Deschide fila eMAG” (fila de lucru există sau nu încă). */
export function setShowTabEnabled(enabled) {
  const button = window.App.dom.byId('btn-show-tab');
  if (enabled) button.removeAttribute('aria-disabled');
  else button.setAttribute('aria-disabled', 'true');
}
