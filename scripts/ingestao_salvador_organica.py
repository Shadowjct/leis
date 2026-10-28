"""Importa a Lei Orgânica de Salvador de fonte oficial, em edição identificada.

Sem checkout/clone do corpus: recupera apenas o PDF institucional da Câmara,
extrai com Poppler (texto real, sem OCR), conserva quebras de página e compara
o caminho alvo via API GitHub antes de eventualmente criar um arquivo novo.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

PDF_URL = "https://www.cms.ba.gov.br/uploads/3bdae368d1a3e255c81b7f262ba1bbf6_1709038424.pdf"
PAGE_URL = "https://www.cms.ba.gov.br/lei-organica"
EXPECTED_PDF_SHA256 = "b98d10caff6d3f9ef053b101622f6d107b4ceda01c3a0cae9f187d3ca85f9598"
DEST = "municipais/BA/salvador/lei-organica/1990/lei-organica-salvador-edicao-2024-emenda-41.md"
PAGE_COUNT = 89


def fetch_pdf():
    req = Request(PDF_URL, headers={"User-Agent": "leis-insercao-oficial/1.0", "Accept-Encoding": "identity"})
    with urlopen(req, timeout=55) as response:
        if response.status != 200 or "pdf" not in response.headers.get("Content-Type", "").lower():
            raise RuntimeError("Documento de origem indisponivel ou nao-PDF")
        data = response.read(5_000_001)
    if len(data) > 5_000_000 or data[:4] != b"%PDF":
        raise RuntimeError("PDF ausente ou maior que o limite")
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_PDF_SHA256:
        raise RuntimeError("A fonte oficial mudou: SHA256 divergente, revisao exigida")
    return data


def pdf_to_pages(source):
    with tempfile.TemporaryDirectory(prefix="lom_salvador_") as folder:
        path = Path(folder) / "original.pdf"
        path.write_bytes(source)
        p = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
            capture_output=True, timeout=100, check=True,
        )
    txt = p.stdout.decode("utf-8", "strict")
    pages = txt.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    if len(pages) != PAGE_COUNT:
        raise RuntimeError(f"Numero de paginas inesperado: {len(pages)}")
    if any(len(page.strip()) < 25 for page in pages):
        raise RuntimeError("Pagina sem texto reconhecivel; nao publicar compilacao incompleta")
    if not (re.search(r"Lei\s+Org[aâ]nica", pages[0], re.I)
            and re.search(r"Emenda\s+n[.ºo°]*\s*41", pages[0], re.I)
            and "2024" in pages[0]):
        raise RuntimeError("Capa e edicao 2024 nao conferem com a fonte oficial")
    material = "\n".join(pages[5:20])
    if not re.search(r"\bArt\.\s*1[ºo°]?\s", material, re.I):
        raise RuntimeError("Artigo 1 ausente nas primeiras paginas da lei")
    if "ATO DAS DISPOSI" not in txt.upper():
        raise RuntimeError("Disposicoes transitorias nao encontradas")
    if "ANEXO" not in "\n".join(pages[-12:]).upper():
        raise RuntimeError("Anexos finais nao encontrados")
    if sum(len(x) for x in pages) < 140_000:
        raise RuntimeError("Texto insuficiente para 89 paginas")
    return pages


def as_markdown(pages):
    body = "\n\n".join(f"## Pagina {n}\n\n{page.strip()}" for n, page in enumerate(pages, start=1)) + "\n"
    meta = {
        "titulo": "Lei Organica do Municipio de Salvador — compilacao oficial 2024",
        "tipo": "Lei Organica",
        "municipio": "Salvador",
        "uf": "BA",
        "codigo_ibge": "2927408",
        "numero": "",
        "data": "",
        "ano_norma_original": "1990",
        "versao_texto": "edicao institucional consolidada pela Camara Municipal de Salvador ate a Emenda 41; publicada em 2024; nao certifica emendas posteriores nem vigencia atual",
        "fonte": PAGE_URL,
        "fonte_texto": PDF_URL,
        "sha256_fonte": EXPECTED_PDF_SHA256,
        "sha256_texto": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "paginas_fonte": 89,
        "baixado_em": "2026-10-28",
    }
    head = "\n".join(f"{key}: {json.dumps(str(value), ensure_ascii=False)}" for key, value in meta.items())
    return "---\n" + head + "\n---\n\n# " + meta["titulo"] + "\n\n" + body


def api(method, token, payload=None):
    url = "https://api.github.com/repos/Shadowjct/leis/contents/" + quote(DEST, safe="/")
    if method == "GET":
        url += "?ref=main"
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "leis-insercao-oficial/1.0",
    }
    data = json.dumps(payload).encode() if payload is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    req = Request(url, headers=headers, data=data, method=method)
    try:
        with urlopen(req, timeout=45) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        if method == "GET" and exc.code == 404:
            return 404, None
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simular", action="store_true")
    args = parser.parse_args()
    if os.environ.get("GITHUB_REPOSITORY") != "Shadowjct/leis" or os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise SystemExit("Somente fork autorizado e branch main")
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise SystemExit("Token ausente")
    status, value = api("GET", token)
    if status == 200:
        print(json.dumps({"status": "ja_existente", "path": DEST, "sha": value["sha"]}))
        return
    if status != 404:
        raise SystemExit(f"Consulta de destino retornou {status}")
    source = fetch_pdf()
    pages = pdf_to_pages(source)
    content = as_markdown(pages)
    print(json.dumps({
        "status": "validado", "pdf_sha256": EXPECTED_PDF_SHA256,
        "pages": len(pages), "markdown_chars": len(content),
        "text_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "path": DEST, "simulacao": args.simular,
    }))
    if args.simular:
        return
    payload = {
        "message": "feat(Salvador): adicionar Lei Organica oficial consolidada ate Emenda 41",
        "content": base64.b64encode(content.encode("utf-8")).decode(),
        "branch": "main",
    }
    http, result = api("PUT", token, payload)
    if http != 201:
        raise SystemExit("Criacao nao confirmada")
    check_http, check = api("GET", token)
    if check_http != 200 or check["sha"] != result["content"]["sha"]:
        raise SystemExit("Readback nao confirmou persistencia")
    print(json.dumps({"status": "publicado", "blob": check["sha"], "commit": result["commit"]["sha"]}))


if __name__ == "__main__":
    main()
