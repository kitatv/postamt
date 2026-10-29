const editor = document.querySelector('#editor');
if (editor) editor.innerHTML = document.querySelector('#draft-content').value;
document.querySelectorAll('[data-command]').forEach(button => button.addEventListener('click', () => {
  editor.focus();
  document.execCommand(button.dataset.command, false, button.dataset.value || null);
}));
document.querySelector('#compose-form')?.addEventListener('submit', () => { document.querySelector('#body').value = editor.innerHTML; });
