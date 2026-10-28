"""Ingestao pontual de lei estadual da Bahia a partir de PDF do governo BA.

No checkout do corpus. Hash do PDF original, 11 paginas, artigos 1..33,
assinatura, identidade e persistencia independente pela API Contents.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
import os

REPO = "Shadowjct/leis"
URL = ("https://www.ba.gov.br/secti/sites/site-secti/files/migracao_2024/"
       "arquivos/File/DECRETOS_E_LEIS/LEI11174.pdf")
SHA256_PDF = "02dbdc7b019f5fe8f4f0febc3f980086e272179be8dcafe87e093ebc1a1d4320"
NUMBER = 11174
YEAR_PATH = "estaduais/BA/leis-ordinarias/2008"
PATH = YEAR_PATH + "/lei-ordinaria-11174-2008-secti-pdf.md"
TITLE = "Lei Ordinária nº 11.174, de 09/12/2008"
EMENTA = ("Dispõe sobre incentivos à inovação e à pesquisa científica e "
          "tecnológica em ambiente produtivo no Estado da Bahia e dá outras providências.")


def source_pdf():
    req = Request(URL, headers={
        "User-Agent": "leis-ba-secti/1.0",
        "Accept-Encoding": "identity",
    })
    with urlopen(req, timeout=40) as response:
        data = response.read(1_000_001)
        if response.status != 200:
            raise RuntimeError("Falha na fonte oficial")
    if not data.startswith(b"%PDF") or len(data) > 1_000_000:
        raise RuntimeError("Fonte nao e PDF de tamanho esperado")
    if hashlib.sha256(data).hexdigest() != SHA256_PDF:
        raise RuntimeError("PDF oficial ALTERADO: abortar e inspecionar nova versao")
    return data


def extract(data):
    with tempfile.TemporaryDirectory(prefix="ba_11174_") as temporary:
        path = Path(temporary) / "source.pdf"
        path.write_bytes(data)
        page_info = subprocess.run(["pdfinfo", str(path)], capture_output=True,
                                   text=True, check=True, timeout=25).stdout
        m = re.search(r"(?m)^Pages:\s+(\d+)", page_info)
        if not m or int(m.group(1)) != 11:
            raise RuntimeError("Paginas do original diferentes de 11")
        proc = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8",
                               str(path), "-"],
                              capture_output=True, check=True, timeout=75)
    text = proc.stdout.decode("utf-8", "strict")
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    if len(pages) != 11:
        raise RuntimeError("Extracao de paginas incompleta")
    if any(len(page.strip()) < 180 for page in pages):
        raise RuntimeError("Pagina sem texto suficiente")
    first = pages[0].upper()
    last = pages[-1].upper()
    if not re.search(r"LEI\s+N[º°O]?\s*11[.]174\b", first):
        raise RuntimeError("Epigrafe/numero divergentes")
    if not re.search(r"09\s+DE\s+DEZEMBRO\s+DE\s+2008", first):
        raise RuntimeError("Data divergente")
    if "O GOVERNADOR DO ESTADO DA BAHIA" not in first:
        raise RuntimeError("Ente ou autoridade divergente")
    if "JAQUES WAGNER" not in last or "Art. 33" not in last:
        raise RuntimeError("Encerramento ou assinatura divergentes")
    joined = "\n".join(pages)
    article_numbers = [int(value) for value in re.findall(
        r"(?m)^\s*Art\.\s*(\d{1,2})(?:[º°]|\s|[.\-])", joined)]
    if article_numbers != list(range(1, 34)):
        raise RuntimeError("Artigos 1..33 incompletos ou repetidos: "
                           + repr(article_numbers))
    if len(joined) < 17000:
        raise RuntimeError("Conteudo do texto truncado")
    return pages


def build_document(pages):
    body = "\n\n".join(
        f"## Página {i}\n\n{page.strip()}"
        for i, page in enumerate(pages, start=1)
    ) + "\n"
    meta = {
        "titulo": TITLE,
        "uf": "BA",
        "tipo": "Lei Ordinária",
        "numero": str(NUMBER),
        "data": "2008-12-09",
        "ementa": EMENTA,
        "orgao": "Governo do Estado da Bahia / SECTI",
        "publicacao": "Diário Oficial do Estado da Bahia, 10/12/2008",
        "versao_texto": ("publicação original em PDF oficial (11 páginas); "
                        "não é compilação e não certifica a vigência atual"),
        "fonte": URL,
        "fonte_institucional": "https://www.ba.gov.br/secti/leis-e-decretos-da-secti",
        "sha256_fonte": SHA256_PDF,
        "sha256_texto_extraido": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "paginas_fonte": "11",
        "artigos_identificados": "33",
    }
    header = "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}"
        for key, value in meta.items()
    )
    return "---\n" + header + "\n---\n\n# " + TITLE + "\n\n" + body


def github(method, path, token, body=None):
    api_url = ("https://api.github.com/repos/" + REPO
               + "/contents/" + quote(path, safe="/"))
    if method == "GET":
        api_url += "?ref=main"
    headers = {
        "User-Agent": "leis-ba-secti/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": "Bearer " + token,
    }
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    if payload is not None:
        headers["Content-Type"] = "application/json"
    try:
        with urlopen(Request(api_url, data=payload, headers=headers, method=method), timeout=40) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        if method == "GET" and exc.code == 404:
            return 404, None
        raise RuntimeError(f"GitHub {method}: HTTP {exc.code}") from exc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simular", action="store_true")
    args = parser.parse_args()
    token = os.getenv("GH_TOKEN", "")
    if (os.getenv("GITHUB_REPOSITORY") != REPO
            or os.getenv("GITHUB_REF") != "refs/heads/main" or not token):
        raise SystemExit("Somente workflow autorizado do fork na main")
    status, directory = github("GET", YEAR_PATH, token)
    if status != 200 or not isinstance(directory, list) or len(directory) >= 1000:
        raise RuntimeError("Nao foi possivel verificar todos os nomes do ano")
    pattern = re.compile(r"(?<!\d)" + str(NUMBER) + r"(?!\d)")
    if any(pattern.search(entry.get("name", "")) for entry in directory):
        print("JA_EXISTENTE", NUMBER, flush=True)
        return
    status, _ = github("GET", PATH, token)
    if status != 404:
        raise RuntimeError("Destino nao esta ausente")
    raw = source_pdf()
    pages = extract(raw)
    result = build_document(pages)
    print("VALIDADO", NUMBER, "paginas", len(pages), "artigos", 33,
          "caracteres", len(result), "sha256_fonte", SHA256_PDF, flush=True)
    if args.simular:
        return
    # Recheck antes da operacao irreversivel.
    status, newdir = github("GET", YEAR_PATH, token)
    if status != 200 or any(pattern.search(entry.get("name", ""))
                            for entry in newdir):
        raise RuntimeError("Numero tornou-se existente antes de publicar")
    status, published = github("PUT", PATH, token, {
        "message": "feat(BA): inserir Lei 11.174/2008 do PDF oficial SECTI",
        "content": base64.b64encode(result.encode("utf-8")).decode("ascii"),
        "branch": "main",
    })
    if status != 201:
        raise RuntimeError("API nao confirmou criacao")
    status, verify = github("GET", PATH, token)
    if status != 200 or verify.get("sha") != published["content"]["sha"]:
        raise RuntimeError("Readback de persistencia falhou")
    print("PUBLICADA", NUMBER, PATH, "blob", verify["sha"],
          "commit", published["commit"]["sha"], flush=True)


if __name__ == "__main__":
    main()
