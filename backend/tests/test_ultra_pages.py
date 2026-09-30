import json

from app.sync.ultra_pages import convert

PDF_META = json.dumps({"linkName": "corr s1.pdf", "mimeType": "application/pdf"}).replace('"', "&quot;")
IMG_META = json.dumps({"fileName": "fig1.png", "mimeType": "image/png"}).replace('"', "&quot;")

BODY = rf"""
<div><h4>Loi exponentielle</h4>
<p>Une loi <strong>exponentielle</strong> de paramètre
<math><semantics><mrow><mi>λ</mi></mrow><annotation encoding="application/x-tex">\lambda</annotation></semantics></math>
a pour densité
<math display="block"><semantics><mrow></mrow><annotation encoding="application/x-tex">f(x) = \lambda e^{{-\lambda x}}, x_1 \ge 0</annotation></semantics></math></p>
<ul><li>sans mémoire</li><li>moyenne 1/λ</li></ul>
<p>Correction : <a href="https://esprit.blackboard.com/bbcswebdav/pid-1-dt-content-rid-23965970_1/xid-23965970_1?sig=abc"
   data-bbtype="attachment" data-bbfile="{PDF_META}">corr s1.pdf</a></p>
<a href="https://esprit.blackboard.com/sessions/9/x/fig1.png?sig=1" data-bbfile="{IMG_META}"><img src="x"></a>
</div>"""


def test_page_to_markdown_with_latex():
    note, files = convert(BODY, "A2.2 Loi exponentielle")
    assert note.startswith("# A2.2 Loi exponentielle\n")
    assert "#### Loi exponentielle" in note
    assert "**exponentielle**" in note
    assert r"$\lambda$" in note and "λ λ" not in note  # LaTeX, not duplicated MathML text
    assert r"$$f(x) = \lambda e^{-\lambda x}, x_1 \ge 0$$" in note  # underscores not escaped
    assert "- sans mémoire" in note
    assert "[corr s1.pdf]" in note and "bbcswebdav" not in note  # expiring URLs dropped


def test_latex_annotation_variants():
    for enc in ("LaTeX", "application/x-tex", "TeX"):
        body = (f'<p>Si <math><semantics><msub><mi>B</mi><mi>t</mi></msub><annotation encoding="{enc}">'
                r"B_t, t\geq 0</annotation></semantics></math> est un mouvement brownien standard, ses trajectoires sont continues.</p>")
        note, _ = convert(body, "t")
        assert r"$B_t, t\geq 0$" in note and "B t" not in note
    # no TeX annotation: fall back to the rendered symbols, without other annotations
    body = ('<p>Soit <math><semantics><mi>x</mi><annotation encoding="MathML-Content">junk</annotation>'
            "</semantics></math> une variable aléatoire réelle quelconque, définie sur l'espace probabilisé Omega.</p>")
    note, _ = convert(body, "t")
    assert "$x$" in note and "junk" not in note


def test_embedded_files_keyed_stably():
    _, files = convert(BODY, "t")
    assert [(f.name, f.key) for f in files][0] == ("corr s1.pdf", "xid-23965970_1")
    assert files[1].name == "fig1.png"
    _, again = convert(BODY.replace("sig=abc", "sig=zzz"), "t")
    assert again[0].key == files[0].key  # new signature, same file


def test_link_only_page_gives_no_note():
    note, files = convert(f'<p><a href="https://esprit.blackboard.com/bbcswebdav/xid-5_1" data-bbfile="{PDF_META}">x</a></p>', "Série 1")
    assert note is None and len(files) == 1


def test_embedded_image_links_to_its_local_copy():
    note, files = convert(BODY, "t", image_path=lambda n: f"Loi exponentielle/{n}")
    assert "![fig1.png](<Loi exponentielle/fig1.png>)" in note
    assert "[corr s1.pdf]" in note  # other files stay references
    assert files[1].name == "fig1.png"
    note, _ = convert(BODY, "t")  # nowhere to put it: a plain reference, as before
    assert "[fig1.png]" in note and "![" not in note
