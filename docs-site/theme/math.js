// Render the formulas the build script left as <span|div data-tex="..."> with the bundled KaTeX.
// Formulas are kept out of Markdown at build time so that "_", "\," or "\\" inside them are not
// read as emphasis or escapes.
document.addEventListener('DOMContentLoaded', () => {
    if (typeof katex === 'undefined') {
        return;
    }
    document.querySelectorAll('[data-tex]').forEach((element) => {
        katex.render(element.getAttribute('data-tex'), element, {
            displayMode: element.classList.contains('math-display'),
            throwOnError: false,
            strict: 'ignore',
        });
    });
});
