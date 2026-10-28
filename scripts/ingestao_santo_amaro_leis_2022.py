"""Ingestao da publicacao original de duas leis de Santo Amaro/BA (2022).

Recupera apenas os dois PDFs oficiais; Poppler extrai texto real, sem OCR.
Mantem divisao por pagina, imagens permanecem acessiveis no PDF primario.
Recusa divergencia de hash, pagina, identidade, artigos ou assinatura. Nao
clona o repositorio, nao reescreve leis ja publicadas e nao infere vigencia.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO = "Shadowjct/leis"
CATALOG = (
    {
        "numero": 2255, "ano": 2022, "artigos": 17, "paginas": 4,
        "paginas_dom": "118–121",
        "ementa": "Institui o Programa Social Reformando Lares, no âmbito do município de Santo Amaro, Bahia, e dá outras providências.",
        "url": "https://www.municipioonline.com.br/Servicos/Publicacoes/FileDownload.ashx?n=LEI%202255.pdf&l=1Pi60he9V2P88ZvNRDjDvkcRDlfZHDB1F&e=pdf",
        "sha": "b3f7d6fb53325743ae8e6bd8ec48e2cf57ecbe46d4ce7a9b46ecd46b8822b1c8",
    },
    {
        "numero": 2256, "ano": 2022, "artigos": 10, "paginas": 2,
        "paginas_dom": "122–123",
        "ementa": "Autoriza a criação do Programa Restaurante Popular no Município de Santo Amaro, Bahia, e dá outras providências.",
        "url": "https://www.municipioonline.com.br/Servicos/Publicacoes/FileDownload.ashx?n=LEI%202256.pdf&l=1MYUmFRSRYJrRiyGeGQdjB4iMh5DcdoNL&e=pdf",
        "sha": "56e18e27b4c9482b908d28d7dccfac6621a10fa3468e10b00a8638086870847d",
    },
)
ROOT = "municipais/BA/santo-amaro/leis-ordinarias/2022"
SOURCE_PAGE = "https://www.municipioonline.com.br/ba/prefeitura/santoamaro/cidadao/legislacao/processo"


def read_source(entry):
    req = Request(entry["url"], headers={"User-Agent": "leis-santo-amaro/1.0",
                                          "Accept-Encoding": "identity"})
    with urlopen(req, timeout=50) as response:
        raw = response.read(1_000_001)
        if response.status != 200 or "pdf" not in response.headers.get("Content-Type", "").lower():
            raise RuntimeError("Fonte oficial nao retornou PDF")
    if not raw.startswith(b"%PDF") or len(raw) > 1_000_000:
        raise RuntimeError("PDF invalido ou acima do limite")
    if hashlib.sha256(raw).hexdigest() != entry["sha"]:
        raise RuntimeError("HASH DA FONTE MUDOU — abortado para revisao")
    return raw


def extract(raw, entry):
    with tempfile.TemporaryDirectory(prefix="santo_amaro_pdf_") as d:
        pdf = Path(d) / "lei.pdf"
        pdf.write_bytes(raw)
        result = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"],
                                check=True, capture_output=True, timeout=75)
    pages = result.stdout.decode("utf-8", "strict").split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    if len(pages) != entry["paginas"] or any(len(page.strip()) < 90 for page in pages):
        raise RuntimeError("Paginas incompletas ou ausentes")
    body = "\n".join(pages)
    number = entry["numero"]
    if not re.search(r"\bLEI\s+N[º°.o]?\s*"+str(number)+r"\s*/\s*2022\b", pages[0], re.I):
        raise RuntimeError("Numero e ano da epigrafe divergentes")
    if "28 DE DEZEMBRO DE 2022" not in pages[0].upper():
        raise RuntimeError("Data de promulgacao ausente")
    if "PREFEITURA MUNICIPAL DE SANTO AMARO" not in pages[0].upper():
        raise RuntimeError("Municipio da fonte divergente")
    last = pages[-1].upper()
    if not ("ALESSANDRA GOMES REIS E SILVA DO CARMO" in last
            and "PREFEITA MUNICIPAL" in last):
        raise RuntimeError("Assinatura nao encontrada na ultima pagina")
    articles = [int(x) for x in re.findall(r"(?m)^\s*Art\.\s*(\d{1,3})(?:[º°o]|\s|[.])", body, re.I)]
    if articles != list(range(1, entry["artigos"]+1)):
        raise RuntimeError("Artigos ausentes, duplicados ou fora da ordem: " + str(articles))
    if len(body) < (6000 if number == 2255 else 3000):
        raise RuntimeError("Extração textual insuficiente")
    return pages


def markdown(pages, entry):
    num = entry["numero"]
    body = "\n\n".join(f"## Página {i}\n\n{page.strip()}" for i, page in enumerate(pages, start=1)) + "\n"
    meta = {
        "titulo": f"Lei Ordinária nº {num}, de 28 de dezembro de 2022",
        "municipio": "Santo Amaro",
        "uf": "BA", "codigo_ibge": "2928604",
        "tipo": "Lei ordinária", "numero": str(num),
        "data": "2022-12-28", "data_publicacao": "2022-12-28",
        "ementa": entry["ementa"],
        "publicacao": "Diário Oficial do Município de Santo Amaro, Ano IV, edição 00600, caderno 1, páginas " + entry["paginas_dom"],
        "versao_texto": "publicação original; texto extraído do PDF oficial com preservação das páginas; não compilado, sem certificação de vigência contemporânea",
        "fonte": SOURCE_PAGE, "fonte_texto": entry["url"],
        "sha256_fonte": entry["sha"],
        "sha256_texto": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "paginas_fonte": str(entry["paginas"]), "baixado_em": "2026-10-28",
    }
    hdr = "\n".join(k + ": " + json.dumps(v, ensure_ascii=False) for k, v in meta.items())
    return "---\n" + hdr + "\n---\n\n# " + meta["titulo"] + "\n\n" + body


def gh(method, path, token, content=None):
    url = "https://api.github.com/repos/" + REPO + "/contents/" + quote(path, safe="/")
    if method == "GET":
        url += "?ref=main"
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28",
               "User-Agent": "leis-santo-amaro/1.0"}
    payload = json.dumps(content, ensure_ascii=False).encode("utf-8") if content else None
    if payload:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=payload, method=method, headers=headers)
    try:
        with urlopen(req, timeout=40) as response:
            return response.status, json.loads(response.read())
    except HTTPError as e:
        if method == "GET" and e.code == 404:
            return 404, None
        raise RuntimeError(f"API GitHub {method} HTTP {e.code}") from e


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simular", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN", "")
    if (os.environ.get("GITHUB_REPOSITORY") != REPO
            or os.environ.get("GITHUB_REF") != "refs/heads/main" or not token):
        raise SystemExit("Operacao exclusiva do workflow do fork na main")
    for entry in CATALOG:
        num = entry["numero"]
        path = ROOT + f"/lei-ordinaria-{num}-2022-dom-00600.md"
        status, old = gh("GET", path, token)
        if status == 200:
            print("JA_EXISTENTE",num,old["sha"],flush=True)
            continue
        if status != 404:
            raise RuntimeError("Consulta de existencia falhou")
        # Independent check prevents an alternate filename for the same law.
        status, folder = gh("GET", ROOT, token)
        if status == 200:
            if not isinstance(folder, list) or len(folder) >= 1000:
                raise RuntimeError("Diretorio anual truncado")
            if any(re.search(r"(?:^|[-_])"+str(num)+r"(?:[-_.])", file["name"])
                   for file in folder):
                raise RuntimeError("Numero ja existente com nome alternativo")
        elif status != 404:
            raise RuntimeError("Diretorio anual inacessivel")
        raw = read_source(entry)
        pages = extract(raw, entry)
        content = markdown(pages, entry)
        print("VALIDADO",num,"paginas",len(pages),"artigos",entry["artigos"],
              "caracteres",len(content),"sha256_fonte",entry["sha"],flush=True)
        if args.simular:
            continue
        status, _ = gh("GET", path, token)
        if status != 404:
            raise RuntimeError("Destino deixou de estar ausente")
        blob = base64.b64encode(content.encode("utf-8")).decode("ascii")
        status, result = gh("PUT", path, token, {
            "message": f"feat(Santo Amaro): inserir Lei {num}/2022 do DOM oficial",
            "content": blob, "branch": "main",
        })
        if status != 201:
            raise RuntimeError("Publicacao nao confirmada")
        status, confirmed = gh("GET", path, token)
        if status != 200 or confirmed["sha"] != result["content"]["sha"]:
            raise RuntimeError("Persistencia nao confirmada")
        print("PUBLICADA",num,"sha",confirmed["sha"],"commit",result["commit"]["sha"],flush=True)


if __name__ == "__main__":
    main()
