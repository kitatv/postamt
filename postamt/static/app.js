const editor = document.querySelector('#editor');
if (editor) editor.innerHTML = document.querySelector('#draft-content').value;
document.querySelectorAll('[data-command]').forEach(button => button.addEventListener('click', () => {
  editor.focus();
  document.execCommand(button.dataset.command, false, button.dataset.value || null);
}));
document.querySelector('#compose-form')?.addEventListener('submit', () => { document.querySelector('#body').value = editor.innerHTML; });

// Incremental display: keep existing rows and append the next batch by GUID.
let loadingMore = false;
document.addEventListener('click', async event => {
  const link = event.target.closest('[data-load-more]');
  if (!link || event.ctrlKey || event.metaKey || event.shiftKey) return;
  event.preventDefault();
  if (loadingMore) return;
  loadingMore = true;
  const original = link.textContent;
  link.textContent = 'Laden …';
  try {
    const response = await fetch(link.href);
    if (!response.ok || response.redirected) throw new Error('Laden fehlgeschlagen');
    const page = new DOMParser().parseFromString(await response.text(), 'text/html');
    const rows = document.querySelector('#mail-rows');
    const known = new Set([...rows.querySelectorAll('[data-guid]')].map(row => row.dataset.guid));
    for (const row of page.querySelectorAll('#mail-rows [data-guid]')) {
      if (!known.has(row.dataset.guid)) rows.append(row);
    }
    document.querySelector('#message-count').textContent = `${rows.querySelectorAll('[data-guid]').length} von ${page.querySelector('#message-count').textContent.split(' von ')[1]}`;
    document.querySelector('#load-more').replaceChildren(...page.querySelector('#load-more').childNodes);
    const url = new URL(link.href);
    history.replaceState(null, '', url);
    // Retain the cumulative list when selecting a message.
    rows.querySelectorAll('a[data-guid]').forEach(row => {
      const destination = new URL(row.href);
      destination.searchParams.set('loaded', url.searchParams.get('loaded'));
      row.href = destination;
    });
  } catch (_) {
    link.textContent = 'Erneut versuchen →';
  } finally {
    loadingMore = false;
  }
});

const workspace = document.querySelector('[data-refresh-seconds]');
if (workspace && Number(workspace.dataset.refreshSeconds) > 0) {
  const delay = Number(workspace.dataset.refreshSeconds) * 1000;
  const status = document.querySelector('#refresh-status');
  const refresh = async () => {
    try {
      if (loadingMore) return;
      status.textContent = 'Neue E-Mails werden geprüft …';
      const response = await fetch(workspace.dataset.refreshUrl, {
        method: 'POST', headers: {'X-CSRFToken': workspace.dataset.csrf, 'Accept': 'application/json'}
      });
      if (!response.ok || response.redirected) throw new Error('Abruf fehlgeschlagen');
      const result = await response.json();
      if (result.imported > 0) { location.reload(); return; }
      status.textContent = 'Auf dem neuesten Stand.';
    } catch (_) {
      status.textContent = 'Automatischer Abruf fehlgeschlagen. Konten prüfen.';
    } finally {
      window.setTimeout(refresh, delay);
    }
  };
  window.setTimeout(refresh, delay);
}
