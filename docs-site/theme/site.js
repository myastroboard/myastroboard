// Small additions to the mdBook pages: a "Live demo" link in the top bar, and a zoom on screenshots.
// DOM built with explicit APIs only (no HTML strings).
document.addEventListener('DOMContentLoaded', () => {
    addDemoLink();
    enableScreenshotZoom();
});

function addDemoLink() {
    const buttons = document.querySelector('.right-buttons');
    if (!buttons) {
        return;
    }
    const link = document.createElement('a');
    link.className = 'mab-demo-link';
    link.href = 'https://demo.myastroboard.org/';
    link.title = 'Try the live demo';
    const icon = document.createElement('i');
    icon.className = 'bi bi-play-circle';
    icon.setAttribute('aria-hidden', 'true');
    const label = document.createElement('span');
    label.textContent = 'Live demo';
    link.append(icon, label);
    buttons.prepend(link);
}

function enableScreenshotZoom() {
    const dialog = document.createElement('dialog');
    dialog.className = 'mab-lightbox';
    const large = document.createElement('img');
    large.alt = '';
    dialog.appendChild(large);
    dialog.addEventListener('click', () => dialog.close());
    document.body.appendChild(dialog);

    // Screenshots only: not the logo, and not images that are already links.
    document.querySelectorAll('.content img').forEach((image) => {
        if (image.closest('a') || image.closest('.mab-hero')) {
            return;
        }
        image.classList.add('mab-zoomable');
        image.addEventListener('click', () => {
            large.src = image.currentSrc || image.src;
            large.alt = image.alt;
            dialog.showModal();
        });
    });
}
