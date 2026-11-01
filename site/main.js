// Screenshot changes are immediate: no animation is needed for this control.
const image = document.querySelector('#workspace-image');
const buttons = document.querySelectorAll('[data-screenshot]');
for (const button of buttons) {
  button.addEventListener('click', () => {
    const theme = button.dataset.screenshot;
    image.src = `assets/workspace-${theme}.png`;
    for (const choice of buttons) choice.setAttribute('aria-pressed', String(choice === button));
  });
}
