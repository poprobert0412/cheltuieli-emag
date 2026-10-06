/* app-api.js — clientul aplicației locale: cheia de acces și toate cererile către /api/*.
 * Primește: fragmentul adresei (#t=<cheie>), pus de program când deschide pagina. Dă înapoi, ca window.App.api, funcții
 * care întorc Promise: hello, getState, startRun, cancelRun, listRuns, getAnalysis, getFile (Blob), deleteSession, shutdown,
 * getUpdate (versiunea nouă și starea actualizării), applyUpdate („Actualizează acum”).
 * Cheia: citită o singură dată, scoasă din adresă cu history.replaceState și ținută DOAR în memoria acestui fișier;
 * nu ajunge în localStorage, sessionStorage, cookie, în vreo adresă cerută sau în linkuri. Pleacă doar în antetul X-App-Token.
 * Singurul loc din interfață care face cereri de rețea, și doar spre căi relative /api/... (aceeași origine = aplicația
 * de pe calculatorul tău). Erorile devin ApiError cu `kind`: 'network' (nu răspunde), 'auth' (cheie lipsă sau refuzată),
 * 'http' (aplicația a răspuns cu o eroare, mesajul ei în română e în `message`), 'parse', 'client'.
 * Ce NU face: nu decide ce se afișează la o eroare (asta e treaba ecranelor) și nu reîncearcă singur.
 */
(function (root) {
  'use strict';

  const App = (root.App = root.App || {});

  const TOKEN_HEADER = 'X-App-Token';
  // Cheia e secrets.token_urlsafe(32): 43 de caractere din [A-Za-z0-9_-]. Acceptăm 16–128, ca să nu depindă de lungimea exactă,
  // dar nimic în afara acestui alfabet: o valoare ciudată din adresă nu are voie să ajungă într-un antet.
  const TOKEN_PATTERN = /^[A-Za-z0-9_-]{16,128}$/;
  const HASH_PATTERN = /^#t=([^&]*)$/;
  // Numele unui folder de rulare (ex. 2026-10-05_11-07-55 sau cu sufixul _demo): litere, cifre, „-” și „_”. Altceva nu devine adresă.
  const RUN_ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
  const FILE_NAMES = ['raport.html', 'produse.csv', 'istoric_preturi.csv', 'rezumat.txt']; // lista albă a aplicației
  // Aplicația locală răspunde în milisecunde; peste 8 s o socotim căzută (o cerere agățată nu are voie să țină pagina în așteptare).
  const FAST_TIMEOUT_MS = 8000;
  // Un raport mare sau un fișier descărcat poate dura mai mult, dar tot are o limită.
  const SLOW_TIMEOUT_MS = 60000;

  let token = null;

  /** Eroare de API: `kind` spune de unde vine, `status` e codul HTTP (0 dacă n-a existat răspuns), `code` și `message` vin de la aplicație. */
  function ApiError(kind, status, code, message) {
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.code = code;
    this.message = message;
  }
  ApiError.prototype = Object.create(Error.prototype);
  ApiError.prototype.constructor = ApiError;

  /** Citește cheia din #t=..., scoate fragmentul din adresă și întoarce true dacă există o cheie validă. */
  function init() {
    const match = HASH_PATTERN.exec(root.location.hash);
    if (match) {
      token = TOKEN_PATTERN.test(match[1]) ? match[1] : null;
      try {
        root.history.replaceState(null, '', root.location.pathname + root.location.search);
      } catch (e) { /* fără History API cheia ar rămâne în adresă: nu avem ce face, dar nici nu o folosim în altă parte */ }
    }
    return token !== null;
  }

  /** True dacă pagina are o cheie validă în memorie. */
  function hasToken() {
    return token !== null;
  }

  /** Mesajul în română pentru un răspuns de eroare fără corp înțeles. */
  function fallbackMessage(status) {
    if (status === 401 || status === 403) return 'Aplicația a refuzat cererea paginii (cheia de acces lipsește sau nu mai e bună).';
    if (status === 404) return 'Aplicația nu are ce a cerut pagina (fișier sau rulare inexistentă).';
    if (status === 409) return 'Aplicația e ocupată: rulează deja o analiză.';
    return 'Aplicația a răspuns cu eroarea ' + status + '.';
  }

  /** Transformă un răspuns de eroare ({"error": {"code", "message"}}) într-un ApiError. */
  function httpError(status, bodyText) {
    let code = '';
    let message = '';
    try {
      const parsed = JSON.parse(bodyText);
      if (parsed && parsed.error && typeof parsed.error === 'object') {
        code = typeof parsed.error.code === 'string' ? parsed.error.code : '';
        message = typeof parsed.error.message === 'string' ? parsed.error.message : '';
      }
    } catch (e) { /* corp care nu e JSON: rămâne mesajul de rezervă */ }
    return new ApiError(status === 401 ? 'auth' : 'http', status, code, message || fallbackMessage(status));
  }

  /** Citește corpul unui răspuns reușit ca JSON (corp gol = null). */
  function readJson(response) {
    return response.text().then(function (text) {
      if (!text) return null;
      try {
        return JSON.parse(text);
      } catch (e) {
        throw new ApiError('parse', response.status, 'bad_json', 'Aplicația a trimis un răspuns pe care pagina nu-l poate citi.');
      }
    });
  }

  /** O cerere către aplicație cu cheia în antet. options: body (obiect, trimis ca JSON), blob (true = răspunsul e fișier), timeoutMs. */
  function request(method, path, options) {
    const opts = options || {};
    if (token === null) return Promise.reject(new ApiError('auth', 0, 'no_token', 'Pagina nu are cheia de acces la aplicație.'));
    const headers = {};
    headers[TOKEN_HEADER] = token;
    const fetchOptions = { method: method, headers: headers, cache: 'no-store', credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer' };
    if (opts.body !== undefined) {
      headers['Content-Type'] = 'application/json';
      fetchOptions.body = JSON.stringify(opts.body);
    }
    let timer = null;
    if (typeof root.AbortController === 'function') {
      const controller = new root.AbortController();
      fetchOptions.signal = controller.signal;
      timer = root.setTimeout(function () { controller.abort(); }, opts.timeoutMs || FAST_TIMEOUT_MS);
    }
    const done = function () { if (timer !== null) root.clearTimeout(timer); };
    return root.fetch(path, fetchOptions).then(function (response) {
      if (!response.ok) {
        return response.text().then(function (text) { throw httpError(response.status, text); });
      }
      return opts.blob ? response.blob() : readJson(response);
    }).then(function (value) {
      done();
      return value;
    }, function (error) {
      done();
      if (error instanceof ApiError) throw error;
      throw new ApiError('network', 0, 'network', 'Nu pot vorbi cu aplicația de pe calculator.');
    });
  }

  /** Promise respins cu o eroare de client (ceva ce pagina nu are voie să ceară). */
  function refuse(message) {
    return Promise.reject(new ApiError('client', 0, 'bad_request', message));
  }

  /** Verifică numele unui folder de rulare înainte să ajungă într-o adresă. */
  function validRunId(id) {
    return typeof id === 'string' && RUN_ID_PATTERN.test(id);
  }

  function hello() { return request('GET', '/api/hello'); }
  function getState() { return request('GET', '/api/state'); }
  function listRuns() { return request('GET', '/api/runs'); }
  function cancelRun() { return request('POST', '/api/runs/current/cancel', { body: {} }); }
  function shutdown() { return request('POST', '/api/shutdown', { body: {} }); }
  // Cuvântul de confirmare e mereu „DA”: ecranul acceptă și „da”, dar aplicația cere exact „DA” (ca --sterge-sesiunea).
  function deleteSession() { return request('POST', '/api/session/delete', { body: { confirm: 'DA' } }); }
  function getUpdate() { return request('GET', '/api/update'); }
  function applyUpdate() { return request('POST', '/api/update/apply', { body: {} }); }

  /** Pornește o rulare: mode 'real' sau 'demo'; thresholdLei doar dacă omul a schimbat pragul (altfel aplicația folosește implicitul ei). */
  function startRun(mode, thresholdLei) {
    if (mode !== 'real' && mode !== 'demo') return refuse('Modul de rulare nu e valid.');
    const body = { mode: mode };
    if (typeof thresholdLei === 'number') body.threshold_lei = thresholdLei;
    return request('POST', '/api/runs', { body: body });
  }

  /** Conținutul analiza.json al unei rulări (aplicația îi limitează mărimea). */
  function getAnalysis(id) {
    if (!validRunId(id)) return refuse('Numele rulării nu e valid.');
    return request('GET', '/api/runs/' + id + '/analysis', { timeoutMs: SLOW_TIMEOUT_MS });
  }

  /** Un fișier al rulării (doar din lista albă), ca Blob: se descarcă cu cheia în antet, nu printr-un link simplu. */
  function getFile(id, name) {
    if (!validRunId(id)) return refuse('Numele rulării nu e valid.');
    if (FILE_NAMES.indexOf(name) < 0) return refuse('Fișierul cerut nu e pe lista fișierelor care se pot descărca.');
    return request('GET', '/api/runs/' + id + '/files/' + name, { blob: true, timeoutMs: SLOW_TIMEOUT_MS });
  }

  App.api = {
    init: init,
    hasToken: hasToken,
    hello: hello,
    getState: getState,
    startRun: startRun,
    cancelRun: cancelRun,
    listRuns: listRuns,
    getAnalysis: getAnalysis,
    getFile: getFile,
    deleteSession: deleteSession,
    shutdown: shutdown,
    getUpdate: getUpdate,
    applyUpdate: applyUpdate,
    ApiError: ApiError,
    FILE_NAMES: FILE_NAMES.slice(),
  };
})(window);
